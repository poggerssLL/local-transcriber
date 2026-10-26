"""Stage 2 remote access tests: allowed_subjects, subject selection, and bounded rate limiting."""

from __future__ import annotations

import io
import json
import socket
import threading
import wave
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.database import Database
from local_transcriber.models import Subject
from local_transcriber.remote_gateway import (
    IDENTITY_HEADER,
    REMOTE_PREFIX,
    SESSION_COOKIE,
    InMemoryRateLimiter,
    RemoteGatewayConfig,
    RemoteGatewayConfigError,
    create_remote_gateway_app,
)
from local_transcriber.repository import Repository

HOST = "notebook.example-tailnet.ts.net"
ORIGIN = f"https://{HOST}"
IDENTITY = "aluno@example.com"
OTHER_IDENTITY = "colega@example.com"
FILENAME = "Aula Stage2.wav"
TITLE = "Aula Stage2 Titulo"


def _wav_bytes(*, frames: int = 800, value: int = 0) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(value.to_bytes(2, "little", signed=True) * frames)
    return output.getvalue()


class MockClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr(socket, "create_connection", safe_create_connection)


@pytest.fixture
def runtime(tmp_path: Path) -> SimpleNamespace:
    config = AppConfig(RuntimePaths((tmp_path / "runtime").resolve()))
    config.paths.ensure_directories()
    database = Database(config.paths.database)
    database.initialize()
    repository = Repository(database)
    sub1 = repository.add_subject(Subject(name="Direito Constitucional"))
    sub2 = repository.add_subject(Subject(name="Direito Penal"))
    sub3 = repository.add_subject(Subject(name="Direito Civil"))
    return SimpleNamespace(
        config=config,
        repository=repository,
        subject1=sub1,
        subject2=sub2,
        subject3=sub3,
    )


def _client_for(
    runtime: SimpleNamespace,
    settings: RemoteGatewayConfig,
    clock: MockClock | None = None,
) -> TestClient:
    app_clock = clock or MockClock()
    app = create_remote_gateway_app(
        runtime.config,
        gateway_config=settings,
        clock=app_clock,
        rate_limit_clock=app_clock,
    )
    return TestClient(app)


def _headers(identity: str = IDENTITY, **extra: str) -> dict[str, str]:
    return {"host": HOST, IDENTITY_HEADER: identity, **extra}


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
    key: str = "upload-stage2-0000000001",
    body: bytes | None = None,
    subject_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
):
    payload = _wav_bytes() if body is None else body
    req_headers = {
        **headers,
        "idempotency-key": key,
        "content-type": "audio/wav",
        "x-filename": FILENAME.replace(" ", "%20"),
        "x-title": TITLE.replace(" ", "%20"),
        "x-lesson-date": "2026-10-25",
    }
    if subject_id is not None:
        req_headers["x-subject-id"] = subject_id
    if extra_headers:
        req_headers.update(extra_headers)
    return client.post(f"{REMOTE_PREFIX}/uploads", content=payload, headers=req_headers)


# ==============================================================================
# 1. Config & Migration Tests
# ==============================================================================


def test_config_legacy_subject_id_fallback(runtime: SimpleNamespace) -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "subject_id": runtime.subject1.id,
    }
    config = RemoteGatewayConfig.from_mapping(raw)
    assert config.allowed_subjects == frozenset({runtime.subject1.id})
    assert config.subject_id == runtime.subject1.id


def test_config_empty_allowed_subjects_fails() -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "allowed_subjects": [],
    }
    with pytest.raises(RemoteGatewayConfigError, match="allowed_subjects must be a non-empty list"):
        RemoteGatewayConfig.from_mapping(raw)


def test_config_empty_allowed_subjects_with_legacy_subject_id_fails(
    runtime: SimpleNamespace,
) -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "allowed_subjects": [],
        "subject_id": runtime.subject1.id,
    }
    with pytest.raises(RemoteGatewayConfigError, match="allowed_subjects must be a non-empty list"):
        RemoteGatewayConfig.from_mapping(raw)


