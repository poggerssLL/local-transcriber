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
from .models import TranscriptionSettings
from .models_manager import ModelManager
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
        language = None if args.language.lower() == "auto" else args.language
        settings = TranscriptionSettings(
            model_name=args.model,
            language=language,
            beam_size=args.beam_size,
            word_timestamps=not args.no_word_timestamps,
            vad_filter=not args.no_vad,
            profile=args.profile,
        )

        def progress(event: ProgressEvent) -> None:
            print(f"[{event.stage}] {event.message}", file=err)

        transcript = TranscriptionService(repository, config.paths).transcribe(
            args.recording_id, settings, progress=progress
        )
        print(f"{transcript.id}\t{transcript.language or 'unknown'}", file=out)
        return 0
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
