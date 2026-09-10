"""SQLite connection management and idempotent schema migration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 4

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS subjects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    lesson_date TEXT NOT NULL,
    original_name TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    media_format TEXT NOT NULL,
    duration_seconds REAL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    relative_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcription_jobs (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    engine TEXT NOT NULL,
    model_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','running','succeeded','failed','cancelled')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL UNIQUE REFERENCES transcription_jobs(id) ON DELETE RESTRICT,
    language TEXT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
    end_seconds REAL NOT NULL CHECK (end_seconds >= start_seconds),
    text TEXT NOT NULL,
    UNIQUE (transcript_id, ordinal)
);

CREATE TABLE IF NOT EXISTS words (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    text TEXT NOT NULL,
    start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
    end_seconds REAL NOT NULL CHECK (end_seconds >= start_seconds),
    probability REAL CHECK (probability IS NULL OR (probability >= 0 AND probability <= 1)),
    UNIQUE (segment_id, ordinal)
);

CREATE TABLE IF NOT EXISTS exported_artifacts (
    id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recordings_subject_date ON recordings(subject_id, lesson_date);
CREATE INDEX IF NOT EXISTS idx_jobs_recording_status ON transcription_jobs(recording_id, status);
CREATE INDEX IF NOT EXISTS idx_segments_transcript ON segments(transcript_id, ordinal);
"""

_MIGRATION_V2 = """
ALTER TABLE transcripts ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE transcripts ADD COLUMN metrics_json TEXT;
ALTER TABLE exported_artifacts ADD COLUMN media_type TEXT;
ALTER TABLE exported_artifacts ADD COLUMN size_bytes INTEGER
    CHECK (size_bytes IS NULL OR size_bytes >= 0);
ALTER TABLE exported_artifacts ADD COLUMN sha256 TEXT
    CHECK (sha256 IS NULL OR length(sha256) = 64);

CREATE VIRTUAL TABLE recording_search USING fts5(
    recording_id UNINDEXED,
    title,
    subject_name,
    transcript_text,
    tokenize = 'unicode61 remove_diacritics 2'
);

INSERT INTO recording_search(rowid, recording_id, title, subject_name, transcript_text)
SELECT
    r.rowid,
    r.id,
    r.title,
    s.name,
    COALESCE((
        SELECT group_concat(ordered.text, ' ')
        FROM (
            SELECT t.text
            FROM transcripts AS t
            WHERE t.recording_id = r.id
            ORDER BY t.created_at, t.id
        ) AS ordered
    ), '')
FROM recordings AS r
JOIN subjects AS s ON s.id = r.subject_id;

CREATE TRIGGER recordings_search_insert AFTER INSERT ON recordings BEGIN
    INSERT INTO recording_search(rowid, recording_id, title, subject_name, transcript_text)
    VALUES (
        new.rowid,
        new.id,
        new.title,
        (SELECT name FROM subjects WHERE id = new.subject_id),
        ''
    );
END;

CREATE TRIGGER recordings_search_update AFTER UPDATE OF title, subject_id ON recordings BEGIN
    UPDATE recording_search
    SET title = new.title,
        subject_name = (SELECT name FROM subjects WHERE id = new.subject_id)
    WHERE rowid = new.rowid;
END;

CREATE TRIGGER recordings_search_delete AFTER DELETE ON recordings BEGIN
    DELETE FROM recording_search WHERE rowid = old.rowid;
END;

CREATE TRIGGER subjects_search_update AFTER UPDATE OF name ON subjects BEGIN
    UPDATE recording_search
    SET subject_name = new.name
    WHERE recording_id IN (SELECT id FROM recordings WHERE subject_id = new.id);
END;

CREATE TRIGGER transcripts_search_insert AFTER INSERT ON transcripts BEGIN
    UPDATE recording_search
    SET transcript_text = COALESCE((
        SELECT group_concat(ordered.text, ' ')
        FROM (
            SELECT text
            FROM transcripts
            WHERE recording_id = new.recording_id
            ORDER BY created_at, id
        ) AS ordered
    ), '')
    WHERE recording_id = new.recording_id;
END;

CREATE TRIGGER transcripts_search_update AFTER UPDATE OF text ON transcripts BEGIN
    UPDATE recording_search
    SET transcript_text = COALESCE((
        SELECT group_concat(ordered.text, ' ')
        FROM (
            SELECT text
            FROM transcripts
            WHERE recording_id = new.recording_id
            ORDER BY created_at, id
        ) AS ordered
    ), '')
    WHERE recording_id = new.recording_id;
END;

CREATE TRIGGER transcripts_search_delete AFTER DELETE ON transcripts BEGIN
    UPDATE recording_search
    SET transcript_text = COALESCE((
        SELECT group_concat(ordered.text, ' ')
        FROM (
            SELECT text
            FROM transcripts
            WHERE recording_id = old.recording_id
            ORDER BY created_at, id
        ) AS ordered
    ), '')
    WHERE recording_id = old.recording_id;
END;
"""

