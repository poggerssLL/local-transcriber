from __future__ import annotations

import wave
from datetime import date
from io import StringIO

import pytest

from local_transcriber import (
    Database,
    ExportFormat,
    ModelNotInstalledError,
    Recording,
    Repository,
    RuntimePaths,
    Subject,
    Transcript,
    TranscriptionJob,
)
from local_transcriber.cli import build_parser, run


def invoke(arguments: list[str]):
    output = StringIO()
    errors = StringIO()
    result = run(build_parser().parse_args(arguments), out=output, err=errors)
    return result, output.getvalue(), errors.getvalue()


def test_cli_subject_and_recording_lists_use_existing_services(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_TRANSCRIBER_DATA_DIR", str((tmp_path / "runtime").resolve()))
    result, output, _ = invoke(["subjects", "add", "Língua Portuguesa"])
    assert result == 0
    subject_id = output.split("\t", 1)[0]
    assert "Língua Portuguesa" in invoke(["subjects", "list"])[1]
    result, output, _ = invoke(["recordings", "list", "--subject", subject_id])
    assert result == 0
    assert output == ""


def test_cli_models_list_and_check_do_not_download(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_TRANSCRIBER_DATA_DIR", str((tmp_path / "runtime").resolve()))
    result, output, _ = invoke(["models", "list"])
    assert result == 0
    assert "small\tnot-installed" in output
    result, output, _ = invoke(["models", "check", "small"])
    assert result == 1
    assert output == "small\tnot-installed\n"


def test_cli_parser_exposes_transcription_defaults() -> None:
    args = build_parser().parse_args(["transcribe", "recording-id"])
    assert args.model == "small"
    assert args.profile == "auto"
    assert args.language == "auto"
    assert args.beam_size == 5


def test_cli_import_list_transcribe_guard_and_delete(tmp_path, monkeypatch) -> None:
    runtime = (tmp_path / "runtime").resolve()
    monkeypatch.setenv("LOCAL_TRANSCRIBER_DATA_DIR", str(runtime))
    _, output, _ = invoke(["subjects", "add", "Áudio"])
    subject_id = output.split("\t", 1)[0]
    media = tmp_path / "aula.wav"
    with wave.open(str(media), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 800)
    _, output, _ = invoke(
        [
            "recordings",
            "import",
            str(media),
            "--title",
            "Aula",
            "--subject",
            subject_id,
            "--date",
            "2026-09-09",
        ]
    )
    recording_id = output.split("\t", 1)[0]
    assert recording_id in invoke(["recordings", "list"])[1]
    with pytest.raises(ModelNotInstalledError):
        invoke(["transcribe", recording_id])
    with pytest.raises(ValueError, match="--confirm"):
        invoke(["recordings", "delete", recording_id])
    assert invoke(["recordings", "delete", recording_id, "--confirm"])[0] == 0


def test_cli_lists_shows_and_exports_transcript(tmp_path, monkeypatch) -> None:
    paths = RuntimePaths((tmp_path / "runtime").resolve())
    paths.ensure_directories()
    monkeypatch.setenv("LOCAL_TRANSCRIBER_DATA_DIR", str(paths.root))
    database = Database(paths.database)
    database.initialize()
    repository = Repository(database)
    subject = repository.add_subject(Subject(name="Teste"))
    recording = repository.add_recording(
        Recording(
            title="Aula",
            subject_id=subject.id,
            lesson_date=date(2026, 9, 9),
            original_name="aula.wav",
            sha256="b" * 64,
            size_bytes=1,
            media_format="wav",
            relative_path="media/aula.wav",
        )
    )
    job = repository.add_job(
        TranscriptionJob(recording_id=recording.id, engine="test", model_name="artificial")
    )
    transcript = repository.add_transcript(
        Transcript(
            recording_id=recording.id,
            job_id=job.id,
            language="pt",
            text="Olá",
        )
    )
    assert transcript.id in invoke(["transcripts", "list"])[1]
    assert '"text": "Olá"' in invoke(["transcripts", "show", transcript.id])[1]
    result, output, _ = invoke(["export", transcript.id, "--format", ExportFormat.JSON.value])
    assert result == 0
    assert "exports/" in output
