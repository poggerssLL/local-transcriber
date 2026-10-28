"""Private, disabled-by-default loopback gateway for the remote upload flow (Phase 8J-A).

The gateway is a separate FastAPI application that only listens on ``127.0.0.1`` and
exposes a closed allowlist of operations: issue a CSRF session, upload one media file,
create one transcription job for a gateway-owned recording, read job progress and read
the transcript after the job succeeded. It never forwards requests to the core API,
never runs a queue worker (the core ``serve`` process remains the single consumer of
the persistent queue) and never accepts destinations, URLs or paths from the client.

Identity comes from the ``Tailscale-User-Login`` header. That header is only trustworthy
when the request was produced by a restricted local reverse proxy (for example a future
``tailscale serve`` configuration) that strips any client-supplied value. This phase does
not configure or start any tunnel; real exposure requires a later security gate.
"""

from __future__ import annotations

import asyncio
import base64
import errno
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import shutil
import sqlite3
import stat
import time
import unicodedata
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.requests import ClientDisconnect

from .api import _CONTENT_TYPES, _safe_message, _security_headers, _SingleWorkerLock
from .config import AppConfig, RuntimePaths
from .database import Database
from .media import (
    DuplicateMediaError,
    InvalidMediaError,
    MediaImportError,
    MediaImportSettings,
    MediaLibrary,
    MediaTooLargeError,
    UnsupportedMediaError,
    sanitize_filename,
)
from .models import JobStatus, Recording, TranscriptionJob, TranscriptionSettings
from .models_manager import ModelManager, ModelNotInstalledError
from .queueing import TranscriptionQueue
from .repository import Repository

REMOTE_PREFIX = "/remote/v1"
REMOTE_DIRNAME = "remote"
CONFIG_FILENAME = "gateway.json"
SECRET_FILENAME = "csrf.key"
STATE_FILENAME = "gateway.sqlite3"
INCOMING_DIRNAME = "incoming"
LOCK_FILENAME = ".gateway.lock"
IDENTITY_HEADER = "tailscale-user-login"
CSRF_HEADER = "x-csrf-token"
IDEMPOTENCY_HEADER = "idempotency-key"
SESSION_COOKIE = "lt_remote_session"
DEFAULT_PORT = 8766
DEFAULT_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
DEFAULT_MIN_FREE_DISK_BYTES = 1024 * 1024 * 1024
DEFAULT_CSRF_TTL_SECONDS = 3600
DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0
STALE_CLAIM_SECONDS = 900.0
SECRET_BYTES = 32
LOOPBACK_BINDINGS = frozenset({"127.0.0.1", "testserver"})
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}$")
_HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9.\-]{0,251}[a-z0-9])?$")
_MODEL_NAME = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CONFIG_KEYS = frozenset(
    {
        "enabled",
        "allowed_identities",
        "allowed_hosts",
        "allowed_origins",
        "allowed_subjects",
        "subject_id",
        "model_name",
        "profile",
        "language",
        "max_upload_bytes",
        "min_free_disk_bytes",
        "csrf_ttl_seconds",
        "request_timeout_seconds",
    }
)
_REUSABLE_JOB_STATUSES = frozenset({JobStatus.PENDING, JobStatus.RUNNING, JobStatus.SUCCEEDED})
LOGGER = logging.getLogger(__name__)


class RemoteGatewayError(RuntimeError):
    """Base error for the remote gateway configuration and lifecycle."""


class RemoteGatewayDisabledError(RemoteGatewayError):
    """The gateway is not enabled in the runtime configuration."""


class RemoteGatewayConfigError(RemoteGatewayError):
    """The runtime configuration is missing, malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class RemoteGatewayConfig:
    """Validated runtime configuration. Any missing or malformed value fails closed."""

    enabled: bool
    allowed_identities: frozenset[str]
    allowed_hosts: frozenset[str]
    allowed_origins: frozenset[str]
    allowed_subjects: frozenset[str] = frozenset()
    subject_id: str | None = None
    model_name: str = "small"
    profile: str = "auto"
    language: str | None = None
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    min_free_disk_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES
    csrf_ttl_seconds: int = DEFAULT_CSRF_TTL_SECONDS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.allowed_subjects and not self.subject_id:
            raise RemoteGatewayConfigError(
                "either allowed_subjects or subject_id must be configured"
            )
        if not self.allowed_subjects and self.subject_id:
            object.__setattr__(self, "allowed_subjects", frozenset({self.subject_id}))
        elif (
            self.allowed_subjects
            and self.subject_id
            and self.subject_id not in self.allowed_subjects
        ):
            raise RemoteGatewayConfigError("legacy subject_id must be included in allowed_subjects")

    @classmethod
    def from_mapping(cls, raw: object) -> RemoteGatewayConfig:
        if not isinstance(raw, dict):
            raise RemoteGatewayConfigError("gateway configuration must be a JSON object")
        unknown = set(raw) - _CONFIG_KEYS
        if unknown:
            raise RemoteGatewayConfigError("gateway configuration contains unknown keys")
        enabled = raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise RemoteGatewayConfigError("enabled must be a boolean")
        identities = _string_set(raw.get("allowed_identities"), "allowed_identities")
        if any(_IDENTITY.fullmatch(item) is None for item in identities):
            raise RemoteGatewayConfigError("allowed_identities contains a malformed login")
        hosts = frozenset(item.lower() for item in _string_set(raw.get("allowed_hosts"), "hosts"))
        if any(_HOSTNAME.fullmatch(item) is None for item in hosts):
            raise RemoteGatewayConfigError("allowed_hosts must contain bare hostnames")
        origins = _string_set(raw.get("allowed_origins"), "allowed_origins")
        for origin in origins:
            parsed = _parse_origin(origin)
            if parsed is None or parsed[0] != "https" or parsed[1] not in hosts:
                raise RemoteGatewayConfigError(
                    "allowed_origins must be https origins of allowed hosts"
                )
        has_allowed_subjects = "allowed_subjects" in raw
        allowed_subjects: frozenset[str] = frozenset()
        if has_allowed_subjects:
            allowed_subjects = _string_set(raw["allowed_subjects"], "allowed_subjects")
            for item in allowed_subjects:
                if _UUID.fullmatch(item) is None:
                    raise RemoteGatewayConfigError("allowed_subjects contains invalid UUID")

        raw_subject = raw.get("subject_id")
        subject_id: str | None = None
        if raw_subject is not None:
            if not isinstance(raw_subject, str) or _UUID.fullmatch(raw_subject) is None:
                raise RemoteGatewayConfigError("subject_id must be an existing subject UUID")
            subject_id = raw_subject

        if not has_allowed_subjects and subject_id is None:
            raise RemoteGatewayConfigError(
                "either allowed_subjects or subject_id must be configured"
            )

        if not has_allowed_subjects and subject_id is not None:
            allowed_subjects = frozenset({subject_id})
        elif has_allowed_subjects and subject_id is not None:
            if subject_id not in allowed_subjects:
                raise RemoteGatewayConfigError(
                    "legacy subject_id must be included in allowed_subjects"
                )

        model_name = raw.get("model_name", "small")
        if not isinstance(model_name, str) or _MODEL_NAME.fullmatch(model_name) is None:
            raise RemoteGatewayConfigError("model_name is malformed")
        profile = raw.get("profile", "auto")
        if profile not in {"auto", "cpu", "cuda"}:
            raise RemoteGatewayConfigError("profile must be auto, cpu or cuda")
        language = raw.get("language")
        if language is not None and (
            not isinstance(language, str) or re.fullmatch(r"[a-z]{2,3}", language) is None
        ):
            raise RemoteGatewayConfigError("language must be null or an ISO language code")
        max_upload = _bounded_int(
            raw.get("max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES),
            "max_upload_bytes",
            1,
            DEFAULT_MAX_UPLOAD_BYTES,
        )
        min_free = _bounded_int(
            raw.get("min_free_disk_bytes", DEFAULT_MIN_FREE_DISK_BYTES),
            "min_free_disk_bytes",
            0,
            1024**5,
        )
        ttl = _bounded_int(
            raw.get("csrf_ttl_seconds", DEFAULT_CSRF_TTL_SECONDS), "csrf_ttl_seconds", 60, 86400
        )
        timeout = raw.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 1 <= timeout <= 3600
        ):
            raise RemoteGatewayConfigError("request_timeout_seconds must be between 1 and 3600")
        return cls(
            enabled=enabled,
            allowed_identities=identities,
            allowed_hosts=hosts,
            allowed_origins=origins,
            allowed_subjects=allowed_subjects,
            subject_id=subject_id,
            model_name=model_name,
            profile=profile,
            language=language,
            max_upload_bytes=max_upload,
            min_free_disk_bytes=min_free,
            csrf_ttl_seconds=ttl,
            request_timeout_seconds=float(timeout),
        )


def _string_set(value: object, name: str) -> frozenset[str]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise RemoteGatewayConfigError(f"{name} must be a non-empty list")
    if any(not isinstance(item, str) or not item or item != item.strip() for item in value):
        raise RemoteGatewayConfigError(f"{name} must contain non-empty strings")
    return frozenset(value)


def _bounded_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RemoteGatewayConfigError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def _parse_origin(value: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
        or value != f"https://{hostname.lower()}"
    ):
        return None
    return parsed.scheme, hostname.lower()


def remote_dir(paths: RuntimePaths) -> Path:
    return paths.root / REMOTE_DIRNAME


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def _safe_directory(paths: RuntimePaths, directory: Path) -> Path:
    """Create a runtime directory, refusing links and anything outside the runtime."""
    if directory.exists() and _is_link(directory):
        raise RemoteGatewayConfigError("gateway runtime directories must not be links")
    directory.mkdir(parents=True, exist_ok=True)
    if _is_link(directory) or not directory.is_dir():
        raise RemoteGatewayConfigError("gateway runtime directories must not be links")
    resolved = directory.resolve(strict=True)
    if paths.root not in resolved.parents:
        raise RemoteGatewayConfigError("gateway runtime directory escapes the runtime")
    return resolved


def load_remote_config(paths: RuntimePaths) -> RemoteGatewayConfig:
    """Load the runtime configuration. A missing file means disabled (the default)."""
    path = remote_dir(paths) / CONFIG_FILENAME
    try:
        info = os.lstat(path)
    except FileNotFoundError as error:
        raise RemoteGatewayDisabledError("remote gateway is disabled") from error
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
        raise RemoteGatewayConfigError("gateway configuration must be a small regular file")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RemoteGatewayConfigError("gateway configuration is not valid JSON") from error
    config = RemoteGatewayConfig.from_mapping(raw)
    if not config.enabled:
        raise RemoteGatewayDisabledError("remote gateway is disabled")
    return config


def load_or_create_secret(paths: RuntimePaths) -> bytes:
    """Return the CSRF/identity HMAC secret stored outside Git with a restricted ACL."""
    from .chatgpt_auth import secure_file_permissions
    from .exceptions import ChatGPTAuthError

    directory = _safe_directory(paths, remote_dir(paths))
    path = directory / SECRET_FILENAME
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        )
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(secrets.token_bytes(SECRET_BYTES))
    try:
        secure_file_permissions(path)
    except ChatGPTAuthError as error:
        raise RemoteGatewayConfigError("could not restrict the gateway secret") from error
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_size != SECRET_BYTES:
        raise RemoteGatewayConfigError("gateway secret is not a valid regular file")
    secret = path.read_bytes()
    if len(secret) != SECRET_BYTES:
        raise RemoteGatewayConfigError("gateway secret is not valid")
    return secret


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResumableInitRequest(ApiModel):
    filename: str = Field(min_length=1, max_length=255)
    total_bytes: int = Field(strict=True, gt=0)
    enqueue: bool = Field(default=False, strict=True)
    subject_id: str | None = None
    title: str | None = Field(default=None, max_length=500)
    lesson_date: date | None = None

    @field_validator("filename")
    @classmethod
    def valid_filename(cls, value: str) -> str:
        if any(c in "/\\" or unicodedata.category(c) == "Cc" for c in value):
            raise ValueError("invalid_filename")
        return unicodedata.normalize("NFC", value)


class ResumableSessionResponse(ApiModel):
    upload_id: str
    state: str
    total_bytes: int
    current_offset: int
    chunk_bytes: int
    expected_sha256: str
    expires_at: int
    recording_id: str | None = None
    enqueue: bool = False
    queue_state: str | None = None
    job_id: str | None = None
    error_code: str | None = None


class RemoteSessionResponse(ApiModel):
    csrf_token: str
    expires_at: int
    max_upload_bytes: int


class RemoteSubjectResponse(ApiModel):
    id: str
    name: str


class RemoteRecordingResponse(ApiModel):
    id: str
    title: str
    size_bytes: int
    media_format: str
    duration_seconds: float | None
    created_at: datetime


class RemoteJobCreate(ApiModel):
    recording_id: str = Field(min_length=36, max_length=36)


class RemoteJobResponse(ApiModel):
    id: str
    recording_id: str
    status: str
    phase: str
    progress_percent: float | None
    processed_seconds: float
    total_seconds: float | None
    error_message: str | None
    transcript_available: bool
    created_at: datetime
    updated_at: datetime


class RemoteSegmentResponse(ApiModel):
    start_seconds: float
    end_seconds: float
    text: str


class RemoteTranscriptResponse(ApiModel):
    id: str
    job_id: str
    recording_id: str
    language: str | None
    text: str
    segments: list[RemoteSegmentResponse]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _Claim:
    outcome: str
    row: sqlite3.Row | None = None


_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS remote_uploads (
    key_hash TEXT PRIMARY KEY,
    identity_hash TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('receiving', 'importing', 'completed')),
    sha256 TEXT,
    recording_id TEXT,
    claimed_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS remote_uploads_owner
    ON remote_uploads (identity_hash, recording_id);
CREATE UNIQUE INDEX IF NOT EXISTS remote_uploads_completed_recording
    ON remote_uploads (recording_id) WHERE recording_id IS NOT NULL AND state = 'completed';
CREATE TABLE IF NOT EXISTS remote_jobs (
    key_hash TEXT PRIMARY KEY,
    identity_hash TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('creating', 'completed')),
    job_id TEXT,
    claimed_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS remote_jobs_owner ON remote_jobs (identity_hash, job_id);
"""