def test_config_explicit_null_allowed_subjects_with_legacy_subject_id_fails(
    runtime: SimpleNamespace,
) -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "allowed_subjects": None,
        "subject_id": runtime.subject1.id,
    }
    with pytest.raises(RemoteGatewayConfigError, match="allowed_subjects must be a non-empty list"):
        RemoteGatewayConfig.from_mapping(raw)


def test_config_explicit_null_allowed_subjects_without_subject_id_fails() -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "allowed_subjects": None,
    }
    with pytest.raises(RemoteGatewayConfigError, match="allowed_subjects must be a non-empty list"):
        RemoteGatewayConfig.from_mapping(raw)


def test_config_invalid_uuid_fails() -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "allowed_subjects": ["not-a-valid-uuid"],
    }
    with pytest.raises(RemoteGatewayConfigError, match="allowed_subjects contains invalid UUID"):
        RemoteGatewayConfig.from_mapping(raw)


def test_config_mixed_subject_id_outside_allowlist_fails(runtime: SimpleNamespace) -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "allowed_subjects": [runtime.subject1.id],
        "subject_id": runtime.subject2.id,
    }
    with pytest.raises(
        RemoteGatewayConfigError, match="legacy subject_id must be included in allowed_subjects"
    ):
        RemoteGatewayConfig.from_mapping(raw)


def test_config_mixed_subject_id_inside_allowlist_succeeds(runtime: SimpleNamespace) -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "allowed_subjects": [runtime.subject1.id, runtime.subject2.id],
        "subject_id": runtime.subject1.id,
    }
    config = RemoteGatewayConfig.from_mapping(raw)
    assert config.allowed_subjects == frozenset({runtime.subject1.id, runtime.subject2.id})
    assert config.subject_id == runtime.subject1.id


def test_config_missing_both_fails() -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
    }
    with pytest.raises(
        RemoteGatewayConfigError, match="either allowed_subjects or subject_id must be configured"
    ):
        RemoteGatewayConfig.from_mapping(raw)


def test_config_rejects_allow_all_subjects(runtime: SimpleNamespace) -> None:
    raw = {
        "enabled": True,
        "allowed_identities": [IDENTITY],
        "allowed_hosts": [HOST],
        "allowed_origins": [ORIGIN],
        "allowed_subjects": [runtime.subject1.id],
        "allow_all_subjects": True,
    }
    with pytest.raises(
        RemoteGatewayConfigError, match="gateway configuration contains unknown keys"
    ):
        RemoteGatewayConfig.from_mapping(raw)


def test_config_startup_fails_if_any_subject_missing_from_db(runtime: SimpleNamespace) -> None:
    ghost_id = str(uuid4())
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id, ghost_id}),
    )
    app = create_remote_gateway_app(runtime.config, gateway_config=settings)
    with pytest.raises(
        RemoteGatewayConfigError,
        match=f"configured subject '{ghost_id}' does not exist on notebook",
    ):
        with TestClient(app):
            pass


# ==============================================================================
# 2. Endpoint GET /remote/v1/subjects
# ==============================================================================


def test_get_subjects_returns_only_allowlisted(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id, runtime.subject3.id}),
    )
    with _client_for(runtime, settings) as client:
        response = client.get(f"{REMOTE_PREFIX}/subjects", headers=_headers(IDENTITY))
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        ids = {item["id"] for item in data}
        assert ids == {runtime.subject1.id, runtime.subject3.id}
        assert runtime.subject2.id not in ids


def test_get_subjects_payload_schema_leak_free(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
    )
    with _client_for(runtime, settings) as client:
        response = client.get(f"{REMOTE_PREFIX}/subjects", headers=_headers(IDENTITY))
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        item = data[0]
        assert set(item.keys()) == {"id", "name"}
        assert "created_at" not in item
        assert "recordings" not in item


