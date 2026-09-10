from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event
from time import sleep

import pytest

from local_transcriber import (
    Database,
    EngineOutput,
    JobPhase,
    JobStatus,
    ProfileResolver,
    ProgressEvent,
    Recording,
    Repository,
    RuntimeCapabilities,
    RuntimePaths,
    Segment,
    Subject,
    TranscriptionQueue,
    TranscriptionService,
    TranscriptionWorker,
    Word,
)


@dataclass
class FixedProbe:
    def inspect(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(frozenset({"int8"}), 0, frozenset(), "no CUDA")


@dataclass
class FakeClock:
    now: datetime = datetime(2026, 9, 10, tzinfo=UTC)
    elapsed: float = 10.0

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def monotonic(self) -> float:
        value = self.elapsed
        self.elapsed += 1.0
        return value


def _write_fake_model(path: Path) -> None:
    path.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (path / name).write_bytes(b"test")


def _context(tmp_path: Path, *, duration: float = 120.0):
    paths = RuntimePaths((tmp_path / "runtime").resolve())
    paths.ensure_directories()
    database = Database(paths.database)
    database.initialize()
    repository = Repository(database)
    subject = repository.add_subject(Subject(name="Fila"))
    media = paths.media / "audio.wav"
    media.write_bytes(b"managed")
    recording = repository.add_recording(
        Recording(
            title="Aula",
            subject_id=subject.id,
            lesson_date=date(2026, 9, 10),
            original_name="audio.wav",
            sha256="a" * 64,
            size_bytes=7,
            media_format="wav",
            duration_seconds=duration,
            relative_path="media/audio.wav",
        )
    )
    _write_fake_model(paths.models / "small")
    return paths, database, repository, recording


class ProgressEngine:
    name = "fake"

    def __init__(self, duration: float = 120.0) -> None:
        self.duration = duration

    def transcribe(self, request, progress=None):
        segments = []
        for ordinal, end in enumerate((self.duration / 2, self.duration)):
            segment = Segment(
                ordinal=ordinal,
                start_seconds=0 if ordinal == 0 else self.duration / 2,
                end_seconds=end,
                text=f"segmento {ordinal}",
                words=(Word(text="palavra", start_seconds=end - 1, end_seconds=end),),
            )
            segments.append(segment)
            if progress is not None:
                progress(
                    ProgressEvent(
                        "transcribing",
                        "segment decoded",
                        ordinal + 1,
                        end,
                        self.duration,
                        min(99.999, end / self.duration * 100),
                    )
                )
        return EngineOutput(
            text="segmento 0 segmento 1",
            segments=tuple(segments),
            language="pt",
            language_probability=0.9,
            audio_duration_seconds=self.duration,
        )


def _queue(tmp_path: Path, *, duration: float = 120.0, max_attempts: int = 3):
    paths, database, repository, recording = _context(tmp_path, duration=duration)
    clock = FakeClock()
    queue = TranscriptionQueue(repository, paths, now=lambda: clock.now)
    job = queue.enqueue(recording.id, max_attempts=max_attempts)
    return paths, database, repository, recording, clock, queue, job


def test_enqueue_does_not_create_engine_or_run_inference(tmp_path: Path) -> None:
    paths, _database, repository, recording = _context(tmp_path)
    queue = TranscriptionQueue(repository, paths)
    job = queue.enqueue(recording.id)
    assert job.status is JobStatus.PENDING
    assert job.phase is JobPhase.QUEUED
    assert repository.list_transcripts(recording.id) == []


def test_atomic_claim_allows_only_one_of_two_workers(tmp_path: Path) -> None:
    _paths, _database, repository, _recording, clock, _queue_service, job = _queue(tmp_path)

    def claim(worker: str):
        return repository.claim_next_job(worker, now=clock.now, lease_seconds=30)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, ("worker-a", "worker-b")))
    winners = [item for item in claimed if item is not None]
    assert len(winners) == 1
    assert winners[0].id == job.id
    assert repository.get_job(job.id).attempt_count == 1


