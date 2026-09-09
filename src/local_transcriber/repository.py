"""Parameterized persistence operations for domain models."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from .database import Database
from .models import (
    ExportedArtifact,
    JobStatus,
    Recording,
    Segment,
    Subject,
    Transcript,
    TranscriptionJob,
    Word,
    utc_now,
)

_ALLOWED_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


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
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO transcription_jobs
                   (id, recording_id, engine, model_name, status,
                    error_message, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.id,
                    job.recording_id,
                    job.engine,
                    job.model_name,
                    job.status.value,
                    job.error_message,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
        return job

    def get_job(self, job_id: str) -> TranscriptionJob | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return TranscriptionJob(
            id=row["id"],
            recording_id=row["recording_id"],
            engine=row["engine"],
            model_name=row["model_name"],
            status=JobStatus(row["status"]),
            error_message=row["error_message"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def update_job_status(
        self, job_id: str, status: JobStatus, *, error_message: str | None = None
    ) -> TranscriptionJob:
        if not isinstance(status, JobStatus):
            status = JobStatus(status)
        current = self.get_job(job_id)
        if current is None:
            raise KeyError(f"job not found: {job_id}")
        if status not in _ALLOWED_TRANSITIONS[current.status]:
            raise ValueError(f"invalid job transition: {current.status.value} -> {status.value}")
        if status is JobStatus.FAILED and not error_message:
            raise ValueError("failed jobs require an error message")
        updated_at = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """UPDATE transcription_jobs
                   SET status = ?, error_message = ?, updated_at = ?
                   WHERE id = ?""",
                (status.value, error_message, updated_at.isoformat(), job_id),
            )
        result = self.get_job(job_id)
        assert result is not None
        return result

    def add_transcript(self, transcript: Transcript) -> Transcript:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO transcripts (id, recording_id, job_id, language, text, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    transcript.id,
                    transcript.recording_id,
                    transcript.job_id,
                    transcript.language,
                    transcript.text,
                    transcript.created_at.isoformat(),
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
            segments=tuple(segments),
            created_at=_dt(row["created_at"]),
        )

    def add_artifact(self, artifact: ExportedArtifact) -> ExportedArtifact:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO exported_artifacts
                   (id, transcript_id, kind, relative_path, created_at) VALUES (?, ?, ?, ?, ?)""",
                (
                    artifact.id,
                    artifact.transcript_id,
                    artifact.kind,
                    artifact.relative_path,
                    artifact.created_at.isoformat(),
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
                created_at=_dt(r["created_at"]),
            )
            for r in rows
        ]
