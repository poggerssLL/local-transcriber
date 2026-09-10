"""Command-line interface for the local transcription workflow."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import TextIO

from .config import AppConfig
from .database import Database
from .exporters import ExportFormat, TranscriptExporter
from .media import MediaLibrary
from .models import JobStatus, TranscriptionJob, TranscriptionSettings
from .models_manager import ModelManager
from .queueing import TranscriptionQueue, TranscriptionWorker
from .repository import Repository
from .transcription import CTranslate2RuntimeProbe, ProgressEvent, TranscriptionService

PACKAGE_NAME = "local-transcriber"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-transcriber")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version(PACKAGE_NAME)}")
    commands = parser.add_subparsers(dest="command", required=True)

    config = commands.add_parser("config", help="inspect local configuration and runtime")
    config.add_subparsers(dest="action", required=True).add_parser("check")

    subjects = commands.add_parser("subjects", help="manage subjects")
    subject_actions = subjects.add_subparsers(dest="action", required=True)
    add_subject = subject_actions.add_parser("add")
    add_subject.add_argument("name")
    subject_actions.add_parser("list")

    recordings = commands.add_parser("recordings", help="manage recordings")
    recording_actions = recordings.add_subparsers(dest="action", required=True)
    import_recording = recording_actions.add_parser("import")
    import_recording.add_argument("path", type=Path)
    import_recording.add_argument("--title", required=True)
    import_recording.add_argument("--subject", required=True)
    import_recording.add_argument("--date", required=True, type=date.fromisoformat)
    list_recordings = recording_actions.add_parser("list")
    list_recordings.add_argument("--subject")
    delete_recording = recording_actions.add_parser("delete")
    delete_recording.add_argument("recording_id")
    delete_recording.add_argument("--confirm", action="store_true")

    models = commands.add_parser("models", help="manage local Whisper models")
    model_actions = models.add_subparsers(dest="action", required=True)
    model_actions.add_parser("list")
    check_model = model_actions.add_parser("check")
    check_model.add_argument("model")
    download_model = model_actions.add_parser("download")
    download_model.add_argument("model")
    download_model.add_argument("--confirm", action="store_true")

    transcribe = commands.add_parser("transcribe", help="transcribe a managed recording")
    transcribe.add_argument("recording_id")
    transcribe.add_argument("--model", default="small")
    transcribe.add_argument("--profile", choices=("auto", "cpu", "cuda"), default="auto")
    transcribe.add_argument("--language", default="auto")
    transcribe.add_argument("--beam-size", type=int, default=5)
    transcribe.add_argument("--no-word-timestamps", action="store_true")
    transcribe.add_argument("--no-vad", action="store_true")

    jobs = commands.add_parser("jobs", help="manage the persistent transcription queue")
    job_actions = jobs.add_subparsers(dest="action", required=True)
    enqueue = job_actions.add_parser("enqueue")
    enqueue.add_argument("recording_id")
    _add_transcription_options(enqueue)
    enqueue.add_argument("--max-attempts", type=int, default=3)
    list_jobs = job_actions.add_parser("list")
    list_jobs.add_argument("--status", choices=[status.value for status in JobStatus])
    show_job = job_actions.add_parser("show")
    show_job.add_argument("job_id")
    cancel_job = job_actions.add_parser("cancel")
    cancel_job.add_argument("job_id")
    retry_job = job_actions.add_parser("retry")
    retry_job.add_argument("job_id")

    worker = commands.add_parser("worker", help="run the local persistent queue worker")
    worker_actions = worker.add_subparsers(dest="action", required=True)
    run_worker = worker_actions.add_parser("run")
    run_worker.add_argument("--once", action="store_true")

    transcripts = commands.add_parser("transcripts", help="inspect transcripts")
    transcript_actions = transcripts.add_subparsers(dest="action", required=True)
    list_transcripts = transcript_actions.add_parser("list")
    list_transcripts.add_argument("--recording")
    show_transcript = transcript_actions.add_parser("show")
    show_transcript.add_argument("transcript_id")

    export = commands.add_parser("export", help="export a transcript")
    export.add_argument("transcript_id")
    export.add_argument("--format", choices=[item.value for item in ExportFormat], required=True)
    return parser


def _add_transcription_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default="small")
    parser.add_argument("--profile", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--no-word-timestamps", action="store_true")
    parser.add_argument("--no-vad", action="store_true")


def _transcription_settings(args: argparse.Namespace) -> TranscriptionSettings:
    language = None if args.language.lower() == "auto" else args.language
    return TranscriptionSettings(
        model_name=args.model,
        language=language,
        beam_size=args.beam_size,
        word_timestamps=not args.no_word_timestamps,
        vad_filter=not args.no_vad,
        profile=args.profile,
    )


def _job_payload(job: TranscriptionJob) -> dict[str, object]:
    return {
        "id": job.id,
        "recording_id": job.recording_id,
        "engine": job.engine,
        "model_name": job.model_name,
        "status": job.status.value,
        "phase": job.phase.value,
        "progress_percent": job.progress_percent,
        "processed_seconds": job.processed_seconds,
        "total_seconds": job.total_seconds,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "started_at": None if job.started_at is None else job.started_at.isoformat(),
        "finished_at": None if job.finished_at is None else job.finished_at.isoformat(),
        "cancel_requested_at": (
            None if job.cancel_requested_at is None else job.cancel_requested_at.isoformat()
        ),
        "worker_id": job.worker_id,
        "lease_expires_at": (
            None if job.lease_expires_at is None else job.lease_expires_at.isoformat()
        ),
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "settings": None if job.settings is None else asdict(job.settings),
    }


def _context() -> tuple[AppConfig, Repository, MediaLibrary]:
    config = AppConfig.from_env()
    config.paths.ensure_directories()
    database = Database(config.paths.database)
    database.initialize()
    repository = Repository(database)
    return config, repository, MediaLibrary(repository, config.paths)


def run(args: argparse.Namespace, *, out: TextIO, err: TextIO) -> int:
    config, repository, library = _context()
    if args.command == "config":
        capabilities = CTranslate2RuntimeProbe().inspect()
        payload = {
            "runtime_root": str(config.paths.root),
            "database": str(config.paths.database),
            "models": str(config.paths.models),
            "cpu_compute_types": sorted(capabilities.cpu_compute_types),
            "cuda_device_count": capabilities.cuda_device_count,
            "cuda_compute_types": sorted(capabilities.cuda_compute_types),
            "cuda_error": capabilities.cuda_error,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
        return 0
    if args.command == "subjects":
        if args.action == "add":
            subject = library.create_subject(args.name)
            print(f"{subject.id}\t{subject.name}", file=out)
        else:
            for subject in repository.list_subjects():
                print(f"{subject.id}\t{subject.name}", file=out)
        return 0
    if args.command == "recordings":
        if args.action == "import":
            recording = library.import_file(
                args.path,
                title=args.title,
                subject_id=args.subject,
                lesson_date=args.date,
            )
            print(f"{recording.id}\t{recording.title}\t{recording.relative_path}", file=out)
        elif args.action == "list":
            for recording in library.list_recordings(args.subject):
                print(
                    f"{recording.id}\t{recording.lesson_date.isoformat()}\t{recording.title}",
                    file=out,
                )
        else:
            if not args.confirm:
                raise ValueError("recording deletion requires --confirm")
            if not library.delete_recording(args.recording_id):
                raise KeyError(f"recording not found: {args.recording_id}")
            print(f"deleted\t{args.recording_id}", file=out)
        return 0
    if args.command == "models":
        manager = ModelManager(config.paths)
        if args.action == "list":
            for status in manager.list_models():
                print(
                    f"{status.name}\t{'installed' if status.installed else 'not-installed'}",
                    file=out,
                )
        elif args.action == "check":
            status = manager.status(args.model)
            print(
                f"{status.name}\t{'installed' if status.installed else 'not-installed'}", file=out
            )
            return 0 if status.installed else 1
        else:
            installed = manager.download(args.model, confirm=args.confirm)
            print(f"installed\t{args.model}\t{installed}", file=out)
        return 0
    if args.command == "transcribe":
        settings = _transcription_settings(args)

        def progress(event: ProgressEvent) -> None:
            print(f"[{event.stage}] {event.message}", file=err)

        transcript = TranscriptionService(repository, config.paths).transcribe(
            args.recording_id, settings, progress=progress
        )
        print(f"{transcript.id}\t{transcript.language or 'unknown'}", file=out)
        return 0
    if args.command == "jobs":
        queue = TranscriptionQueue(repository, config.paths)
        if args.action == "enqueue":
            job = queue.enqueue(
                args.recording_id,
                _transcription_settings(args),
                max_attempts=args.max_attempts,
            )
            print(f"{job.id}\t{job.status.value}\t{job.phase.value}", file=out)
        elif args.action == "list":
            status = None if args.status is None else JobStatus(args.status)
            for job in repository.list_jobs(status):
                percent = (
                    "unknown" if job.progress_percent is None else f"{job.progress_percent:.2f}"
                )
                print(
                    f"{job.id}\t{job.status.value}\t{job.phase.value}\t"
                    f"{percent}\t{job.attempt_count}/{job.max_attempts}",
                    file=out,
                )
        elif args.action == "show":
            job = repository.get_job(args.job_id)
            if job is None:
                raise KeyError(f"job not found: {args.job_id}")
            payload = _job_payload(job)
            payload["events"] = [
                {
                    "sequence": event.sequence,
                    "phase": event.phase.value,
                    "message": event.message,
                    "completed_segments": event.completed_segments,
                    "processed_seconds": event.processed_seconds,
                    "total_seconds": event.total_seconds,
                    "percent": event.percent,
                    "created_at": event.created_at.isoformat(),
                }
                for event in repository.list_job_events(job.id)
            ]
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=out)
        elif args.action == "cancel":
            job = queue.cancel(args.job_id)
            print(f"{job.id}\t{job.status.value}\t{job.phase.value}", file=out)
        else:
            job = queue.retry(args.job_id)
            print(f"{job.id}\t{job.status.value}\t{job.phase.value}", file=out)
        return 0
    if args.command == "worker":

        def worker_progress(event: ProgressEvent) -> None:
            percent = "" if event.percent is None else f" {event.percent:.2f}%"
            print(f"[{event.phase}]{percent} {event.message}", file=err)

        return TranscriptionWorker(repository, config.paths, progress=worker_progress).run(
            once=args.once
        )
    if args.command == "transcripts":
        if args.action == "list":
            for transcript in repository.list_transcripts(args.recording):
                print(
                    f"{transcript.id}\t{transcript.recording_id}\t"
                    f"{transcript.language or 'unknown'}",
                    file=out,
                )
        else:
            transcript = repository.get_transcript(args.transcript_id)
            if transcript is None:
                raise KeyError(f"transcript not found: {args.transcript_id}")
            payload = {
                "id": transcript.id,
                "recording_id": transcript.recording_id,
                "job_id": transcript.job_id,
                "language": transcript.language,
                "language_probability": transcript.language_probability,
                "text": transcript.text,
                "settings": asdict(transcript.settings),
                "metrics": None if transcript.metrics is None else asdict(transcript.metrics),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=out)
        return 0
    transcript = repository.get_transcript(args.transcript_id)
    if transcript is None:
        raise KeyError(f"transcript not found: {args.transcript_id}")
    artifact = TranscriptExporter(repository, config.paths).export(transcript, args.format)
    print(f"{artifact.id}\t{artifact.relative_path}", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args, out=sys.stdout, err=sys.stderr)
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
