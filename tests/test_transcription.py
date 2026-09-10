from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_transcriber import (
    Database,
    EngineOutput,
    FasterWhisperEngine,
    JobStatus,
    ModelDownloadConfirmationError,
    ModelManager,
    ModelNotInstalledError,
    ProfileResolver,
    Recording,
    Repository,
    RuntimeCapabilities,
    RuntimePaths,
    RuntimeProfileError,
    Segment,
    Subject,
    Transcript,
    TranscriptionJob,
    TranscriptionService,
    TranscriptionSettings,
    Word,
)


@dataclass
class FakeProbe:
    capabilities: RuntimeCapabilities

    def inspect(self) -> RuntimeCapabilities:
        return self.capabilities


def capabilities(*, cuda: bool) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        cpu_compute_types=frozenset({"int8", "float32"}),
        cuda_device_count=1 if cuda else 0,
        cuda_compute_types=frozenset({"int8_float16"}) if cuda else frozenset(),
        cuda_error=None if cuda else "no compatible CUDA device",
    )


def test_profiles_choose_cuda_or_explicit_cpu() -> None:
    resolver = ProfileResolver(FakeProbe(capabilities(cuda=True)))
    assert resolver.resolve("auto").device == "cuda"
    assert resolver.resolve("auto").compute_type == "int8_float16"
    assert resolver.resolve("cpu").compute_type == "int8"


def test_auto_falls_back_but_explicit_cuda_fails_actionably() -> None:
    resolver = ProfileResolver(FakeProbe(capabilities(cuda=False)))
    automatic = resolver.resolve("auto")
    assert automatic.device == "cpu"
    assert automatic.compute_type == "int8"
    assert "fallback" in automatic.reason
    with pytest.raises(RuntimeProfileError, match="CUDA 12, cuDNN 9"):
        resolver.resolve("cuda")


def _write_fake_model(directory: Path) -> None:
    for filename in ("config.json", "model.bin", "tokenizer.json"):
        (directory / filename).write_bytes(b"test")


def test_models_require_confirmation_and_use_managed_directory(tmp_path: Path) -> None:
    paths = RuntimePaths((tmp_path / "runtime").resolve())
    calls = []

    def downloader(name: str, *, output_dir: str, cache_dir: str) -> str:
        calls.append((name, output_dir, cache_dir))
        _write_fake_model(Path(output_dir))
        return output_dir

    manager = ModelManager(paths, downloader=downloader)
    with pytest.raises(ModelDownloadConfirmationError):
        manager.download("small", confirm=False)
    assert calls == []
    installed = manager.download("small", confirm=True)
    assert installed == paths.models / "small"
    assert manager.require_installed("small") == installed
    assert calls[0][0] == "small"
    assert Path(calls[0][2]).is_relative_to(paths.models)
    assert not any(status.name.endswith(".en") for status in manager.list_models())


def test_missing_model_never_invokes_downloader(tmp_path: Path) -> None:
    calls = []
    manager = ModelManager(
        RuntimePaths((tmp_path / "runtime").resolve()),
        downloader=lambda *args, **kwargs: calls.append((args, kwargs)) or "unused",
    )
    with pytest.raises(ModelNotInstalledError, match="--confirm"):
        manager.require_installed("small")
    assert calls == []


def test_service_with_missing_model_never_creates_engine_or_job(tmp_path: Path) -> None:
    paths, database, repository, recording = _service_context(tmp_path, install_model=False)
    created = []
    service = TranscriptionService(
        repository,
        paths,
        engine_factory=lambda profile: created.append(profile),
    )
    with pytest.raises(ModelNotInstalledError):
        service.transcribe(recording.id)
    assert created == []
    with database.connect() as connection:
        count = connection.execute("SELECT count(*) FROM transcription_jobs").fetchone()[0]
    assert count == 0


def test_faster_whisper_adapter_consumes_lazy_segments_and_converts_output(tmp_path: Path) -> None:
    consumed = False

    class FakeModel:
        def transcribe(self, path: str, **kwargs: object):
            assert path.endswith("audio.wav")
            assert kwargs["language"] == "pt"

            def segments():
                nonlocal consumed
                yield SimpleNamespace(
                    start=0.0,
                    end=1.25,
                    text=" Olá mundo",
                    words=[SimpleNamespace(start=0.0, end=0.4, word=" Olá", probability=0.98)],
                )
                consumed = True

            return segments(), SimpleNamespace(
                language="pt", language_probability=0.91, duration=1.25
            )

    model_path = tmp_path / "model"
    media_path = tmp_path / "audio.wav"
    events = []
    engine = FasterWhisperEngine(model_factory=lambda path, device, compute: FakeModel())
    output = engine.transcribe(
        SimpleNamespace(
            media_path=media_path,
            model_path=model_path,
            settings=TranscriptionSettings(
                language="pt", profile="cpu", device="cpu", compute_type="int8"
            ),
        ),
        events.append,
    )
    assert consumed is True
    assert output.text == "Olá mundo"
    assert output.language == "pt"
    assert output.language_probability == pytest.approx(0.91)
    assert output.segments[0].words[0].probability == pytest.approx(0.98)
    assert events[-1].completed_segments == 1
    assert events[-1].processed_seconds == pytest.approx(1.25)
    assert events[-1].percent < 100


