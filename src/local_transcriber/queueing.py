"""Persistent local transcription queue and single-job worker."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from time import perf_counter, sleep
from uuid import uuid4

from .config import RuntimePaths
from .exceptions import LeaseOwnershipLost
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
        lease_expires_at: datetime,
        *,
        max_transient_retries: int = 3,
        retry_interval: float | None = None,
        safety_margin: float | None = None,
    ) -> None:
        self.repository = repository
        self.job_id = job_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.now = now
        self.max_transient_retries = max_transient_retries
        self.retry_interval = retry_interval or max(0.01, min(0.25, lease_seconds / 12))
        self.safety_margin = safety_margin or max(0.01, min(1.0, lease_seconds / 6))
        self._confirmed_expiry = lease_expires_at
        self._stop = Event()
        self._lost = Event()
        self._finished = Event()
        self._state_lock = Lock()
        self._first_error: Exception | None = None
        self._loss: LeaseOwnershipLost | None = None
        self._thread = Thread(target=self._run, name="transcription-lease", daemon=True)

    def __enter__(self) -> _LeaseHeartbeat:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.lease_seconds))

    @property
    def first_error(self) -> Exception | None:
        with self._state_lock:
            return self._first_error

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    @property
    def stopped(self) -> bool:
        return self._finished.is_set() and not self._thread.is_alive()

    def raise_if_lost(self) -> None:
        if not self._lost.is_set():
            return
        with self._state_lock:
            loss = self._loss
        assert loss is not None
        raise LeaseOwnershipLost(str(loss)) from loss

    def _record_error(self, error: Exception) -> None:
        with self._state_lock:
            if self._first_error is None:
                self._first_error = error

    def _mark_lost(self, error: Exception) -> None:
        self._record_error(error)
        loss = (
            error
            if isinstance(error, LeaseOwnershipLost)
            else LeaseOwnershipLost("lease could not be renewed safely")
        )
        with self._state_lock:
            self._loss = loss
        self._lost.set()

    def _can_retry_safely(self) -> bool:
        safe_until = self._confirmed_expiry - timedelta(seconds=self.safety_margin)
        return self.now() < safe_until

    def _renew(self) -> bool:
        transient_failures = 0
        while not self._stop.is_set():
            renewed_at = self.now()
            try:
                self.repository.renew_lease(
                    self.job_id,
                    self.worker_id,
                    now=renewed_at,
                    lease_seconds=self.lease_seconds,
                )
            except LeaseOwnershipLost as error:
                self._mark_lost(error)
                return False
            except sqlite3.OperationalError as error:
                self._record_error(error)
                transient_failures += 1
                if transient_failures > self.max_transient_retries or not self._can_retry_safely():
                    self._mark_lost(error)
                    return False
                if self._stop.wait(self.retry_interval):
                    return False
            except Exception as error:
                self._mark_lost(error)
                return False
            else:
                self._confirmed_expiry = renewed_at + timedelta(seconds=self.lease_seconds)
                return True
        return False

    def _run(self) -> None:
        interval = max(0.05, self.lease_seconds / 3)
        try:
            while not self._stop.wait(interval):
                if not self._renew():
                    return
        finally:
            self._finished.set()


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
        self._last_heartbeat: _LeaseHeartbeat | None = None
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
        assert job.lease_expires_at is not None
        heartbeat = _LeaseHeartbeat(
            self.repository,
            job.id,
            self.worker_id,
            self.lease_seconds,
            self.now,
            job.lease_expires_at,
        )
        self._last_heartbeat = heartbeat
        try:
            with heartbeat:
                self.service.process_claimed_job(
                    job.id,
                    self.worker_id,
                    lease_seconds=self.lease_seconds,
                    progress=self.progress,
                    lease_guard=heartbeat.raise_if_lost,
                )
        except LeaseOwnershipLost:
            pass
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