def test_get_subjects_rejects_unauthenticated(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
    )
    with _client_for(runtime, settings) as client:
        response = client.get(f"{REMOTE_PREFIX}/subjects", headers={"host": HOST})
        assert response.status_code == 401
        assert response.json()["detail"] == "missing remote identity"


def test_get_subjects_rejects_unallowed_identity(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
    )
    with _client_for(runtime, settings) as client:
        response = client.get(f"{REMOTE_PREFIX}/subjects", headers=_headers(OTHER_IDENTITY))
        assert response.status_code == 403
        assert response.json()["detail"] == "remote identity is not allowed"


def test_get_subjects_rejects_funnel(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
    )
    with _client_for(runtime, settings) as client:
        response = client.get(
            f"{REMOTE_PREFIX}/subjects",
            headers=_headers(IDENTITY, **{"tailscale-funnel-request": "?1"}),
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "funnel requests are not allowed"


def test_get_subjects_rejects_bad_host(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
    )
    with _client_for(runtime, settings) as client:
        response = client.get(
            f"{REMOTE_PREFIX}/subjects",
            headers={"host": "attacker.com", IDENTITY_HEADER: IDENTITY},
        )
        assert response.status_code == 400


# ==============================================================================
# 3. Upload & Subject Selection Tests
# ==============================================================================


def test_upload_with_valid_x_subject_id(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id, runtime.subject2.id}),
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)
        resp = _upload(client, headers, subject_id=runtime.subject2.id)
        assert resp.status_code == 201
        rec_id = resp.json()["id"]
        recording = runtime.repository.get_recording(rec_id)
        assert recording is not None
        assert recording.subject_id == runtime.subject2.id


def test_upload_with_unauthorized_x_subject_id(runtime: SimpleNamespace) -> None:
    # subject3 exists in DB, but only subject1 and subject2 are allowlisted
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id, runtime.subject2.id}),
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)
        resp = _upload(client, headers, subject_id=runtime.subject3.id)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "subject is not authorized for remote upload"


def test_upload_with_malformed_x_subject_id(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)
        resp = _upload(client, headers, subject_id="not-a-valid-uuid-syntax")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "malformed X-Subject-Id header"


def test_upload_with_missing_header_multiple_subjects_fails(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id, runtime.subject2.id}),
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)
        resp = _upload(client, headers, subject_id=None)
        assert resp.status_code == 400
        assert "X-Subject-Id header is required" in resp.json()["detail"]


def test_upload_with_missing_header_single_legacy_subject_fallback(
    runtime: SimpleNamespace,
) -> None:
    # When single subject is allowed AND configured as legacy default subject_id
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=runtime.subject1.id,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)
        resp = _upload(client, headers, subject_id=None)
        assert resp.status_code == 201
        rec_id = resp.json()["id"]
        recording = runtime.repository.get_recording(rec_id)
        assert recording is not None
        assert recording.subject_id == runtime.subject1.id


def test_upload_with_missing_header_single_subject_no_default_requires_explicit_selection(
    runtime: SimpleNamespace,
) -> None:
    # When single subject is allowed, but subject_id is None (no legacy default)
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=None,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)
        resp = _upload(client, headers, subject_id=None)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "X-Subject-Id header is required"


# ==============================================================================
# 4. Idempotency & Replay with Subject Fingerprint
# ==============================================================================


def test_upload_idempotency_mismatched_subject_fails(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id, runtime.subject2.id}),
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)
        key = "idempotency-subject-mismatch-01"

        # 1. Upload with subject1 succeeds
        resp1 = _upload(client, headers, key=key, subject_id=runtime.subject1.id)
        assert resp1.status_code == 201

        # 2. Resend same key with subject2 -> fails with 422 mismatch
        resp2 = _upload(client, headers, key=key, subject_id=runtime.subject2.id)
        assert resp2.status_code == 422
        assert resp2.json()["detail"] == "Idempotency-Key was already used for another request"