RESUMABLE_CHUNK_BYTES = 8 * 1024 * 1024
RESUMABLE_TTL = 86400
RESUMABLE_ACTIVE_PER_IDENTITY = 8
RESUMABLE_ACTIVE_GLOBAL = 64
# One running finalization and at most two waiting, bounded before state changes.
RESUMABLE_FINALIZATION_PENDING = 2
RESUMABLE_GC_INTERVAL = 300
_RESUMABLE_ID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RESUMABLE_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS remote_resumable_sessions (
    upload_id TEXT PRIMARY KEY NOT NULL
        CHECK(length(upload_id)=32 AND upload_id NOT GLOB '*[^0-9a-f]*'),
    identity_hash TEXT NOT NULL
        CHECK(length(identity_hash)=64 AND identity_hash NOT GLOB '*[^0-9a-f]*'),
    key_hash TEXT NOT NULL
        CHECK(length(key_hash)=64 AND key_hash NOT GLOB '*[^0-9a-f]*'),
    fingerprint TEXT NOT NULL
        CHECK(length(fingerprint)=64 AND fingerprint NOT GLOB '*[^0-9a-f]*'),
    filename TEXT NOT NULL CHECK(length(filename) BETWEEN 1 AND 255),
    media_extension TEXT NOT NULL CHECK(media_extension IN ('.m4a','.aac','.mp3','.wav')),
    total_bytes INTEGER NOT NULL CHECK(typeof(total_bytes)='integer' AND total_bytes>0),
    chunk_bytes INTEGER NOT NULL
        CHECK(typeof(chunk_bytes)='integer' AND chunk_bytes BETWEEN 1 AND 33554432),
    current_offset INTEGER NOT NULL DEFAULT 0
        CHECK(typeof(current_offset)='integer' AND current_offset BETWEEN 0 AND total_bytes),
    expected_sha256 TEXT NOT NULL
        CHECK(length(expected_sha256)=64 AND expected_sha256 NOT GLOB '*[^0-9a-f]*'),
    validated_sha256 TEXT CHECK(validated_sha256 IS NULL OR validated_sha256=expected_sha256),
    state TEXT NOT NULL DEFAULT 'uploading'
        CHECK(state IN ('uploading','assembling','importing','completed','aborted','expired')),
    enqueue INTEGER NOT NULL DEFAULT 0 CHECK(enqueue IN (0,1)),
    recording_id TEXT,
    import_started_at INTEGER,
    error_code TEXT,
    created_at INTEGER NOT NULL CHECK(created_at>=0),
    updated_at INTEGER NOT NULL CHECK(updated_at>=created_at),
    expires_at INTEGER NOT NULL CHECK(expires_at=created_at+86400),
    cleanup_completed_at INTEGER,
    UNIQUE(identity_hash, key_hash),
    CHECK(state NOT IN ('assembling','importing','completed') OR current_offset=total_bytes),
    CHECK(state NOT IN ('importing','completed') OR validated_sha256 IS NOT NULL),
    CHECK(state NOT IN ('importing','completed') OR import_started_at IS NOT NULL),
    CHECK(recording_id IS NULL OR state IN ('importing','completed')),
    CHECK(state<>'completed' OR recording_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS remote_resumable_chunks (
    upload_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK(typeof(chunk_index)='integer' AND chunk_index>=0),
    offset_start INTEGER NOT NULL CHECK(typeof(offset_start)='integer' AND offset_start>=0),
    size_bytes INTEGER NOT NULL CHECK(typeof(size_bytes)='integer' AND size_bytes>0),
    sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    committed_at INTEGER NOT NULL CHECK(committed_at>=0),
    PRIMARY KEY(upload_id, chunk_index),
    UNIQUE(upload_id, offset_start),
    FOREIGN KEY(upload_id) REFERENCES remote_resumable_sessions(upload_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_resumable_sessions_gc
    ON remote_resumable_sessions(state, expires_at);
CREATE INDEX IF NOT EXISTS idx_resumable_sessions_identity
    ON remote_resumable_sessions(identity_hash, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_resumable_recording
    ON remote_resumable_sessions(recording_id) WHERE recording_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS remote_gateway_schema_migrations (
    name TEXT PRIMARY KEY NOT NULL,
    applied_at INTEGER NOT NULL CHECK(applied_at>=0)
);
CREATE TABLE IF NOT EXISTS remote_resumable_metadata (
    upload_id TEXT PRIMARY KEY NOT NULL
        REFERENCES remote_resumable_sessions(upload_id) ON DELETE RESTRICT,
    subject_id TEXT NOT NULL,
    title TEXT NOT NULL,
    lesson_date TEXT NOT NULL
);
"""


class GatewayStateStore:
    """Idempotency and ownership metadata kept in the gateway's own SQLite file.

    The core database (schema v4) is not modified. Keys are namespaced per identity and
    stored only as HMAC digests. Resumable filenames and import metadata stay in this
    isolated runtime database; audio bytes and raw logins are never persisted here.
    """

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.clock = clock

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _immediate(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"BEGIN IMMEDIATE;\n{_STATE_SCHEMA}\n{_RESUMABLE_SCHEMA_V1}\nCOMMIT;"
            )
            connection.execute(
                "INSERT OR IGNORE INTO remote_gateway_schema_migrations VALUES (?, ?)",
                ("resumable_v1", int(self.clock())),
            )
            connection.execute("PRAGMA user_version = 1")

    def resumable(self, upload_id: str, identity_hash: str | None = None) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                """SELECT s.*, m.subject_id, m.title, m.lesson_date
                   FROM remote_resumable_sessions s
                   JOIN remote_resumable_metadata m USING (upload_id)
                   WHERE s.upload_id = ? AND (? IS NULL OR s.identity_hash = ?)""",
                (upload_id, identity_hash, identity_hash),
            ).fetchone()

    def resumable_rows(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM remote_resumable_sessions").fetchall()

    def resumable_reserved_bytes(self) -> int:
        with self._connect() as connection:
            return connection.execute(
                """SELECT COALESCE(SUM(3 * total_bytes), 0) FROM remote_resumable_sessions
                   WHERE state IN ('uploading','assembling','importing')"""
            ).fetchone()[0]

    def resumable_init(
        self,
        identity_hash: str,
        key_hash: str,
        fingerprint: str,
        body: ResumableInitRequest,
        expected_sha256: str,
        subject_id: str,
        free_bytes: int,
        min_free_bytes: int,
    ) -> tuple[sqlite3.Row, bool]:
        now = int(self.clock())
        with self._immediate() as connection:
            # Expire inactive uploads atomically before checking counts/reservations.
            # Busy assemblies and ambiguous imports keep their conservative reservation.
            connection.execute(
                """UPDATE remote_resumable_sessions
                   SET state = 'expired', updated_at = ?, error_code = 'session_expired'
                   WHERE state = 'uploading' AND expires_at <= ?""",
                (now, now),
            )
            old = connection.execute(
                """SELECT * FROM remote_resumable_sessions
                   WHERE identity_hash = ? AND key_hash = ?""",
                (identity_hash, key_hash),
            ).fetchone()
            if old is not None:
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409, "idempotency_conflict")
                return old, False
            counts = connection.execute(
                """SELECT COUNT(*), COALESCE(SUM(identity_hash = ?), 0)
                   FROM remote_resumable_sessions
                   WHERE state IN ('uploading','assembling','importing')""",
                (identity_hash,),
            ).fetchone()
            if counts[0] >= RESUMABLE_ACTIVE_GLOBAL or counts[1] >= RESUMABLE_ACTIVE_PER_IDENTITY:
                raise HTTPException(
                    429, "active_session_limit_reached", headers={"Retry-After": "2"}
                )
            reservations = connection.execute(
                """SELECT COALESCE(SUM(3 * total_bytes), 0) FROM remote_resumable_sessions
                   WHERE state IN ('uploading','assembling','importing')"""
            ).fetchone()[0]
            if free_bytes < min_free_bytes + reservations + 3 * body.total_bytes:
                raise HTTPException(507, "insufficient_storage")
            upload_id = uuid4().hex
            connection.execute(
                """INSERT INTO remote_resumable_sessions
                   (upload_id,identity_hash,key_hash,fingerprint,filename,media_extension,
                    total_bytes,chunk_bytes,expected_sha256,enqueue,created_at,updated_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    upload_id,
                    identity_hash,
                    key_hash,
                    fingerprint,
                    body.filename,
                    Path(body.filename).suffix.lower(),
                    body.total_bytes,
                    RESUMABLE_CHUNK_BYTES,
                    expected_sha256,
                    int(body.enqueue),
                    now,
                    now,
                    now + RESUMABLE_TTL,
                ),
            )
            connection.execute(
                "INSERT INTO remote_resumable_metadata VALUES (?,?,?,?)",
                (
                    upload_id,
                    subject_id,
                    body.title or Path(body.filename).stem,
                    (body.lesson_date or date.today()).isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM remote_resumable_sessions WHERE upload_id = ?",
                (upload_id,),
            ).fetchone()
            return row, True

    def resumable_transition(
        self,
        upload_id: str,
        previous: str,
        state: str,
        *,
        error_code: str | None = None,
        digest: str | None = None,
        recording_id: str | None = None,
    ) -> bool:
        now = int(self.clock())
        with self._immediate() as connection:
            result = connection.execute(
                """UPDATE remote_resumable_sessions SET state = ?, updated_at = ?,
                   error_code = ?, validated_sha256 = COALESCE(?, validated_sha256),
                   import_started_at = CASE WHEN ? = 'importing' THEN COALESCE(import_started_at, ?)
                       ELSE import_started_at END,
                   recording_id = COALESCE(?, recording_id)
                   WHERE upload_id = ? AND state = ?""",
                (state, now, error_code, digest, state, now, recording_id, upload_id, previous),
            )
            return result.rowcount == 1

    def resumable_chunks(self, upload_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                """SELECT * FROM remote_resumable_chunks
                   WHERE upload_id = ? ORDER BY chunk_index""",
                (upload_id,),
            ).fetchall()

    def resumable_commit_chunk(
        self,
        row: sqlite3.Row,
        size: int,
        digest: str,
        chunk_index: int,
    ) -> None:
        now = int(self.clock())
        with self._immediate() as connection:
            result = connection.execute(
                """UPDATE remote_resumable_sessions
                   SET current_offset = current_offset + ?, updated_at = ?
                   WHERE upload_id = ? AND state = 'uploading' AND current_offset = ?
                       AND expires_at > ?""",
                (size, now, row["upload_id"], row["current_offset"], now),
            )
            if result.rowcount != 1:
                raise HTTPException(409, "session_changed")
            connection.execute(
                "INSERT INTO remote_resumable_chunks VALUES (?,?,?,?,?,?)",
                (row["upload_id"], chunk_index, row["current_offset"], size, digest, now),
            )

    def resumable_cleaned(self, upload_id: str) -> None:
        with self._immediate() as connection:
            connection.execute(
                """UPDATE remote_resumable_sessions SET cleanup_completed_at = ?
                   WHERE upload_id = ?""",
                (int(self.clock()), upload_id),
            )

    def resumable_forget(self, upload_id: str) -> None:
        with self._immediate() as connection:
            connection.execute(
                "DELETE FROM remote_resumable_chunks WHERE upload_id = ?", (upload_id,)
            )
            connection.execute(
                "DELETE FROM remote_resumable_metadata WHERE upload_id = ?", (upload_id,)
            )
            connection.execute(
                """DELETE FROM remote_resumable_sessions WHERE upload_id = ?
                   AND cleanup_completed_at IS NOT NULL
                   AND state IN ('completed','aborted','expired')""",
                (upload_id,),
            )

    def claim_upload(
        self,
        key_hash: str,
        identity_hash: str,
        fingerprint: str,
        *,
        legacy_fingerprint: str | None = None,
    ) -> _Claim:
        now = self.clock()
        with self._immediate() as connection:
            row = connection.execute(
                "SELECT * FROM remote_uploads WHERE key_hash = ?", (key_hash,)
            ).fetchone()
            if row is None:
                connection.execute(
                    """INSERT INTO remote_uploads
                       (key_hash, identity_hash, fingerprint, state, claimed_at, updated_at)
                       VALUES (?, ?, ?, 'receiving', ?, ?)""",
                    (key_hash, identity_hash, fingerprint, now, now),
                )
                return _Claim("claimed")
            if row["identity_hash"] != identity_hash:
                return _Claim("mismatch")
            if legacy_fingerprint is not None and row["fingerprint"] == legacy_fingerprint:
                return _Claim("legacy", row)
            if row["fingerprint"] != fingerprint:
                return _Claim("mismatch")
            if row["state"] == "completed":
                return _Claim("completed", row)
            if row["state"] == "importing":
                if now - row["claimed_at"] < STALE_CLAIM_SECONDS:
                    return _Claim("busy")
                return _Claim("verify", row)
            if now - row["claimed_at"] < STALE_CLAIM_SECONDS:
                return _Claim("busy")
            connection.execute(
                """UPDATE remote_uploads SET state = 'receiving', sha256 = NULL,
                   claimed_at = ?, updated_at = ? WHERE key_hash = ?""",
                (now, now, key_hash),
            )
            return _Claim("claimed")

    def reclaim_stale_import(self, key_hash: str) -> bool:
        now = self.clock()
        with self._immediate() as connection:
            updated = connection.execute(
                """UPDATE remote_uploads SET state = 'receiving', sha256 = NULL,
                   claimed_at = ?, updated_at = ?
                   WHERE key_hash = ? AND state = 'importing' AND claimed_at <= ?""",
                (now, now, key_hash, now - STALE_CLAIM_SECONDS),
            )
            return updated.rowcount == 1

    def mark_importing(self, key_hash: str, sha256: str) -> None:
        now = self.clock()
        with self._immediate() as connection:
            connection.execute(
                """UPDATE remote_uploads SET state = 'importing', sha256 = ?,
                   claimed_at = ?, updated_at = ? WHERE key_hash = ? AND state = 'receiving'""",
                (sha256, now, now, key_hash),
            )

    def complete_upload(self, key_hash: str, recording_id: str) -> None:
        now = self.clock()
        with self._immediate() as connection:
            current = connection.execute(
                "SELECT identity_hash FROM remote_uploads WHERE key_hash = ?", (key_hash,)
            ).fetchone()
            if current is None:
                raise RemoteGatewayError("upload key not found")
            identity_hash = current["identity_hash"]
            conflict = connection.execute(
                """SELECT 1 FROM remote_uploads
                   WHERE recording_id = ? AND identity_hash != ? AND state = 'completed' LIMIT 1""",
                (recording_id, identity_hash),
            ).fetchone()
            if conflict is not None:
                raise RemoteGatewayError("recording is already owned by a different identity")
            connection.execute(
                """UPDATE remote_uploads SET state = 'completed', recording_id = ?,
                   updated_at = ? WHERE key_hash = ?""",
                (recording_id, now, key_hash),
            )

    def release_upload(self, key_hash: str) -> None:
        with self._immediate() as connection:
            connection.execute(
                "DELETE FROM remote_uploads WHERE key_hash = ? AND state != 'completed'",
                (key_hash,),
            )

    def owns_recording(self, identity_hash: str, recording_id: str) -> bool:
        with self._connect() as connection:
            other = connection.execute(
                """SELECT 1 FROM remote_uploads WHERE identity_hash != ? AND recording_id = ?
                   AND state = 'completed' UNION ALL
                   SELECT 1 FROM remote_resumable_sessions WHERE identity_hash != ?
                   AND recording_id = ? AND state IN ('importing','completed') LIMIT 1""",
                (identity_hash, recording_id, identity_hash, recording_id),
            ).fetchone()
            if other is not None:
                return False
            row = connection.execute(
                """SELECT 1 FROM remote_uploads WHERE identity_hash = ? AND recording_id = ?
                   AND state = 'completed' UNION ALL
                   SELECT 1 FROM remote_resumable_sessions WHERE identity_hash = ?
                   AND recording_id = ? AND state IN ('importing','completed') LIMIT 1""",
                (identity_hash, recording_id, identity_hash, recording_id),
            ).fetchone()
        return row is not None

    def claim_job(self, key_hash: str, identity_hash: str, recording_id: str) -> _Claim:
        now = self.clock()
        with self._immediate() as connection:
            row = connection.execute(
                "SELECT * FROM remote_jobs WHERE key_hash = ?", (key_hash,)
            ).fetchone()
            if row is None:
                connection.execute(
                    """INSERT INTO remote_jobs
                       (key_hash, identity_hash, recording_id, state, claimed_at, updated_at)
                       VALUES (?, ?, ?, 'creating', ?, ?)""",
                    (key_hash, identity_hash, recording_id, now, now),
                )
                return _Claim("claimed")
            if row["identity_hash"] != identity_hash or row["recording_id"] != recording_id:
                return _Claim("mismatch")
            if row["state"] == "completed":
                return _Claim("completed", row)
            # A 'creating' row can be resumed: the per-recording reuse check makes the
            # retry safe even if a previous attempt enqueued before crashing.
            connection.execute(
                "UPDATE remote_jobs SET claimed_at = ?, updated_at = ? WHERE key_hash = ?",
                (now, now, key_hash),
            )
            return _Claim("claimed")

    def complete_job(self, key_hash: str, job_id: str) -> None:
        now = self.clock()
        with self._immediate() as connection:
            connection.execute(
                """UPDATE remote_jobs SET state = 'completed', job_id = ?, updated_at = ?
                   WHERE key_hash = ?""",
                (job_id, now, key_hash),
            )

    def release_job(self, key_hash: str) -> None:
        with self._immediate() as connection:
            connection.execute(
                "DELETE FROM remote_jobs WHERE key_hash = ? AND state = 'creating'", (key_hash,)
            )

    def owns_job(self, identity_hash: str, job_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM remote_jobs WHERE identity_hash = ? AND job_id = ?
                   AND state = 'completed' LIMIT 1""",
                (identity_hash, job_id),
            ).fetchone()
        return row is not None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class CsrfSigner:
    """Expiring CSRF tokens bound to the identity digest and a per-session cookie."""

    def __init__(self, secret: bytes, ttl_seconds: int, clock: Callable[[], float]) -> None:
        self.secret = secret
        self.ttl_seconds = ttl_seconds
        self.clock = clock

    def _mac(self, identity_hash: str, session_id: str, expires: int) -> str:
        message = f"csrf|{identity_hash}|{session_id}|{expires}".encode("ascii")
        return _b64(hmac.new(self.secret, message, hashlib.sha256).digest())

    def issue(self, identity_hash: str) -> tuple[str, str, int]:
        expires = int(self.clock()) + self.ttl_seconds
        nonce = secrets.token_urlsafe(32)
        session_id = f"{nonce}.{expires}.{self._mac(identity_hash, 'cookie|' + nonce, expires)}"
        return session_id, f"{expires}.{self._mac(identity_hash, session_id, expires)}", expires

    def verify_cookie(self, identity_hash: str, session_id: str | None) -> bool:
        if not session_id or len(session_id) > 128:
            return False
        parts = session_id.split(".")
        if len(parts) != 3:
            return False
        nonce, expires_text, mac = parts
        if re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce) is None:
            return False
        if not expires_text.isdigit() or len(expires_text) > 12:
            return False
        expires = int(expires_text)
        if expires <= self.clock() or expires - self.clock() > self.ttl_seconds:
            return False
        expected = self._mac(identity_hash, "cookie|" + nonce, expires)
        return hmac.compare_digest(expected.encode("ascii"), mac.encode("ascii", "replace"))

    def verify(self, identity_hash: str, session_id: str | None, token: str | None) -> bool:
        if not session_id or not token or len(token) > 256 or len(session_id) > 128:
            return False
        if not self.verify_cookie(identity_hash, session_id):
            return False
        expires_text, separator, mac = token.partition(".")
        if not separator or not expires_text.isdigit() or len(expires_text) > 12:
            return False
        expires = int(expires_text)
        now = self.clock()
        if expires <= now or expires - now > self.ttl_seconds:
            return False
        expected = self._mac(identity_hash, session_id, expires)
        return hmac.compare_digest(expected.encode("ascii"), mac.encode("ascii", "replace"))


@dataclass
class _IdentityBucket:
    read_tokens: float
    read_updated: float
    mutation_tokens: float
    mutation_updated: float
    last_seen: float


class InMemoryRateLimiter:
    """Bounded in-memory rate limiter using token buckets indexed by identity_hash.

    Groups:
    - 'read': burst 30 tokens, refills at 0.5 tokens/sec (30 tokens per 60s).
    - 'mutation': burst 5 tokens, refills at 1/12 tokens/sec (5 tokens per 60s).
    Capacity: bounded to 100 identities, TTL of 300s.
    """

    MAX_IDENTITIES = 100
    TTL_SECONDS = 300.0

    READ_BURST = 30.0
    READ_REFILL_RATE = 0.5  # 30 tokens per 60 seconds

    MUTATION_BURST = 5.0
    MUTATION_REFILL_RATE = 1.0 / 12.0  # 5 tokens per 60 seconds (1 token / 12s)

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._identities: dict[str, _IdentityBucket] = {}

    def acquire(self, identity_hash: str, group: str) -> tuple[bool, int]:
        """Attempt to acquire a token for group ('read' or 'mutation').

        Returns (allowed, retry_after_seconds). If allowed is True, retry_after is 0.
        If allowed is False, retry_after is a positive integer.
        """
        now = self._clock()
        with self._lock:
            cutoff = now - self.TTL_SECONDS
            expired = [k for k, v in self._identities.items() if v.last_seen < cutoff]
            for k in expired:
                del self._identities[k]

            bucket = self._identities.get(identity_hash)
            if bucket is None:
                if len(self._identities) >= self.MAX_IDENTITIES:
                    oldest_expiry = min(
                        v.last_seen + self.TTL_SECONDS for v in self._identities.values()
                    )
                    retry_after = max(1, math.ceil(oldest_expiry - now))
                    return False, retry_after
                bucket = _IdentityBucket(
                    read_tokens=self.READ_BURST,
                    read_updated=now,
                    mutation_tokens=self.MUTATION_BURST,
                    mutation_updated=now,
                    last_seen=now,
                )
                self._identities[identity_hash] = bucket

            bucket.last_seen = now

            if group == "mutation":
                elapsed = max(0.0, now - bucket.mutation_updated)
                tokens = min(
                    self.MUTATION_BURST,
                    bucket.mutation_tokens + elapsed * self.MUTATION_REFILL_RATE,
                )
                bucket.mutation_updated = now
                if tokens >= 1.0:
                    bucket.mutation_tokens = tokens - 1.0
                    return True, 0
                bucket.mutation_tokens = tokens
                needed = 1.0 - tokens
                retry_after = max(1, math.ceil(needed / self.MUTATION_REFILL_RATE))
                return False, retry_after
            else:
                elapsed = max(0.0, now - bucket.read_updated)
                tokens = min(
                    self.READ_BURST,
                    bucket.read_tokens + elapsed * self.READ_REFILL_RATE,
                )
                bucket.read_updated = now
                if tokens >= 1.0:
                    bucket.read_tokens = tokens - 1.0
                    return True, 0
                bucket.read_tokens = tokens
                needed = 1.0 - tokens
                retry_after = max(1, math.ceil(needed / self.READ_REFILL_RATE))
                return False, retry_after


def _decode_header_text(value: str | None, name: str, *, maximum: int) -> str:
    if value is None:
        raise HTTPException(400, f"missing {name} header")
    try:
        decoded = unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise HTTPException(400, f"malformed {name} header") from error
    if not decoded.strip() or len(decoded) > maximum or re.search(r"[\x00-\x1f\x7f]", decoded):
        raise HTTPException(400, f"malformed {name} header")
    return decoded.strip()


def _single_header(request: Request, name: str) -> str | None:
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise HTTPException(400, f"duplicated {name} header")
    return values[0] if values else None


def _recording_payload(recording: Recording) -> RemoteRecordingResponse:
    return RemoteRecordingResponse(
        id=recording.id,
        title=recording.title,
        size_bytes=recording.size_bytes,
        media_format=recording.media_format,
        duration_seconds=recording.duration_seconds,
        created_at=recording.created_at,
    )


def _error(status: int, detail: str, headers: Mapping[str, str] | None = None) -> JSONResponse:
    response = JSONResponse({"detail": detail}, status_code=status, headers=headers)
    _security_headers(response)
    return response


def _staging_path(incoming: Path, upload_id: str, *parts: str) -> Path:
    """Confine every operation and reject Windows reparse points, including ancestors."""
    if _RESUMABLE_ID.fullmatch(upload_id) is None:
        raise HTTPException(404, "upload_not_found")
    target = incoming / upload_id
    for part in parts:
        if Path(part).name != part or part in {".", ".."}:
            raise RemoteGatewayConfigError("invalid staging path")
        target /= part
    for candidate in (target, *target.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if _is_link(candidate) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise RemoteGatewayConfigError("staging reparse point refused")
        if candidate == incoming.parent.parent:
            break
    if incoming.resolve() not in target.resolve().parents:
        raise RemoteGatewayConfigError("staging path escapes incoming")
    return target


def _purge_staging(incoming: Path, upload_id: str) -> None:
    directory = _staging_path(incoming, upload_id)
    if not directory.exists():
        return

    def remove(path: Path) -> None:
        relative = path.relative_to(directory)
        checked = _staging_path(incoming, upload_id, *relative.parts)
        if checked.is_dir():
            for child in checked.iterdir():
                remove(child)
            checked.rmdir()
        else:
            checked.unlink()

    remove(directory)


async def _receive_resumable_chunk(
    request: Request,
    destination: Path,
    size: int,
    expected_hash: str,
    timeout: float,
) -> None:
    received = 0
    digest = hashlib.sha256()
    try:
        async with asyncio.timeout(timeout):
            with destination.open("xb") as output:
                async for data in request.stream():
                    for start in range(0, len(data), 1024 * 1024):
                        block = memoryview(data)[start : start + 1024 * 1024]
                        received += len(block)
                        if received > size:
                            raise HTTPException(413, "chunk_too_large")
                        output.write(block)
                        digest.update(block)
                if received != size:
                    raise HTTPException(400, "chunk_interrupted")
                if digest.hexdigest() != expected_hash:
                    raise HTTPException(422, "chunk_hash_mismatch")
                output.flush()
                os.fsync(output.fileno())
    except TimeoutError as error:
        raise HTTPException(408, "chunk_timeout") from error
    except ClientDisconnect as error:
        raise HTTPException(400, "chunk_interrupted") from error


def create_remote_gateway_app(
    config: AppConfig | None = None,
    *,
    gateway_config: RemoteGatewayConfig | None = None,
    model_manager: ModelManager | None = None,
    clock: Callable[[], float] = time.time,
    rate_limit_clock: Callable[[], float] | None = None,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> FastAPI:
    """Build the loopback-only gateway. Raises when disabled or misconfigured."""
    app_config = config or AppConfig.from_env()
    paths = app_config.paths
    settings = gateway_config or load_remote_config(paths)
    if not settings.enabled:
        raise RemoteGatewayDisabledError("remote gateway is disabled")
    base = _safe_directory(paths, remote_dir(paths))
    incoming = _safe_directory(paths, base / INCOMING_DIRNAME)
    secret = load_or_create_secret(paths)
    database = Database(paths.database)
    repository = Repository(database)
    models = model_manager or ModelManager(paths)
    library = MediaLibrary(
        repository,
        paths,
        settings=MediaImportSettings(max_size_bytes=settings.max_upload_bytes),
    )
    queue = TranscriptionQueue(repository, paths, models=models)
    store = GatewayStateStore(base / STATE_FILENAME, clock=clock)
    signer = CsrfSigner(secret, settings.csrf_ttl_seconds, clock)
    limiter_clock = (
        rate_limit_clock
        if rate_limit_clock is not None
        else (clock if clock is not time.time else time.monotonic)
    )
    rate_limiter = InMemoryRateLimiter(clock=limiter_clock)
    gateway_lock = _SingleWorkerLock(base / LOCK_FILENAME)
    job_lock = Lock()
    upload_lock = asyncio.Lock()
    resumable_busy: set[str] = set()
    resumable_tasks: dict[str, asyncio.Task[None]] = {}
    finalization_slot = asyncio.Semaphore(1)
    busy_guard = Lock()
    gc_stop = asyncio.Event()

    @contextmanager
    def session_operation(upload_id: str) -> Iterator[None]:
        with busy_guard:
            if upload_id in resumable_busy:
                raise HTTPException(409, "session_busy")
            resumable_busy.add(upload_id)
        try:
            yield
        finally:
            with busy_guard:
                resumable_busy.discard(upload_id)

    def cleanup_session(upload_id: str) -> None:
        _purge_staging(incoming, upload_id)
        store.resumable_cleaned(upload_id)

    def collect_resumable(*, startup: bool = False) -> None:
        now = int(clock())
        rows = store.resumable_rows()
        known = {row["upload_id"] for row in rows}
        for row in rows:
            upload_id = row["upload_id"]
            try:
                with session_operation(upload_id):
                    row = store.resumable(upload_id)
                    if row is None:
                        continue
                    state = row["state"]
                    if state in {"uploading", "assembling"} and row["expires_at"] <= now:
                        store.resumable_transition(
                            upload_id, state, "expired", error_code="session_expired"
                        )
                        state = "expired"
                    if state == "importing":
                        if startup:
                            store.resumable_transition(
                                upload_id,
                                "importing",
                                "importing",
                                error_code=(
                                    "import_outcome_unknown"
                                    if row["recording_id"] is None
                                    else "completion_pending"
                                ),
                            )
                        continue
                    if state in {"aborted", "expired", "completed"}:
                        cleanup_session(upload_id)
                        if now >= max(row["expires_at"], row["updated_at"]) + 7 * 86400:
                            store.resumable_forget(upload_id)
                        continue
                    if not startup:
                        continue
                    if state == "assembling":
                        store.resumable_transition(upload_id, "assembling", "uploading")
                    directory = _staging_path(incoming, upload_id, "chunks")
                    directory.mkdir(parents=True, exist_ok=True)
                    chunks = store.resumable_chunks(upload_id)
                    committed = {f"{chunk['chunk_index']:08d}.chunk" for chunk in chunks}
                    offset = 0
                    valid = True
                    for index, chunk in enumerate(chunks):
                        file = _staging_path(incoming, upload_id, "chunks", f"{index:08d}.chunk")
                        if (
                            chunk["chunk_index"] != index
                            or chunk["offset_start"] != offset
                            or not file.is_file()
                            or file.stat().st_size != chunk["size_bytes"]
                        ):
                            valid = False
                            break
                        digest = hashlib.sha256()
                        with file.open("rb") as stream:
                            while block := stream.read(1024 * 1024):
                                digest.update(block)
                        if digest.hexdigest() != chunk["sha256"]:
                            valid = False
                            break
                        offset += chunk["size_bytes"]
                    if not valid or offset != row["current_offset"]:
                        store.resumable_transition(
                            upload_id,
                            "uploading",
                            "aborted",
                            error_code="staging_corrupt",
                        )
                        cleanup_session(upload_id)
                        continue
                    for child in directory.iterdir():
                        if child.name not in committed:
                            checked = _staging_path(incoming, upload_id, "chunks", child.name)
                            if checked.is_file():
                                checked.unlink()
                    for name in ("assembled.part", f"assembled{row['media_extension']}"):
                        _staging_path(incoming, upload_id, name).unlink(missing_ok=True)
            except HTTPException as error:
                if error.status_code != 409:
                    LOGGER.error("resumable GC refused unsafe staging")
            except OSError:
                LOGGER.warning("resumable GC session I/O failed; retry next cycle")
        for directory in incoming.iterdir():
            try:
                if (
                    _RESUMABLE_ID.fullmatch(directory.name)
                    and directory.name not in known
                    and store.resumable(directory.name) is None
                ):
                    _purge_staging(incoming, directory.name)
            except (OSError, HTTPException):
                LOGGER.warning("resumable GC directory unavailable; retry next cycle")

    async def resumable_gc() -> None:
        while not gc_stop.is_set():
            try:
                await asyncio.wait_for(gc_stop.wait(), timeout=RESUMABLE_GC_INTERVAL)
            except TimeoutError:
                try:
                    await asyncio.to_thread(collect_resumable)
                    app.state.resumable_gc_error = False
                except (OSError, HTTPException):
                    LOGGER.warning("resumable GC I/O failed; retry next cycle")
                except sqlite3.Error:
                    app.state.resumable_gc_error = True
                    LOGGER.error("resumable GC database unavailable; requests fail closed")

    def owned_session(upload_id: str, identity_hash: str) -> sqlite3.Row:
        row = store.resumable(upload_id, identity_hash)
        if row is None:
            raise HTTPException(404, "upload_not_found")
        if row["state"] in {"uploading", "assembling"} and row["expires_at"] <= int(clock()):
            try:
                with session_operation(upload_id):
                    if store.resumable_transition(
                        upload_id,
                        row["state"],
                        "expired",
                        error_code="session_expired",
                    ):
                        cleanup_session(upload_id)
            except HTTPException as error:
                if error.status_code != 409:
                    raise
                raise HTTPException(410, "session_expired", headers=session_headers(row)) from error
            row = store.resumable(upload_id, identity_hash)
            assert row is not None
        headers = session_headers(row)
        if row["state"] in {"aborted", "expired"}:
            if row["cleanup_completed_at"] is None:
                try:
                    with session_operation(upload_id):
                        cleanup_session(upload_id)
                except (HTTPException, OSError):
                    # A cancelled assembly/PATCH may still own its files. GC retries.
                    LOGGER.warning("resumable terminal cleanup deferred")
            raise HTTPException(
                410, row["error_code"] or f"session_{row['state']}", headers=headers
            )
        if row["state"] == "importing" and row["error_code"] == "import_outcome_unknown":
            raise HTTPException(409, "import_outcome_unknown", headers=headers)
        return row

    def session_headers(row: sqlite3.Row) -> dict[str, str]:
        return {
            "Current-Offset": str(row["current_offset"]),
            "Upload-Expires": str(row["expires_at"]),
        }

    def session_payload(row: sqlite3.Row) -> ResumableSessionResponse:
        values = {
            name: row[name] for name in ResumableSessionResponse.model_fields if name in row.keys()
        }
        if row["recording_id"] is not None and row["enqueue"]:
            jobs = [
                job for job in repository.list_jobs() if job.recording_id == row["recording_id"]
            ]
            if jobs:
                job = max(jobs, key=lambda item: item.created_at)
                values.update(job_id=job.id, queue_state=job.status.value)
        return ResumableSessionResponse(**values)

    def hash_header(request: Request, name: str) -> str:
        value = _single_header(request, name)
        if value is None or _SHA256.fullmatch(value) is None:
            raise HTTPException(400, "invalid_hash_header")
        return value

    def assemble_resumable(row: sqlite3.Row) -> Path | None:
        upload_id = row["upload_id"]
        destination = _staging_path(incoming, upload_id, "assembled.part")
        digest = hashlib.sha256()
        received = 0
        with destination.open("wb") as output:
            for index, chunk in enumerate(store.resumable_chunks(upload_id)):
                if chunk["chunk_index"] != index or chunk["offset_start"] != received:
                    raise RemoteGatewayError("invalid chunk manifest")
                source = _staging_path(incoming, upload_id, "chunks", f"{index:08d}.chunk")
                chunk_digest = hashlib.sha256()
                size = 0
                with source.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
                        chunk_digest.update(block)
                        size += len(block)
                        output.write(block)
                if size != chunk["size_bytes"] or chunk_digest.hexdigest() != chunk["sha256"]:
                    raise RemoteGatewayError("invalid persisted chunk")
                received += size
            output.flush()
            os.fsync(output.fileno())
        if received != row["total_bytes"] or digest.hexdigest() != row["expected_sha256"]:
            store.resumable_transition(
                upload_id,
                "assembling",
                "aborted",
                error_code="final_hash_mismatch",
            )
            cleanup_session(upload_id)
            return None
        final = _staging_path(incoming, upload_id, f"assembled{row['media_extension']}")
        os.replace(destination, final)
        if row["expires_at"] <= int(clock()):
            store.resumable_transition(
                upload_id,
                "assembling",
                "expired",
                error_code="session_expired",
            )
        if not store.resumable_transition(
            upload_id,
            "assembling",
            "importing",
            digest=digest.hexdigest(),
        ):
            cleanup_session(upload_id)
            return None
        return final

    async def finish_resumable(row: sqlite3.Row) -> None:
        upload_id = row["upload_id"]
        acquired = False
        try:
            await finalization_slot.acquire()
            acquired = True
            current = store.resumable(upload_id)
            if current is None or current["state"] != "assembling":
                return
            final = await asyncio.to_thread(assemble_resumable, row)
            if final is None:
                return

            def import_media() -> Recording:
                checked = _staging_path(incoming, upload_id, final.name)
                with checked.open("rb") as stream:
                    return library.import_stream(
                        stream,
                        original_name=row["filename"],
                        title=row["title"],
                        subject_id=row["subject_id"],
                        lesson_date=date.fromisoformat(row["lesson_date"]),
                    )

            try:
                recording = await asyncio.to_thread(import_media)
            except (
                DuplicateMediaError,
                InvalidMediaError,
                UnsupportedMediaError,
                MediaTooLargeError,
            ):
                # These Core exceptions are raised before add_recording/commit.
                # Other exceptions remain ambiguous, including failures after commit.
                store.resumable_transition(
                    upload_id, "importing", "aborted", error_code="media_rejected"
                )
                await asyncio.to_thread(cleanup_session, upload_id)
                return
            if not store.resumable_transition(
                upload_id,
                "importing",
                "importing",
                recording_id=recording.id,
            ):
                raise RemoteGatewayError("import completion could not be recorded")
            if row["enqueue"]:
                await asyncio.to_thread(
                    _create_job,
                    row["identity_hash"],
                    key_digest(row["identity_hash"], f"resumable-job-{upload_id}"),
                    recording.id,
                )
            if not store.resumable_transition(upload_id, "importing", "completed"):
                raise RemoteGatewayError("import completion could not be recorded")
            await asyncio.to_thread(cleanup_session, upload_id)
        except Exception:
            current = store.resumable(upload_id)
            if current is not None:
                state = current["state"]
                if state == "assembling":
                    store.resumable_transition(
                        upload_id,
                        state,
                        "aborted",
                        error_code="assembly_failed",
                    )
                    await asyncio.to_thread(cleanup_session, upload_id)
                elif state == "importing":
                    store.resumable_transition(
                        upload_id,
                        state,
                        state,
                        error_code=(
                            "import_outcome_unknown"
                            if current["recording_id"] is None
                            else "queue_unavailable"
                        ),
                    )
                elif state == "completed":
                    store.resumable_transition(
                        upload_id,
                        state,
                        state,
                        error_code="cleanup_pending",
                    )
                    await asyncio.to_thread(cleanup_session, upload_id)
            LOGGER.error("resumable processing failed for upload %s", upload_id)
        finally:
            if acquired:
                finalization_slot.release()
            with busy_guard:
                resumable_busy.discard(upload_id)
            resumable_tasks.pop(upload_id, None)

    def identity_digest(identity: str) -> str:
        return hmac.new(secret, f"identity|{identity}".encode(), hashlib.sha256).hexdigest()

    def key_digest(identity_hash: str, key: str) -> str:
        return hmac.new(
            secret, f"key|{identity_hash}|{key}".encode("ascii"), hashlib.sha256
        ).hexdigest()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        paths.ensure_directories()
        database.initialize()
        for sub_id in sorted(settings.allowed_subjects):
            if repository.get_subject(sub_id) is None:
                raise RemoteGatewayConfigError(
                    f"configured subject '{sub_id}' does not exist on notebook"
                )
        gateway_lock.acquire()
        try:
            store.initialize()
            # Only one gateway process owns this directory, so leftovers are orphans.
            for leftover in incoming.glob("*.part"):
                if leftover.is_file() and not _is_link(leftover):
                    leftover.unlink(missing_ok=True)
            await asyncio.to_thread(collect_resumable, startup=True)
            gc_stop.clear()
            collector = asyncio.create_task(resumable_gc())
            app.state.resumable_gc_task = collector
            try:
                yield
            finally:
                gc_stop.set()
                await asyncio.gather(collector, return_exceptions=True)
                await asyncio.gather(*list(resumable_tasks.values()), return_exceptions=True)
        finally:
            gateway_lock.release()

    app = FastAPI(
        title="Local Transcriber Remote Gateway",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        debug=False,
    )
    app.state.gateway_config = settings
    app.state.repository = repository
    app.state.store = store
    app.state.signer = signer
    app.state.rate_limiter = rate_limiter
    app.state.resumable_tasks = resumable_tasks
    app.state.collect_resumable = collect_resumable
    app.state.resumable_gc_error = False
    remote_web_root = Path(__file__).with_name("remote_web")

    @app.middleware("http")
    async def enforce_gateway_boundary(request: Request, call_next: Callable):  # type: ignore[type-arg]
        server = request.scope.get("server")
        if server is None or server[0] not in LOOPBACK_BINDINGS:
            return _error(403, "public server binding is not allowed")
        if request.headers.getlist("tailscale-funnel-request"):
            return _error(403, "funnel requests are not allowed")
        hosts = request.headers.getlist("host")
        if len(hosts) != 1:
            return _error(400, "untrusted Host header")
        raw_host = hosts[0].strip()
        try:
            parsed_host = urlsplit(f"//{raw_host}")
            hostname = parsed_host.hostname
            has_port = parsed_host.port is not None
        except ValueError:
            return _error(400, "untrusted Host header")
        if (
            hostname is None
            or has_port
            or parsed_host.username is not None
            or parsed_host.password is not None
            or parsed_host.path not in {"", "/"}
            or parsed_host.query
            or parsed_host.fragment
            or raw_host.lower() != hostname.lower()
            or hostname.lower() not in settings.allowed_hosts
        ):
            return _error(400, "untrusted Host header")
        identities = request.headers.getlist(IDENTITY_HEADER)
        if not identities or not identities[0].strip():
            return _error(401, "missing remote identity")
        if len(identities) > 1:
            return _error(403, "duplicated remote identity header")
        if identities[0] not in settings.allowed_identities:
            LOGGER.warning("remote gateway refused a request without an allowed identity")
            return _error(403, "remote identity is not allowed")
        identity_hash = identity_digest(identities[0])
        request.state.identity_hash = identity_hash
        origins = request.headers.getlist("origin")
        if len(origins) > 1:
            return _error(403, "untrusted Origin header")
        if origins:
            origin = origins[0].strip()
            if _parse_origin(origin) is None or origin not in settings.allowed_origins:
                return _error(403, "untrusted Origin header")
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site is not None and fetch_site not in {"same-origin", "none"}:
            return _error(403, "cross-site request refused")
        is_resumable = request.url.path == f"{REMOTE_PREFIX}/uploads/resumable" or (
            request.url.path.startswith(f"{REMOTE_PREFIX}/uploads/resumable/")
        )
        if is_resumable:
            if not origins:
                upload_id = request.url.path.removeprefix(f"{REMOTE_PREFIX}/uploads/resumable/")
                exact_status_read = (
                    request.method == "GET"
                    and re.fullmatch(r"[0-9a-f]{32}", upload_id) is not None
                    and request.url.path == f"{REMOTE_PREFIX}/uploads/resumable/{upload_id}"
                )
                csrf_tokens = request.headers.getlist(CSRF_HEADER)
                fetch_sites = request.headers.getlist("sec-fetch-site")
                fetch_modes = request.headers.getlist("sec-fetch-mode")
                if not (
                    exact_status_read
                    and len(csrf_tokens) == 1
                    and signer.verify(
                        identity_hash,
                        request.cookies.get(SESSION_COOKIE),
                        csrf_tokens[0],
                    )
                    and fetch_sites == ["same-origin"]
                    and fetch_modes == ["cors"]
                ):
                    return _error(403, "Origin header is required")
            if not signer.verify_cookie(identity_hash, request.cookies.get(SESSION_COOKIE)):
                return _error(403, "invalid or expired session cookie")
            if app.state.resumable_gc_error:
                return _error(503, "resumable_storage_unavailable")
        if request.method in MUTATING_METHODS:
            if not origins:
                return _error(403, "Origin header is required")
            tokens = request.headers.getlist(CSRF_HEADER)
            token = tokens[0] if len(tokens) == 1 else None
            if not signer.verify(identity_hash, request.cookies.get(SESSION_COOKIE), token):
                return _error(403, "invalid or expired CSRF token")
        group = "mutation" if request.method in MUTATING_METHODS else "read"
        allowed, retry_after = rate_limiter.acquire(identity_hash, group)
        if not allowed:
            LOGGER.warning(
                "remote rate limit exceeded: group=%s identity_hash=%s retry_after=%d",
                group,
                identity_hash[:8],
                retry_after,
            )
            return _error(429, "rate limit exceeded", headers={"Retry-After": str(retry_after)})
        try:
            response = await call_next(request)
        except Exception as error:
            LOGGER.error("remote gateway request failed: %s", type(error).__name__)
            response = _error(500, "internal server error")
        _security_headers(response)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error_: RequestValidationError) -> JSONResponse:
        return _error(422, "invalid request")

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        detail = error.detail if isinstance(error.detail, str) else "request failed"
        return _error(error.status_code, detail, headers=error.headers)

    app.mount(
        "/remote/assets",
        StaticFiles(directory=remote_web_root, html=False),
        name="remote-web-assets",
    )

    @app.get("/", include_in_schema=False)
    @app.get("/remote", include_in_schema=False)
    @app.get("/remote/", include_in_schema=False)
    def remote_web_index() -> FileResponse:
        return FileResponse(remote_web_root / "index.html", media_type="text/html")

    @app.get(f"{REMOTE_PREFIX}/session", response_model=RemoteSessionResponse)
    def issue_session(request: Request, response: Response) -> RemoteSessionResponse:
        session_id, token, expires = signer.issue(request.state.identity_hash)
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=settings.csrf_ttl_seconds,
            path=REMOTE_PREFIX,
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return RemoteSessionResponse(
            csrf_token=token, expires_at=expires, max_upload_bytes=settings.max_upload_bytes
        )

    @app.get(f"{REMOTE_PREFIX}/health")
    def health_check() -> dict[str, str]:
        """Minimal authenticated loopback readiness probe; exposes zero internal state."""
        return {"status": "ok"}

    @app.get(f"{REMOTE_PREFIX}/subjects", response_model=list[RemoteSubjectResponse])
    async def list_remote_subjects(request: Request) -> list[RemoteSubjectResponse]:
        identity_hash: str = request.state.identity_hash
        subjects = await asyncio.to_thread(repository.list_subjects)
        allowed = settings.allowed_subjects
        filtered = [
            RemoteSubjectResponse(id=s.id, name=s.name) for s in subjects if s.id in allowed
        ]
        LOGGER.info(
            "remote subjects listed: count=%d identity_hash=%s",
            len(filtered),
            identity_hash[:8],
        )
        return filtered

    def _existing_recording(row: sqlite3.Row) -> Recording:
        recording = repository.get_recording(row["recording_id"])
        if recording is None:
            raise HTTPException(410, "recording is no longer available on the notebook")
        return recording

    @app.post(f"{REMOTE_PREFIX}/uploads/resumable", response_model=ResumableSessionResponse)
    async def init_resumable(request: Request, body: ResumableInitRequest) -> JSONResponse:
        key = _single_header(request, IDEMPOTENCY_HEADER)
        if key is None or _IDEMPOTENCY_KEY.fullmatch(key) is None:
            raise HTTPException(400, "invalid_idempotency_key")
        expected = hash_header(request, "x-expected-sha256")
        if Path(body.filename).suffix.lower() not in {".m4a", ".aac", ".mp3", ".wav"}:
            raise HTTPException(400, "invalid_extension")
        if body.total_bytes > settings.max_upload_bytes:
            raise HTTPException(413, "upload_too_large")
        subject_id = body.subject_id
        if subject_id is None and len(settings.allowed_subjects) == 1:
            subject_id = next(iter(settings.allowed_subjects))
        if subject_id is None:
            raise HTTPException(400, "subject_required")
        if subject_id not in settings.allowed_subjects:
            raise HTTPException(403, "subject_not_allowed")
        if await asyncio.to_thread(repository.get_subject, subject_id) is None:
            raise HTTPException(422, "subject_not_found")
        immutable = body.model_dump(mode="json")
        immutable.update(subject_id=subject_id, expected_sha256=expected)
        fingerprint = hashlib.sha256(
            json.dumps(
                immutable,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        identity_hash = request.state.identity_hash
        async with upload_lock:
            row, created = store.resumable_init(
                identity_hash,
                key_digest(identity_hash, key),
                fingerprint,
                body,
                expected,
                subject_id,
                disk_usage(incoming).free,
                settings.min_free_disk_bytes,
            )
            if created:
                try:
                    directory = _staging_path(incoming, row["upload_id"], "chunks")
                    directory.mkdir(parents=True)
                except Exception as error:
                    store.resumable_transition(
                        row["upload_id"],
                        "uploading",
                        "aborted",
                        error_code="staging_unavailable",
                    )
                    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
                        raise HTTPException(507, "insufficient_storage") from error
                    raise
        if not created:
            row = owned_session(row["upload_id"], identity_hash)
        headers = session_headers(row)
        headers["Location"] = f"{REMOTE_PREFIX}/uploads/resumable/{row['upload_id']}"
        return JSONResponse(
            session_payload(row).model_dump(mode="json"),
            status_code=201 if created else 200,
            headers=headers,
        )

    @app.get(
        f"{REMOTE_PREFIX}/uploads/resumable/{{upload_id}}", response_model=ResumableSessionResponse
    )
    def get_resumable(upload_id: str, request: Request) -> JSONResponse:
        row = owned_session(upload_id, request.state.identity_hash)
        return JSONResponse(
            session_payload(row).model_dump(mode="json"), headers=session_headers(row)
        )

    @app.patch(f"{REMOTE_PREFIX}/uploads/resumable/{{upload_id}}", status_code=204)
    async def patch_resumable(upload_id: str, request: Request) -> Response:
        owned_session(upload_id, request.state.identity_hash)
        with session_operation(upload_id):
            row = store.resumable(upload_id, request.state.identity_hash)
            assert row is not None
            headers = session_headers(row)
            if row["state"] != "uploading":
                raise HTTPException(409, "session_not_uploading", headers=headers)
            raw_offset = _single_header(request, "upload-offset")
            if (
                raw_offset is None
                or len(raw_offset) > 20
                or re.fullmatch(r"[0-9]+", raw_offset) is None
            ):
                raise HTTPException(400, "invalid_upload_offset")
            if int(raw_offset) != row["current_offset"]:
                raise HTTPException(409, "offset_conflict", headers=headers)
            if _single_header(request, "transfer-encoding") is not None:
                raise HTTPException(411, "content_length_required")
            raw_length = _single_header(request, "content-length")
            if raw_length is None:
                raise HTTPException(411, "content_length_required")
            if len(raw_length) > 20 or re.fullmatch(r"[0-9]+", raw_length) is None:
                raise HTTPException(400, "invalid_content_length")
            size = int(raw_length)
            remaining = row["total_bytes"] - row["current_offset"]
            if size > min(row["chunk_bytes"], remaining):
                raise HTTPException(413, "invalid_chunk_size")
            if size < 1 or size != min(row["chunk_bytes"], remaining):
                raise HTTPException(400, "invalid_chunk_length")
            if _single_header(request, "content-type") != "application/octet-stream":
                raise HTTPException(415, "invalid_chunk_content_type")
            digest = hash_header(request, "x-chunk-sha256")
            index = row["current_offset"] // row["chunk_bytes"]
            temporary = _staging_path(incoming, upload_id, "chunks", f".{uuid4().hex}.part")
            try:
                await _receive_resumable_chunk(
                    request,
                    temporary,
                    size,
                    digest,
                    settings.request_timeout_seconds,
                )
                target = _staging_path(incoming, upload_id, "chunks", f"{index:08d}.chunk")
                os.replace(temporary, target)
                store.resumable_commit_chunk(row, size, digest, index)
            except OSError as error:
                if error.errno == errno.ENOSPC:
                    raise HTTPException(507, "insufficient_storage") from error
                raise
            finally:
                _staging_path(incoming, upload_id, "chunks", temporary.name).unlink(missing_ok=True)
            headers["Current-Offset"] = str(row["current_offset"] + size)
            return Response(status_code=204, headers=headers)

    @app.post(
        f"{REMOTE_PREFIX}/uploads/resumable/{{upload_id}}/finalize",
        response_model=ResumableSessionResponse,
    )
    async def finalize_resumable(
        upload_id: str,
        request: Request,
        body: ApiModel,
    ) -> JSONResponse:
        row = owned_session(upload_id, request.state.identity_hash)
        expected = hash_header(request, "x-expected-sha256")
        if expected != row["expected_sha256"]:
            raise HTTPException(409, "expected_hash_conflict", headers=session_headers(row))
        if row["current_offset"] != row["total_bytes"]:
            raise HTTPException(409, "upload_incomplete", headers=session_headers(row))
        accepted_headers = {
            **session_headers(row),
            "Location": f"{REMOTE_PREFIX}/uploads/resumable/{upload_id}",
            "Retry-After": "2",
        }
        if row["state"] == "completed" or (
            row["state"] == "importing"
            and row["recording_id"] is not None
            and upload_id not in resumable_tasks
        ):
            with session_operation(upload_id):
                if row["enqueue"]:
                    await asyncio.to_thread(
                        _create_job,
                        row["identity_hash"],
                        key_digest(row["identity_hash"], f"resumable-job-{upload_id}"),
                        row["recording_id"],
                    )
                store.resumable_transition(upload_id, row["state"], "completed")
                await asyncio.to_thread(cleanup_session, upload_id)
                row = store.resumable(upload_id)
                assert row is not None
                return JSONResponse(
                    session_payload(row).model_dump(mode="json"), headers=session_headers(row)
                )
        if row["state"] in {"assembling", "importing"}:
            return JSONResponse(
                session_payload(row).model_dump(mode="json"),
                status_code=202,
                headers=accepted_headers,
            )
        with busy_guard:
            if upload_id in resumable_busy:
                raise HTTPException(409, "session_busy", headers=session_headers(row))
            if len(resumable_tasks) >= 1 + RESUMABLE_FINALIZATION_PENDING:
                raise HTTPException(503, "finalization_busy", headers={"Retry-After": "2"})
            resumable_busy.add(upload_id)
        try:
            if not store.resumable_transition(upload_id, "uploading", "assembling"):
                raise HTTPException(409, "session_changed")
            updated = store.resumable(upload_id)
            assert updated is not None
            resumable_tasks[upload_id] = asyncio.create_task(finish_resumable(updated))
        except BaseException:
            with busy_guard:
                resumable_busy.discard(upload_id)
            raise
        return JSONResponse(
            session_payload(updated).model_dump(mode="json"),
            status_code=202,
            headers=accepted_headers,
        )

    @app.delete(f"{REMOTE_PREFIX}/uploads/resumable/{{upload_id}}", status_code=204)
    async def delete_resumable(upload_id: str, request: Request) -> Response:
        row = owned_session(upload_id, request.state.identity_hash)
        if row["state"] in {"importing", "completed"}:
            raise HTTPException(409, "cannot_abort_import", headers=session_headers(row))
        if row["state"] == "assembling":
            if not store.resumable_transition(upload_id, "assembling", "aborted"):
                raise HTTPException(409, "cannot_abort_import")
            task = resumable_tasks.get(upload_id)
            if task is not None:
                await asyncio.shield(task)
            with session_operation(upload_id):
                cleanup_session(upload_id)
        else:
            with session_operation(upload_id):
                if not store.resumable_transition(upload_id, "uploading", "aborted"):
                    raise HTTPException(409, "session_changed")
                cleanup_session(upload_id)
        return Response(status_code=204)

    @app.post(f"{REMOTE_PREFIX}/uploads", response_model=RemoteRecordingResponse)
    async def upload(request: Request) -> JSONResponse:
        identity_hash: str = request.state.identity_hash
        key = _single_header(request, IDEMPOTENCY_HEADER)
        if key is None or _IDEMPOTENCY_KEY.fullmatch(key) is None:
            raise HTTPException(400, "a valid Idempotency-Key header is required")
        if _single_header(request, "transfer-encoding") is not None:
            raise HTTPException(411, "Content-Length is required")
        declared = _single_header(request, "content-length")
        if declared is None:
            raise HTTPException(411, "Content-Length is required")
        if not declared.isdigit() or len(declared) > 15:
            raise HTTPException(400, "invalid Content-Length")
        expected_bytes = int(declared)
        if expected_bytes < 1:
            raise HTTPException(400, "empty upload")
        if expected_bytes > settings.max_upload_bytes:
            raise HTTPException(413, "upload is too large")
        filename = sanitize_filename(
            _decode_header_text(_single_header(request, "x-filename"), "X-Filename", maximum=255)
        )
        extension = Path(filename).suffix.lower()
        content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip()
        if content_type.lower() not in _CONTENT_TYPES.get(extension, frozenset()):
            raise HTTPException(415, "Content-Type does not match a supported media filename")
        raw_title = _single_header(request, "x-title")
        title = (
            Path(filename).stem
            if raw_title is None
            else _decode_header_text(raw_title, "X-Title", maximum=500)
        )
        raw_date = _single_header(request, "x-lesson-date")
        try:
            lesson_date = date.today() if raw_date is None else date.fromisoformat(raw_date)
        except ValueError as error:
            raise HTTPException(400, "malformed X-Lesson-Date header") from error

        raw_subject_id = _single_header(request, "x-subject-id")
        if raw_subject_id is not None:
            if _UUID.fullmatch(raw_subject_id) is None:
                raise HTTPException(400, "malformed X-Subject-Id header")
            if raw_subject_id not in settings.allowed_subjects:
                raise HTTPException(403, "subject is not authorized for remote upload")
            resolved_subject_id = raw_subject_id
        else:
            if (
                settings.subject_id is not None
                and len(settings.allowed_subjects) == 1
                and settings.subject_id in settings.allowed_subjects
            ):
                resolved_subject_id = settings.subject_id
            elif len(settings.allowed_subjects) > 1:
                raise HTTPException(
                    400, "X-Subject-Id header is required when multiple subjects are authorized"
                )
            else:
                raise HTTPException(400, "X-Subject-Id header is required")

        subject_record = await asyncio.to_thread(repository.get_subject, resolved_subject_id)
        if subject_record is None:
            raise HTTPException(422, "subject does not exist on the notebook")

        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    filename,
                    title,
                    lesson_date.isoformat(),
                    expected_bytes,
                    content_type.lower(),
                    resolved_subject_id,
                ],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        legacy_fingerprint = hashlib.sha256(
            json.dumps(
                [filename, title, lesson_date.isoformat(), expected_bytes, content_type.lower()],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        key_hash = key_digest(identity_hash, key)

        claim = await asyncio.to_thread(
            store.claim_upload,
            key_hash,
            identity_hash,
            fingerprint,
            legacy_fingerprint=legacy_fingerprint,
        )
        if claim.outcome == "legacy":
            raise HTTPException(409, "legacy upload fingerprint requires a new Idempotency-Key")
        if claim.outcome == "mismatch":
            raise HTTPException(422, "Idempotency-Key was already used for another request")
        if claim.outcome == "busy":
            raise HTTPException(409, "an upload with this Idempotency-Key is in progress")
        if claim.outcome == "completed" and claim.row is not None:
            recording = await asyncio.to_thread(_existing_recording, claim.row)
            return _replayed(_recording_payload(recording), 200)
        if claim.outcome == "verify" and claim.row is not None:
            recovered = await asyncio.to_thread(
                repository.find_recording_by_sha256, claim.row["sha256"]
            )
            if recovered is not None:
                # Ownership after a crash during import cannot be proven without core
                # schema modifications; fail closed to prevent IDOR across identities.
                raise HTTPException(409, "this media already exists in the notebook library")
            if not await asyncio.to_thread(store.reclaim_stale_import, key_hash):
                raise HTTPException(409, "an upload with this Idempotency-Key is in progress")

        async with upload_lock:
            usage = disk_usage(incoming)
            if (
                usage.free - store.resumable_reserved_bytes() - expected_bytes * 2
                < settings.min_free_disk_bytes
            ):
                await asyncio.to_thread(store.release_upload, key_hash)
                raise HTTPException(507, "insufficient free disk space on the notebook")

            temporary = incoming / f"{uuid4()}.part"
            completed = False
            try:
                digest, received = await _receive_body(
                    request,
                    temporary,
                    expected_bytes=expected_bytes,
                    maximum=settings.max_upload_bytes,
                    timeout=settings.request_timeout_seconds,
                )
                if await asyncio.to_thread(repository.find_recording_by_sha256, digest) is not None:
                    raise HTTPException(409, "this media already exists in the notebook library")
                await asyncio.to_thread(store.mark_importing, key_hash, digest)

                def import_media() -> Recording:
                    with temporary.open("rb") as stream:
                        return library.import_stream(
                            stream,
                            original_name=filename,
                            title=title,
                            subject_id=resolved_subject_id,
                            lesson_date=lesson_date,
                        )

                try:
                    recording = await asyncio.to_thread(import_media)
                except (DuplicateMediaError, sqlite3.IntegrityError) as error:
                    if (
                        isinstance(error, sqlite3.IntegrityError)
                        and "FOREIGN KEY" in str(error).upper()
                    ):
                        raise HTTPException(422, "media could not be imported") from error
                    raise HTTPException(
                        409, "this media already exists in the notebook library"
                    ) from error
                except MediaTooLargeError as error:
                    raise HTTPException(413, "upload is too large") from error
                except (UnsupportedMediaError, InvalidMediaError) as error:
                    raise HTTPException(415, "file is not supported decodable media") from error
                except (MediaImportError, KeyError) as error:
                    raise HTTPException(422, "media could not be imported") from error
                try:
                    await asyncio.to_thread(store.complete_upload, key_hash, recording.id)
                except RemoteGatewayError as error:
                    raise HTTPException(
                        409, "this media already exists in the notebook library"
                    ) from error
                completed = True
                return JSONResponse(
                    _recording_payload(recording).model_dump(mode="json"), status_code=201
                )
            except BaseException:
                if not completed:
                    await asyncio.to_thread(store.release_upload, key_hash)
                raise
            finally:
                temporary.unlink(missing_ok=True)

    def _job_payload(job: TranscriptionJob) -> RemoteJobResponse:
        return RemoteJobResponse(
            id=job.id,
            recording_id=job.recording_id,
            status=job.status.value,
            phase=job.phase.value,
            progress_percent=job.progress_percent,
            processed_seconds=job.processed_seconds,
            total_seconds=job.total_seconds,
            error_message=None
            if job.error_message is None
            else _safe_message(job.error_message, paths.root),
            transcript_available=job.status is JobStatus.SUCCEEDED,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    def _create_job(identity_hash: str, key_hash: str, recording_id: str) -> tuple[int, Any]:
        if not store.owns_recording(identity_hash, recording_id):
            raise HTTPException(404, "recording not found")
        with job_lock:
            claim = store.claim_job(key_hash, identity_hash, recording_id)
            if claim.outcome == "mismatch":
                raise HTTPException(422, "Idempotency-Key was already used for another request")
            if claim.outcome == "completed" and claim.row is not None:
                job = repository.get_job(claim.row["job_id"])
                if job is None:
                    raise HTTPException(410, "job is no longer available on the notebook")
                return 200, job
            completed = False
            try:
                recording = repository.get_recording(recording_id)
                if recording is None:
                    raise HTTPException(410, "recording is no longer available on the notebook")
                reusable = [
                    job
                    for job in repository.list_jobs()
                    if job.recording_id == recording_id and job.status in _REUSABLE_JOB_STATUSES
                ]
                if reusable:
                    job = max(reusable, key=lambda item: item.created_at)
                    store.complete_job(key_hash, job.id)
                    completed = True
                    return 200, job
                job = queue.enqueue(
                    recording_id,
                    TranscriptionSettings(
                        model_name=settings.model_name,
                        profile=settings.profile,
                        language=settings.language,
                    ),
                )
                store.complete_job(key_hash, job.id)
                completed = True
                return 202, job
            except KeyError as error:
                raise HTTPException(
                    410, "recording is no longer available on the notebook"
                ) from error
            except ModelNotInstalledError as error:
                raise HTTPException(
                    409, "the transcription model is not installed on the notebook"
                ) from error
            except FileNotFoundError as error:
                raise HTTPException(409, "managed media is missing on the notebook") from error
            finally:
                if not completed:
                    store.release_job(key_hash)

    @app.post(f"{REMOTE_PREFIX}/jobs", response_model=RemoteJobResponse)
    async def create_job(request: Request, payload: RemoteJobCreate) -> JSONResponse:
        identity_hash: str = request.state.identity_hash
        key = _single_header(request, IDEMPOTENCY_HEADER)
        if key is None or _IDEMPOTENCY_KEY.fullmatch(key) is None:
            raise HTTPException(400, "a valid Idempotency-Key header is required")
        if _UUID.fullmatch(payload.recording_id) is None:
            raise HTTPException(404, "recording not found")
        status, job = await asyncio.to_thread(
            _create_job, identity_hash, key_digest(identity_hash, key), payload.recording_id
        )
        if status == 200:
            return _replayed(_job_payload(job), 200)
        return JSONResponse(_job_payload(job).model_dump(mode="json"), status_code=status)

    def _owned_job(identity_hash: str, job_id: str) -> TranscriptionJob:
        if _UUID.fullmatch(job_id) is None or not store.owns_job(identity_hash, job_id):
            raise HTTPException(404, "job not found")
        job = repository.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job

    @app.get(f"{REMOTE_PREFIX}/jobs/{{job_id}}", response_model=RemoteJobResponse)
    async def get_job(request: Request, job_id: str) -> RemoteJobResponse:
        job = await asyncio.to_thread(_owned_job, request.state.identity_hash, job_id)
        return _job_payload(job)

    def _transcript_for(identity_hash: str, job_id: str) -> RemoteTranscriptResponse:
        job = _owned_job(identity_hash, job_id)
        if job.status is not JobStatus.SUCCEEDED:
            raise HTTPException(409, "transcript is not available until the job succeeds")
        transcript = next(
            (
                item
                for item in repository.list_transcripts(job.recording_id)
                if item.job_id == job.id
            ),
            None,
        )
        if transcript is None:
            raise HTTPException(404, "transcript not found")
        return RemoteTranscriptResponse(
            id=transcript.id,
            job_id=transcript.job_id,
            recording_id=transcript.recording_id,
            language=transcript.language,
            text=transcript.text,
            segments=[
                RemoteSegmentResponse(
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    text=segment.text,
                )
                for segment in transcript.segments
            ],
            created_at=transcript.created_at,
        )

    @app.get(f"{REMOTE_PREFIX}/jobs/{{job_id}}/transcript", response_model=RemoteTranscriptResponse)
    async def get_transcript(request: Request, job_id: str) -> RemoteTranscriptResponse:
        return await asyncio.to_thread(_transcript_for, request.state.identity_hash, job_id)

    return app


def _replayed(model: BaseModel, status: int) -> JSONResponse:
    response = JSONResponse(model.model_dump(mode="json"), status_code=status)
    response.headers["Idempotent-Replayed"] = "true"
    return response


async def _receive_body(
    request: Request,
    destination: Path,
    *,
    expected_bytes: int,
    maximum: int,
    timeout: float,
) -> tuple[str, int]:
    """Stream the raw body to a new runtime file, counting the bytes actually received."""
    digest = hashlib.sha256()
    received = 0
    try:
        async with asyncio.timeout(timeout):
            with destination.open("xb") as output:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > expected_bytes or received > maximum:
                        raise HTTPException(413, "received more bytes than declared")
                    digest.update(chunk)
                    output.write(chunk)
    except TimeoutError as error:
        raise HTTPException(408, "upload timed out") from error
    except ClientDisconnect as error:
        raise HTTPException(400, "upload was interrupted") from error
    if received != expected_bytes:
        raise HTTPException(400, "upload was interrupted before all declared bytes arrived")
    return digest.hexdigest(), received
