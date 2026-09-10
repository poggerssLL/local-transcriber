"""Persistent local transcription queue and single-job worker."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from threading import Event, Thread
from time import perf_counter, sleep
from uuid import uuid4

from .config import RuntimePaths
from .models import TranscriptionJob, TranscriptionSettings, utc_now
from .models_manager import ModelManager
from .repository import Repository
from .transcription import EngineFactory, ProfileResolver, ProgressCallback, TranscriptionService


class TranscriptionQueue:
    """Validate and persist queue commands without starting inference."""

    def __init__(
        self,
        repository: Repository,
        paths: RuntimePaths,
        *,
        models: ModelManager | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.models = models or ModelManager(paths)
        self.now = now

    def enqueue(
        self,
        recording_id: str,
        settings: TranscriptionSettings | None = None,
        *,
        max_attempts: int = 3,
    ) -> TranscriptionJob:
        requested = settings or TranscriptionSettings()
        recording = self.repository.get_recording(recording_id)
        if recording is None:
            raise KeyError(f"recording not found: {recording_id}")
        self.models.require_installed(requested.model_name)
        media_path = self.paths.resolve_relative(recording.relative_path)
        if not media_path.is_file():
            raise FileNotFoundError("managed media file is missing")
        created_at = self.now()
        return self.repository.add_job(
            TranscriptionJob(
                recording_id=recording.id,
                engine=requested.engine,
                model_name=requested.model_name,
                settings=requested,
                total_seconds=recording.duration_seconds,
                max_attempts=max_attempts,
                created_at=created_at,
                updated_at=created_at,
            )
        )

    def cancel(self, job_id: str) -> TranscriptionJob:
        return self.repository.request_job_cancel(job_id, now=self.now())

    def retry(self, job_id: str) -> TranscriptionJob:
        return self.repository.retry_job(job_id, now=self.now())


class _LeaseHeartbeat:
    def __init__(
        self,
        repository: Repository,
        job_id: str,
        worker_id: str,
        lease_seconds: float,
        now: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.job_id = job_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.now = now
        self._stop = Event()
        self._thread = Thread(target=self._run, name="transcription-lease", daemon=True)

    def __enter__(self) -> _LeaseHeartbeat:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.lease_seconds))

    def _run(self) -> None:
        interval = max(0.1, self.lease_seconds / 3)
        while not self._stop.wait(interval):
            try:
                self.repository.renew_lease(
                    self.job_id,
                    self.worker_id,
                    now=self.now(),
                    lease_seconds=self.lease_seconds,
                )
            except Exception:
                return


class TranscriptionWorker:
    """Sequential worker. One instance processes at most one job at a time."""

    def __init__(
        self,
        repository: Repository,
        paths: RuntimePaths,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 60.0,
        poll_interval: float = 1.0,
        models: ModelManager | None = None,
        profiles: ProfileResolver | None = None,
        engine_factory: EngineFactory | None = None,
        clock: Callable[[], float] = perf_counter,
        now: Callable[[], datetime] = utc_now,
        sleeper: Callable[[float], None] = sleep,
        progress: ProgressCallback | None = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if poll_interval < 0:
            raise ValueError("poll_interval must be non-negative")
        self.repository = repository
        self.paths = paths
        self.worker_id = worker_id or f"local-{uuid4()}"
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.now = now
        self.sleeper = sleeper
        self.progress = progress
        self.service = TranscriptionService(
            repository,
            paths,
            models=models,
            profiles=profiles,
            engine_factory=engine_factory,
            clock=clock,
            now=now,
        )

    def run_once(self) -> TranscriptionJob | None:
        job = self.repository.claim_next_job(
            self.worker_id,
            now=self.now(),
            lease_seconds=self.lease_seconds,
        )
        if job is None:
            return None
        with _LeaseHeartbeat(
            self.repository,
            job.id,
            self.worker_id,
            self.lease_seconds,
            self.now,
        ):
            self.service.process_claimed_job(
                job.id,
                self.worker_id,
                lease_seconds=self.lease_seconds,
                progress=self.progress,
            )
        result = self.repository.get_job(job.id)
        assert result is not None
        return result

    def run(self, *, once: bool = False) -> int:
        try:
            while True:
                processed = self.run_once()
                if once:
                    return 0
                if processed is None:
                    self.sleeper(self.poll_interval)
        except (KeyboardInterrupt, SystemExit):
            return 130
