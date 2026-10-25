"""Phase 8J-A: private, disabled-by-default remote gateway (synthetic fixtures only)."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import socket
import threading
import wave
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from local_transcriber import cli
from local_transcriber.api import create_app
from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.database import Database
from local_transcriber.media import MediaLibrary
from local_transcriber.models import JobStatus, Segment, Subject
from local_transcriber.models_manager import ModelManager
from local_transcriber.queueing import TranscriptionWorker
from local_transcriber.remote_gateway import (
    CONFIG_FILENAME,
    REMOTE_PREFIX,
    SESSION_COOKIE,
    STALE_CLAIM_SECONDS,
    GatewayStateStore,
    RemoteGatewayConfig,
    RemoteGatewayConfigError,
    RemoteGatewayDisabledError,
    create_remote_gateway_app,
    load_remote_config,
)
from local_transcriber.repository import Repository
from local_transcriber.transcription import (
    EngineOutput,
    ProfileResolver,
    ProgressEvent,
    RuntimeCapabilities,
)

HOST = "notebook.example-tailnet.ts.net"
ORIGIN = f"https://{HOST}"
IDENTITY = "aluno@example.com"
OTHER_IDENTITY = "colega@example.com"
FILENAME = "Aula Sintetica.wav"
TITLE = "Titulo sintetico"


def _wav_bytes(*, frames: int = 800, value: int = 0) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(value.to_bytes(2, "little", signed=True) * frames)
    return output.getvalue()


@dataclass
class FixedProbe:
    def inspect(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(frozenset({"int8"}), 0, frozenset(), "no CUDA")


class FakeEngine:
    name = "fake"

    def transcribe(self, request, progress=None):
        segment = Segment(ordinal=0, start_seconds=0, end_seconds=0.1, text="texto sintetico")
        if progress is not None:
            progress(ProgressEvent("transcribing", "segment decoded", 1, 0.1, 0.1, 99.0))
        return EngineOutput("texto sintetico", (segment,), "pt", 0.99, 0.1)


class Clock:
    def __init__(self) -> None:
        self.value = 1_900_000_000.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def _is_loopback(address: object) -> bool:
        if isinstance(address, tuple) and len(address) >= 1:
            host = address[0]
            return host in ("127.0.0.1", "::1", "localhost")
        if isinstance(address, str):
            return address in ("127.0.0.1", "::1", "localhost")
        return False

    def safe_create_connection(address, *args, **kwargs):
        if _is_loopback(address):
            return original_create_connection(address, *args, **kwargs)
        raise AssertionError(f"network access is not allowed in gateway tests: {address}")

    def safe_connect(self, address):
        if _is_loopback(address):
            return original_connect(self, address)
        raise AssertionError(f"network access is not allowed in gateway tests: {address}")

    monkeypatch.setattr(socket, "create_connection", safe_create_connection)
    monkeypatch.setattr(socket.socket, "connect", safe_connect)


@pytest.fixture
def runtime(tmp_path: Path) -> SimpleNamespace:
    config = AppConfig(RuntimePaths((tmp_path / "runtime").resolve()))
    config.paths.ensure_directories()
    database = Database(config.paths.database)
    database.initialize()
    repository = Repository(database)
    subject = repository.add_subject(Subject(name="Remoto"))
    return SimpleNamespace(config=config, repository=repository, subject_id=subject.id)


def _settings(runtime: SimpleNamespace, **overrides) -> RemoteGatewayConfig:
    values = {
        "enabled": True,
        "allowed_identities": frozenset({IDENTITY, OTHER_IDENTITY}),
        "allowed_hosts": frozenset({HOST}),
        "allowed_origins": frozenset({ORIGIN}),
        "subject_id": runtime.subject_id,
        "max_upload_bytes": 64 * 1024,
        "min_free_disk_bytes": 0,
    }
    values.update(overrides)
    return RemoteGatewayConfig(**values)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def gateway(runtime: SimpleNamespace, clock: Clock) -> Iterator[TestClient]:
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        yield client


def _headers(identity: str = IDENTITY, **extra: str) -> dict[str, str]:
    return {"host": HOST, "tailscale-user-login": identity, **extra}


def _session(client: TestClient, identity: str = IDENTITY) -> dict[str, str]:
    response = client.get(f"{REMOTE_PREFIX}/session", headers=_headers(identity))
    assert response.status_code == 200, response.text
    session_id = response.cookies.get(SESSION_COOKIE)
    assert session_id
    return _headers(
        identity,
        origin=ORIGIN,
        **{
            "x-csrf-token": response.json()["csrf_token"],
            "cookie": f"{SESSION_COOKIE}={session_id}",
        },
    )


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    key: str = "upload-key-0000000001",
    body: bytes | None = None,
    filename: str = FILENAME,
    content_type: str = "audio/wav",
):
    payload = _wav_bytes() if body is None else body
    return client.post(
        f"{REMOTE_PREFIX}/uploads",
        content=payload,
        headers={
            **headers,
            "idempotency-key": key,
            "content-type": content_type,
            "x-filename": filename.replace(" ", "%20"),
            "x-title": TITLE.replace(" ", "%20"),
            "x-lesson-date": "2026-10-20",
        },
    )


def _create_job(client: TestClient, headers: dict[str, str], recording_id: str, key: str):
    return client.post(
        f"{REMOTE_PREFIX}/jobs",
        json={"recording_id": recording_id},
        headers={**headers, "idempotency-key": key},
    )


def _install_model(runtime: SimpleNamespace) -> None:
    model = runtime.config.paths.models / "small"
    model.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (model / name).write_bytes(b"test")


def _run_worker_once(runtime: SimpleNamespace) -> None:
    worker = TranscriptionWorker(
        runtime.repository,
        runtime.config.paths,
        models=ModelManager(runtime.config.paths),
        profiles=ProfileResolver(FixedProbe()),
        engine_factory=lambda _profile: FakeEngine(),
        poll_interval=0,
    )
    assert worker.run_once() is not None


def _incoming_parts(runtime: SimpleNamespace) -> list[Path]:
    root = runtime.config.paths.root
    return list((root / "remote" / "incoming").glob("*")) + list(
        (runtime.config.paths.media / ".incoming").glob("*")
    )


# --- disabled by default and configuration ---------------------------------------------


def test_gateway_is_disabled_without_runtime_configuration(runtime: SimpleNamespace) -> None:
    with pytest.raises(RemoteGatewayDisabledError):
        load_remote_config(runtime.config.paths)
    with pytest.raises(RemoteGatewayDisabledError):
        create_remote_gateway_app(runtime.config)
    remote = runtime.config.paths.root / "remote"
    remote.mkdir()
    raw = {
        "enabled": False,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "subject_id": runtime.subject_id,
    }
    (remote / CONFIG_FILENAME).write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RemoteGatewayDisabledError):
        load_remote_config(runtime.config.paths)
    raw["enabled"] = True
    (remote / CONFIG_FILENAME).write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_remote_config(runtime.config.paths)
    assert loaded.max_upload_bytes == 200 * 1024 * 1024
    assert loaded.allowed_identities == frozenset({IDENTITY})


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": 1},
        {"enabled": "true"},
        {"allowed_identities": []},
        {"allowed_identities": ["not-a-login"]},
        {"allowed_identities": [" aluno@example.com"]},
        {"allowed_hosts": ["https://host.example"]},
        {"allowed_origins": [f"http://{HOST}"]},
        {"allowed_origins": ["https://other.example"]},
        {"allowed_origins": [f"{ORIGIN}/path"]},
        {"allowed_origins": [f"{ORIGIN}/"]},
        {"allowed_origins": [f"{ORIGIN}:8443"]},
        {"subject_id": "../media"},
        {"model_name": "../../models"},
        {"profile": "gpu"},
        {"max_upload_bytes": 201 * 1024 * 1024},
        {"max_upload_bytes": True},
        {"csrf_ttl_seconds": 5},
        {"request_timeout_seconds": 0},
    ],
)
def test_malformed_configuration_fails_closed(runtime: SimpleNamespace, change: dict) -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "subject_id": runtime.subject_id,
        **change,
    }
    with pytest.raises(RemoteGatewayConfigError):
        RemoteGatewayConfig.from_mapping(raw)


def test_invalid_json_configuration_fails_closed(runtime: SimpleNamespace) -> None:
    remote = runtime.config.paths.root / "remote"
    remote.mkdir()
    (remote / CONFIG_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(RemoteGatewayConfigError):
        load_remote_config(runtime.config.paths)


def test_unknown_subject_prevents_startup(runtime: SimpleNamespace) -> None:
    settings = _settings(runtime, subject_id="00000000-0000-4000-8000-000000000000")
    app = create_remote_gateway_app(runtime.config, gateway_config=settings)
    with pytest.raises(RemoteGatewayConfigError), TestClient(app):
        pass


def test_cli_refuses_disabled_gateway_and_public_host(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    import uvicorn

    monkeypatch.setenv("LOCAL_TRANSCRIBER_DATA_DIR", str(runtime.config.paths.root))
    monkeypatch.setattr(uvicorn, "run", lambda *_a, **_k: pytest.fail("server must not start"))
    assert cli.main(["remote-gateway", "serve"]) == 2
    assert "disabled" in capsys.readouterr().err
    assert cli.main(["remote-gateway", "serve", "--host", "0.0.0.0"]) == 2
    assert "127.0.0.1" in capsys.readouterr().err


def test_cli_starts_only_on_loopback_without_access_log(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    remote = runtime.config.paths.root / "remote"
    remote.mkdir()
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "subject_id": runtime.subject_id,
    }
    (remote / CONFIG_FILENAME).write_text(json.dumps(raw), encoding="utf-8")
    calls: list[dict] = []
    monkeypatch.setenv("LOCAL_TRANSCRIBER_DATA_DIR", str(runtime.config.paths.root))
    monkeypatch.setattr(uvicorn, "run", lambda _app, **kwargs: calls.append(kwargs))
    assert cli.main(["remote-gateway", "serve"]) == 0
    assert calls == [
        {
            "host": "127.0.0.1",
            "port": 8766,
            "workers": 1,
            "access_log": False,
            "proxy_headers": False,
            "server_header": False,
        }
    ]


# --- identity, host, origin and CSRF ---------------------------------------------------


@pytest.mark.parametrize(
    "path", [f"{REMOTE_PREFIX}/session", f"{REMOTE_PREFIX}/unknown", "/api/recordings", "/"]
)
def test_missing_or_unknown_identity_is_denied_everywhere(gateway: TestClient, path: str) -> None:
    missing_response = gateway.get(path, headers={"host": HOST})
    assert missing_response.status_code == 401
    assert missing_response.json() == {"detail": "missing remote identity"}
    empty_response = gateway.get(path, headers=_headers(""))
    assert empty_response.status_code == 401
    assert empty_response.json() == {"detail": "missing remote identity"}
    for identity in ("intruso@example.com", "ALUNO@example.com", "aluno@example.com "):
        response = gateway.get(path, headers=_headers(identity))
        assert response.status_code == 403
        assert response.json() == {"detail": "remote identity is not allowed"}


def test_duplicated_identity_header_is_denied(gateway: TestClient) -> None:
    response = gateway.get(
        f"{REMOTE_PREFIX}/session",
        headers=[
            ("host", HOST),
            ("tailscale-user-login", IDENTITY),
            ("tailscale-user-login", OTHER_IDENTITY),
        ],
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "duplicated remote identity header"}


def test_tailscale_funnel_is_rejected(gateway: TestClient) -> None:
    response = gateway.get(
        f"{REMOTE_PREFIX}/session",
        headers={**_headers(), "tailscale-funnel-request": "?1"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "funnel requests are not allowed"}


def test_untrusted_host_and_public_binding_are_refused(
    runtime: SimpleNamespace, clock: Clock, gateway: TestClient
) -> None:
    for host in (
        "evil.example",
        "127.0.0.1",
        f"user@{HOST}",
        f"{HOST}:notaport",
        f"{HOST}:8766",
        f"{HOST}/path",
        f"{HOST}?query=1",
        f"{HOST}#frag",
    ):
        response = gateway.get(f"{REMOTE_PREFIX}/session", headers={**_headers(), "host": host})
        assert response.status_code == 400
        assert response.json() == {"detail": "untrusted Host header"}
    public = TestClient(gateway.app, base_url="http://192.0.2.10")
    try:
        response = public.get(f"{REMOTE_PREFIX}/session", headers=_headers())
    finally:
        public.close()
    assert response.status_code == 403
    assert response.json() == {"detail": "public server binding is not allowed"}


def test_session_cookie_is_strict_and_security_headers_are_present(gateway: TestClient) -> None:
    response = gateway.get(f"{REMOTE_PREFIX}/session", headers=_headers())
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    for attribute in ("secure", "httponly", "samesite=strict", f"path={REMOTE_PREFIX}"):
        assert attribute in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.json()["max_upload_bytes"] == 64 * 1024


def test_mutations_require_origin_and_bound_unexpired_csrf(
    gateway: TestClient, clock: Clock
) -> None:
    headers = _session(gateway)
    assert _upload(gateway, {k: v for k, v in headers.items() if k != "origin"}).status_code == 403
    assert _upload(gateway, {**headers, "origin": "https://evil.example"}).status_code == 403
    assert _upload(gateway, {**headers, "origin": f"http://{HOST}"}).status_code == 403
    no_token = {k: v for k, v in headers.items() if k != "x-csrf-token"}
    assert _upload(gateway, no_token).status_code == 403
    no_cookie = {k: v for k, v in headers.items() if k != "cookie"}
    assert _upload(gateway, no_cookie).status_code == 403
    assert _upload(gateway, {**headers, "x-csrf-token": "1.forged"}).status_code == 403
    other = _session(gateway, OTHER_IDENTITY)
    assert _upload(gateway, {**headers, "x-csrf-token": other["x-csrf-token"]}).status_code == 403
    assert _upload(gateway, {**headers, "cookie": other["cookie"]}).status_code == 403
    assert _upload(gateway, {**headers, "sec-fetch-site": "cross-site"}).status_code == 403
    clock.value += 3601
    response = _upload(gateway, headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "invalid or expired CSRF token"}


def test_origin_with_trailing_slash_or_port_is_refused(gateway: TestClient) -> None:
    for bad_origin in (f"{ORIGIN}/", f"{ORIGIN}:8443", f"{ORIGIN}:443"):
        response = gateway.get(f"{REMOTE_PREFIX}/session", headers=_headers(origin=bad_origin))
        assert response.status_code == 403
        assert response.json() == {"detail": "untrusted Origin header"}


def test_get_with_foreign_origin_is_refused(gateway: TestClient) -> None:
    response = gateway.get(
        f"{REMOTE_PREFIX}/session", headers=_headers(origin="https://evil.example")
    )
    assert response.status_code == 403


# --- forbidden operations --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/recordings"),
        ("GET", "/api/models"),
        ("GET", "/api/runtime"),
        ("GET", "/api/openapi.json"),
        ("GET", f"{REMOTE_PREFIX}/openapi.json"),
        ("GET", "/docs"),
        ("GET", f"{REMOTE_PREFIX}/auth/chatgpt/login"),
        ("POST", f"{REMOTE_PREFIX}/auth/chatgpt/logout"),
        ("GET", f"{REMOTE_PREFIX}/models"),
        ("POST", f"{REMOTE_PREFIX}/settings"),
        ("GET", f"{REMOTE_PREFIX}/runtime"),
        ("DELETE", f"{REMOTE_PREFIX}/recordings/00000000-0000-4000-8000-000000000000"),
        ("DELETE", f"{REMOTE_PREFIX}/jobs/00000000-0000-4000-8000-000000000000"),
        ("POST", f"{REMOTE_PREFIX}/jobs/00000000-0000-4000-8000-000000000000/cancel"),
        ("PUT", f"{REMOTE_PREFIX}/uploads"),
        ("GET", f"{REMOTE_PREFIX}/uploads"),
        ("GET", f"{REMOTE_PREFIX}/jobs/..%2F..%2Fapi%2Fruntime"),
        ("GET", f"{REMOTE_PREFIX}/jobs/%2E%2E/transcript"),
        ("GET", f"{REMOTE_PREFIX}/media/..%5C..%5Clocal_transcriber.sqlite3"),
        ("GET", "/assets/app.js"),
    ],
)
def test_forbidden_routes_are_not_exposed(gateway: TestClient, method: str, path: str) -> None:
    headers = _session(gateway)
    response = gateway.request(method, path, headers=headers)
    assert response.status_code in {404, 405}
    assert "Traceback" not in response.text


# --- uploads ---------------------------------------------------------------------------


def test_valid_upload_persists_on_the_notebook_without_leaking_personal_data(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    response = _upload(gateway, _session(gateway))
    assert response.status_code == 201, response.text
    payload = response.json()
    assert set(payload) == {
        "id",
        "title",
        "size_bytes",
        "media_format",
        "duration_seconds",
        "created_at",
    }
    recording = runtime.repository.get_recording(payload["id"])
    assert recording is not None
    assert recording.subject_id == runtime.subject_id
    assert recording.title == TITLE
    assert runtime.config.paths.resolve_relative(recording.relative_path).is_file()
    assert _incoming_parts(runtime) == []
    state = (runtime.config.paths.root / "remote" / "gateway.sqlite3").read_bytes()
    for secret in (IDENTITY.encode(), FILENAME.encode(), TITLE.encode()):
        assert secret not in state


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"content_type": "application/octet-stream"}, 415),
        ({"content_type": "audio/mpeg"}, 415),
        ({"filename": "aula.exe", "content_type": "audio/wav"}, 415),
        ({"body": b"not decodable media" * 4}, 415),
        ({"key": "short"}, 400),
        ({"key": "invalid key with spaces!!"}, 400),
        ({"filename": "%FF%FE.wav"}, 400),
    ],
)
def test_invalid_uploads_are_rejected_and_cleaned(
    gateway: TestClient, runtime: SimpleNamespace, overrides: dict, status: int
) -> None:
    headers = _session(gateway)
    response = _upload(gateway, headers, **overrides)
    assert response.status_code == status
    assert runtime.repository.list_recordings() == []
    assert _incoming_parts(runtime) == []
    # The claim is released, so a valid retry with the same key succeeds.
    assert _upload(gateway, headers).status_code == 201


def test_upload_requires_content_length_and_enforces_limit(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    headers = _session(gateway)
    too_large = _upload(gateway, headers, body=b"\0" * (64 * 1024 + 1))
    assert too_large.status_code == 413

    def chunks():
        yield _wav_bytes()

    chunked = gateway.post(
        f"{REMOTE_PREFIX}/uploads",
        content=chunks(),
        headers={
            **headers,
            "idempotency-key": "upload-key-chunked-0001",
            "content-type": "audio/wav",
            "x-filename": "aula.wav",
        },
    )
    assert chunked.status_code == 411
    assert runtime.repository.list_recordings() == []
    assert _incoming_parts(runtime) == []


def _raw_upload(
    app,
    headers: dict[str, str],
    *,
    declared: int,
    chunks: list[bytes],
    disconnect: bool,
    delay: float = 0,
) -> tuple[int | None, bytes]:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    raw_headers += [
        (b"content-length", str(declared).encode()),
        (b"content-type", b"audio/wav"),
        (b"x-filename", b"aula.wav"),
        (b"idempotency-key", b"upload-key-raw-000001"),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"{REMOTE_PREFIX}/uploads",
        "raw_path": f"{REMOTE_PREFIX}/uploads".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8766),
    }
    messages = [{"type": "http.request", "body": chunk, "more_body": True} for chunk in chunks]
    if disconnect:
        messages.append({"type": "http.disconnect"})
    else:
        messages.append({"type": "http.request", "body": b"", "more_body": False})
    sent: dict[str, object] = {"status": None, "body": b""}

    async def receive():
        if delay:
            await asyncio.sleep(delay)
        if messages:
            return messages.pop(0)
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]
        elif message["type"] == "http.response.body":
            sent["body"] = sent["body"] + message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return sent["status"], sent["body"]  # type: ignore[return-value]


def test_interrupted_upload_is_discarded_and_retry_succeeds(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    headers = _session(gateway)
    media = _wav_bytes()
    status, _body = _raw_upload(
        gateway.app, headers, declared=len(media), chunks=[media[:100]], disconnect=True
    )
    assert status in {None, 400}
    assert runtime.repository.list_recordings() == []
    assert _incoming_parts(runtime) == []
    status, _body = _raw_upload(
        gateway.app, headers, declared=len(media), chunks=[media[:100]], disconnect=False
    )
    assert status == 400
    assert _incoming_parts(runtime) == []
    status, body = _raw_upload(
        gateway.app,
        headers,
        declared=len(media),
        chunks=[media[:100], media[100:]],
        disconnect=False,
    )
    assert status == 201, body
    assert len(runtime.repository.list_recordings()) == 1


def test_bytes_beyond_declared_length_are_rejected(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    headers = _session(gateway)
    media = _wav_bytes()
    status, _body = _raw_upload(
        gateway.app, headers, declared=100, chunks=[media], disconnect=False
    )
    assert status == 413
    assert runtime.repository.list_recordings() == []
    assert _incoming_parts(runtime) == []


def test_slow_upload_times_out_and_is_cleaned(runtime: SimpleNamespace, clock: Clock) -> None:
    settings = replace(_settings(runtime), request_timeout_seconds=0.05)
    app = create_remote_gateway_app(runtime.config, gateway_config=settings, clock=clock)
    with TestClient(app) as client:
        headers = _session(client)
        status, _body = _raw_upload(
            app, headers, declared=10, chunks=[b"12345"], disconnect=False, delay=0.2
        )
    assert status == 408
    assert runtime.repository.list_recordings() == []
    assert _incoming_parts(runtime) == []


def test_insufficient_disk_space_is_refused(runtime: SimpleNamespace, clock: Clock) -> None:
    settings = _settings(runtime, min_free_disk_bytes=10 * 1024 * 1024)
    app = create_remote_gateway_app(
        runtime.config,
        gateway_config=settings,
        clock=clock,
        disk_usage=lambda _path: SimpleNamespace(free=1024 * 1024),
    )
    with TestClient(app) as client:
        headers = _session(client)
        assert _upload(client, headers).status_code == 507
    assert runtime.repository.list_recordings() == []


def test_upload_idempotency_replays_without_duplicates(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    headers = _session(gateway)
    first = _upload(gateway, headers)
    assert first.status_code == 201
    replay = _upload(gateway, headers)
    assert replay.status_code == 200
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert len(runtime.repository.list_recordings()) == 1
    mismatch = _upload(gateway, headers, body=_wav_bytes(frames=900))
    assert mismatch.status_code == 422
    # The same bytes under a new key are a duplicate; the existing ID is not disclosed.
    duplicate = _upload(gateway, headers, key="upload-key-0000000002")
    assert duplicate.status_code == 409
    assert first.json()["id"] not in duplicate.text
    # Another identity cannot replay this identity's key.
    other = _upload(gateway, _session(gateway, OTHER_IDENTITY))
    assert other.status_code == 409
    assert first.json()["id"] not in other.text
    assert len(runtime.repository.list_recordings()) == 1


def test_crash_between_core_import_and_gateway_record_recovers_on_retry(
    gateway: TestClient, runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _session(gateway)
    original = GatewayStateStore.complete_upload
    calls = {"count": 0}

    def crash_once(self, key_hash, recording_id):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated crash after core import")
        return original(self, key_hash, recording_id)

    monkeypatch.setattr(GatewayStateStore, "complete_upload", crash_once)
    failed = _upload(gateway, headers)
    assert failed.status_code == 500
    assert failed.json() == {"detail": "internal server error"}
    assert len(runtime.repository.list_recordings()) == 1

    # On retry, because the recording is in core but ownership cannot be proved without
    # core schema changes, the gateway fails closed with 409 to prevent IDOR across identities.
    retry = _upload(gateway, headers)
    assert retry.status_code == 409
    assert retry.json() == {"detail": "this media already exists in the notebook library"}
    assert len(runtime.repository.list_recordings()) == 1


def test_two_distinct_identities_same_audio_prevents_idor(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    _install_model(runtime)
    headers_a = _session(gateway, IDENTITY)
    headers_b = _session(gateway, OTHER_IDENTITY)
    audio = _wav_bytes(frames=600)

    # Identity A uploads the audio successfully
    resp_a = _upload(gateway, headers_a, key="upload-key-ident-a-001", body=audio)
    assert resp_a.status_code == 201
    rec_id_a = resp_a.json()["id"]

    # Identity B uploads the same audio and gets 409 Conflict
    resp_b = _upload(gateway, headers_b, key="upload-key-ident-b-001", body=audio)
    assert resp_b.status_code == 409
    assert resp_b.json() == {"detail": "this media already exists in the notebook library"}
    assert rec_id_a not in resp_b.text

    # Identity B CANNOT create a job for Identity A's recording (404 Not Found)
    job_b = _create_job(gateway, headers_b, rec_id_a, "job-key-b-idor-probe")
    assert job_b.status_code == 404
    assert job_b.json() == {"detail": "recording not found"}

    # Identity A creates a job and runs worker to generate transcript
    job_a = _create_job(gateway, headers_a, rec_id_a, "job-key-a-legit-0001")
    assert job_a.status_code == 202
    job_id_a = job_a.json()["id"]
    _run_worker_once(runtime)

    # Identity B CANNOT access Identity A's job progress or transcript
    assert (
        gateway.get(
            f"{REMOTE_PREFIX}/jobs/{job_id_a}", headers=_headers(OTHER_IDENTITY)
        ).status_code
        == 404
    )
    assert (
        gateway.get(
            f"{REMOTE_PREFIX}/jobs/{job_id_a}/transcript", headers=_headers(OTHER_IDENTITY)
        ).status_code
        == 404
    )


def test_stale_importing_claim_fails_closed_when_sha_found_in_core_preventing_idor(
    gateway: TestClient, runtime: SimpleNamespace, clock: Clock
) -> None:
    import hashlib
    import hmac

    # 1. Identity A uploads an audio file successfully
    audio = _wav_bytes(frames=650)
    headers_a = _session(gateway, IDENTITY)
    resp_a = _upload(gateway, headers_a, key="upload-key-a-stale-001", body=audio)
    assert resp_a.status_code == 201
    rec_id_a = resp_a.json()["id"]

    # 2. Identity B had previously started uploading the same audio and reached 'importing'
    # before crashing or timing out
    headers_b = _session(gateway, OTHER_IDENTITY)
    key_b = "upload-key-b-stale-001"
    secret = (runtime.config.paths.root / "remote" / "csrf.key").read_bytes()
    id_hash_b = hmac.new(secret, f"identity|{OTHER_IDENTITY}".encode(), hashlib.sha256).hexdigest()
    key_hash_b = hmac.new(
        secret, f"key|{id_hash_b}|{key_b}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    fingerprint_b = hashlib.sha256(
        json.dumps(
            [FILENAME, TITLE, "2026-10-20", len(audio), "audio/wav"],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    sha = hashlib.sha256(audio).hexdigest()
    store = gateway.app.state.store
    store.claim_upload(key_hash_b, id_hash_b, fingerprint_b)
    store.mark_importing(key_hash_b, sha)

    # 3. Time passes beyond STALE_CLAIM_SECONDS
    clock.value += STALE_CLAIM_SECONDS + 10

    # 4. Identity B retries. Because ownership of the core recording cannot be proven
    # without core schema changes, the gateway must fail closed with 409
    retry_b = _upload(gateway, headers_b, key=key_b, body=audio)
    assert retry_b.status_code == 409
    assert retry_b.json() == {"detail": "this media already exists in the notebook library"}

    # 5. Identity B did NOT gain ownership of Identity A's recording
    assert not store.owns_recording(id_hash_b, rec_id_a)
    job_probe = _create_job(gateway, headers_b, rec_id_a, "job-key-b-probe-stale")
    assert job_probe.status_code == 404


def test_crash_before_core_import_reclaims_stale_claim_and_succeeds(
    gateway: TestClient, runtime: SimpleNamespace, clock: Clock
) -> None:
    import hashlib
    import hmac

    headers = _session(gateway)
    media = _wav_bytes(frames=750)
    key = "upload-crash-before-import-001"

    secret = (runtime.config.paths.root / "remote" / "csrf.key").read_bytes()
    identity_hash = hmac.new(secret, f"identity|{IDENTITY}".encode(), hashlib.sha256).hexdigest()
    key_hash = hmac.new(
        secret, f"key|{identity_hash}|{key}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    fingerprint = hashlib.sha256(
        json.dumps(
            [FILENAME, TITLE, "2026-10-20", len(media), "audio/wav"],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    store = gateway.app.state.store
    store.claim_upload(key_hash, identity_hash, fingerprint)
    store.mark_importing(key_hash, "0" * 64)

    # Immediate retry (< STALE_CLAIM_SECONDS) while importing must return 409 busy
    busy = _upload(gateway, headers, key=key, body=media)
    assert busy.status_code == 409
    assert busy.json() == {"detail": "an upload with this Idempotency-Key is in progress"}

    # After stale period (> STALE_CLAIM_SECONDS), retry finds sha NOT in core,
    # reclaims stale import and succeeds!
    clock.value += STALE_CLAIM_SECONDS + 1
    recovered = _upload(gateway, headers, key=key, body=media)
    assert recovered.status_code == 201
    assert len(runtime.repository.list_recordings()) == 1


def test_simultaneous_disk_check_serializes_and_refuses_overflow(
    runtime: SimpleNamespace, clock: Clock
) -> None:
    # 200 frames of wav = ~3244 bytes. With minimum free disk 50 KB and starting free 55 KB,
    # the first upload passes, second sees reduced disk and gets 507.
    media_1 = _wav_bytes(frames=200)
    media_2 = _wav_bytes(frames=250)
    free_bytes = [55 * 1024]

    def dynamic_disk_usage(_path):
        val = free_bytes[0]
        free_bytes[0] = max(0, free_bytes[0] - 50 * 1024)
        return SimpleNamespace(free=val)

    settings = _settings(runtime, min_free_disk_bytes=50 * 1024)
    app = create_remote_gateway_app(
        runtime.config,
        gateway_config=settings,
        clock=clock,
        disk_usage=dynamic_disk_usage,
    )
    with TestClient(app) as client:
        headers_1 = _session(client, IDENTITY)
        headers_2 = _session(client, OTHER_IDENTITY)

        resp1 = _upload(client, headers_1, key="upload-disc-000000001", body=media_1)
        assert resp1.status_code == 201

        resp2 = _upload(client, headers_2, key="upload-disc-000000002", body=media_2)
        assert resp2.status_code == 507
        assert resp2.json() == {"detail": "insufficient free disk space on the notebook"}


def test_complete_upload_prohibits_same_recording_for_distinct_identity(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    from local_transcriber.remote_gateway import RemoteGatewayError

    store = gateway.app.state.store
    rec_id = "11111111-2222-3333-4444-555555555555"
    store.claim_upload("key1", "id_a", "fp1")
    store.complete_upload("key1", rec_id)

    store.claim_upload("key2", "id_b", "fp2")
    with pytest.raises(RemoteGatewayError, match="already owned by a different identity"):
        store.complete_upload("key2", rec_id)

    # owns_recording for id_b must return False
    assert not store.owns_recording("id_b", rec_id)
    assert store.owns_recording("id_a", rec_id)


def test_stale_receiving_claim_is_reclaimed(
    gateway: TestClient, runtime: SimpleNamespace, clock: Clock
) -> None:
    headers = _session(gateway)
    # Simulate a process that died while receiving: claim the key through a first request
    # that is interrupted before the gateway could release it.
    media = _wav_bytes()
    original_release = GatewayStateStore.release_upload
    GatewayStateStore.release_upload = lambda self, key_hash: None  # type: ignore[method-assign]
    try:
        status, _body = _raw_upload(
            gateway.app, headers, declared=len(media), chunks=[media[:10]], disconnect=False
        )
    finally:
        GatewayStateStore.release_upload = original_release  # type: ignore[method-assign]
    assert status == 400
    complete = dict(chunks=[media], disconnect=False)
    status, _body = _raw_upload(gateway.app, headers, declared=len(media), **complete)
    assert status == 409
    clock.value += STALE_CLAIM_SECONDS + 1
    status, body = _raw_upload(gateway.app, headers, declared=len(media), **complete)
    assert status == 201, body
    assert len(runtime.repository.list_recordings()) == 1


# --- jobs, progress and transcript ----------------------------------------------------


def test_job_creation_is_idempotent_single_and_does_not_consume_queue(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    _install_model(runtime)
    headers = _session(gateway)
    recording_id = _upload(gateway, headers).json()["id"]
    created = _create_job(gateway, headers, recording_id, "job-key-000000000001")
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]
    replay = _create_job(gateway, headers, recording_id, "job-key-000000000001")
    assert replay.status_code == 200
    assert replay.json()["id"] == job_id
    second_key = _create_job(gateway, headers, recording_id, "job-key-000000000002")
    assert second_key.status_code == 200
    assert second_key.json()["id"] == job_id
    assert [job.id for job in runtime.repository.list_jobs()] == [job_id]
    assert runtime.repository.get_job(job_id).status is JobStatus.PENDING
    assert not any(thread.name == "local-transcriber-worker" for thread in threading.enumerate())


def test_job_creation_validates_ownership_and_model(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    headers = _session(gateway)
    recording_id = _upload(gateway, headers).json()["id"]
    missing_model = _create_job(gateway, headers, recording_id, "job-key-000000000001")
    assert missing_model.status_code == 409
    assert runtime.repository.list_jobs() == []
    _install_model(runtime)
    assert _create_job(gateway, headers, recording_id, "job-key-000000000001").status_code == 202
    library = MediaLibrary(runtime.repository, runtime.config.paths)
    local = library.import_stream(
        io.BytesIO(_wav_bytes(value=7)),
        original_name="local.wav",
        title="Local",
        subject_id=runtime.subject_id,
        lesson_date=__import__("datetime").date(2026, 10, 1),
    )
    assert _create_job(gateway, headers, local.id, "job-key-000000000003").status_code == 404
    other = _session(gateway, OTHER_IDENTITY)
    assert _create_job(gateway, other, recording_id, "job-key-000000000004").status_code == 404
    mismatch = _create_job(gateway, headers, local.id, "job-key-000000000001")
    assert mismatch.status_code == 404
    bad = gateway.post(
        f"{REMOTE_PREFIX}/jobs",
        json={"recording_id": recording_id, "model_name": "large"},
        headers={**headers, "idempotency-key": "job-key-000000000005"},
    )
    assert bad.status_code == 422
    assert len(runtime.repository.list_jobs()) == 1


def test_crash_between_enqueue_and_gateway_record_recovers_single_job(
    gateway: TestClient, runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_model(runtime)
    headers = _session(gateway)
    recording_id = _upload(gateway, headers).json()["id"]
    original = GatewayStateStore.complete_job
    calls = {"count": 0}

    def crash_once(self, key_hash, job_id):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated crash after enqueue")
        return original(self, key_hash, job_id)

    monkeypatch.setattr(GatewayStateStore, "complete_job", crash_once)
    assert _create_job(gateway, headers, recording_id, "job-key-000000000001").status_code == 500
    assert len(runtime.repository.list_jobs()) == 1
    retry = _create_job(gateway, headers, recording_id, "job-key-000000000001")
    assert retry.status_code == 200
    assert retry.json()["id"] == runtime.repository.list_jobs()[0].id
    assert len(runtime.repository.list_jobs()) == 1


def test_create_job_with_deleted_recording_returns_410_and_releases_claim(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    _install_model(runtime)
    headers = _session(gateway)
    recording_id = _upload(gateway, headers).json()["id"]
    # Simulate deletion of recording from notebook core
    runtime.repository.delete_recording(recording_id)
    response = _create_job(gateway, headers, recording_id, "job-key-del-000000001")
    assert response.status_code == 410
    assert response.json() == {"detail": "recording is no longer available on the notebook"}
    # The claim was released, not left stuck in 'creating'
    assert not gateway.app.state.store.owns_job(
        gateway.app.state.signer.issue(headers["tailscale-user-login"])[0],
        "job-key-del-000000001",
    )


def test_load_or_create_secret_validates_and_reapplies_acl_on_existing_secret(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import local_transcriber.chatgpt_auth as auth_mod
    from local_transcriber.exceptions import ChatGPTAuthError
    from local_transcriber.remote_gateway import (
        SECRET_FILENAME,
        load_or_create_secret,
        remote_dir,
    )

    secret = load_or_create_secret(runtime.config.paths)
    assert len(secret) == 32
    secret_path = remote_dir(runtime.config.paths) / SECRET_FILENAME
    assert secret_path.is_file()

    # Second call on pre-existing file must invoke secure_file_permissions again
    calls = []
    original_secure = auth_mod.secure_file_permissions
    monkeypatch.setattr(
        auth_mod,
        "secure_file_permissions",
        lambda p: calls.append(p) or original_secure(p),
    )
    secret2 = load_or_create_secret(runtime.config.paths)
    assert secret2 == secret
    assert calls == [secret_path]

    # If secure_file_permissions fails on pre-existing secret, startup fails closed
    monkeypatch.setattr(
        auth_mod,
        "secure_file_permissions",
        lambda _p: (_ for _ in ()).throw(ChatGPTAuthError("cannot restrict ACL")),
    )
    with pytest.raises(RemoteGatewayConfigError, match="could not restrict the gateway secret"):
        load_or_create_secret(runtime.config.paths)


def test_progress_and_transcript_only_after_completion(
    gateway: TestClient, runtime: SimpleNamespace
) -> None:
    _install_model(runtime)
    headers = _session(gateway)
    recording_id = _upload(gateway, headers).json()["id"]
    job_id = _create_job(gateway, headers, recording_id, "job-key-000000000001").json()["id"]
    progress = gateway.get(f"{REMOTE_PREFIX}/jobs/{job_id}", headers=_headers())
    assert progress.status_code == 200
    assert progress.json()["status"] == "pending"
    assert progress.json()["transcript_available"] is False
    assert "worker_id" not in progress.json()
    early = gateway.get(f"{REMOTE_PREFIX}/jobs/{job_id}/transcript", headers=_headers())
    assert early.status_code == 409
    # The core worker (simulated here with a fake engine) is the only queue consumer.
    _run_worker_once(runtime)
    done = gateway.get(f"{REMOTE_PREFIX}/jobs/{job_id}", headers=_headers())
    assert done.json()["status"] == "succeeded"
    assert done.json()["transcript_available"] is True
    transcript = gateway.get(f"{REMOTE_PREFIX}/jobs/{job_id}/transcript", headers=_headers())
    assert transcript.status_code == 200
    assert transcript.json()["text"] == "texto sintetico"
    assert transcript.json()["segments"][0]["text"] == "texto sintetico"
    other = gateway.get(
        f"{REMOTE_PREFIX}/jobs/{job_id}/transcript", headers=_headers(OTHER_IDENTITY)
    )
    assert other.status_code == 404
    assert gateway.get(f"{REMOTE_PREFIX}/jobs/not-a-uuid", headers=_headers()).status_code == 404


def test_gateway_logs_do_not_contain_personal_data(
    runtime: SimpleNamespace, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        _install_model(runtime)
        client.get(f"{REMOTE_PREFIX}/session", headers=_headers("intruso@example.com"))
        headers = _session(client)
        recording_id = _upload(client, headers).json()["id"]
        _create_job(client, headers, recording_id, "job-key-000000000001")
        _upload(client, headers, key="upload-key-0000000009", body=b"bad" * 10)
    text = caplog.text
    for secret in (
        IDENTITY,
        "intruso@example.com",
        FILENAME,
        TITLE,
        str(runtime.config.paths.root),
    ):
        assert secret not in text


def test_core_api_remains_loopback_and_has_no_remote_routes(runtime: SimpleNamespace) -> None:
    app = create_app(runtime.config, start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get(f"{REMOTE_PREFIX}/session").status_code == 404
        assert client.get("/api/health", headers={"host": HOST}).status_code == 400
        assert client.app.state.database.schema_version() == 4
