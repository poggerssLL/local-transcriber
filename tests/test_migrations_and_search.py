import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from local_transcriber import (
    SCHEMA_VERSION,
    Database,
    Recording,
    Repository,
    Subject,
    Transcript,
    TranscriptionJob,
)
from local_transcriber.database import _MIGRATION_V2, _MIGRATION_V3, _SCHEMA_V1


def _create_v1_database(path: Path) -> tuple[str, str]:
    subject_id = "subject-v1"
    recording_id = "recording-v1"
    created = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA_V1)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "INSERT INTO subjects (id, name, created_at) VALUES (?, ?, ?)",
            (subject_id, "Matemática", created),
        )
        connection.execute(
            """INSERT INTO recordings
               (id, title, subject_id, lesson_date, original_name, sha256, size_bytes,
                media_format, duration_seconds, relative_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                recording_id,
                "Álgebra linear",
                subject_id,
                "2026-01-01",
                "aula.wav",
                "a" * 64,
                100,
                "wav",
                1.0,
                "media/aula.wav",
                created,
            ),
        )
        connection.execute(
            """INSERT INTO transcription_jobs
               (id, recording_id, engine, model_name, status, error_message, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("job-v1", recording_id, "test", "legacy", "succeeded", None, created, created),
        )
        connection.execute(
            """INSERT INTO transcripts
               (id, recording_id, job_id, language, text, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("transcript-v1", recording_id, "job-v1", "pt", "conteúdo legado", created),
        )
    return subject_id, recording_id


def test_v4_migrates_existing_v1_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "existing-v1.sqlite3"
    subject_id, recording_id = _create_v1_database(path)
    database = Database(path)

    database.initialize()
    database.initialize()

    assert database.schema_version() == SCHEMA_VERSION == 4
    repository = Repository(database)
    assert repository.get_subject(subject_id).name == "Matemática"
    assert repository.get_recording(recording_id).title == "Álgebra linear"
    assert repository.search_recordings("algebra")[0].recording_id == recording_id
    assert repository.search_recordings("legado")[0].recording_id == recording_id


def test_empty_database_runs_all_migrations(tmp_path: Path) -> None:
    database = Database(tmp_path / "empty.sqlite3")
    database.initialize()
    database.initialize()

    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(transcripts)")}
        fts = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'recording_search'"
        ).fetchone()
    assert {"settings_json", "metrics_json", "language_probability"} <= columns
    assert fts is not None


def test_existing_v2_database_migrates_to_v4(tmp_path: Path) -> None:
    path = tmp_path / "existing-v2.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA_V1)
        connection.executescript(_MIGRATION_V2)
        connection.execute("PRAGMA user_version = 2")
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(transcripts)")}
    assert database.schema_version() == SCHEMA_VERSION == 4
    assert "language_probability" in columns


def test_existing_v3_database_migrates_to_v4(tmp_path: Path) -> None:
    path = tmp_path / "existing-v3.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA_V1)
        connection.executescript(_MIGRATION_V2)
        connection.executescript(_MIGRATION_V3)
        connection.execute("PRAGMA user_version = 3")
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        job_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(transcription_jobs)")
        }
        events = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'transcription_job_events'"
        ).fetchone()
    assert database.schema_version() == SCHEMA_VERSION == 4
    assert {"phase", "attempt_count", "lease_expires_at", "settings_json"} <= job_columns
    assert events is not None


def test_fts_searches_title_subject_and_transcript_safely(tmp_path: Path) -> None:
    database = Database(tmp_path / "search.sqlite3")
    database.initialize()
    repository = Repository(database)
    subject = repository.add_subject(Subject(name="Física aplicada"))
    recording = repository.add_recording(
        Recording(
            title="Álgebra vetorial",
            subject_id=subject.id,
            lesson_date=date(2026, 2, 3),
            original_name="aula.wav",
            sha256="b" * 64,
            size_bytes=1,
            media_format="wav",
            duration_seconds=1,
            relative_path="media/aula.wav",
        )
    )
    job = repository.add_job(
        TranscriptionJob(recording_id=recording.id, engine="test", model_name="artificial")
    )
    repository.add_transcript(
        Transcript(
            recording_id=recording.id,
            job_id=job.id,
            language="pt",
            text="Hoje estudamos equações diferenciais.",
        )
    )

    assert repository.search_recordings("algebra")[0].recording_id == recording.id
    assert repository.search_recordings("Física")[0].recording_id == recording.id
    assert repository.search_recordings("equações diferenciais")[0].recording_id == recording.id
    assert repository.search_recordings("' OR *") == []
