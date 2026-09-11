"""Versioned localhost HTTP API and persistent job event streams."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime
from importlib.metadata import version
from pathlib import Path
from threading import Event, Thread
from typing import Annotated, BinaryIO
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .config import AppConfig
from .database import Database
from .exporters import ExportFormat, TranscriptExporter
from .media import (
    DuplicateMediaError,
    InvalidMediaError,
    MediaImportError,
    MediaImportSettings,
    MediaLibrary,
    MediaTooLargeError,
    UnsupportedMediaError,
)
from .models import (
    ExportedArtifact,
    JobEvent,
    JobPhase,
    JobStatus,
    Recording,
    Segment,
    Subject,
    Transcript,
    TranscriptionJob,
    TranscriptionSettings,
    Word,
)
from .models_manager import ModelManager, ModelNotInstalledError
from .queueing import TranscriptionQueue, TranscriptionWorker
from .repository import Repository
from .transcription import CTranslate2RuntimeProbe, EngineFactory, ProfileResolver

PACKAGE_NAME = "local-transcriber"
API_PREFIX = "/api"
WEB_ROOT = Path(__file__).with_name("web")
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "testserver"})
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
TERMINAL_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})
_CONTENT_TYPES = {
    ".wav": frozenset({"audio/wav", "audio/x-wav", "audio/vnd.wave"}),
    ".mp3": frozenset({"audio/mpeg", "audio/mp3"}),
    ".flac": frozenset({"audio/flac", "audio/x-flac"}),
    ".m4a": frozenset({"audio/mp4", "audio/x-m4a"}),
    ".ogg": frozenset({"audio/ogg", "application/ogg"}),
    ".mp4": frozenset({"audio/mp4", "video/mp4"}),
    ".mkv": frozenset({"audio/x-matroska", "video/x-matroska"}),
    ".webm": frozenset({"audio/webm", "video/webm"}),
}
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
LOGGER = logging.getLogger(__name__)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: str
    version: str
    schema_version: int


class VersionResponse(ApiModel):
    version: str
    api_version: str
    schema_version: int


class CapabilitiesResponse(ApiModel):
    api_version: str
    transcription_engine: str
    queue_worker: str
    sse_replay: bool
    media_range: bool
    model_download_via_api: bool
    model_download_command: str
    upload_max_bytes: int
    export_formats: list[str]


class SubjectCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class SubjectResponse(ApiModel):
    id: str
    name: str
    created_at: datetime


class RecordingResponse(ApiModel):
    id: str
    title: str
    subject_id: str
    lesson_date: date
    original_name: str
    size_bytes: int
    media_format: str
    duration_seconds: float | None
    created_at: datetime


class SearchResponse(ApiModel):
    recording_id: str
    title: str
    subject_name: str
    lesson_date: date
    excerpt: str


class ModelResponse(ApiModel):
    name: str
    installed: bool
    required_action: str | None


class RuntimeResponse(ApiModel):
    cpu_compute_types: list[str]
    cuda_device_count: int
    cuda_compute_types: list[str]
    cuda_available: bool
    cuda_error: str | None
    recommended_profile: str
    worker_running: bool


class JobCreate(ApiModel):
    recording_id: str
    model_name: str = "small"
    profile: str = Field(default="auto", pattern="^(auto|cpu|cuda)$")
    language: str | None = None
    beam_size: int = Field(default=5, ge=1, le=100)
    word_timestamps: bool = True
    vad_filter: bool = True
    max_attempts: int = Field(default=3, ge=1, le=20)


class JobResponse(ApiModel):
    id: str
    recording_id: str
    engine: str
    model_name: str
    status: str
    phase: str
    progress_percent: float | None
    processed_seconds: float
    total_seconds: float | None
    attempt_count: int
    max_attempts: int
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    error_message: str | None
    last_event_sequence: int
    created_at: datetime
    updated_at: datetime


class WordResponse(ApiModel):
    id: str
    text: str
    start_seconds: float
    end_seconds: float
    probability: float | None


class SegmentResponse(ApiModel):
    id: str
    ordinal: int
    start_seconds: float
    end_seconds: float
    text: str
    words: list[WordResponse]


class TranscriptResponse(ApiModel):
    id: str
    recording_id: str
    job_id: str
    language: str | None
    language_probability: float | None
    text: str
    settings: dict[str, object]
    metrics: dict[str, object] | None
    segments: list[SegmentResponse]
    created_at: datetime


class ExportCreate(ApiModel):
    format: ExportFormat


class ExportResponse(ApiModel):
    id: str
    transcript_id: str
    kind: str
    media_type: str | None
    size_bytes: int | None
    sha256: str | None
    created_at: datetime


class _WorkerController:
    def __init__(
        self,
        worker: TranscriptionWorker,
        *,
        poll_interval: float = 0.5,
        max_transient_retries: int = 3,
        retry_interval: float | None = None,
    ) -> None:
        if max_transient_retries < 0:
            raise ValueError("max_transient_retries must be non-negative")
        if retry_interval is not None and retry_interval <= 0:
            raise ValueError("retry_interval must be positive")
        self.worker = worker
        self.poll_interval = poll_interval
        self.max_transient_retries = max_transient_retries
        self.retry_interval = retry_interval or max(0.01, min(0.25, poll_interval))
        self.stop_requested = Event()
        self.thread = Thread(target=self._run, name="local-transcriber-worker", daemon=False)
        self.first_transient_error: sqlite3.OperationalError | None = None
        self.fatal_error: sqlite3.OperationalError | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_requested.set()
        self.thread.join()

    def _run(self) -> None:
        transient_failures = 0
        while not self.stop_requested.is_set():
            try:
                processed = self.worker.run_once()
            except sqlite3.OperationalError as error:
                if not _is_transient_sqlite_error(error):
                    self.fatal_error = error
                    LOGGER.exception("local worker stopped after a permanent SQLite error")
                    return
                if self.first_transient_error is None:
                    self.first_transient_error = error
                transient_failures += 1
                if transient_failures > self.max_transient_retries:
                    self.fatal_error = error
                    LOGGER.exception("local worker stopped after bounded SQLite retries")
                    return
                if self.stop_requested.wait(self.retry_interval):
                    return
                continue
            transient_failures = 0
            if processed is None:
                self.stop_requested.wait(self.poll_interval)


def _is_transient_sqlite_error(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int) and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return True
    message = str(error).casefold()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "database is busy",
            "database table is locked",
            "database schema is locked",
        )
    )


class _SingleWorkerLock:
    """Hold a process-level lock so one runtime has only one queue consumer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            handle.close()
            raise RuntimeError(
                "another API worker is already active for this runtime; use one Uvicorn worker"
            ) from error
        self.handle = handle

    def release(self) -> None:
        handle = self.handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self.handle = None


