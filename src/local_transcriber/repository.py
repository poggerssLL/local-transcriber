"""Parameterized persistence operations for domain models."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from re import findall

from .database import Database
from .models import (
    ExportedArtifact,
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

    def complete_transcription(self, job_id: str, transcript: Transcript) -> Transcript:
        """Atomically publish a transcript and mark its running job successful."""
        if transcript.job_id != job_id:
            raise ValueError("transcript job does not match completed job")
        updated_at = utc_now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT status, recording_id FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"job not found: {job_id}")
            if JobStatus(row["status"]) is not JobStatus.RUNNING:
                raise ValueError("only a running job can publish a transcript")
            if row["recording_id"] != transcript.recording_id:
                raise ValueError("transcript recording does not match completed job")
            self._insert_transcript(connection, transcript)
            connection.execute(
                """UPDATE transcription_jobs
                   SET status = ?, error_message = NULL, updated_at = ? WHERE id = ?""",
                (JobStatus.SUCCEEDED.value, updated_at.isoformat(), job_id),
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
