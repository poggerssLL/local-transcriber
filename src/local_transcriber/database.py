"""SQLite connection management and idempotent schema migration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 3

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

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            try:
                connection.execute("BEGIN")
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def schema_version(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