def test_upload_idempotency_same_subject_replays(runtime: SimpleNamespace) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=runtime.subject1.id,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)
        key = "idempotency-same-subject-01"

        # 1. First upload succeeds
        resp1 = _upload(client, headers, key=key, subject_id=runtime.subject1.id)
        assert resp1.status_code == 201
        rec_id = resp1.json()["id"]

        # 2. Resend same key with same subject -> returns 200 with replayed header
        resp2 = _upload(client, headers, key=key, subject_id=runtime.subject1.id)
        assert resp2.status_code == 200
        assert resp2.headers.get("idempotent-replayed") == "true"
        assert resp2.json()["id"] == rec_id


def test_upload_legacy_5_element_fingerprint_replay_fails_closed(runtime: SimpleNamespace) -> None:
    import hashlib
    import hmac

    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=runtime.subject1.id,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    audio = _wav_bytes()
    key = "legacy-upload-replay-key-001"

    with _client_for(runtime, settings) as client:
        headers = _session(client)
        secret = (runtime.config.paths.root / "remote" / "csrf.key").read_bytes()
        identity_hash = hmac.new(
            secret, f"identity|{IDENTITY}".encode(), hashlib.sha256
        ).hexdigest()
        key_hash = hmac.new(
            secret, f"key|{identity_hash}|{key}".encode("ascii"), hashlib.sha256
        ).hexdigest()

        # Legacy 5-element fingerprint without subject_id
        legacy_fingerprint = hashlib.sha256(
            json.dumps(
                [FILENAME, TITLE, "2026-10-25", len(audio), "audio/wav"],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        store = client.app.state.store
        store.claim_upload(key_hash, identity_hash, legacy_fingerprint)

        # Retry with the same key under Stage 2
        retry_resp = _upload(client, headers, key=key, body=audio)
        assert retry_resp.status_code == 409
        assert (
            retry_resp.json()["detail"]
            == "legacy upload fingerprint requires a new Idempotency-Key"
        )

        # The claim in remote_uploads was NOT deleted (remains recorded)
        with store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remote_uploads WHERE key_hash = ?", (key_hash,)
            ).fetchone()
            assert row is not None
            assert row["fingerprint"] == legacy_fingerprint


def test_upload_fails_closed_if_subject_deleted_mid_stream(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=runtime.subject1.id,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings) as client:
        headers = _session(client)

        # Simulate concurrent deletion of subject right before import_stream runs
        def simulate_mid_stream_delete(*args, **kwargs):
            # Delete subject from DB
            with runtime.repository.database.transaction() as conn:
                conn.execute("DELETE FROM subjects WHERE id = ?", (runtime.subject1.id,))
            raise KeyError(f"subject not found: {runtime.subject1.id}")

        monkeypatch.setattr(client.app.state.repository, "get_recording", lambda *a, **k: None)
        # Monkeypatch media import to trigger KeyError
        from local_transcriber.media import MediaLibrary

        monkeypatch.setattr(MediaLibrary, "import_stream", simulate_mid_stream_delete)

        resp = _upload(client, headers, subject_id=runtime.subject1.id)
        assert resp.status_code == 422
        assert resp.json()["detail"] == "media could not be imported"


# ==============================================================================
# 5. Rate Limiting Tests (Token Bucket, Bounded Memory, Isolation)
# ==============================================================================


def test_rate_limit_read_group_burst_and_exhaustion(runtime: SimpleNamespace) -> None:
    mock_clock = MockClock()
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
    )
    with _client_for(runtime, settings, clock=mock_clock) as client:
        # 30 immediate reads succeed (burst = 30)
        for i in range(30):
            resp = client.get(f"{REMOTE_PREFIX}/subjects", headers=_headers(IDENTITY))
            assert resp.status_code == 200, f"Read #{i + 1} failed"

        # 31st immediate read exhausts bucket and returns 429 with integer Retry-After
        resp31 = client.get(f"{REMOTE_PREFIX}/subjects", headers=_headers(IDENTITY))
        assert resp31.status_code == 429
        assert resp31.json()["detail"] == "rate limit exceeded"
        retry_after = resp31.headers.get("retry-after")
        assert retry_after is not None
        assert retry_after.isdigit()
        assert int(retry_after) >= 1

        # Advance clock by refill time (needed = 1 token, rate = 0.5/s -> 2s)
        mock_clock.advance(2.0)
        resp32 = client.get(f"{REMOTE_PREFIX}/subjects", headers=_headers(IDENTITY))
        assert resp32.status_code == 200


