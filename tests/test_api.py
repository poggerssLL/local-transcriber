from __future__ import annotations

import asyncio
import io
import json
import re
import socket
import wave
from dataclasses import dataclass
from pathlib import Path
from threading import Timer
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from local_transcriber.api import create_app, stream_job_events
from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.media import MediaImportSettings
from local_transcriber.models import (
    JobPhase,
    JobStatus,
    Segment,
    Transcript,
    TranscriptionJob,
    Word,
)
from local_transcriber.transcription import (
    EngineOutput,
    ProfileResolver,
    ProgressEvent,
    RuntimeCapabilities,
)


def _wav_bytes(*, frames: int = 800) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * frames)
    return output.getvalue()


def _write_fake_model(path: Path) -> None:
    path.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (path / name).write_bytes(b"test")


@dataclass
class FixedProbe:
    def inspect(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(frozenset({"int8"}), 0, frozenset(), "no CUDA")


class FakeEngine:
    name = "fake"

    def transcribe(self, request, progress=None):
        segment = Segment(
            ordinal=0,
            start_seconds=0,
            end_seconds=0.1,
            text="conteúdo de teste",
            words=(Word(text="conteúdo", start_seconds=0, end_seconds=0.1),),
        )
        if progress is not None:
            progress(ProgressEvent("transcribing", "segment decoded", 1, 0.1, 0.1, 99.999))
        return EngineOutput("conteúdo de teste", (segment,), "pt", 0.99, 0.1)


@pytest.fixture
def app(tmp_path: Path):
    config = AppConfig(RuntimePaths((tmp_path / "runtime").resolve()))
    return create_app(
        config,
        start_worker=False,
        sse_poll_interval=0.01,
        sse_heartbeat_interval=0.02,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as current:
        yield current


def _create_subject(client: TestClient, name: str = "Redes") -> str:
    response = client.post("/api/subjects", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _upload(client: TestClient, subject_id: str, *, name: str = "aula.wav") -> dict:
    response = client.post(
        "/api/recordings",
        data={"title": "Aula local", "subject_id": subject_id, "lesson_date": "2026-09-10"},
        files={"file": (name, _wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _install_model(app) -> None:
    _write_fake_model(app.state.config.paths.models / "small")


def _seed_transcript(app, recording_id: str) -> Transcript:
    job = app.state.repository.add_job(
        TranscriptionJob(
            recording_id=recording_id,
            engine="fake",
            model_name="small",
            status=JobStatus.SUCCEEDED,
            phase=JobPhase.COMPLETED,
            progress_percent=100,
        )
    )
    return app.state.repository.add_transcript(
        Transcript(
            recording_id=recording_id,
            job_id=job.id,
            language="pt",
            text="conteúdo pesquisável",
            segments=(
                Segment(
                    ordinal=0,
                    start_seconds=0,
                    end_seconds=0.1,
                    text="conteúdo pesquisável",
                    words=(Word(text="conteúdo", start_seconds=0, end_seconds=0.1),),
                ),
            ),
        )
    )


def _terminal_job(client: TestClient) -> str:
    recording = _upload(client, _create_subject(client))
    _install_model(client.app)
    job = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()
    repository = client.app.state.repository
    repository.update_job_status(job["id"], JobStatus.RUNNING)
    repository.update_job_status(job["id"], JobStatus.FAILED, error_message="test failure")
    return job["id"]


def test_health_version_capabilities_and_openapi(client: TestClient) -> None:
    assert client.get("/api/health").json() == {
        "status": "ok",
        "version": "0.7.0",
        "schema_version": 4,
    }
    assert client.get("/api/version").json()["api_version"] == "1"
    capabilities = client.get("/api/capabilities").json()
    assert capabilities["model_download_via_api"] is False
    assert capabilities["sse_replay"] is True
    openapi = client.get("/api/openapi.json").json()
    assert openapi["info"]["version"] == "0.7.0"
    assert all(path.startswith("/api/") for path in openapi["paths"])


def test_openapi_is_offline_and_visual_docs_are_not_exposed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_network(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    openapi = client.get("/api/openapi.json")
    assert openapi.status_code == 200
    assert openapi.headers["content-type"].startswith("application/json")
    assert "cdn.jsdelivr.net" not in openapi.text
    assert client.get("/api/health").status_code == 200
    responses = [
        client.get("/api/docs"),
        client.get("/docs"),
        client.get("/redoc"),
        client.get("/api/redoc"),
    ]
    assert all(response.status_code == 404 for response in responses)
    html_responses = [
        response
        for response in [openapi, *responses]
        if response.headers.get("content-type", "").startswith("text/html")
    ]
    assert all(
        re.search(r"https?://", response.text, re.IGNORECASE) is None for response in html_responses
    )


def test_subject_recording_upload_list_detail_search_and_delete(client: TestClient) -> None:
    subject_id = _create_subject(client)
    recording = _upload(client, subject_id, name="../../aula.wav")
    assert recording["original_name"] == "aula.wav"
    assert client.get("/api/recordings").json() == [recording]
    assert client.get(f"/api/recordings/{recording['id']}").json() == recording
    _seed_transcript(client.app, recording["id"])
    assert (
        client.get("/api/search", params={"q": "conteúdo"}).json()[0]["recording_id"]
        == recording["id"]
    )
    assert client.delete(f"/api/recordings/{recording['id']}").status_code == 204
    assert client.get(f"/api/recordings/{recording['id']}").status_code == 404


def test_upload_rejects_invalid_content_type_and_invalid_media(client: TestClient) -> None:
    subject_id = _create_subject(client)
    wrong_type = client.post(
        "/api/recordings",
        data={"title": "A", "subject_id": subject_id, "lesson_date": "2026-09-10"},
        files={"file": ("aula.wav", _wav_bytes(), "text/plain")},
    )
    assert wrong_type.status_code == 415
    invalid = client.post(
        "/api/recordings",
        data={"title": "A", "subject_id": subject_id, "lesson_date": "2026-09-10"},
        files={"file": ("aula.wav", b"not media", "audio/wav")},
    )
    assert invalid.status_code == 415


def test_upload_limit_is_enforced(tmp_path: Path) -> None:
    config = AppConfig(RuntimePaths((tmp_path / "limited").resolve()))
    limited = create_app(
        config,
        start_worker=False,
        media_settings=MediaImportSettings(max_size_bytes=64, chunk_size_bytes=16),
    )
    with TestClient(limited) as client:
        subject_id = _create_subject(client)
        declared = client.post(
            "/api/recordings",
            data={"title": "A", "subject_id": subject_id, "lesson_date": "2026-09-10"},
            files={"file": ("large.wav", b"x", "audio/wav")},
            headers={"Content-Length": str(2 * 1024 * 1024)},
        )
        assert declared.status_code == 413
        response = client.post(
            "/api/recordings",
            data={"title": "A", "subject_id": subject_id, "lesson_date": "2026-09-10"},
            files={"file": ("large.wav", _wav_bytes(), "audio/wav")},
        )
    assert response.status_code == 413
    assert list(config.paths.media.rglob("*.part")) == []


def test_host_origin_and_security_headers(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Host": "example.invalid"}).status_code == 400
    blocked = client.post(
        "/api/subjects",
        json={"name": "Privado"},
        headers={"Origin": "https://example.invalid"},
    )
    assert blocked.status_code == 403
    allowed = client.post(
        "/api/subjects",
        json={"name": "Local"},
        headers={"Origin": "http://127.0.0.1:8765"},
    )
    assert allowed.status_code == 201
    assert allowed.headers["x-content-type-options"] == "nosniff"
    assert allowed.headers["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in allowed.headers


def test_request_received_on_public_binding_is_refused(app) -> None:
    async def request_public_address():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://192.168.1.20") as client:
            return await client.get("/api/health", headers={"Host": "127.0.0.1"})

    response = asyncio.run(request_public_address())
    assert response.status_code == 403
    assert response.json()["detail"] == "public server binding is not allowed"


def test_queue_cancel_retry_and_model_status(client: TestClient) -> None:
    subject_id = _create_subject(client)
    recording = _upload(client, subject_id)
    absent = client.post("/api/jobs", json={"recording_id": recording["id"]})
    assert absent.status_code == 409
    assert "models download small --confirm" in absent.json()["detail"]
    _install_model(client.app)
    created = client.post("/api/jobs", json={"recording_id": recording["id"]})
    assert created.status_code == 202
    job = created.json()
    assert job["status"] == "pending"
    cancelled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    retried = client.post(f"/api/jobs/{job['id']}/retry")
    assert retried.json()["status"] == "pending"
    assert client.get("/api/models").json()[2]["installed"] is True


def test_transcripts_segments_words_exports_and_download(client: TestClient) -> None:
    subject_id = _create_subject(client)
    recording = _upload(client, subject_id)
    transcript = _seed_transcript(client.app, recording["id"])
    detail = client.get(f"/api/transcripts/{transcript.id}")
    assert detail.status_code == 200
    assert detail.json()["segments"][0]["words"][0]["text"] == "conteúdo"
    assert len(client.get(f"/api/transcripts/{transcript.id}/segments").json()) == 1
    assert len(client.get(f"/api/transcripts/{transcript.id}/words").json()) == 1
    created = client.post(f"/api/transcripts/{transcript.id}/exports", json={"format": "json"})
    assert created.status_code == 201
    artifact = created.json()
    downloaded = client.get(f"/api/exports/{artifact['id']}")
    assert downloaded.status_code == 200
    assert json.loads(downloaded.content)["transcript"]["text"] == "conteúdo pesquisável"
    duplicate = client.post(f"/api/transcripts/{transcript.id}/exports", json={"format": "json"})
    assert duplicate.status_code == 409


def test_media_streaming_supports_ranges_and_rejects_invalid_ranges(client: TestClient) -> None:
    recording = _upload(client, _create_subject(client))
    complete = client.get(f"/api/recordings/{recording['id']}/media")
    assert complete.status_code == 200
    assert complete.headers["accept-ranges"] == "bytes"
    partial = client.get(
        f"/api/recordings/{recording['id']}/media", headers={"Range": "bytes=4-11"}
    )
    assert partial.status_code == 206
    assert partial.content == complete.content[4:12]
    assert partial.headers["content-range"].startswith("bytes 4-11/")
    invalid = client.get(
        f"/api/recordings/{recording['id']}/media", headers={"Range": "bytes=99999-"}
    )
    assert invalid.status_code == 416
    assert invalid.headers["content-range"].startswith("bytes */")


def test_job_event_query_supports_incremental_cursors(client: TestClient) -> None:
    job_id = _terminal_job(client)
    repository = client.app.state.repository
    all_events = repository.list_job_events(job_id)
    assert [event.sequence for event in all_events] == [1, 2, 3]
    assert repository.list_job_events(job_id, after_sequence=0) == all_events
    assert [event.sequence for event in repository.list_job_events(job_id, after_sequence=1)] == [
        2,
        3,
    ]
    assert repository.list_job_events(job_id, after_sequence=3) == []
    assert repository.list_job_events(job_id, after_sequence=99) == []


def test_job_event_query_applies_bounded_limit_in_order(client: TestClient) -> None:
    job_id = _terminal_job(client)
    repository = client.app.state.repository
    first = repository.list_job_events(job_id, after_sequence=0, limit=2)
    second = repository.list_job_events(job_id, after_sequence=first[-1].sequence, limit=2)
    assert [event.sequence for event in first] == [1, 2]
    assert [event.sequence for event in second] == [3]
    with pytest.raises(ValueError, match="non-negative"):
        repository.list_job_events(job_id, after_sequence=-1)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        repository.list_job_events(job_id, limit=0)


def test_sse_drains_backlog_in_incremental_batches_without_sleep(client: TestClient) -> None:
    job_id = _terminal_job(client)
    repository = client.app.state.repository

    class RepositorySpy:
        def __init__(self):
            self.database = repository.database
            self.calls: list[tuple[int, int | None]] = []

        def list_job_events(self, selected_job_id, *, after_sequence=0, limit=None):
            assert selected_job_id == job_id
            self.calls.append((after_sequence, limit))
            return repository.list_job_events(
                selected_job_id, after_sequence=after_sequence, limit=limit
            )

        def get_job(self, selected_job_id):
            return repository.get_job(selected_job_id)

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    async def forbidden_sleep(_seconds: float) -> None:
        raise AssertionError("backlog draining must not wait for the poll interval")

    async def consume():
        spy = RepositorySpy()
        chunks = [
            chunk
            async for chunk in stream_job_events(
                ConnectedRequest(),
                spy,
                job_id,
                0,
                poll_interval=1,
                heartbeat_interval=30,
                batch_size=1,
                sleeper=forbidden_sleep,
            )
        ]
        return spy.calls, chunks

    calls, chunks = asyncio.run(consume())
    event_ids = [int(match) for match in re.findall(r"^id: (\d+)$", "".join(chunks), re.MULTILINE)]
    assert event_ids == [1, 2, 3]
    assert calls == [(0, 1), (1, 1), (2, 1), (3, 1), (3, 1)]
    assert all(limit == 1 for _cursor, limit in calls)


def test_sse_detects_terminal_event_arriving_during_polling(client: TestClient) -> None:
    recording = _upload(client, _create_subject(client))
    _install_model(client.app)
    job = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()
    repository = client.app.state.repository
    slept = False

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    async def publish_terminal(_seconds: float) -> None:
        nonlocal slept
        assert not slept
        slept = True
        client.app.state.queue.cancel(job["id"])

    async def consume():
        return [
            chunk
            async for chunk in stream_job_events(
                ConnectedRequest(),
                repository,
                job["id"],
                0,
                poll_interval=1,
                heartbeat_interval=30,
                batch_size=10,
                sleeper=publish_terminal,
            )
        ]

    body = "".join(asyncio.run(consume()))
    assert slept is True
    assert "id: 2\n" in body
    assert "event: cancellation\n" in body


def test_sse_heartbeat_with_no_events_after_cursor_is_deterministic(
    client: TestClient,
) -> None:
    recording = _upload(client, _create_subject(client))
    _install_model(client.app)
    job = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    times = iter((0.0, 2.0))

    async def forbidden_sleep(_seconds: float) -> None:
        raise AssertionError("heartbeat should be emitted before sleeping")

    async def consume_two():
        stream = stream_job_events(
            ConnectedRequest(),
            client.app.state.repository,
            job["id"],
            1,
            poll_interval=1,
            heartbeat_interval=1,
            batch_size=10,
            clock=lambda: next(times),
            sleeper=forbidden_sleep,
        )
        chunks = [await anext(stream), await anext(stream)]
        await stream.aclose()
        return chunks

    assert asyncio.run(consume_two()) == ["retry: 2000\n\n", ": heartbeat\n\n"]


def test_sse_initial_replay_last_event_id_and_terminal_close(client: TestClient) -> None:
    recording = _upload(client, _create_subject(client))
    _install_model(client.app)
    job = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()
    client.post(f"/api/jobs/{job['id']}/cancel")
    initial = client.get(f"/api/jobs/{job['id']}/events")
    assert initial.status_code == 200
    assert initial.headers["content-type"].startswith("text/event-stream")
    assert "id: 1\n" in initial.text
    assert "event: cancellation\n" in initial.text
    resumed = client.get(f"/api/jobs/{job['id']}/events", headers={"Last-Event-ID": "1"})
    assert "id: 1\n" not in resumed.text
    assert "event: cancellation\n" in resumed.text
    assert (
        client.get(
            f"/api/jobs/{job['id']}/events", headers={"Last-Event-ID": "invalid"}
        ).status_code
        == 422
    )


def test_job_snapshot_cursor_seeds_sse_without_replaying_older_events(
    client: TestClient,
) -> None:
    recording = _upload(client, _create_subject(client))
    _install_model(client.app)
    created = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()
    assert created["last_event_sequence"] == 1
    cancelled = client.post(f"/api/jobs/{created['id']}/cancel").json()
    assert cancelled["last_event_sequence"] == 2

    resumed = client.get(f"/api/jobs/{created['id']}/events?after_sequence=1")
    assert "id: 1\n" not in resumed.text
    assert "id: 2\n" in resumed.text

    current = client.get(
        f"/api/jobs/{created['id']}/events?after_sequence=1",
        headers={"Last-Event-ID": "2"},
    )
    assert "id: 1\n" not in current.text
    assert "id: 2\n" not in current.text
    assert client.get(f"/api/jobs/{created['id']}/events?after_sequence=-1").status_code == 422


def test_sse_heartbeat_while_waiting(client: TestClient) -> None:
    recording = _upload(client, _create_subject(client))
    _install_model(client.app)
    job = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()
    timer = Timer(0.08, lambda: client.app.state.queue.cancel(job["id"]))
    timer.start()
    try:
        response = client.get(f"/api/jobs/{job['id']}/events")
    finally:
        timer.join()
    assert ": heartbeat\n\n" in response.text
    assert "event: cancellation\n" in response.text


def test_sse_disconnect_does_not_cancel_job(client: TestClient) -> None:
    recording = _upload(client, _create_subject(client))
    _install_model(client.app)
    job = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()

    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    async def consume() -> list[str]:
        chunks = []
        async for chunk in stream_job_events(
            DisconnectedRequest(),
            client.app.state.repository,
            job["id"],
            0,
            poll_interval=0.01,
            heartbeat_interval=0.02,
            batch_size=10,
        ):
            chunks.append(chunk)
        return chunks

    assert len(asyncio.run(consume())) == 2
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "pending"


def test_worker_lifecycle_processes_jobs_and_stops(tmp_path: Path) -> None:
    config = AppConfig(RuntimePaths((tmp_path / "worker-runtime").resolve()))
    app = create_app(
        config,
        engine_factory=lambda _profile: FakeEngine(),
        profiles=ProfileResolver(FixedProbe()),
        worker_poll_interval=0.01,
        sse_poll_interval=0.01,
        sse_heartbeat_interval=0.02,
    )
    with TestClient(app) as client:
        _install_model(app)
        recording = _upload(client, _create_subject(client))
        job = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()
        deadline = monotonic() + 3
        while monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "succeeded":
                break
            sleep(0.01)
        assert current["status"] == "succeeded"
        events = client.get(f"/api/jobs/{job['id']}/events").text
        assert "event: state\n" in events
        assert "event: phase\n" in events
        assert "event: progress\n" in events
        assert "event: completion\n" in events
        assert app.state.worker_controller.thread.is_alive()
    assert not app.state.worker_controller.thread.is_alive()


def test_sse_exposes_failed_terminal_event(tmp_path: Path) -> None:
    class BrokenEngine:
        name = "broken"

        def transcribe(self, request, progress=None):
            raise RuntimeError(f"decoder failed at {request.media_path}")

    config = AppConfig(RuntimePaths((tmp_path / "failed-runtime").resolve()))
    app = create_app(
        config,
        engine_factory=lambda _profile: BrokenEngine(),
        profiles=ProfileResolver(FixedProbe()),
        worker_poll_interval=0.01,
    )
    with TestClient(app) as client:
        _install_model(app)
        recording = _upload(client, _create_subject(client))
        job = client.post("/api/jobs", json={"recording_id": recording["id"]}).json()
        deadline = monotonic() + 3
        while monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "failed":
                break
            sleep(0.01)
        assert current["status"] == "failed"
        response = client.get(f"/api/jobs/{job['id']}/events")
        assert "event: failure\n" in response.text
        assert str(config.paths.root) not in response.text


def test_second_api_worker_for_same_runtime_is_refused(tmp_path: Path) -> None:
    config = AppConfig(RuntimePaths((tmp_path / "single-worker-runtime").resolve()))
    first = create_app(config, worker_poll_interval=0.01)
    second = create_app(config, worker_poll_interval=0.01)
    with TestClient(first):
        with pytest.raises(RuntimeError, match="one Uvicorn worker"):
            with TestClient(second):
                pass


def test_responses_do_not_disclose_absolute_runtime_paths(client: TestClient) -> None:
    subject_id = _create_subject(client)
    recording = _upload(client, subject_id)
    responses = [
        client.get("/api/health"),
        client.get("/api/capabilities"),
        client.get("/api/models"),
        client.get("/api/recordings"),
        client.get(f"/api/recordings/{recording['id']}"),
    ]
    runtime_root = str(client.app.state.config.paths.root)
    assert all(runtime_root not in response.text for response in responses)