def _subject_payload(subject: Subject) -> SubjectResponse:
    return SubjectResponse(id=subject.id, name=subject.name, created_at=subject.created_at)


def _recording_payload(recording: Recording) -> RecordingResponse:
    return RecordingResponse(
        id=recording.id,
        title=recording.title,
        subject_id=recording.subject_id,
        lesson_date=recording.lesson_date,
        original_name=recording.original_name,
        size_bytes=recording.size_bytes,
        media_format=recording.media_format,
        duration_seconds=recording.duration_seconds,
        created_at=recording.created_at,
    )


def _job_payload(job: TranscriptionJob, root: Path, *, last_event_sequence: int = 0) -> JobResponse:
    return JobResponse(
        id=job.id,
        recording_id=job.recording_id,
        engine=job.engine,
        model_name=job.model_name,
        status=job.status.value,
        phase=job.phase.value,
        progress_percent=job.progress_percent,
        processed_seconds=job.processed_seconds,
        total_seconds=job.total_seconds,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        started_at=job.started_at,
        finished_at=job.finished_at,
        cancel_requested_at=job.cancel_requested_at,
        error_message=None if job.error_message is None else _safe_message(job.error_message, root),
        last_event_sequence=last_event_sequence,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _word_payload(word: Word) -> WordResponse:
    return WordResponse(
        id=word.id,
        text=word.text,
        start_seconds=word.start_seconds,
        end_seconds=word.end_seconds,
        probability=word.probability,
    )


def _segment_payload(segment: Segment) -> SegmentResponse:
    return SegmentResponse(
        id=segment.id,
        ordinal=segment.ordinal,
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
        text=segment.text,
        words=[_word_payload(word) for word in segment.words],
    )


def _transcript_payload(transcript: Transcript) -> TranscriptResponse:
    return TranscriptResponse(
        id=transcript.id,
        recording_id=transcript.recording_id,
        job_id=transcript.job_id,
        language=transcript.language,
        language_probability=transcript.language_probability,
        text=transcript.text,
        settings=asdict(transcript.settings),
        metrics=None if transcript.metrics is None else asdict(transcript.metrics),
        segments=[_segment_payload(segment) for segment in transcript.segments],
        created_at=transcript.created_at,
    )


def _export_payload(artifact: ExportedArtifact) -> ExportResponse:
    return ExportResponse(
        id=artifact.id,
        transcript_id=artifact.transcript_id,
        kind=artifact.kind,
        media_type=artifact.media_type,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        created_at=artifact.created_at,
    )


def _safe_message(error: object, root: Path) -> str:
    raw = error.args[0] if isinstance(error, KeyError) and error.args else error
    message = re.sub(r"\s+", " ", str(raw)).strip()
    message = re.sub(re.escape(str(root)), "<runtime>", message, flags=re.IGNORECASE)
    message = re.sub(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n]*", "<path>", message)
    return message[:500] or "request failed"


def _security_headers(response: Response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; base-uri 'none'; connect-src 'self'; font-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; img-src 'self'; media-src 'self'; "
        "object-src 'none'; script-src 'self'; style-src 'self'"
    )
    response.headers["Cache-Control"] = "no-store"


def _origin_is_local(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _media_content_type_is_valid(upload: UploadFile) -> bool:
    suffix = Path(upload.filename or "").suffix.lower()
    supplied = (upload.content_type or "").split(";", 1)[0].strip().lower()
    return supplied in _CONTENT_TYPES.get(suffix, frozenset())


def _event_name(event: JobEvent, job: TranscriptionJob) -> str:
    if event.phase is JobPhase.COMPLETED:
        return {
            JobStatus.SUCCEEDED: "completion",
            JobStatus.FAILED: "failure",
            JobStatus.CANCELLED: "cancellation",
        }.get(job.status, "state")
    if event.phase is JobPhase.CANCELLING:
        return "cancellation"
    if event.phase is JobPhase.TRANSCRIBING and (
        event.completed_segments or event.processed_seconds or event.percent
    ):
        return "progress"
    if event.phase in {JobPhase.QUEUED, JobPhase.CLAIMING}:
        return "state"
    return "phase"


def _sse_event(event: JobEvent, job: TranscriptionJob, root: Path) -> str:
    data = {
        "job_id": event.job_id,
        "sequence": event.sequence,
        "status": job.status.value,
        "phase": event.phase.value,
        "message": _safe_message(event.message, root),
        "completed_segments": event.completed_segments,
        "processed_seconds": event.processed_seconds,
        "total_seconds": event.total_seconds,
        "percent": event.percent,
        "created_at": event.created_at.isoformat(),
    }
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {_event_name(event, job)}\ndata: {encoded}\n\n"


async def stream_job_events(
    request: Request,
    repository: Repository,
    job_id: str,
    cursor: int,
    *,
    poll_interval: float,
    heartbeat_interval: float,
    batch_size: int = 100,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    """Replay persisted events, then wait without retaining a SQLite connection."""
    if cursor < 0:
        raise ValueError("cursor must be non-negative")
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    monotonic_clock = clock or asyncio.get_running_loop().time
    last_sent = monotonic_clock()
    yield "retry: 2000\n\n"
    while True:
        events = await asyncio.to_thread(
            repository.list_job_events,
            job_id,
            after_sequence=cursor,
            limit=batch_size,
        )
        if events:
            job = await asyncio.to_thread(repository.get_job, job_id)
            if job is None:
                return
            for event in events:
                yield _sse_event(event, job, repository.database.path.parent)
                cursor = event.sequence
                last_sent = monotonic_clock()
            if await request.is_disconnected():
                return
            # Query again immediately after any non-empty batch. Waiting happens
            # only after an empty incremental query confirms the backlog is drained.
            continue
        job = await asyncio.to_thread(repository.get_job, job_id)
        if job is None:
            return
        if job.status in TERMINAL_STATUSES:
            # State and terminal event commit together. One incremental confirmation
            # covers a transition that happened between the query and state read.
            terminal_events = await asyncio.to_thread(
                repository.list_job_events,
                job_id,
                after_sequence=cursor,
                limit=batch_size,
            )
            if terminal_events:
                for event in terminal_events:
                    yield _sse_event(event, job, repository.database.path.parent)
                    cursor = event.sequence
                    last_sent = monotonic_clock()
                if await request.is_disconnected():
                    return
                if len(terminal_events) == batch_size:
                    continue
            return
        if await request.is_disconnected():
            return
        if monotonic_clock() - last_sent >= heartbeat_interval:
            yield ": heartbeat\n\n"
            last_sent = monotonic_clock()
        await sleeper(poll_interval)


def _parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    if value is None:
        return None
    match = _RANGE.fullmatch(value.strip())
    if match is None or "," in value or size <= 0:
        raise ValueError("invalid byte range")
    first, last = match.groups()
    if not first and not last:
        raise ValueError("invalid byte range")
    if first:
        start = int(first)
        end = size - 1 if not last else int(last)
        if start >= size or end < start:
            raise ValueError("range is outside the media")
        return start, min(end, size - 1)
    length = int(last)
    if length <= 0:
        raise ValueError("invalid byte range")
    return max(0, size - length), size - 1


def _file_chunks(path: Path, start: int, end: int, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    with path.open("rb") as stream:
        stream.seek(start)
        remaining = end - start + 1
        while remaining:
            chunk = stream.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def create_app(
    config: AppConfig | None = None,
    *,
    engine_factory: EngineFactory | None = None,
    profiles: ProfileResolver | None = None,
    model_manager: ModelManager | None = None,
    media_settings: MediaImportSettings | None = None,
    start_worker: bool = True,
    worker_poll_interval: float = 0.5,
    sse_poll_interval: float = 0.5,
    sse_heartbeat_interval: float = 15.0,
    sse_batch_size: int = 100,
) -> FastAPI:
    """Build an app with injectable local dependencies for deterministic tests."""
    if worker_poll_interval <= 0 or sse_poll_interval <= 0 or sse_heartbeat_interval <= 0:
        raise ValueError("poll and heartbeat intervals must be positive")
    if not 1 <= sse_batch_size <= 1000:
        raise ValueError("sse_batch_size must be between 1 and 1000")
    app_config = config or AppConfig.from_env()
    database = Database(app_config.paths.database)
    repository = Repository(database)
    models = model_manager or ModelManager(app_config.paths)
    library = MediaLibrary(repository, app_config.paths, settings=media_settings)
    queue = TranscriptionQueue(repository, app_config.paths, models=models)
    exporter = TranscriptExporter(repository, app_config.paths)
    worker = TranscriptionWorker(
        repository,
        app_config.paths,
        models=models,
        profiles=profiles,
        engine_factory=engine_factory,
        poll_interval=worker_poll_interval,
    )
    controller = _WorkerController(worker, poll_interval=worker_poll_interval)
    worker_lock = _SingleWorkerLock(app_config.paths.root / ".api-worker.lock")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        app_config.paths.ensure_directories()
        database.initialize()
        if start_worker:
            worker_lock.acquire()
            try:
                controller.start()
            except BaseException:
                worker_lock.release()
                raise
        try:
            yield
        finally:
            if start_worker:
                try:
                    await asyncio.to_thread(controller.stop)
                finally:
                    worker_lock.release()

    app = FastAPI(
        title="Local Transcriber API",
        version=version(PACKAGE_NAME),
        docs_url=None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
        lifespan=lifespan,
        debug=False,
    )
    app.state.config = app_config
    app.state.database = database
    app.state.repository = repository
    app.state.library = library
    app.state.queue = queue
    app.state.worker_controller = controller
    app.state.worker_lock = worker_lock

    def job_payload(job: TranscriptionJob) -> JobResponse:
        # Read the cursor before refreshing the job. A concurrent event can then be
        # replayed, but the response can never skip an event newer than its snapshot.
        event_sequence = repository.last_job_event_sequence(job.id)
        snapshot = repository.get_job(job.id) or job
        return _job_payload(
            snapshot,
            app_config.paths.root,
            last_event_sequence=event_sequence,
        )

    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="web-assets")

    @app.middleware("http")
    async def enforce_local_http(request: Request, call_next: Callable):  # type: ignore[type-arg]
        server = request.scope.get("server")
        server_host = None if server is None else server[0]
        if server_host not in LOCAL_HOSTS:
            response = JSONResponse(
                {"detail": "public server binding is not allowed"}, status_code=403
            )
            _security_headers(response)
            return response
        host = request.url.hostname
        if host not in LOCAL_HOSTS:
            response = JSONResponse({"detail": "untrusted Host header"}, status_code=400)
            _security_headers(response)
            return response
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin is not None and not _origin_is_local(origin):
                response = JSONResponse({"detail": "untrusted Origin header"}, status_code=403)
                _security_headers(response)
                return response
        if request.method == "POST" and request.url.path == f"{API_PREFIX}/recordings":
            declared_length = request.headers.get("content-length")
            if declared_length is not None:
                try:
                    request_bytes = int(declared_length)
                    if request_bytes < 0:
                        raise ValueError
                except ValueError:
                    response = JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
                    _security_headers(response)
                    return response
                maximum_request = library.settings.max_size_bytes + MULTIPART_OVERHEAD_BYTES
                if request_bytes > maximum_request:
                    response = JSONResponse({"detail": "upload is too large"}, status_code=413)
                    _security_headers(response)
                    return response
        response = await call_next(request)
        _security_headers(response)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse({"detail": details}, status_code=422)

    @app.exception_handler(Exception)
    async def domain_error(_request: Request, error: Exception) -> JSONResponse:
        if isinstance(error, KeyError):
            status = 404
        elif isinstance(error, MediaTooLargeError):
            status = 413
        elif isinstance(error, (UnsupportedMediaError, InvalidMediaError)):
            status = 415
        elif isinstance(
            error, (DuplicateMediaError, ModelNotInstalledError, sqlite3.IntegrityError)
        ):
            status = 409
        elif isinstance(error, (MediaImportError, ValueError)):
            status = 422
        elif isinstance(error, FileNotFoundError):
            status = 409
        else:
            status = 500
        message = (
            "internal server error"
            if status == 500
            else _safe_message(error, app_config.paths.root)
        )
        return JSONResponse({"detail": message}, status_code=status)

    for handled_error in (
        KeyError,
        MediaTooLargeError,
        UnsupportedMediaError,
        InvalidMediaError,
        DuplicateMediaError,
        ModelNotInstalledError,
        sqlite3.IntegrityError,
        MediaImportError,
        ValueError,
        FileNotFoundError,
    ):
        app.add_exception_handler(handled_error, domain_error)

    @app.get(f"{API_PREFIX}/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok", version=version(PACKAGE_NAME), schema_version=database.schema_version()
        )

    @app.get("/", include_in_schema=False, response_class=FileResponse)
    def web_interface() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html", media_type="text/html")

    @app.get(f"{API_PREFIX}/capabilities", response_model=CapabilitiesResponse)
    def capabilities() -> CapabilitiesResponse:
        return CapabilitiesResponse(
            api_version="1",
            transcription_engine="faster-whisper",
            queue_worker="local-sequential",
            sse_replay=True,
            media_range=True,
            model_download_via_api=False,
            model_download_command="local-transcriber models download MODEL --confirm",
            upload_max_bytes=library.settings.max_size_bytes,
            export_formats=[item.value for item in ExportFormat],
        )

    @app.get(f"{API_PREFIX}/version", response_model=VersionResponse)
    def api_version() -> VersionResponse:
        return VersionResponse(
            version=version(PACKAGE_NAME), api_version="1", schema_version=database.schema_version()
        )

    @app.get(f"{API_PREFIX}/subjects", response_model=list[SubjectResponse])
    def list_subjects() -> list[SubjectResponse]:
        return [_subject_payload(item) for item in repository.list_subjects()]

    @app.post(f"{API_PREFIX}/subjects", response_model=SubjectResponse, status_code=201)
    def create_subject(payload: SubjectCreate) -> SubjectResponse:
        return _subject_payload(library.create_subject(payload.name))

    @app.get(f"{API_PREFIX}/recordings", response_model=list[RecordingResponse])
    def list_recordings(subject_id: str | None = None) -> list[RecordingResponse]:
        return [_recording_payload(item) for item in library.list_recordings(subject_id)]

    @app.post(f"{API_PREFIX}/recordings", response_model=RecordingResponse, status_code=201)
    def upload_recording(
        title: Annotated[str, Form(min_length=1, max_length=500)],
        subject_id: Annotated[str, Form(min_length=1)],
        lesson_date: Annotated[date, Form()],
        file: Annotated[UploadFile, File()],
    ) -> RecordingResponse:
        if not _media_content_type_is_valid(file):
            raise UnsupportedMediaError("Content-Type does not match a supported media filename")
        if file.size is not None and file.size > library.settings.max_size_bytes:
            raise MediaTooLargeError(f"media exceeds {library.settings.max_size_bytes} bytes")
        recording = library.import_stream(
            file.file,
            original_name=file.filename or "media",
            title=title,
            subject_id=subject_id,
            lesson_date=lesson_date,
        )
        return _recording_payload(recording)

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}", response_model=RecordingResponse)
    def get_recording(recording_id: str) -> RecordingResponse:
        recording = repository.get_recording(recording_id)
        if recording is None:
            raise KeyError("recording not found")
        return _recording_payload(recording)

    @app.delete(
        f"{API_PREFIX}/recordings/{{recording_id}}", status_code=204, response_class=Response
    )
    def delete_recording(recording_id: str) -> Response:
        if not library.delete_recording(recording_id):
            raise KeyError("recording not found")
        return Response(status_code=204)

    @app.get(f"{API_PREFIX}/search", response_model=list[SearchResponse])
    def search(q: str = Query(min_length=1, max_length=500), limit: int = Query(50, ge=1, le=500)):
        return [
            SearchResponse(**asdict(item)) for item in repository.search_recordings(q, limit=limit)
        ]

    @app.get(f"{API_PREFIX}/models", response_model=list[ModelResponse])
    def list_models() -> list[ModelResponse]:
        return [
            ModelResponse(
                name=item.name,
                installed=item.installed,
                required_action=None
                if item.installed
                else f"local-transcriber models download {item.name} --confirm",
            )
            for item in models.list_models()
        ]

    @app.get(f"{API_PREFIX}/runtime", response_model=RuntimeResponse)
    def runtime_status() -> RuntimeResponse:
        inspected = CTranslate2RuntimeProbe().inspect()
        cuda_available = (
            inspected.cuda_device_count > 0 and "int8_float16" in inspected.cuda_compute_types
        )
        return RuntimeResponse(
            cpu_compute_types=sorted(inspected.cpu_compute_types),
            cuda_device_count=inspected.cuda_device_count,
            cuda_compute_types=sorted(inspected.cuda_compute_types),
            cuda_available=cuda_available,
            cuda_error=(
                None
                if inspected.cuda_error is None
                else _safe_message(inspected.cuda_error, app_config.paths.root)
            ),
            recommended_profile="cuda" if cuda_available else "cpu",
            worker_running=controller.thread.is_alive(),
        )

    @app.get(f"{API_PREFIX}/jobs", response_model=list[JobResponse])
    def list_jobs(status: JobStatus | None = None) -> list[JobResponse]:
        return [job_payload(item) for item in repository.list_jobs(status)]

    @app.post(f"{API_PREFIX}/jobs", response_model=JobResponse, status_code=202)
    def create_job(payload: JobCreate) -> JobResponse:
        settings = TranscriptionSettings(
            model_name=payload.model_name,
            profile=payload.profile,
            language=payload.language,
            beam_size=payload.beam_size,
            word_timestamps=payload.word_timestamps,
            vad_filter=payload.vad_filter,
        )
        return job_payload(
            queue.enqueue(payload.recording_id, settings, max_attempts=payload.max_attempts)
        )

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}", response_model=JobResponse)
    def get_job(job_id: str) -> JobResponse:
        job = repository.get_job(job_id)
        if job is None:
            raise KeyError("job not found")
        return job_payload(job)

    @app.post(f"{API_PREFIX}/jobs/{{job_id}}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str) -> JobResponse:
        return job_payload(queue.cancel(job_id))

    @app.post(f"{API_PREFIX}/jobs/{{job_id}}/retry", response_model=JobResponse)
    def retry_job(job_id: str) -> JobResponse:
        return job_payload(queue.retry(job_id))

    @app.get(f"{API_PREFIX}/transcripts", response_model=list[TranscriptResponse])
    def list_transcripts(recording_id: str | None = None) -> list[TranscriptResponse]:
        return [_transcript_payload(item) for item in repository.list_transcripts(recording_id)]

    @app.get(f"{API_PREFIX}/transcripts/{{transcript_id}}", response_model=TranscriptResponse)
    def get_transcript(transcript_id: str) -> TranscriptResponse:
        transcript = repository.get_transcript(transcript_id)
        if transcript is None:
            raise KeyError("transcript not found")
        return _transcript_payload(transcript)

    @app.get(
        f"{API_PREFIX}/transcripts/{{transcript_id}}/segments",
        response_model=list[SegmentResponse],
    )
    def list_segments(transcript_id: str) -> list[SegmentResponse]:
        transcript = repository.get_transcript(transcript_id)
        if transcript is None:
            raise KeyError("transcript not found")
        return [_segment_payload(segment) for segment in transcript.segments]

    @app.get(f"{API_PREFIX}/transcripts/{{transcript_id}}/words", response_model=list[WordResponse])
    def list_words(transcript_id: str) -> list[WordResponse]:
        transcript = repository.get_transcript(transcript_id)
        if transcript is None:
            raise KeyError("transcript not found")
        return [_word_payload(word) for segment in transcript.segments for word in segment.words]

    @app.get(
        f"{API_PREFIX}/transcripts/{{transcript_id}}/exports",
        response_model=list[ExportResponse],
    )
    def list_exports(transcript_id: str) -> list[ExportResponse]:
        if repository.get_transcript(transcript_id) is None:
            raise KeyError("transcript not found")
        return [_export_payload(item) for item in repository.list_artifacts(transcript_id)]

    @app.post(
        f"{API_PREFIX}/transcripts/{{transcript_id}}/exports",
        response_model=ExportResponse,
        status_code=201,
    )
    def create_export(transcript_id: str, payload: ExportCreate) -> ExportResponse:
        transcript = repository.get_transcript(transcript_id)
        if transcript is None:
            raise KeyError("transcript not found")
        if any(
            item.kind == payload.format.value for item in repository.list_artifacts(transcript_id)
        ):
            raise sqlite3.IntegrityError("export format already exists for this transcript")
        return _export_payload(exporter.export(transcript, payload.format))

    @app.get(f"{API_PREFIX}/exports/{{artifact_id}}")
    def download_export(artifact_id: str):
        artifact = repository.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError("export not found")
        path = exporter.exported_path(artifact)
        if not path.is_file():
            raise FileNotFoundError("managed export file is missing")
        return FileResponse(
            path,
            media_type=artifact.media_type or "application/octet-stream",
            filename=f"transcript.{artifact.kind}",
        )

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}/media")
    def stream_media(recording_id: str, range_header: str | None = Header(None, alias="Range")):
        recording = repository.get_recording(recording_id)
        if recording is None:
            raise KeyError("recording not found")
        path = app_config.paths.resolve_relative(recording.relative_path)
        if not path.is_file():
            raise FileNotFoundError("managed media file is missing")
        size = path.stat().st_size
        try:
            byte_range = _parse_range(range_header, size)
        except ValueError as error:
            response = JSONResponse({"detail": str(error)}, status_code=416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return response
        media_type = mimetypes.guess_type(recording.original_name)[0] or "application/octet-stream"
        start, end = (0, max(0, size - 1)) if byte_range is None else byte_range
        response = StreamingResponse(
            _file_chunks(path, start, end),
            status_code=200 if byte_range is None else 206,
            media_type=media_type,
        )
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Content-Length"] = str(max(0, end - start + 1))
        if byte_range is not None:
            response.headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return response

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}/events")
    async def job_events(
        request: Request,
        job_id: str,
        after_sequence: Annotated[int | None, Query(ge=0)] = None,
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        if repository.get_job(job_id) is None:
            raise KeyError("job not found")
        try:
            header_cursor = 0 if last_event_id is None else int(last_event_id)
            if header_cursor < 0:
                raise ValueError
        except ValueError as error:
            raise ValueError("Last-Event-ID must be a non-negative integer") from error
        cursor = max(after_sequence or 0, header_cursor)

        return StreamingResponse(
            stream_job_events(
                request,
                repository,
                job_id,
                cursor,
                poll_interval=sse_poll_interval,
                heartbeat_interval=sse_heartbeat_interval,
                batch_size=sse_batch_size,
            ),
            media_type="text/event-stream",
            headers={"Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    return app