_MIGRATION_V3 = """
ALTER TABLE transcripts ADD COLUMN language_probability REAL
    CHECK (language_probability IS NULL OR
           (language_probability >= 0 AND language_probability <= 1));
"""

_MIGRATION_V4 = """
ALTER TABLE transcription_jobs ADD COLUMN phase TEXT NOT NULL DEFAULT 'queued'
    CHECK (phase IN ('queued','claiming','loading_model','transcribing','finalizing',
                     'cancelling','completed'));
ALTER TABLE transcription_jobs ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE transcription_jobs ADD COLUMN progress_percent REAL DEFAULT 0
    CHECK (progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100));
ALTER TABLE transcription_jobs ADD COLUMN processed_seconds REAL NOT NULL DEFAULT 0
    CHECK (processed_seconds >= 0);
ALTER TABLE transcription_jobs ADD COLUMN total_seconds REAL
    CHECK (total_seconds IS NULL OR total_seconds >= 0);
ALTER TABLE transcription_jobs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0
    CHECK (attempt_count >= 0);
ALTER TABLE transcription_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3
    CHECK (max_attempts >= 1);
ALTER TABLE transcription_jobs ADD COLUMN started_at TEXT;
ALTER TABLE transcription_jobs ADD COLUMN finished_at TEXT;
ALTER TABLE transcription_jobs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE transcription_jobs ADD COLUMN worker_id TEXT;
ALTER TABLE transcription_jobs ADD COLUMN lease_expires_at TEXT;

UPDATE transcription_jobs
SET phase = CASE status
        WHEN 'pending' THEN 'queued'
        WHEN 'running' THEN 'transcribing'
        ELSE 'completed'
    END,
    progress_percent = CASE WHEN status = 'succeeded' THEN 100 ELSE 0 END,
    attempt_count = CASE WHEN status = 'pending' THEN 0 ELSE 1 END,
    started_at = CASE WHEN status = 'pending' THEN NULL ELSE updated_at END,
    finished_at = CASE
        WHEN status IN ('succeeded','failed','cancelled') THEN updated_at
        ELSE NULL
    END;

CREATE TABLE transcription_job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES transcription_jobs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    phase TEXT NOT NULL CHECK (
        phase IN ('queued','claiming','loading_model','transcribing','finalizing',
                  'cancelling','completed')
    ),
    message TEXT NOT NULL CHECK (length(trim(message)) > 0),
    completed_segments INTEGER NOT NULL DEFAULT 0 CHECK (completed_segments >= 0),
    processed_seconds REAL NOT NULL DEFAULT 0 CHECK (processed_seconds >= 0),
    total_seconds REAL CHECK (total_seconds IS NULL OR total_seconds >= 0),
    percent REAL CHECK (percent IS NULL OR (percent >= 0 AND percent <= 100)),
    created_at TEXT NOT NULL,
    UNIQUE (job_id, sequence)
);

INSERT INTO transcription_job_events
    (job_id, sequence, phase, message, completed_segments, processed_seconds,
     total_seconds, percent, created_at)
SELECT id, 1, phase, 'migrated job state', 0, processed_seconds, total_seconds,
       progress_percent, updated_at
FROM transcription_jobs;

CREATE INDEX idx_jobs_queue_claim
    ON transcription_jobs(status, cancel_requested_at, created_at, id);
CREATE INDEX idx_jobs_lease
    ON transcription_jobs(status, lease_expires_at);
CREATE INDEX idx_job_events_order
    ON transcription_job_events(job_id, sequence);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=False)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
                )
            if version < 1:
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{_SCHEMA_V1}\nPRAGMA user_version = 1;\nCOMMIT;"
                )
                version = 1
            if version < 2:
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{_MIGRATION_V2}\nPRAGMA user_version = 2;\nCOMMIT;"
                )
                version = 2
            if version < 3:
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{_MIGRATION_V3}\nPRAGMA user_version = 3;\nCOMMIT;"
                )
                version = 3
            if version < 4:
                connection.executescript(
                    f"BEGIN IMMEDIATE;\n{_MIGRATION_V4}\nPRAGMA user_version = 4;\nCOMMIT;"
                )

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def schema_version(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