def test_rate_limit_mutation_group_burst_and_exhaustion(runtime: SimpleNamespace) -> None:
    mock_clock = MockClock()
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=runtime.subject1.id,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings, clock=mock_clock) as client:
        headers = _session(client)
        # 5 immediate mutations succeed (burst = 5)
        for i in range(5):
            resp = _upload(
                client,
                headers,
                key=f"rate-limit-mut-{i:04d}-key",
                body=_wav_bytes(value=i + 1),
            )
            assert resp.status_code == 201, f"Mutation #{i + 1} failed"

        # 6th immediate mutation returns 429
        resp6 = _upload(
            client,
            headers,
            key="rate-limit-mut-0005-key",
            body=_wav_bytes(value=6),
        )
        assert resp6.status_code == 429
        assert resp6.json()["detail"] == "rate limit exceeded"
        retry_after = resp6.headers.get("retry-after")
        assert retry_after is not None
        assert retry_after.isdigit()
        assert int(retry_after) == 12  # needed = 1 token, refill = 1/12s -> 12 seconds


def test_rate_limit_refill_via_monotonic_clock(runtime: SimpleNamespace) -> None:
    mock_clock = MockClock()
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=runtime.subject1.id,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings, clock=mock_clock) as client:
        headers = _session(client)
        for i in range(5):
            assert (
                _upload(
                    client,
                    headers,
                    key=f"refill-test-{i:04d}-key",
                    body=_wav_bytes(value=i + 1),
                ).status_code
                == 201
            )

        # 6th blocked
        assert (
            _upload(
                client,
                headers,
                key="refill-test-0005-key",
                body=_wav_bytes(value=6),
            ).status_code
            == 429
        )

        # Advance clock by 12s
        mock_clock.advance(12.0)
        resp = _upload(
            client,
            headers,
            key="refill-test-0005-key",
            body=_wav_bytes(value=6),
        )
        assert resp.status_code == 201


def test_rate_limit_does_not_consume_idempotency_key(runtime: SimpleNamespace) -> None:
    mock_clock = MockClock()
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=runtime.subject1.id,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings, clock=mock_clock) as client:
        headers = _session(client)
        # Exhaust 5 mutation tokens
        for i in range(5):
            assert (
                _upload(
                    client,
                    headers,
                    key=f"key-burn-test-{i:04d}-key",
                    body=_wav_bytes(value=i + 1),
                ).status_code
                == 201
            )

        # Attempt with key "important-key-429-test" -> gets 429
        blocked_resp = _upload(
            client,
            headers,
            key="important-key-429-test",
            body=_wav_bytes(value=100),
        )
        assert blocked_resp.status_code == 429

        # Advance clock so token refills
        mock_clock.advance(12.0)

        # Retry with the same key -> must succeed with 201 without burning the claim
        retry_resp = _upload(
            client,
            headers,
            key="important-key-429-test",
            body=_wav_bytes(value=100),
        )
        assert retry_resp.status_code == 201