def _service_context(tmp_path: Path, *, install_model: bool = True):
    paths = RuntimePaths((tmp_path / "runtime").resolve())
    paths.ensure_directories()
    database = Database(paths.database)
    database.initialize()
    repository = Repository(database)
    subject = repository.add_subject(Subject(name="Português"))
    media = paths.media / "audio.wav"
    media.write_bytes(b"managed media")
    recording = repository.add_recording(
        Recording(
            title="Aula",
            subject_id=subject.id,
            lesson_date=date(2026, 9, 9),
            original_name="audio.wav",
            sha256="a" * 64,
            size_bytes=13,
            media_format="wav",
            duration_seconds=2.0,
            relative_path="media/audio.wav",
        )
    )
    if install_model:
        model = paths.models / "small"
        model.mkdir()
        _write_fake_model(model)
    return paths, database, repository, recording


class SuccessfulEngine:
    name = "fake"

    def transcribe(self, request, progress=None):
        return EngineOutput(
            text="Olá",
            segments=(
                Segment(
                    ordinal=0,
                    start_seconds=0,
                    end_seconds=1,
                    text="Olá",
                    words=(Word(text="Olá", start_seconds=0, end_seconds=1, probability=0.9),),
                ),
            ),
            language="pt",
            language_probability=0.95,
            audio_duration_seconds=2,
        )


def test_service_publishes_complete_transcript_and_metrics_atomically(tmp_path: Path) -> None:
    paths, _database, repository, recording = _service_context(tmp_path)
    ticks = iter((10.0, 11.5))
    events = []
    service = TranscriptionService(
        repository,
        paths,
        profiles=ProfileResolver(FakeProbe(capabilities(cuda=False))),
        engine_factory=lambda profile: SuccessfulEngine(),
        clock=lambda: next(ticks),
    )
    transcript = service.transcribe(recording.id, progress=events.append)
    assert repository.get_job(transcript.job_id).status is JobStatus.SUCCEEDED
    assert repository.get_transcript(transcript.id) == transcript
    assert transcript.settings.device == "cpu"
    assert transcript.settings.compute_type == "int8"
    assert transcript.metrics.processing_duration_seconds == pytest.approx(1.5)
    assert transcript.metrics.word_count == 1
    assert [event.stage for event in events] == ["started", "completed"]


def test_failure_records_sanitized_error_without_partial_transcript(tmp_path: Path) -> None:
    paths, database, repository, recording = _service_context(tmp_path)

    class BrokenEngine:
        name = "broken"

        def transcribe(self, request, progress=None):
            raise RuntimeError(f"decoder failed at {request.media_path}")

    service = TranscriptionService(
        repository,
        paths,
        profiles=ProfileResolver(FakeProbe(capabilities(cuda=False))),
        engine_factory=lambda profile: BrokenEngine(),
    )
    with pytest.raises(RuntimeError, match="decoder failed"):
        service.transcribe(recording.id)
    assert repository.list_transcripts(recording.id) == []
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status, error_message FROM transcription_jobs WHERE recording_id = ?",
            (recording.id,),
        ).fetchone()
    assert row["status"] == "failed"
    assert "<runtime>" in row["error_message"]
    assert str(paths.root) not in row["error_message"]


def test_atomic_completion_rolls_back_partial_transcript(tmp_path: Path) -> None:
    paths, _database, repository, recording = _service_context(tmp_path)
    job = repository.add_job(
        TranscriptionJob(recording_id=recording.id, engine="test", model_name="small")
    )
    repository.update_job_status(job.id, JobStatus.RUNNING)
    invalid = Transcript(
        recording_id=recording.id,
        job_id=job.id,
        language="pt",
        text="duplicated segment id",
        segments=(
            Segment(id="same", ordinal=0, start_seconds=0, end_seconds=1, text="A"),
            Segment(id="same", ordinal=1, start_seconds=1, end_seconds=2, text="B"),
        ),
    )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        repository.complete_transcription(job.id, invalid)
    assert repository.list_transcripts(recording.id) == []
    assert repository.get_job(job.id).status is JobStatus.RUNNING
