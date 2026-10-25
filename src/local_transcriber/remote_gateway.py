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
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import stat
import time
from collections.abc import AsyncIterator, Callable, Iterator
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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
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
    subject_id: str
    model_name: str = "small"
    profile: str = "auto"
    language: str | None = None
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    min_free_disk_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES
    csrf_ttl_seconds: int = DEFAULT_CSRF_TTL_SECONDS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS

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
        subject_id = raw.get("subject_id")
        if not isinstance(subject_id, str) or _UUID.fullmatch(subject_id) is None:
            raise RemoteGatewayConfigError("subject_id must be an existing subject UUID")
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


class RemoteSessionResponse(ApiModel):
    csrf_token: str
    expires_at: int
    max_upload_bytes: int


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


class GatewayStateStore:
    """Idempotency and ownership metadata kept in the gateway's own SQLite file.

    The core database (schema v4) is not modified. Keys are namespaced per identity and
    stored only as HMAC digests; no login, filename or payload is persisted here.
    """

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.clock = clock

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
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
            connection.executescript(f"BEGIN IMMEDIATE;\n{_STATE_SCHEMA}\nCOMMIT;")
            connection.execute("PRAGMA user_version = 1")

    def claim_upload(self, key_hash: str, identity_hash: str, fingerprint: str) -> _Claim:
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
            if row["identity_hash"] != identity_hash or row["fingerprint"] != fingerprint:
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
                   AND state = 'completed' LIMIT 1""",
                (identity_hash, recording_id),
            ).fetchone()
            if other is not None:
                return False
            row = connection.execute(
                """SELECT 1 FROM remote_uploads WHERE identity_hash = ? AND recording_id = ?
                   AND state = 'completed' LIMIT 1""",
                (identity_hash, recording_id),
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
        session_id = secrets.token_urlsafe(32)
        expires = int(self.clock()) + self.ttl_seconds
        return session_id, f"{expires}.{self._mac(identity_hash, session_id, expires)}", expires

    def verify(self, identity_hash: str, session_id: str | None, token: str | None) -> bool:
        if not session_id or not token or len(token) > 256 or len(session_id) > 128:
            return False
        if re.fullmatch(r"[A-Za-z0-9_-]{16,128}", session_id) is None:
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


def _error(status: int, detail: str) -> JSONResponse:
    response = JSONResponse({"detail": detail}, status_code=status)
    _security_headers(response)
    return response


def create_remote_gateway_app(
    config: AppConfig | None = None,
    *,
    gateway_config: RemoteGatewayConfig | None = None,
    model_manager: ModelManager | None = None,
    clock: Callable[[], float] = time.time,
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
    gateway_lock = _SingleWorkerLock(base / LOCK_FILENAME)
    job_lock = Lock()
    upload_lock = asyncio.Lock()

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
        if repository.get_subject(settings.subject_id) is None:
            raise RemoteGatewayConfigError("configured subject_id does not exist")
        gateway_lock.acquire()
        try:
            store.initialize()
            # Only one gateway process owns this directory, so leftovers are orphans.
            for leftover in incoming.glob("*.part"):
                if leftover.is_file() and not _is_link(leftover):
                    leftover.unlink(missing_ok=True)
            yield
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
        if request.method in MUTATING_METHODS:
            if not origins:
                return _error(403, "Origin header is required")
            tokens = request.headers.getlist(CSRF_HEADER)
            token = tokens[0] if len(tokens) == 1 else None
            if not signer.verify(identity_hash, request.cookies.get(SESSION_COOKIE), token):
                return _error(403, "invalid or expired CSRF token")
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
        return _error(error.status_code, detail)

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

    def _existing_recording(row: sqlite3.Row) -> Recording:
        recording = repository.get_recording(row["recording_id"])
        if recording is None:
            raise HTTPException(410, "recording is no longer available on the notebook")
        return recording

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
        fingerprint = hashlib.sha256(
            json.dumps(
                [filename, title, lesson_date.isoformat(), expected_bytes, content_type.lower()],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        key_hash = key_digest(identity_hash, key)

        claim = await asyncio.to_thread(store.claim_upload, key_hash, identity_hash, fingerprint)
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
            if usage.free - expected_bytes * 2 < settings.min_free_disk_bytes:
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
                            subject_id=settings.subject_id,
                            lesson_date=lesson_date,
                        )

                try:
                    recording = await asyncio.to_thread(import_media)
                except (DuplicateMediaError, sqlite3.IntegrityError) as error:
                    raise HTTPException(
                        409, "this media already exists in the notebook library"
                    ) from error
                except MediaTooLargeError as error:
                    raise HTTPException(413, "upload is too large") from error
                except (UnsupportedMediaError, InvalidMediaError) as error:
                    raise HTTPException(415, "file is not supported decodable media") from error
                except MediaImportError as error:
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
