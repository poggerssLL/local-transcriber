from __future__ import annotations

import io
import sqlite3
import wave
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from threading import Event, Lock, current_thread

from fastapi.testclient import TestClient

from local_transcriber.api import _WorkerController, create_app
from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.database import Database
from local_transcriber.models import Recording, Subject, TranscriptionJob
from local_transcriber.repository import Repository


def _repository(tmp_path: Path) -> tuple[RuntimePaths, Database, Repository]:
    paths = RuntimePaths((tmp_path / "runtime").resolve())
    paths.ensure_directories()
    database = Database(paths.database)
    database.initialize()
    return paths, database, Repository(database)


def _recording(repository: Repository, paths: RuntimePaths) -> Recording:
    subject = repository.add_subject(Subject(name="Concorrência"))
    media = paths.media / "aula.wav"
    media.write_bytes(b"managed")
    return repository.add_recording(
        Recording(
            title="Aula sintética",
            subject_id=subject.id,
            lesson_date=date(2026, 9, 10),
            original_name="aula.wav",
            sha256="c" * 64,
            size_bytes=7,
            media_format="wav",
            duration_seconds=1,
            relative_path="media/aula.wav",
        )
    )


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(b"\0\0" * 800)
    return output.getvalue()


def test_empty_queue_does_not_start_immediate_transaction(tmp_path: Path, monkeypatch) -> None:
    _paths, database, repository = _repository(tmp_path)
    original_transaction = database.transaction
    immediate_transactions = 0

    @contextmanager
    def tracked_transaction(*, immediate: bool = False):
        nonlocal immediate_transactions
        if immediate:
            immediate_transactions += 1
        with original_transaction(immediate=immediate) as connection:
            yield connection

    monkeypatch.setattr(database, "transaction", tracked_transaction)

    assert repository.claim_next_job("idle-worker") is None
    assert immediate_transactions == 0


def test_http_upload_succeeds_while_idle_worker_polls_without_writer_locks(
    tmp_path: Path, monkeypatch
) -> None:
    config = AppConfig(RuntimePaths((tmp_path / "http-runtime").resolve()))
    app = create_app(config, worker_poll_interval=0.001)
    repository = app.state.repository
    database = repository.database
    original_preflight = repository._has_claimable_work
    original_transaction = database.transaction
    idle_poll_seen = Event()
    worker_immediate_transactions = 0
    counter_lock = Lock()

    def tracked_preflight(*args, **kwargs):
        result = original_preflight(*args, **kwargs)
        if current_thread().name == "local-transcriber-worker":
            idle_poll_seen.set()
        return result

    @contextmanager
    def tracked_transaction(*, immediate: bool = False):
        nonlocal worker_immediate_transactions
        if immediate and current_thread().name == "local-transcriber-worker":
            with counter_lock:
                worker_immediate_transactions += 1
        with original_transaction(immediate=immediate) as connection:
            yield connection

    monkeypatch.setattr(repository, "_has_claimable_work", tracked_preflight)
    monkeypatch.setattr(database, "transaction", tracked_transaction)

    with TestClient(app) as client:
        assert idle_poll_seen.wait(timeout=2)
        subject = client.post("/api/subjects", json={"name": "Sistemas"})
        assert subject.status_code == 201
        upload = client.post(
            "/api/recordings",
            data={
                "title": "Aula local",
                "subject_id": subject.json()["id"],
                "lesson_date": "2026-09-10",
            },
            files={"file": ("aula.wav", _wav_bytes(), "audio/wav")},
        )
        assert upload.status_code == 201

    assert worker_immediate_transactions == 0


def test_job_created_after_empty_preflight_is_claimed_on_next_poll(tmp_path: Path) -> None:
    paths, _database, repository = _repository(tmp_path)

    assert repository.claim_next_job("worker-a") is None

    recording = _recording(repository, paths)
    job = repository.add_job(
        TranscriptionJob(
            recording_id=recording.id,
            engine="faster-whisper",
            model_name="small",
            total_seconds=recording.duration_seconds,
        )
    )

    claimed = repository.claim_next_job("worker-a")
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.worker_id == "worker-a"


def test_worker_controller_retries_transient_claim_failure_and_stays_alive() -> None:
    continued = Event()
    release = Event()

    class FlakyWorker:
        calls = 0

        def run_once(self):
            self.calls += 1
            if self.calls == 1:
                raise sqlite3.OperationalError("database is locked")
            continued.set()
            assert release.wait(timeout=2)
            return None

    worker = FlakyWorker()
    controller = _WorkerController(
        worker,
        poll_interval=0.01,
        max_transient_retries=2,
        retry_interval=0.001,
    )
    controller.start()
    try:
        assert continued.wait(timeout=2)
        assert controller.thread.is_alive()
    finally:
        release.set()
        controller.stop()

    assert worker.calls == 2
    assert isinstance(controller.first_transient_error, sqlite3.OperationalError)
    assert controller.fatal_error is None


def test_worker_controller_does_not_retry_permanent_sqlite_error() -> None:
    permanent = sqlite3.OperationalError("no such table: transcription_jobs")

    class BrokenWorker:
        calls = 0

        def run_once(self):
            self.calls += 1
            raise permanent

    worker = BrokenWorker()
    controller = _WorkerController(worker, poll_interval=0.01, retry_interval=0.001)

    controller._run()

    assert worker.calls == 1
    assert controller.first_transient_error is None
    assert controller.fatal_error is permanent


def test_worker_controller_bounds_repeated_transient_claim_failures() -> None:
    locked = sqlite3.OperationalError("database table is locked")

    class LockedWorker:
        calls = 0

        def run_once(self):
            self.calls += 1
            raise locked

    worker = LockedWorker()
    controller = _WorkerController(
        worker,
        poll_interval=0.01,
        max_transient_retries=2,
        retry_interval=0.001,
    )

    controller._run()

    assert worker.calls == 3
    assert controller.first_transient_error is locked
    assert controller.fatal_error is locked