def test_worker_heartbeat_renews_lease_while_engine_is_busy(tmp_path: Path) -> None:
    paths, _database, repository, _recording = _context(tmp_path)
    job = TranscriptionQueue(repository, paths).enqueue(repository.list_recordings()[0].id)
    started = Event()
    release = Event()

    class BlockingEngine:
        name = "blocking"

        def transcribe(self, request, progress=None):
            started.set()
            assert release.wait(timeout=3)
            return EngineOutput("", (), "pt", 0.9, 120)

    worker = TranscriptionWorker(
        repository,
        paths,
        worker_id="worker-a",
        lease_seconds=0.3,
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: BlockingEngine(),
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.run_once)
        assert started.wait(timeout=2)
        sleep(0.45)
        assert repository.claim_next_job("worker-b", lease_seconds=0.3) is None
        release.set()
        assert future.result(timeout=3).status is JobStatus.SUCCEEDED
    assert repository.get_job(job.id).attempt_count == 1


def test_expired_lease_is_recovered_and_reclaimed_from_the_beginning(tmp_path: Path) -> None:
    _paths, _database, repository, _recording, clock, _queue_service, job = _queue(tmp_path)
    assert repository.claim_next_job("worker-a", now=clock.now, lease_seconds=10).id == job.id
    repository.update_claimed_job(
        job.id,
        "worker-a",
        phase=JobPhase.TRANSCRIBING,
        message="partial progress",
        processed_seconds=60,
        total_seconds=120,
        percent=50,
        now=clock.now,
        lease_seconds=10,
    )
    clock.advance(11)
    reclaimed = repository.claim_next_job("worker-b", now=clock.now, lease_seconds=10)
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.worker_id == "worker-b"
    assert reclaimed.attempt_count == 2
    assert reclaimed.processed_seconds == 0
    assert any("restart" in event.message for event in repository.list_job_events(job.id))


def test_cancel_requested_job_is_not_reexecuted_during_recovery(tmp_path: Path) -> None:
    _paths, _database, repository, _recording, clock, queue, job = _queue(tmp_path)
    repository.claim_next_job("worker-a", now=clock.now, lease_seconds=10)
    queue.cancel(job.id)
    clock.advance(11)
    assert repository.claim_next_job("worker-b", now=clock.now, lease_seconds=10) is None
    recovered = repository.get_job(job.id)
    assert recovered.status is JobStatus.CANCELLED
    assert recovered.phase is JobPhase.COMPLETED


def test_retry_preserves_attempt_count_and_enforces_limit(tmp_path: Path) -> None:
    _paths, _database, repository, _recording, clock, queue, job = _queue(tmp_path, max_attempts=1)
    repository.claim_next_job("worker-a", now=clock.now, lease_seconds=10)
    repository.fail_claimed_job(job.id, "worker-a", "RuntimeError: decoder failed", now=clock.now)
    with pytest.raises(ValueError, match="attempt limit"):
        queue.retry(job.id)

    second = queue.enqueue(job.recording_id, max_attempts=2)
    repository.claim_next_job("worker-a", now=clock.now, lease_seconds=10)
    repository.fail_claimed_job(
        second.id, "worker-a", "RuntimeError: decoder failed", now=clock.now
    )
    retried = queue.retry(second.id)
    assert retried.status is JobStatus.PENDING
    assert retried.attempt_count == 1


