"""Resumable gateway protocol; synthetic media and isolated runtime only."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_remote_gateway import (
    OTHER_IDENTITY,
    _install_model,
    _session,
    _settings,
    _upload,
    _wav_bytes,
)
from test_remote_gateway import _no_network as _no_network
from test_remote_gateway import clock as clock
from test_remote_gateway import runtime as runtime

import local_transcriber.remote_gateway as gateway_module
from local_transcriber.media import MediaLibrary
from local_transcriber.remote_gateway import REMOTE_PREFIX, create_remote_gateway_app

URL = f"{REMOTE_PREFIX}/uploads/resumable"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def remote(runtime, clock, monkeypatch):
    # Exercise multiple server-sized chunks with a tiny synthetic WAV.
    monkeypatch.setattr(gateway_module, "RESUMABLE_CHUNK_BYTES", 512)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, app=app, headers=_session(client), clock=clock, runtime=runtime
        )


def _request(remote, method, url, **kwargs):
    # Refill the real limiter deterministically; never disable the security boundary.
    remote.clock.value += 13
    headers = {**remote.headers, **kwargs.pop("headers", {})}
    return remote.client.request(method, url, headers=headers, **kwargs)


def _init(remote, data=None, key="synthetic-resumable-key-0001", **fields):
    data = _wav_bytes() if data is None else data
    body = {"filename": "synthetic.wav", "total_bytes": len(data), **fields}
    return _request(
        remote,
        "POST",
        URL,
        json=body,
        headers={"Idempotency-Key": key, "X-Expected-Sha256": _hash(data)},
    )


def _patch(remote, upload_id, data, offset=0, **headers):
    return _request(
        remote,
        "PATCH",
        f"{URL}/{upload_id}",
        content=data,
        headers={
            "Content-Type": "application/octet-stream",
            "Upload-Offset": str(offset),
            "X-Chunk-Sha256": _hash(data),
            **headers,
        },
    )


def _send(remote, upload_id, data):
    for offset in range(0, len(data), 512):
        response = _patch(remote, upload_id, data[offset : offset + 512], offset)
        assert response.status_code == 204, response.text
        assert int(response.headers["Current-Offset"]) == min(offset + 512, len(data))


def _finalize(remote, upload_id, data):
    return _request(
        remote,
        "POST",
        f"{URL}/{upload_id}/finalize",
        json={},
        headers={"X-Expected-Sha256": _hash(data)},
    )


def _drain(remote):
    async def wait():
        await asyncio.gather(*list(remote.app.state.resumable_tasks.values()))

    remote.client.portal.call(wait)


def _staging(remote, upload_id):
    return remote.runtime.config.paths.root / "remote" / "incoming" / upload_id


def test_complete_flow_offsets_integrity_and_replay(remote):
    data = _wav_bytes()
    initialized = _init(remote, data, title="Synthetic title", lesson_date="2026-10-26")
    assert initialized.status_code == 201, initialized.text
    session = initialized.json()
    upload_id = session["upload_id"]
    assert initialized.headers["Location"] == f"{URL}/{upload_id}"
    assert session["chunk_bytes"] == 512
    assert session["expires_at"] == int(remote.clock()) + 86400
    assert _init(remote, data, title="Synthetic title", lesson_date="2026-10-26").status_code == 200

    first = _patch(remote, upload_id, data[:512])
    assert first.status_code == 204
    for offset in (0, 513):
        conflict = _patch(remote, upload_id, data[512:1024], offset)
        assert conflict.status_code == 409
        assert conflict.headers["Current-Offset"] == "512"
    status = _request(remote, "GET", f"{URL}/{upload_id}")
    assert status.json()["current_offset"] == 512
    assert status.headers["Upload-Expires"] == initialized.headers["Upload-Expires"]
    for offset in range(512, len(data), 512):
        assert _patch(remote, upload_id, data[offset : offset + 512], offset).status_code == 204

    accepted = _finalize(remote, upload_id, data)
    assert accepted.status_code == 202, accepted.text
    _drain(remote)
    completed = _request(remote, "GET", f"{URL}/{upload_id}")
    assert completed.status_code == 200
    assert completed.json()["state"] == "completed"
    recording = remote.runtime.repository.get_recording(completed.json()["recording_id"])
    assert recording.sha256 == _hash(data)
    assert recording.subject_id == remote.runtime.subject_id
    assert recording.title == "Synthetic title"
    assert recording.lesson_date.isoformat() == "2026-10-26"
    assert (
        remote.runtime.config.paths.resolve_relative(recording.relative_path).read_bytes() == data
    )
    assert not _staging(remote, upload_id).exists()
    assert _finalize(remote, upload_id, data).status_code == 200
    assert len(remote.runtime.repository.list_recordings()) == 1
    assert not remote.runtime.repository.list_jobs()
    assert _request(remote, "DELETE", f"{URL}/{upload_id}").status_code == 409


def test_corrupt_chunk_keeps_manifest_and_offset(remote):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]
    response = _patch(remote, upload_id, data[:512], **{"X-Chunk-Sha256": "0" * 64})
    assert response.status_code == 422
    assert not list((_staging(remote, upload_id) / "chunks").iterdir())
    assert not remote.app.state.store.resumable_chunks(upload_id)
    assert _request(remote, "GET", f"{URL}/{upload_id}").json()["current_offset"] == 0
    assert _patch(remote, upload_id, data[:512]).status_code == 204


def test_delete_purges_staging_and_prevents_resume(remote):
    upload_id = _init(remote).json()["upload_id"]
    assert _patch(remote, upload_id, _wav_bytes()[:512]).status_code == 204
    assert _request(remote, "DELETE", f"{URL}/{upload_id}").status_code == 204
    assert not _staging(remote, upload_id).exists()
    assert _request(remote, "GET", f"{URL}/{upload_id}").status_code == 410
    assert _patch(remote, upload_id, _wav_bytes()[:512]).status_code == 410
    assert not remote.runtime.repository.list_recordings()


@pytest.mark.parametrize(
    "fields",
    [
        {"total_bytes": True},
        {"total_bytes": "42"},
        {"total_bytes": 1.5},
        {"total_bytes": 0},
        {"enqueue": "false"},
        {"filename": "../a.wav"},
        {"filename": "a\\b.wav"},
        {"filename": "a\x00.wav"},
        {"filename": ""},
        {"extra": "forbidden"},
    ],
)
def test_strict_init_model(remote, fields):
    assert _init(remote, **fields).status_code == 422
    assert not remote.app.state.store.resumable_rows()


@pytest.mark.parametrize(
    "fields,status",
    [
        ({"filename": "media.ogg"}, 400),
        ({"total_bytes": 65537}, 413),
        ({"subject_id": "not-authorized"}, 403),
    ],
)
def test_init_constraints(remote, fields, status):
    assert _init(remote, **fields).status_code == status
    assert not remote.app.state.store.resumable_rows()


@pytest.mark.parametrize(
    "field,value", [("title", "different"), ("enqueue", True), ("lesson_date", "2020-01-01")]
)
def test_idempotency_fingerprint_includes_metadata(remote, field, value):
    first = _init(remote)
    assert first.status_code == 201
    changed = _init(remote, **{field: value})
    assert changed.status_code == 409
    assert changed.json()["detail"] == "idempotency_conflict"
    assert len(remote.app.state.store.resumable_rows()) == 1


@pytest.mark.parametrize(
    "header,value", [("X-Expected-Sha256", "oops"), ("Idempotency-Key", "short")]
)
def test_init_rejects_invalid_headers(remote, header, value):
    response = _request(
        remote,
        "POST",
        URL,
        json={"filename": "a.wav", "total_bytes": 12},
        headers={
            "Idempotency-Key": "synthetic-resumable-key-0001",
            "X-Expected-Sha256": "a" * 64,
            header: value,
        },
    )
    assert response.status_code == 400


def test_identity_isolation_on_every_endpoint(remote):
    upload_id = _init(remote).json()["upload_id"]
    remote.headers = _session(remote.client, OTHER_IDENTITY)
    assert _request(remote, "GET", f"{URL}/{upload_id}").status_code == 404
    assert _patch(remote, upload_id, _wav_bytes()[:512]).status_code == 404
    assert _finalize(remote, upload_id, _wav_bytes()).status_code == 404
    assert _request(remote, "DELETE", f"{URL}/{upload_id}").status_code == 404
    other = _init(remote)
    assert other.status_code == 201
    assert other.json()["upload_id"] != upload_id


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Tailscale-Funnel-Request": "true"}, 403),
        ({"origin": "https://elsewhere.invalid"}, 403),
        ({"x-csrf-token": "invalid"}, 403),
        ({"host": "elsewhere.invalid"}, 400),
    ],
)
def test_resumable_preserves_gateway_boundary(remote, headers, status):
    response = _request(remote, "POST", URL, json={}, headers=headers)
    assert response.status_code == status


def test_chunk_contract_and_incomplete_finalize(remote):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]
    short = _patch(remote, upload_id, data[:511])
    assert short.status_code == 400
    assert short.json()["detail"] == "invalid_chunk_length"
    assert _patch(remote, upload_id, data[:512], **{"Upload-Offset": "-1"}).status_code == 400
    assert _patch(remote, upload_id, data[:512], **{"Content-Type": "audio/wav"}).status_code == 415
    assert _patch(remote, upload_id, data[:512], **{"X-Chunk-Sha256": "invalid"}).status_code == 400
    assert _finalize(remote, upload_id, data).status_code == 409
    assert not remote.runtime.repository.list_recordings()


def test_final_hash_mismatch_never_imports(remote):
    data = _wav_bytes()
    upload_id = _init(remote, b"x" * len(data)).json()["upload_id"]
    _send(remote, upload_id, data)
    assert _finalize(remote, upload_id, b"x" * len(data)).status_code == 202
    _drain(remote)
    response = _request(remote, "GET", f"{URL}/{upload_id}")
    assert response.status_code == 410
    assert response.json()["detail"] == "final_hash_mismatch"
    assert not remote.runtime.repository.list_recordings()
    assert not _staging(remote, upload_id).exists()


def test_enqueue_uses_core_queue_without_worker_and_replays_once(remote):
    _install_model(remote.runtime)
    data = _wav_bytes()
    upload_id = _init(remote, data, enqueue=True).json()["upload_id"]
    _send(remote, upload_id, data)
    assert _finalize(remote, upload_id, data).status_code == 202
    _drain(remote)
    response = _request(remote, "GET", f"{URL}/{upload_id}")
    assert response.json()["queue_state"] == "pending"
    assert response.json()["job_id"]
    assert _finalize(remote, upload_id, data).status_code == 200
    assert len(remote.runtime.repository.list_jobs()) == 1
    assert not hasattr(remote.app.state, "worker")


def test_gateway_schema_is_separate_and_migration_idempotent(remote):
    core = remote.runtime.config.paths.database
    with sqlite3.connect(core) as connection:
        before = connection.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    _init(remote)
    remote.app.state.store.initialize()
    with remote.app.state.store._connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM remote_gateway_schema_migrations").fetchone()[
                0
            ]
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO remote_resumable_chunks VALUES (?,?,?,?,?,?)",
                ("f" * 32, 0, 0, 1, "a" * 64, 1),
            )
    with sqlite3.connect(core) as connection:
        assert (
            before
            == connection.execute(
                "SELECT type,name,sql FROM sqlite_master ORDER BY name"
            ).fetchall()
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_disk_reservation_accounts_for_all_active_sessions(runtime, clock, monkeypatch):
    free = SimpleNamespace(free=5000)
    app = create_remote_gateway_app(
        runtime.config, gateway_config=_settings(runtime), clock=clock, disk_usage=lambda _: free
    )
    with TestClient(app) as client:
        remote = SimpleNamespace(client=client, headers=_session(client), clock=clock)
        assert _init(remote, b"x" * 1000).status_code == 201
        assert _init(remote, b"y" * 1000, key="synthetic-resumable-key-0002").status_code == 507
        assert _init(remote, b"x" * 1000).status_code == 200


def test_crash_after_core_import_blocks_reimport_on_restart(runtime, clock, monkeypatch):
    monkeypatch.setattr(gateway_module, "RESUMABLE_CHUNK_BYTES", 512)
    original = MediaLibrary.import_stream
    calls = []

    def import_then_crash(library, *args, **kwargs):
        recording = original(library, *args, **kwargs)
        calls.append(recording.id)
        raise RuntimeError("simulated crash after core commit")

    monkeypatch.setattr(MediaLibrary, "import_stream", import_then_crash)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    data = _wav_bytes()
    with TestClient(app) as client:
        remote = SimpleNamespace(client=client, app=app, headers=_session(client), clock=clock)
        upload_id = _init(remote, data).json()["upload_id"]
        _send(remote, upload_id, data)
        _finalize(remote, upload_id, data)
        _drain(remote)
        assert _request(remote, "GET", f"{URL}/{upload_id}").status_code == 409
        started = app.state.store.resumable(upload_id)["import_started_at"]
    monkeypatch.setattr(MediaLibrary, "import_stream", original)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        remote = SimpleNamespace(client=client, app=app, headers=_session(client), clock=clock)
        response = _request(remote, "GET", f"{URL}/{upload_id}")
        assert response.status_code == 409
        assert response.json()["detail"] == "import_outcome_unknown"
        assert _finalize(remote, upload_id, data).status_code == 409
        assert app.state.store.resumable(upload_id)["import_started_at"] == started
    assert len(calls) == len(runtime.repository.list_recordings()) == 1


@pytest.mark.parametrize(
    "checkpoint",
    [
        "fsync",
        "after_fsync",
        "rename",
        "after_rename",
        "before_commit",
        "after_commit",
    ],
)
def test_chunk_crash_checkpoints_reconcile_manifest(runtime, clock, monkeypatch, checkpoint):
    monkeypatch.setattr(gateway_module, "RESUMABLE_CHUNK_BYTES", 512)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    data = _wav_bytes()
    with TestClient(app) as client:
        remote = SimpleNamespace(
            client=client, app=app, headers=_session(client), clock=clock, runtime=runtime
        )
        upload_id = _init(remote, data).json()["upload_id"]
        with monkeypatch.context() as patch:

            def crash(*args, **kwargs):
                raise OSError("synthetic persistence interruption")

            if checkpoint in {"fsync", "after_fsync", "rename", "after_rename"}:
                name = "fsync" if "fsync" in checkpoint else "replace"
                original = getattr(gateway_module.os, name)

                def io_fault(*args, **kwargs):
                    if checkpoint.startswith("after_"):
                        original(*args, **kwargs)
                    crash()

                patch.setattr(gateway_module.os, name, io_fault)
            else:
                commit = app.state.store.resumable_commit_chunk

                def commit_fault(*args, **kwargs):
                    if checkpoint == "after_commit":
                        commit(*args, **kwargs)
                    crash()

                patch.setattr(app.state.store, "resumable_commit_chunk", commit_fault)
            assert _patch(remote, upload_id, data[:512]).status_code == 500
        expected = 512 if checkpoint == "after_commit" else 0
        assert app.state.store.resumable(upload_id)["current_offset"] == expected
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        remote = SimpleNamespace(
            client=client, app=app, headers=_session(client), clock=clock, runtime=runtime
        )
        status = _request(remote, "GET", f"{URL}/{upload_id}")
        assert status.json()["current_offset"] == expected
        files = list((_staging(remote, upload_id) / "chunks").iterdir())
        assert len(files) == (1 if expected else 0)
        assert (
            _patch(remote, upload_id, data[expected : expected + 512], expected).status_code == 204
        )


def test_startup_expires_sessions_and_removes_orphans(runtime, clock):
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        remote = SimpleNamespace(
            client=client, app=app, headers=_session(client), clock=clock, runtime=runtime
        )
        upload_id = _init(remote).json()["upload_id"]
        orphan = _staging(remote, "f" * 32)
        orphan.mkdir()
        (orphan / "synthetic.part").write_bytes(b"partial")
    clock.value += 86401
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        remote.client = client
        remote.headers = _session(client)
        assert _request(remote, "GET", f"{URL}/{upload_id}").status_code == 410
        assert app.state.store.resumable(upload_id)["state"] == "expired"
        assert not _staging(remote, upload_id).exists()
        assert not orphan.exists()
        assert _request(remote, "DELETE", f"{URL}/{upload_id}").status_code == 410


def test_concurrent_patch_returns_busy_without_corruption(remote, monkeypatch):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]
    entered = threading.Event()
    release = threading.Event()
    receive = gateway_module._receive_resumable_chunk

    async def delayed(*args, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 10)
        return await receive(*args, **kwargs)

    monkeypatch.setattr(gateway_module, "_receive_resumable_chunk", delayed)
    responses = []
    first = threading.Thread(target=lambda: responses.append(_patch(remote, upload_id, data[:512])))
    first.start()
    try:
        assert entered.wait(10)
        busy = _patch(remote, upload_id, data[:512])
        assert busy.status_code == 409
        assert busy.json()["detail"] == "session_busy"
    finally:
        release.set()
        first.join(10)
    assert not first.is_alive()
    assert responses[0].status_code == 204
    assert remote.app.state.store.resumable(upload_id)["current_offset"] == 512
    assert len(remote.app.state.store.resumable_chunks(upload_id)) == 1


def test_queue_failure_can_resume_without_importing_again(remote):
    data = _wav_bytes()
    upload_id = _init(remote, data, enqueue=True).json()["upload_id"]
    _send(remote, upload_id, data)
    _finalize(remote, upload_id, data)
    _drain(remote)
    status = _request(remote, "GET", f"{URL}/{upload_id}")
    assert status.json()["state"] == "importing"
    assert status.json()["error_code"] == "queue_unavailable"
    assert len(remote.runtime.repository.list_recordings()) == 1
    _install_model(remote.runtime)
    response = _finalize(remote, upload_id, data)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "completed"
    assert response.json()["error_code"] is None
    assert response.json()["job_id"]
    assert len(remote.runtime.repository.list_jobs()) == 1
    assert len(remote.runtime.repository.list_recordings()) == 1


@pytest.mark.parametrize("corrupt", [False, True])
def test_startup_reconciles_assembly_and_committed_chunks(runtime, clock, monkeypatch, corrupt):
    monkeypatch.setattr(gateway_module, "RESUMABLE_CHUNK_BYTES", 512)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    data = _wav_bytes()
    with TestClient(app) as client:
        remote = SimpleNamespace(
            client=client, app=app, headers=_session(client), clock=clock, runtime=runtime
        )
        upload_id = _init(remote, data).json()["upload_id"]
        _send(remote, upload_id, data)
        assert app.state.store.resumable_transition(upload_id, "uploading", "assembling")
        (_staging(remote, upload_id) / "assembled.part").write_bytes(b"interrupted assembly")
        if corrupt:
            chunk = _staging(remote, upload_id) / "chunks" / "00000000.chunk"
            chunk.write_bytes(b"x" * 512)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        remote.client, remote.app, remote.headers = client, app, _session(client)
        response = _request(remote, "GET", f"{URL}/{upload_id}")
        if corrupt:
            assert response.status_code == 410
            assert response.json()["detail"] == "staging_corrupt"
            assert not _staging(remote, upload_id).exists()
        else:
            assert response.status_code == 200
            assert response.json()["state"] == "uploading"
            assert response.json()["current_offset"] == len(data)
            assert not (_staging(remote, upload_id) / "assembled.part").exists()
            assert _finalize(remote, upload_id, data).status_code == 202
            _drain(remote)
            assert len(runtime.repository.list_recordings()) == 1


def test_delete_during_assembly_waits_and_prevents_core_import(remote, monkeypatch):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]
    _send(remote, upload_id, data)
    entered, release = threading.Event(), threading.Event()
    original_fsync = gateway_module.os.fsync

    def slow_fsync(handle):
        entered.set()
        assert release.wait(10)
        return original_fsync(handle)

    monkeypatch.setattr(gateway_module.os, "fsync", slow_fsync)
    assert _finalize(remote, upload_id, data).status_code == 202
    assert entered.wait(10)
    responses = []
    thread = threading.Thread(
        target=lambda: responses.append(_request(remote, "DELETE", f"{URL}/{upload_id}"))
    )
    thread.start()
    try:
        # Observe the durable cancellation before allowing assembly to finish.
        async def wait_for_abort():
            for _ in range(1000):
                if remote.app.state.store.resumable(upload_id)["state"] == "aborted":
                    return
                await asyncio.sleep(0.001)
            raise AssertionError("cancellation did not become durable")

        remote.client.portal.call(wait_for_abort)
    finally:
        release.set()
        thread.join(10)
    _drain(remote)
    assert not thread.is_alive()
    assert responses[0].status_code == 204
    assert not remote.runtime.repository.list_recordings()
    assert not _staging(remote, upload_id).exists()


def test_foreign_identity_cannot_detect_busy_session(remote, monkeypatch):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]
    entered, release = threading.Event(), threading.Event()
    original = gateway_module._receive_resumable_chunk

    async def slow_receive(*args, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 10)
        return await original(*args, **kwargs)

    monkeypatch.setattr(gateway_module, "_receive_resumable_chunk", slow_receive)
    results = []
    thread = threading.Thread(target=lambda: results.append(_patch(remote, upload_id, data[:512])))
    thread.start()
    try:
        assert entered.wait(10)
        remote.headers = _session(remote.client, OTHER_IDENTITY)
        assert _patch(remote, upload_id, data[:512]).status_code == 404
    finally:
        release.set()
        thread.join(10)
    assert results[0].status_code == 204


def test_reparse_point_is_refused_before_write(remote, monkeypatch):
    upload_id = _init(remote).json()["upload_id"]
    chunks = _staging(remote, upload_id) / "chunks"
    original = gateway_module._is_link
    monkeypatch.setattr(gateway_module, "_is_link", lambda path: path == chunks or original(path))
    assert _patch(remote, upload_id, _wav_bytes()[:512]).status_code == 500
    assert not list(chunks.iterdir())
    assert remote.app.state.store.resumable(upload_id)["current_offset"] == 0


def test_resumable_mutations_obey_existing_rate_limit(remote):
    # Use the same timestamp to consume the actual five-token burst.
    for index in range(5):
        response = remote.client.post(
            URL,
            json={"filename": "synthetic.wav", "total_bytes": 1},
            headers={
                **remote.headers,
                "Idempotency-Key": f"synthetic-burst-key-{index:04d}",
                "X-Expected-Sha256": "a" * 64,
            },
        )
        assert response.status_code == 201
    response = remote.client.post(URL, json={}, headers=remote.headers)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert len(remote.app.state.store.resumable_rows()) == 5


@pytest.mark.parametrize(
    "mode,status", [("disconnect", 400), ("short", 400), ("long", 413), ("timeout", 408)]
)
def test_stream_interruption_does_not_commit_partial_chunk(remote, mode, status):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]
    headers = {
        **remote.headers,
        "Content-Type": "application/octet-stream",
        "Content-Length": "512",
        "Upload-Offset": "0",
        "X-Chunk-Sha256": _hash(data[:512]),
    }
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PATCH",
        "scheme": "http",
        "path": f"{URL}/{upload_id}",
        "raw_path": f"{URL}/{upload_id}".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8766),
    }
    messages = [
        {
            "type": "http.request",
            "body": data[:513] if mode == "long" else data[:200],
            "more_body": True,
        }
    ]
    messages.append(
        {"type": "http.disconnect"}
        if mode == "disconnect"
        else {"type": "http.request", "body": b"", "more_body": False}
    )
    sent = []

    async def receive():
        if mode == "timeout":
            await asyncio.sleep(0.05)
        if messages:
            return messages.pop(0)
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    # Override only this helper's deadline, keeping the app configuration intact.
    original = gateway_module._receive_resumable_chunk

    async def receive_with_short_deadline(request, destination, size, expected_hash, timeout):
        return await original(request, destination, size, expected_hash, 0.01)

    from unittest.mock import patch

    with patch.object(gateway_module, "_receive_resumable_chunk", receive_with_short_deadline):
        remote.client.portal.call(remote.app, scope, receive, send)
    assert (
        next(message["status"] for message in sent if message["type"] == "http.response.start")
        == status
    )
    assert remote.app.state.store.resumable(upload_id)["current_offset"] == 0
    assert not list((_staging(remote, upload_id) / "chunks").iterdir())


def test_restart_can_complete_known_import_without_reimport(runtime, clock, monkeypatch):
    monkeypatch.setattr(gateway_module, "RESUMABLE_CHUNK_BYTES", 512)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    data = _wav_bytes()
    with TestClient(app) as client:
        remote = SimpleNamespace(
            client=client, app=app, headers=_session(client), clock=clock, runtime=runtime
        )
        upload_id = _init(remote, data, enqueue=True).json()["upload_id"]
        _send(remote, upload_id, data)
        _finalize(remote, upload_id, data)
        _drain(remote)
        row = app.state.store.resumable(upload_id)
        assert row["state"] == "importing"
        assert row["recording_id"] is not None
    _install_model(runtime)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        remote.client, remote.app, remote.headers = client, app, _session(client)
        assert _request(remote, "GET", f"{URL}/{upload_id}").status_code == 200
        assert _request(remote, "DELETE", f"{URL}/{upload_id}").status_code == 409
        response = _finalize(remote, upload_id, data)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "completed"
        assert response.json()["recording_id"] == row["recording_id"]
        assert len(runtime.repository.list_recordings()) == len(runtime.repository.list_jobs()) == 1


def test_expiration_is_enforced_without_restart_and_tombstone_is_retained(remote):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]
    remote.clock.value += 86401
    remote.headers = _session(remote.client)
    response = _patch(remote, upload_id, data[:512])
    assert response.status_code == 410
    assert response.headers["Current-Offset"] == "0"
    assert remote.app.state.store.resumable(upload_id)["state"] == "expired"
    assert not _staging(remote, upload_id).exists()


def test_finalization_global_serialization_capacity_and_retry(remote, monkeypatch):
    monkeypatch.setattr(gateway_module, "RESUMABLE_FINALIZATION_PENDING", 1)
    payloads = [_wav_bytes(value=i) for i in range(3)]
    ids = []
    for i, data in enumerate(payloads):
        upload_id = _init(remote, data, key=f"synthetic-capacity-key-{i:04d}").json()["upload_id"]
        _send(remote, upload_id, data)
        ids.append(upload_id)
    entered, release = threading.Event(), threading.Event()
    original = MediaLibrary.import_stream
    active = 0
    peak = 0
    calls = []
    guard = threading.Lock()

    def slow_import(library, *args, **kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
            calls.append(kwargs["original_name"])
        entered.set()
        assert release.wait(10)
        try:
            return original(library, *args, **kwargs)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(MediaLibrary, "import_stream", slow_import)
    try:
        response = _finalize(remote, ids[0], payloads[0])
        assert response.status_code == 202
        assert response.headers["Location"] == f"{URL}/{ids[0]}"
        assert response.headers["Retry-After"] == "2"
        assert entered.wait(10)
        assert _finalize(remote, ids[1], payloads[1]).status_code == 202
        # The second session must not assemble while the first is importing.
        assert not (_staging(remote, ids[1]) / "assembled.part").exists()
        assert remote.app.state.store.resumable(ids[1])["state"] == "assembling"
        replay = _finalize(remote, ids[1], payloads[1])
        assert replay.status_code == 202
        assert replay.headers["Retry-After"] == "2"
        saturated = _finalize(remote, ids[2], payloads[2])
        assert saturated.status_code == 503
        assert saturated.json()["detail"] == "finalization_busy"
        assert remote.app.state.store.resumable(ids[2])["state"] == "uploading"
        assert len(calls) == 1
    finally:
        release.set()
        _drain(remote)
    assert _finalize(remote, ids[2], payloads[2]).status_code == 202
    _drain(remote)
    assert peak == 1
    assert len(remote.runtime.repository.list_recordings()) == 3


@pytest.mark.parametrize("point", ["receive", "fsync", "replace"])
def test_chunk_enospc_is_507_and_resumable(remote, monkeypatch, point):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic disk full")

    async def fail_receive(*args, **kwargs):
        fail()

    with monkeypatch.context() as patch:
        if point == "receive":
            patch.setattr(gateway_module, "_receive_resumable_chunk", fail_receive)
        else:
            patch.setattr(gateway_module.os, point, fail)
        response = _patch(remote, upload_id, data[:512])
        assert response.status_code == 507
        assert response.json()["detail"] == "insufficient_storage"
    assert remote.app.state.store.resumable(upload_id)["current_offset"] == 0
    assert not remote.app.state.store.resumable_chunks(upload_id)
    assert not list((_staging(remote, upload_id) / "chunks").glob("*.part"))
    assert _patch(remote, upload_id, data[:512]).status_code == 204


def test_published_conflict_details(remote):
    data = _wav_bytes()
    upload_id = _init(remote, data).json()["upload_id"]
    assert _patch(remote, upload_id, data[:512], offset=1).json()["detail"] == "offset_conflict"
    assert _finalize(remote, upload_id, data).json()["detail"] == "upload_incomplete"
    assert _finalize(remote, upload_id, b"wrong hash").json()["detail"] == "expected_hash_conflict"
    assert _patch(remote, upload_id, data[:513]).status_code == 413
    _send(remote, upload_id, data)
    assert _finalize(remote, upload_id, data).status_code == 202
    _drain(remote)
    aborted = _request(remote, "DELETE", f"{URL}/{upload_id}")
    assert aborted.status_code == 409
    assert aborted.json()["detail"] == "cannot_abort_import"


@pytest.mark.parametrize("invalid", ["origin", "cookie", "forged", "foreign", "expired"])
def test_resumable_reads_require_authenticated_cookie_and_origin(remote, invalid):
    upload_id = _init(remote).json()["upload_id"]
    headers = {k: v for k, v in remote.headers.items() if k != "x-csrf-token"}
    remote.client.cookies.clear()
    if invalid == "origin":
        headers.pop("origin")
    elif invalid == "cookie":
        headers.pop("cookie")
    elif invalid == "forged":
        headers["cookie"] = f"{gateway_module.SESSION_COOKIE}=forged"
    elif invalid == "foreign":
        headers["cookie"] = _session(remote.client, OTHER_IDENTITY)["cookie"]
    else:
        remote.clock.value += 3601
    assert remote.client.get(f"{URL}/{upload_id}", headers=headers).status_code == 403
    remote.headers = _session(remote.client)
    headers = {k: v for k, v in remote.headers.items() if k != "x-csrf-token"}
    assert remote.client.get(f"{URL}/{upload_id}", headers=headers).status_code == 200


def test_active_session_limits_release_and_preserve_rejected_key(remote, monkeypatch):
    monkeypatch.setattr(gateway_module, "RESUMABLE_ACTIVE_PER_IDENTITY", 1)
    first = _init(remote).json()["upload_id"]
    rejected_key = "synthetic-rejected-key-0001"
    rejected = _init(remote, key=rejected_key)
    assert rejected.status_code == 429
    assert rejected.json()["detail"] == "active_session_limit_reached"
    assert _request(remote, "DELETE", f"{URL}/{first}").status_code == 204
    second = _init(remote, key=rejected_key)
    assert second.status_code == 201
    remote.clock.value += 86401
    remote.headers = _session(remote.client)
    # No GC/GET required to release an expired session's capacity.
    assert _init(remote, key="synthetic-after-expiry-0001").status_code == 201
    assert remote.app.state.store.resumable(second.json()["upload_id"])["state"] == "expired"


def test_active_session_global_limit_and_completion_release(remote, monkeypatch):
    monkeypatch.setattr(gateway_module, "RESUMABLE_ACTIVE_GLOBAL", 1)
    data = _wav_bytes()
    first = _init(remote, data).json()["upload_id"]
    owner = remote.headers
    remote.headers = _session(remote.client, OTHER_IDENTITY)
    rejected = _init(remote, key="synthetic-other-session-0001")
    assert rejected.status_code == 429
    remote.headers = owner
    _send(remote, first, data)
    _finalize(remote, first, data)
    _drain(remote)
    remote.headers = _session(remote.client, OTHER_IDENTITY)
    assert _init(remote, key="synthetic-other-session-0001").status_code == 201


def test_legacy_preflight_respects_resumable_reservations(runtime, clock):
    data = _wav_bytes()
    app = create_remote_gateway_app(
        runtime.config,
        gateway_config=_settings(runtime),
        clock=clock,
        disk_usage=lambda _: SimpleNamespace(free=3 * len(data)),
    )
    with TestClient(app) as client:
        remote = SimpleNamespace(client=client, app=app, headers=_session(client), clock=clock)
        upload_id = _init(remote, data).json()["upload_id"]
        clock.value += 13
        assert _upload(client, remote.headers, body=data).status_code == 507
        assert _request(remote, "DELETE", f"{URL}/{upload_id}").status_code == 204
        clock.value += 13
        assert _upload(client, remote.headers, body=data).status_code == 201


@pytest.mark.parametrize("foreign", [False, True])
def test_duplicate_media_rejection_is_terminal_and_releases_reservation(remote, foreign):
    data = _wav_bytes()
    first = _init(remote, data).json()["upload_id"]
    _send(remote, first, data)
    _finalize(remote, first, data)
    _drain(remote)
    if foreign:
        remote.headers = _session(remote.client, OTHER_IDENTITY)
    second = _init(remote, data, key="synthetic-duplicate-key-0002").json()["upload_id"]
    _send(remote, second, data)
    _finalize(remote, second, data)
    _drain(remote)
    row = remote.app.state.store.resumable(second)
    assert row["state"] == "aborted"
    assert row["error_code"] == "media_rejected"
    assert row["recording_id"] is None
    assert remote.app.state.store.resumable_reserved_bytes() == 0
    assert not _staging(remote, second).exists()
    assert len(remote.runtime.repository.list_recordings()) == 1
    assert _request(remote, "GET", f"{URL}/{second}").status_code == 410


def test_invalid_media_rejection_releases_reservation(remote):
    data = b"undecodable synthetic media"
    upload_id = _init(remote, data).json()["upload_id"]
    _send(remote, upload_id, data)
    _finalize(remote, upload_id, data)
    _drain(remote)
    assert remote.app.state.store.resumable(upload_id)["state"] == "aborted"
    assert remote.app.state.store.resumable_reserved_bytes() == 0
    assert not remote.runtime.repository.list_recordings()


def test_init_replay_reconciles_expiration(remote):
    upload_id = _init(remote).json()["upload_id"]
    remote.clock.value += 86401
    remote.headers = _session(remote.client)
    replay = _init(remote)
    assert replay.status_code == 410
    assert replay.json()["detail"] == "session_expired"
    assert remote.app.state.store.resumable(upload_id)["state"] == "expired"
    assert not _staging(remote, upload_id).exists()


def test_gc_isolates_sessions_and_orphan_directories(remote, monkeypatch):
    first = _init(remote).json()["upload_id"]
    second = _init(remote, key="synthetic-gc-second-0001").json()["upload_id"]
    incoming = _staging(remote, first).parent
    orphan_bad, orphan_good = "a" * 32, "b" * 32
    (incoming / orphan_bad).mkdir()
    (incoming / orphan_good).mkdir()
    original = gateway_module._purge_staging

    def transient(incoming, upload_id):
        if upload_id in {first, orphan_bad}:
            raise PermissionError("synthetic transient lock")
        return original(incoming, upload_id)

    remote.clock.value += 86401
    with monkeypatch.context() as patch:
        patch.setattr(gateway_module, "_purge_staging", transient)
        remote.app.state.collect_resumable()
    assert _staging(remote, first).exists()
    assert not _staging(remote, second).exists()
    assert (incoming / orphan_bad).exists()
    assert not (incoming / orphan_good).exists()
    remote.app.state.collect_resumable()
    assert not _staging(remote, first).exists()
    assert not (incoming / orphan_bad).exists()


def test_periodic_gc_survives_transient_error_and_recovers_database(runtime, clock, monkeypatch):
    monkeypatch.setattr(gateway_module, "RESUMABLE_GC_INTERVAL", 0.01)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        original = app.state.store.resumable_rows
        calls = 0
        recovered = threading.Event()
        allow_recovery = threading.Event()

        def intermittent():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PermissionError("synthetic I/O")
            if not allow_recovery.is_set():
                raise sqlite3.DatabaseError("synthetic database failure")
            recovered.set()
            return original()

        monkeypatch.setattr(app.state.store, "resumable_rows", intermittent)
        headers = _session(client)
        remote = SimpleNamespace(client=client, headers=headers, clock=clock)

        async def wait_database_error():
            for _ in range(1000):
                if app.state.resumable_gc_error:
                    return
                await asyncio.sleep(0.001)
            raise AssertionError("GC did not signal database failure")

        client.portal.call(wait_database_error)
        response = _init(remote)
        assert response.status_code == 503
        assert response.json()["detail"] == "resumable_storage_unavailable"
        allow_recovery.set()
        assert recovered.wait(10)
        assert not app.state.resumable_gc_task.done()

        # A successful cycle clears the fail-closed storage signal.
        async def wait_recovery():
            for _ in range(1000):
                if not app.state.resumable_gc_error:
                    return
                await asyncio.sleep(0.001)
            raise AssertionError("GC did not recover")

        client.portal.call(wait_recovery)
        assert _init(remote).status_code == 201


def test_active_session_limit_is_atomic_between_requests(remote, monkeypatch):
    monkeypatch.setattr(gateway_module, "RESUMABLE_ACTIVE_PER_IDENTITY", 1)
    barrier = threading.Barrier(2)
    responses = []

    def initialize(index):
        barrier.wait(timeout=10)
        responses.append(_init(remote, key=f"synthetic-racing-init-{index:04d}"))

    threads = [threading.Thread(target=initialize, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    assert sorted(response.status_code for response in responses) == [201, 429]
    assert len(remote.app.state.store.resumable_rows()) == 1


def test_restart_reconciles_multiple_pending_finalizations(runtime, clock, monkeypatch):
    monkeypatch.setattr(gateway_module, "RESUMABLE_CHUNK_BYTES", 512)
    data = [_wav_bytes(value=i) for i in range(2)]
    ids = []
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        remote = SimpleNamespace(client=client, app=app, headers=_session(client), clock=clock)
        for i, payload in enumerate(data):
            upload_id = _init(remote, payload, key=f"synthetic-restart-pending-{i:04d}").json()[
                "upload_id"
            ]
            _send(remote, upload_id, payload)
            # Persist the accepted-but-not-importing checkpoint of a lost process.
            assert app.state.store.resumable_transition(upload_id, "uploading", "assembling")
            ids.append(upload_id)
    app = create_remote_gateway_app(runtime.config, gateway_config=_settings(runtime), clock=clock)
    with TestClient(app) as client:
        remote.client, remote.app, remote.headers = client, app, _session(client)
        for upload_id, payload in zip(ids, data, strict=True):
            status = _request(remote, "GET", f"{URL}/{upload_id}")
            assert status.json()["state"] == "uploading"
            assert status.json()["current_offset"] == len(payload)
            assert _finalize(remote, upload_id, payload).status_code == 202
        _drain(remote)
        assert len(runtime.repository.list_recordings()) == 2
        for upload_id, payload in zip(ids, data, strict=True):
            assert _finalize(remote, upload_id, payload).status_code == 200