def test_rate_limit_unauthenticated_does_not_allocate_bucket(runtime: SimpleNamespace) -> None:
    mock_clock = MockClock()
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
    )
    with _client_for(runtime, settings, clock=mock_clock) as client:
        limiter = client.app.state.rate_limiter
        # Missing identity -> 401
        client.get(f"{REMOTE_PREFIX}/subjects", headers={"host": HOST})
        # Unallowed identity -> 403
        client.get(f"{REMOTE_PREFIX}/subjects", headers=_headers("hacker@bad.com"))
        # Funnel request -> 403
        client.get(
            f"{REMOTE_PREFIX}/subjects",
            headers=_headers(IDENTITY, **{"tailscale-funnel-request": "?1"}),
        )

        # No bucket should be allocated in the rate limiter
        assert len(limiter._identities) == 0


def test_rate_limit_bounded_memory_pruning() -> None:
    mock_clock = MockClock(start=100.0)
    limiter = InMemoryRateLimiter(clock=mock_clock)

    # Acquire tokens for 5 identities
    for i in range(5):
        allowed, _ = limiter.acquire(f"hash_{i}", "read")
        assert allowed

    assert len(limiter._identities) == 5

    # Advance clock beyond TTL (300s)
    mock_clock.advance(305.0)

    # New identity arrives -> triggers pruning of the old 5 identities
    allowed, _ = limiter.acquire("hash_new", "read")
    assert allowed
    assert len(limiter._identities) == 1
    assert "hash_new" in limiter._identities


def test_rate_limit_bounded_memory_saturation() -> None:
    mock_clock = MockClock(start=100.0)
    limiter = InMemoryRateLimiter(clock=mock_clock)

    # Fill up to MAX_IDENTITIES (100)
    for i in range(100):
        allowed, _ = limiter.acquire(f"ident_{i}", "read")
        assert allowed

    assert len(limiter._identities) == 100

    # 101st identity arrives without advancing clock past TTL -> rejected
    allowed, retry_after = limiter.acquire("ident_101", "read")
    assert not allowed
    assert retry_after >= 1
    # Still bounded to 100
    assert len(limiter._identities) == 100


def test_rate_limit_isolated_per_identity(runtime: SimpleNamespace) -> None:
    mock_clock = MockClock()
    settings = RemoteGatewayConfig(
        enabled=True,
        allowed_identities=frozenset({IDENTITY, OTHER_IDENTITY}),
        allowed_hosts=frozenset({HOST}),
        allowed_origins=frozenset({ORIGIN}),
        allowed_subjects=frozenset({runtime.subject1.id}),
        subject_id=runtime.subject1.id,
        max_upload_bytes=64 * 1024,
        min_free_disk_bytes=0,
    )
    with _client_for(runtime, settings, clock=mock_clock) as client:
        headers_a = _session(client, IDENTITY)
        headers_b = _session(client, OTHER_IDENTITY)

        # Exhaust Identity A's mutation quota
        for i in range(5):
            assert (
                _upload(
                    client,
                    headers_a,
                    key=f"iso-a-upload-key-{i:03d}",
                    body=_wav_bytes(value=i + 1),
                ).status_code
                == 201
            )

        # A is blocked
        assert (
            _upload(
                client,
                headers_a,
                key="iso-a-upload-key-005",
                body=_wav_bytes(value=6),
            ).status_code
            == 429
        )

        # Identity B is unaffected and can upload
        resp_b = _upload(
            client,
            headers_b,
            key="iso-b-upload-key-000",
            body=_wav_bytes(value=10),
        )
        assert resp_b.status_code == 201


def test_rate_limit_thread_safety() -> None:
    mock_clock = MockClock()
    limiter = InMemoryRateLimiter(clock=mock_clock)
    results: list[bool] = []
    lock = threading.Lock()

    def worker():
        for _ in range(10):
            allowed, _ = limiter.acquire("concurrent_identity", "read")
            with lock:
                results.append(allowed)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 50 attempts made in total; burst capacity is 30, so exactly 30 must succeed and 20 fail
    assert len(results) == 50
    assert results.count(True) == 30
    assert results.count(False) == 20