def test_worker_persists_monotonic_time_progress_and_final_result(tmp_path: Path) -> None:
    paths, database, repository, recording, clock, _queue_service, job = _queue(tmp_path)
    worker = TranscriptionWorker(
        repository,
        paths,
        worker_id="worker-a",
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: ProgressEngine(),
        clock=clock.monotonic,
        now=lambda: clock.now,
    )
    result = worker.run_once()
    assert result.status is JobStatus.SUCCEEDED
    assert result.phase is JobPhase.COMPLETED
    assert result.progress_percent == 100
    transcripts = repository.list_transcripts(recording.id)
    assert len(transcripts) == 1
    events = repository.list_job_events(job.id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    progress = [event.percent for event in events if event.percent is not None]
    assert progress == sorted(progress)
    assert all(percent < 100 for percent in progress[:-1])
    assert progress[-1] == 100
    restarted = Repository(Database(database.path))
    restarted.database.initialize()
    assert restarted.get_job(job.id).status is JobStatus.SUCCEEDED
    assert restarted.list_job_events(job.id) == events


def test_worker_supports_simulated_two_hour_audio_without_timeout(tmp_path: Path) -> None:
    paths, _database, repository, _recording, clock, _queue_service, _job = _queue(
        tmp_path, duration=7200
    )
    result = TranscriptionWorker(
        repository,
        paths,
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: ProgressEngine(7200),
        clock=clock.monotonic,
        now=lambda: clock.now,
    ).run_once()
    assert result.status is JobStatus.SUCCEEDED
    assert result.total_seconds == pytest.approx(7200)


def test_running_cancellation_is_cooperative_and_publishes_nothing(tmp_path: Path) -> None:
    paths, _database, repository, recording, clock, queue, job = _queue(tmp_path)
    seen = 0

    def cancel_after_first_progress(event: ProgressEvent) -> None:
        nonlocal seen
        if event.phase == "transcribing":
            seen += 1
            if seen == 1:
                queue.cancel(job.id)

    result = TranscriptionWorker(
        repository,
        paths,
        worker_id="worker-a",
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: ProgressEngine(),
        clock=clock.monotonic,
        now=lambda: clock.now,
        progress=cancel_after_first_progress,
    ).run_once()
    assert result.status is JobStatus.CANCELLED
    assert repository.list_transcripts(recording.id) == []


def test_engine_and_persistence_errors_do_not_publish_partial_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, _database, repository, recording, clock, queue, first = _queue(tmp_path)

    class BrokenEngine:
        name = "broken"

        def transcribe(self, request, progress=None):
            raise RuntimeError(f"decoder failed at {request.media_path}")

    failed = TranscriptionWorker(
        repository,
        paths,
        worker_id="worker-a",
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: BrokenEngine(),
        clock=clock.monotonic,
        now=lambda: clock.now,
    ).run_once()
    assert failed.status is JobStatus.FAILED
    assert "<runtime>" in failed.error_message
    assert repository.list_transcripts(recording.id) == []

    second = queue.enqueue(recording.id)
    original_complete = repository.complete_transcription

    def broken_complete(*args, **kwargs):
        raise sqlite3.OperationalError("simulated persistence failure")

    monkeypatch.setattr(repository, "complete_transcription", broken_complete)
    failed_persistence = TranscriptionWorker(
        repository,
        paths,
        worker_id="worker-b",
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: ProgressEngine(),
        clock=clock.monotonic,
        now=lambda: clock.now,
    ).run_once()
    monkeypatch.setattr(repository, "complete_transcription", original_complete)
    assert failed_persistence.id == second.id
    assert failed_persistence.status is JobStatus.FAILED
    assert repository.list_transcripts(recording.id) == []


def test_final_publication_is_idempotent_and_callback_failure_is_observational(
    tmp_path: Path,
) -> None:
    paths, _database, repository, recording, clock, _queue_service, job = _queue(tmp_path)
    worker = TranscriptionWorker(
        repository,
        paths,
        worker_id="worker-a",
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: ProgressEngine(),
        clock=clock.monotonic,
        now=lambda: clock.now,
        progress=lambda _event: (_ for _ in ()).throw(RuntimeError("observer failed")),
    )
    assert worker.run_once().status is JobStatus.SUCCEEDED
    transcript = repository.list_transcripts(recording.id)[0]
    assert (
        repository.complete_transcription(job.id, transcript, worker_id="worker-a", now=clock.now)
        == transcript
    )
    assert len(repository.list_transcripts(recording.id)) == 1


def test_synchronous_callback_after_success_cannot_report_failure(tmp_path: Path) -> None:
    paths, _database, repository, recording = _context(tmp_path)
    service = TranscriptionService(
        repository,
        paths,
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: ProgressEngine(),
    )

    def broken_observer(_event: ProgressEvent) -> None:
        raise RuntimeError("observer failed")

    transcript = service.transcribe(recording.id, progress=broken_observer)
    assert repository.get_job(transcript.job_id).status is JobStatus.SUCCEEDED


def test_keyboard_interrupt_stops_worker_without_classifying_domain_failure(tmp_path: Path) -> None:
    paths, _database, repository, _recording, clock, _queue_service, job = _queue(tmp_path)

    class InterruptedEngine:
        name = "interrupted"

        def transcribe(self, request, progress=None):
            raise KeyboardInterrupt

    worker = TranscriptionWorker(
        repository,
        paths,
        worker_id="worker-a",
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: InterruptedEngine(),
        now=lambda: clock.now,
    )
    assert worker.run(once=True) == 130
    interrupted = repository.get_job(job.id)
    assert interrupted.status is JobStatus.RUNNING
    assert interrupted.error_message is None
