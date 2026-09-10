"""Parameterized persistence operations for domain models."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta
from re import findall

from .database import Database
from .models import (
    ExportedArtifact,
    JobEvent,
    JobPhase,
    JobStatus,
    Recording,
    RecordingSearchResult,
    Segment,
    Subject,
    Transcript,
    TranscriptionJob,
    TranscriptionMetrics,
    TranscriptionSettings,
    Word,
    utc_now,
)

_ALLOWED_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: {JobStatus.PENDING},
    JobStatus.CANCELLED: {JobStatus.PENDING},
}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _optional_dt(value: str | None) -> datetime | None:
    return None if value is None else _dt(value)


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_subject(self, subject: Subject) -> Subject:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO subjects (id, name, created_at) VALUES (?, ?, ?)",
                (subject.id, subject.name, subject.created_at.isoformat()),
            )
        return subject

    def get_subject(self, subject_id: str) -> Subject | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, name, created_at FROM subjects WHERE id = ?", (subject_id,)
            ).fetchone()
        return (
            None
            if row is None
            else Subject(id=row["id"], name=row["name"], created_at=_dt(row["created_at"]))
        )

    def list_subjects(self) -> list[Subject]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, created_at FROM subjects ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [Subject(id=r["id"], name=r["name"], created_at=_dt(r["created_at"])) for r in rows]

    def add_recording(self, recording: Recording) -> Recording:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO recordings
                   (id, title, subject_id, lesson_date, original_name, sha256, size_bytes,
                    media_format, duration_seconds, relative_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    recording.id,
                    recording.title,
                    recording.subject_id,
                    recording.lesson_date.isoformat(),
                    recording.original_name,
                    recording.sha256,
                    recording.size_bytes,
                    recording.media_format,
                    recording.duration_seconds,
                    recording.relative_path,
                    recording.created_at.isoformat(),
                ),
            )
        return recording

    def get_recording(self, recording_id: str) -> Recording | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        return None if row is None else self._recording(row)

    def find_recording_by_sha256(self, sha256: str) -> Recording | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM recordings WHERE sha256 = ?", (sha256.lower(),)
            ).fetchone()
        return None if row is None else self._recording(row)

    def list_recordings(self, subject_id: str | None = None) -> list[Recording]:
        with self.database.connect() as connection:
            if subject_id is None:
                rows = connection.execute(
                    "SELECT * FROM recordings ORDER BY lesson_date DESC, created_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM recordings WHERE subject_id = ? "
                    "ORDER BY lesson_date DESC, created_at DESC",
                    (subject_id,),
                ).fetchall()
        return [self._recording(row) for row in rows]

    def delete_recording(self, recording_id: str) -> bool:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM transcripts WHERE recording_id = ?", (recording_id,))
            connection.execute(
                "DELETE FROM transcription_jobs WHERE recording_id = ?", (recording_id,)
            )
            cursor = connection.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
        return cursor.rowcount == 1

    def search_recordings(self, query: str, *, limit: int = 50) -> list[RecordingSearchResult]:
        if limit < 1 or limit > 500:
            raise ValueError("search limit must be between 1 and 500")
        tokens = findall(r"\w+", query, flags=0)
        if not tokens:
            return []
        fts_query = " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT r.id, r.title, s.name AS subject_name, r.lesson_date,
                          snippet(recording_search, 3, '<mark>', '</mark>', '…', 16) AS excerpt
                   FROM recording_search
                   JOIN recordings AS r ON r.id = recording_search.recording_id
                   JOIN subjects AS s ON s.id = r.subject_id
                   WHERE recording_search MATCH ?
                   ORDER BY bm25(recording_search), r.lesson_date DESC, r.id
                   LIMIT ?""",
                (fts_query, limit),
            ).fetchall()
        return [
            RecordingSearchResult(
                recording_id=row["id"],
                title=row["title"],
                subject_name=row["subject_name"],
                lesson_date=date.fromisoformat(row["lesson_date"]),
                excerpt=row["excerpt"],
            )
            for row in rows
        ]

    @staticmethod
    def _recording(row: sqlite3.Row) -> Recording:
        return Recording(
            id=row["id"],
            title=row["title"],
            subject_id=row["subject_id"],
            lesson_date=date.fromisoformat(row["lesson_date"]),
            original_name=row["original_name"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            media_format=row["media_format"],
            duration_seconds=row["duration_seconds"],
            relative_path=row["relative_path"],
            created_at=_dt(row["created_at"]),
        )

    def add_job(self, job: TranscriptionJob) -> TranscriptionJob:
        settings = job.settings or TranscriptionSettings(
            engine=job.engine, model_name=job.model_name
        )
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO transcription_jobs
                   (id, recording_id, engine, model_name, status, error_message,
                    created_at, updated_at, phase, settings_json, progress_percent,
                    processed_seconds, total_seconds, attempt_count, max_attempts,
                    started_at, finished_at, cancel_requested_at, worker_id,
                    lease_expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.id,
                    job.recording_id,
                    job.engine,
                    job.model_name,
                    job.status.value,
                    job.error_message,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                    job.phase.value,
                    self._settings_json(settings),
                    job.progress_percent,
                    job.processed_seconds,
                    job.total_seconds,
                    job.attempt_count,
                    job.max_attempts,
                    None if job.started_at is None else job.started_at.isoformat(),
                    None if job.finished_at is None else job.finished_at.isoformat(),
                    None
                    if job.cancel_requested_at is None
                    else job.cancel_requested_at.isoformat(),
                    job.worker_id,
                    None if job.lease_expires_at is None else job.lease_expires_at.isoformat(),
                ),
            )
            self._append_event(
                connection,
                job.id,
                phase=job.phase,
                message="job queued" if job.status is JobStatus.PENDING else "job created",
                processed_seconds=job.processed_seconds,
                total_seconds=job.total_seconds,
                percent=job.progress_percent,
                created_at=job.created_at,
            )
        return job

    def get_job(self, job_id: str) -> TranscriptionJob | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return self._job(row)

    def list_jobs(self, status: JobStatus | None = None) -> list[TranscriptionJob]:
        with self.database.connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM transcription_jobs ORDER BY created_at DESC, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM transcription_jobs WHERE status = ? "
                    "ORDER BY created_at DESC, id",
                    (JobStatus(status).value,),
                ).fetchall()
        return [self._job(row) for row in rows]

    def update_job_status(
        self, job_id: str, status: JobStatus, *, error_message: str | None = None
    ) -> TranscriptionJob:
        if not isinstance(status, JobStatus):
            status = JobStatus(status)
        updated_at = utc_now()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"job not found: {job_id}")
            current = JobStatus(row["status"])
            if status not in _ALLOWED_TRANSITIONS[current]:
                raise ValueError(f"invalid job transition: {current.value} -> {status.value}")
            if status is JobStatus.FAILED and not error_message:
                raise ValueError("failed jobs require an error message")
            if status is JobStatus.PENDING:
                phase = JobPhase.QUEUED
            elif status is JobStatus.RUNNING:
                phase = JobPhase.TRANSCRIBING
            else:
                phase = JobPhase.COMPLETED
            percent = 100.0 if status is JobStatus.SUCCEEDED else row["progress_percent"]
            finished_at = (
                updated_at.isoformat()
                if status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
                else None
            )
            connection.execute(
                """UPDATE transcription_jobs
                   SET status = ?, phase = ?, error_message = ?, updated_at = ?,
                       progress_percent = ?,
                       attempt_count = attempt_count + CASE WHEN ? = 'running' THEN 1 ELSE 0 END,
                       started_at = CASE WHEN ? = 'running'
                           THEN COALESCE(started_at, ?) ELSE started_at END,
                       finished_at = ?, lease_expires_at = CASE WHEN ? = 'running'
                           THEN lease_expires_at ELSE NULL END
                   WHERE id = ?""",
                (
                    status.value,
                    phase.value,
                    error_message,
                    updated_at.isoformat(),
                    percent,
                    status.value,
                    status.value,
                    updated_at.isoformat(),
                    finished_at,
                    status.value,
                    job_id,
                ),
            )
            self._append_event(
                connection,
                job_id,
                phase=phase,
                message=f"job {status.value}",
                processed_seconds=row["processed_seconds"],
                total_seconds=row["total_seconds"],
                percent=percent,
                created_at=updated_at,
            )
        result = self.get_job(job_id)
        assert result is not None
        return result

    def claim_next_job(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: float = 60.0,
    ) -> TranscriptionJob | None:
        """Recover expired leases and atomically claim one pending job."""
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        claimed_at = now or utc_now()
        lease_expires = claimed_at + timedelta(seconds=lease_seconds)
        with self.database.transaction(immediate=True) as connection:
            self._recover_expired_jobs(connection, claimed_at)
            row = connection.execute(
                """SELECT id FROM transcription_jobs
                   WHERE status = 'pending' AND cancel_requested_at IS NULL
                     AND attempt_count < max_attempts
                   ORDER BY created_at, id LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            cursor = connection.execute(
                """UPDATE transcription_jobs
                   SET status = 'running', phase = 'claiming', worker_id = ?,
                       lease_expires_at = ?, attempt_count = attempt_count + 1,
                       started_at = COALESCE(started_at, ?), finished_at = NULL,
                       error_message = NULL, updated_at = ?
                   WHERE id = ? AND status = 'pending' AND cancel_requested_at IS NULL
                     AND attempt_count < max_attempts""",
                (
                    worker_id,
                    lease_expires.isoformat(),
                    claimed_at.isoformat(),
                    claimed_at.isoformat(),
                    row["id"],
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._append_event(
                connection,
                row["id"],
                phase=JobPhase.CLAIMING,
                message="job claimed",
                created_at=claimed_at,
            )
            claimed = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (row["id"],)
            ).fetchone()
        return self._job(claimed)

    def recover_expired_jobs(self, *, now: datetime | None = None) -> int:
        recovered_at = now or utc_now()
        with self.database.transaction(immediate=True) as connection:
            return self._recover_expired_jobs(connection, recovered_at)

    def renew_lease(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: float = 60.0,
    ) -> None:
        renewed_at = now or utc_now()
        expires = renewed_at + timedelta(seconds=lease_seconds)
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE transcription_jobs SET lease_expires_at = ?, updated_at = ?
                   WHERE id = ? AND status = 'running' AND worker_id = ?""",
                (expires.isoformat(), renewed_at.isoformat(), job_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("job lease ownership was lost")

    def update_claimed_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        phase: JobPhase,
        message: str,
        completed_segments: int = 0,
        processed_seconds: float = 0.0,
        total_seconds: float | None = None,
        percent: float | None = None,
        now: datetime | None = None,
        lease_seconds: float = 60.0,
    ) -> TranscriptionJob:
        changed_at = now or utc_now()
        expires = changed_at + timedelta(seconds=lease_seconds)
        if percent is not None:
            percent = min(99.999, percent)
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"job not found: {job_id}")
            if row["status"] != JobStatus.RUNNING.value or row["worker_id"] != worker_id:
                raise RuntimeError("job lease ownership was lost")
            if row["cancel_requested_at"] is not None:
                raise RuntimeError("job cancellation was requested")
            next_processed = max(float(row["processed_seconds"]), processed_seconds)
            next_total = total_seconds if total_seconds is not None else row["total_seconds"]
            current_percent = row["progress_percent"]
            next_percent = percent
            if next_percent is None:
                next_percent = current_percent
            elif current_percent is not None:
                next_percent = max(float(current_percent), next_percent)
            connection.execute(
                """UPDATE transcription_jobs
                   SET phase = ?, progress_percent = ?, processed_seconds = ?,
                       total_seconds = ?, lease_expires_at = ?, updated_at = ?
                   WHERE id = ? AND status = 'running' AND worker_id = ?""",
                (
                    JobPhase(phase).value,
                    next_percent,
                    next_processed,
                    next_total,
                    expires.isoformat(),
                    changed_at.isoformat(),
                    job_id,
                    worker_id,
                ),
            )
            self._append_event(
                connection,
                job_id,
                phase=JobPhase(phase),
                message=message,
                completed_segments=completed_segments,
                processed_seconds=next_processed,
                total_seconds=next_total,
                percent=next_percent,
                created_at=changed_at,
            )
        result = self.get_job(job_id)
        assert result is not None
        return result

    def request_job_cancel(self, job_id: str, *, now: datetime | None = None) -> TranscriptionJob:
        requested_at = now or utc_now()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"job not found: {job_id}")
            status = JobStatus(row["status"])
            if status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return self._job(row)
            if status is JobStatus.PENDING:
                connection.execute(
                    """UPDATE transcription_jobs
                       SET status = 'cancelled', phase = 'completed', cancel_requested_at = ?,
                           finished_at = ?, updated_at = ? WHERE id = ? AND status = 'pending'""",
                    (
                        requested_at.isoformat(),
                        requested_at.isoformat(),
                        requested_at.isoformat(),
                        job_id,
                    ),
                )
                phase = JobPhase.COMPLETED
                message = "pending job cancelled"
            else:
                connection.execute(
                    """UPDATE transcription_jobs
                       SET phase = 'cancelling', cancel_requested_at = ?, updated_at = ?
                       WHERE id = ? AND status = 'running'""",
                    (requested_at.isoformat(), requested_at.isoformat(), job_id),
                )
                phase = JobPhase.CANCELLING
                message = "cancellation requested"
            self._append_event(
                connection,
                job_id,
                phase=phase,
                message=message,
                processed_seconds=row["processed_seconds"],
                total_seconds=row["total_seconds"],
                percent=row["progress_percent"],
                created_at=requested_at,
            )
        result = self.get_job(job_id)
        assert result is not None
        return result

    def finish_claimed_cancel(
        self, job_id: str, worker_id: str, *, now: datetime | None = None
    ) -> TranscriptionJob:
        return self._finish_claimed(
            job_id,
            worker_id,
            JobStatus.CANCELLED,
            "job cancelled",
            now=now,
        )

    def fail_claimed_job(
        self,
        job_id: str,
        worker_id: str,
        error_message: str,
        *,
        now: datetime | None = None,
    ) -> TranscriptionJob:
        if not error_message.strip():
            raise ValueError("failed jobs require an error message")
        return self._finish_claimed(
            job_id,
            worker_id,
            JobStatus.FAILED,
            "job failed",
            error_message=error_message,
            now=now,
        )

    def retry_job(self, job_id: str, *, now: datetime | None = None) -> TranscriptionJob:
        retried_at = now or utc_now()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"job not found: {job_id}")
            status = JobStatus(row["status"])
            if status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                raise ValueError("only failed or cancelled jobs can be retried")
            if row["attempt_count"] >= row["max_attempts"]:
                raise ValueError("job attempt limit has been reached")
            connection.execute(
                """UPDATE transcription_jobs
                   SET status = 'pending', phase = 'queued', progress_percent = 0,
                       processed_seconds = 0, started_at = NULL, finished_at = NULL,
                       cancel_requested_at = NULL, worker_id = NULL,
                       lease_expires_at = NULL, error_message = NULL, updated_at = ?
                   WHERE id = ? AND status IN ('failed','cancelled')""",
                (retried_at.isoformat(), job_id),
            )
            self._append_event(
                connection,
                job_id,
                phase=JobPhase.QUEUED,
                message="job queued for retry",
                total_seconds=row["total_seconds"],
                percent=0.0,
                created_at=retried_at,
            )
        result = self.get_job(job_id)
        assert result is not None
        return result

    def list_job_events(self, job_id: str) -> list[JobEvent]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM transcription_job_events WHERE job_id = ? ORDER BY sequence",
                (job_id,),
            ).fetchall()
        return [
            JobEvent(
                id=row["id"],
                job_id=row["job_id"],
                sequence=row["sequence"],
                phase=JobPhase(row["phase"]),
                message=row["message"],
                completed_segments=row["completed_segments"],
                processed_seconds=row["processed_seconds"],
                total_seconds=row["total_seconds"],
                percent=row["percent"],
                created_at=_dt(row["created_at"]),
            )
            for row in rows
        ]

    def claimed_job_cancel_requested(self, job_id: str, worker_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT status, worker_id, cancel_requested_at
                   FROM transcription_jobs WHERE id = ?""",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        if row["status"] != JobStatus.RUNNING.value or row["worker_id"] != worker_id:
            raise RuntimeError("job lease ownership was lost")
        return row["cancel_requested_at"] is not None

    def _finish_claimed(
        self,
        job_id: str,
        worker_id: str,
        status: JobStatus,
        message: str,
        *,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> TranscriptionJob:
        if status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            raise ValueError("claimed job can only finish as failed or cancelled")
        finished_at = now or utc_now()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"job not found: {job_id}")
            if row["status"] != JobStatus.RUNNING.value or row["worker_id"] != worker_id:
                raise RuntimeError("job lease ownership was lost")
            connection.execute(
                """UPDATE transcription_jobs
                   SET status = ?, phase = 'completed', error_message = ?, finished_at = ?,
                       lease_expires_at = NULL, updated_at = ?
                   WHERE id = ? AND status = 'running' AND worker_id = ?""",
                (
                    status.value,
                    error_message,
                    finished_at.isoformat(),
                    finished_at.isoformat(),
                    job_id,
                    worker_id,
                ),
            )
            self._append_event(
                connection,
                job_id,
                phase=JobPhase.COMPLETED,
                message=message,
                processed_seconds=row["processed_seconds"],
                total_seconds=row["total_seconds"],
                percent=row["progress_percent"],
                created_at=finished_at,
            )
        result = self.get_job(job_id)
        assert result is not None
        return result

    def _recover_expired_jobs(self, connection: sqlite3.Connection, recovered_at: datetime) -> int:
        rows = connection.execute(
            """SELECT * FROM transcription_jobs
               WHERE status = 'running'
                 AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
               ORDER BY created_at, id""",
            (recovered_at.isoformat(),),
        ).fetchall()
        for row in rows:
            if row["cancel_requested_at"] is not None:
                status = JobStatus.CANCELLED
                phase = JobPhase.COMPLETED
                message = "expired job finalized as cancelled"
                error_message = row["error_message"]
                finished_at = recovered_at.isoformat()
            elif row["attempt_count"] >= row["max_attempts"]:
                status = JobStatus.FAILED
                phase = JobPhase.COMPLETED
                message = "expired job reached attempt limit"
                error_message = "RuntimeError: job attempt limit reached after expired lease"
                finished_at = recovered_at.isoformat()
            else:
                status = JobStatus.PENDING
                phase = JobPhase.QUEUED
                message = "expired lease recovered; inference will restart"
                error_message = None
                finished_at = None
            connection.execute(
                """UPDATE transcription_jobs
                   SET status = ?, phase = ?, progress_percent = ?, processed_seconds = ?,
                       worker_id = NULL, lease_expires_at = NULL, finished_at = ?,
                       error_message = ?, updated_at = ? WHERE id = ? AND status = 'running'""",
                (
                    status.value,
                    phase.value,
                    0.0 if status is JobStatus.PENDING else row["progress_percent"],
                    0.0 if status is JobStatus.PENDING else row["processed_seconds"],
                    finished_at,
                    error_message,
                    recovered_at.isoformat(),
                    row["id"],
                ),
            )
            self._append_event(
                connection,
                row["id"],
                phase=phase,
                message=message,
                processed_seconds=(
                    0.0 if status is JobStatus.PENDING else row["processed_seconds"]
                ),
                total_seconds=row["total_seconds"],
                percent=0.0 if status is JobStatus.PENDING else row["progress_percent"],
                created_at=recovered_at,
            )
        return len(rows)

    @staticmethod
    def _settings_json(settings: TranscriptionSettings) -> str:
        return json.dumps(
            asdict(settings), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        job_id: str,
        *,
        phase: JobPhase,
        message: str,
        completed_segments: int = 0,
        processed_seconds: float = 0.0,
        total_seconds: float | None = None,
        percent: float | None = None,
        created_at: datetime | None = None,
    ) -> None:
        sequence = connection.execute(
            """SELECT COALESCE(MAX(sequence), 0) + 1
               FROM transcription_job_events WHERE job_id = ?""",
            (job_id,),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO transcription_job_events
               (job_id, sequence, phase, message, completed_segments,
                processed_seconds, total_seconds, percent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                sequence,
                JobPhase(phase).value,
                message.strip()[:500] or "job event",
                completed_segments,
                processed_seconds,
                total_seconds,
                percent,
                (created_at or utc_now()).isoformat(),
            ),
        )

    @staticmethod
    def _job(row: sqlite3.Row) -> TranscriptionJob:
        settings_data = json.loads(row["settings_json"])
        settings_data.setdefault("engine", row["engine"])
        settings_data.setdefault("model_name", row["model_name"])
        return TranscriptionJob(
            id=row["id"],
            recording_id=row["recording_id"],
            engine=row["engine"],
            model_name=row["model_name"],
            status=JobStatus(row["status"]),
            phase=JobPhase(row["phase"]),
            settings=TranscriptionSettings(**settings_data),
            progress_percent=row["progress_percent"],
            processed_seconds=row["processed_seconds"],
            total_seconds=row["total_seconds"],
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            started_at=_optional_dt(row["started_at"]),
            finished_at=_optional_dt(row["finished_at"]),
            cancel_requested_at=_optional_dt(row["cancel_requested_at"]),
            worker_id=row["worker_id"],
            lease_expires_at=_optional_dt(row["lease_expires_at"]),
            error_message=row["error_message"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def add_transcript(self, transcript: Transcript) -> Transcript:
        with self.database.transaction() as connection:
            self._insert_transcript(connection, transcript)
        return transcript

    @staticmethod
    def _insert_transcript(connection: sqlite3.Connection, transcript: Transcript) -> None:
        connection.execute(
            """INSERT INTO transcripts
                   (id, recording_id, job_id, language, text, created_at,
                    settings_json, metrics_json, language_probability)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                transcript.id,
                transcript.recording_id,
                transcript.job_id,
                transcript.language,
                transcript.text,
                transcript.created_at.isoformat(),
                json.dumps(
                    asdict(transcript.settings),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                None
                if transcript.metrics is None
                else json.dumps(
                    asdict(transcript.metrics),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                transcript.language_probability,
            ),
        )
        for segment in transcript.segments:
            connection.execute(
                """INSERT INTO segments
                       (id, transcript_id, ordinal, start_seconds, end_seconds, text)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    segment.id,
                    transcript.id,
                    segment.ordinal,
                    segment.start_seconds,
                    segment.end_seconds,
                    segment.text,
                ),
            )
            for ordinal, word in enumerate(segment.words):
                connection.execute(
                    """INSERT INTO words
                           (id, segment_id, ordinal, text, start_seconds, end_seconds, probability)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        word.id,
                        segment.id,
                        ordinal,
                        word.text,
                        word.start_seconds,
                        word.end_seconds,
                        word.probability,
                    ),
                )

    def complete_transcription(
        self,
        job_id: str,
        transcript: Transcript,
        *,
        worker_id: str | None = None,
        now: datetime | None = None,
    ) -> Transcript:
        """Atomically publish a transcript and mark its running job successful."""
        if transcript.job_id != job_id:
            raise ValueError("transcript job does not match completed job")
        updated_at = now or utc_now()
        existing_id: str | None = None
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"job not found: {job_id}")
            existing = connection.execute(
                "SELECT id FROM transcripts WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None and JobStatus(row["status"]) is JobStatus.SUCCEEDED:
                existing_id = existing["id"]
            elif existing is not None:
                raise RuntimeError("job already has a published transcript")
            if JobStatus(row["status"]) is not JobStatus.RUNNING:
                if existing_id is None:
                    raise ValueError("only a running job can publish a transcript")
            elif existing_id is None:
                if worker_id is not None and row["worker_id"] != worker_id:
                    raise RuntimeError("job lease ownership was lost")
                if row["cancel_requested_at"] is not None:
                    raise RuntimeError("job cancellation was requested")
                if row["recording_id"] != transcript.recording_id:
                    raise ValueError("transcript recording does not match completed job")
                self._insert_transcript(connection, transcript)
                connection.execute(
                    """UPDATE transcription_jobs
                       SET status = 'succeeded', phase = 'completed', error_message = NULL,
                           progress_percent = 100, processed_seconds = CASE
                               WHEN total_seconds IS NULL THEN processed_seconds
                               ELSE total_seconds END,
                           finished_at = ?, lease_expires_at = NULL, updated_at = ?
                       WHERE id = ? AND status = 'running'""",
                    (updated_at.isoformat(), updated_at.isoformat(), job_id),
                )
                self._append_event(
                    connection,
                    job_id,
                    phase=JobPhase.COMPLETED,
                    message="transcript published",
                    completed_segments=len(transcript.segments),
                    processed_seconds=(
                        transcript.metrics.audio_duration_seconds
                        if transcript.metrics is not None
                        else row["processed_seconds"]
                    ),
                    total_seconds=(
                        transcript.metrics.audio_duration_seconds
                        if transcript.metrics is not None
                        else row["total_seconds"]
                    ),
                    percent=100.0,
                    created_at=updated_at,
                )
        if existing_id is not None:
            existing_transcript = self.get_transcript(existing_id)
            assert existing_transcript is not None
            return existing_transcript
        return transcript

    def get_transcript(self, transcript_id: str) -> Transcript | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM transcripts WHERE id = ?", (transcript_id,)
            ).fetchone()
            if row is None:
                return None
            segment_rows = connection.execute(
                "SELECT * FROM segments WHERE transcript_id = ? ORDER BY ordinal", (transcript_id,)
            ).fetchall()
            segments = []
            for segment_row in segment_rows:
                word_rows = connection.execute(
                    "SELECT * FROM words WHERE segment_id = ? ORDER BY ordinal",
                    (segment_row["id"],),
                ).fetchall()
                words = tuple(
                    Word(
                        id=w["id"],
                        text=w["text"],
                        start_seconds=w["start_seconds"],
                        end_seconds=w["end_seconds"],
                        probability=w["probability"],
                    )
                    for w in word_rows
                )
                segments.append(
                    Segment(
                        id=segment_row["id"],
                        ordinal=segment_row["ordinal"],
                        start_seconds=segment_row["start_seconds"],
                        end_seconds=segment_row["end_seconds"],
                        text=segment_row["text"],
                        words=words,
                    )
                )
        return Transcript(
            id=row["id"],
            recording_id=row["recording_id"],
            job_id=row["job_id"],
            language=row["language"],
            text=row["text"],
            language_probability=row["language_probability"],
            segments=tuple(segments),
            settings=TranscriptionSettings(**json.loads(row["settings_json"])),
            metrics=None
            if row["metrics_json"] is None
            else TranscriptionMetrics(**json.loads(row["metrics_json"])),
            created_at=_dt(row["created_at"]),
        )

    def list_transcripts(self, recording_id: str | None = None) -> list[Transcript]:
        with self.database.connect() as connection:
            if recording_id is None:
                rows = connection.execute(
                    "SELECT id FROM transcripts ORDER BY created_at DESC, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT id FROM transcripts WHERE recording_id = ?
                       ORDER BY created_at DESC, id""",
                    (recording_id,),
                ).fetchall()
        transcripts = [self.get_transcript(row["id"]) for row in rows]
        return [transcript for transcript in transcripts if transcript is not None]

    def add_artifact(self, artifact: ExportedArtifact) -> ExportedArtifact:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO exported_artifacts
                   (id, transcript_id, kind, relative_path, created_at,
                    media_type, size_bytes, sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact.id,
                    artifact.transcript_id,
                    artifact.kind,
                    artifact.relative_path,
                    artifact.created_at.isoformat(),
                    artifact.media_type,
                    artifact.size_bytes,
                    artifact.sha256,
                ),
            )
        return artifact

    def list_artifacts(self, transcript_id: str) -> list[ExportedArtifact]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM exported_artifacts WHERE transcript_id = ? ORDER BY created_at",
                (transcript_id,),
            ).fetchall()
        return [
            ExportedArtifact(
                id=r["id"],
                transcript_id=r["transcript_id"],
                kind=r["kind"],
                relative_path=r["relative_path"],
                media_type=r["media_type"],
                size_bytes=r["size_bytes"],
                sha256=r["sha256"],
                created_at=_dt(r["created_at"]),
            )
            for r in rows
        ]
