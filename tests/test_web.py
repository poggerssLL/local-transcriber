from __future__ import annotations

import io
import re
import socket
import wave
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_transcriber.api import create_app
from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.models import JobStatus, Segment, Transcript, Word
from local_transcriber.transcription import ProfileResolver, RuntimeCapabilities


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(b"\0\0" * 800)
    return output.getvalue()


def _write_fake_model(path: Path) -> None:
    path.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (path / name).write_bytes(b"test")


@dataclass
class FixedProbe:
    def inspect(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(frozenset({"int8"}), 0, frozenset(), "no CUDA")


@pytest.fixture
def web_app(tmp_path: Path):
    return create_app(
        AppConfig(RuntimePaths((tmp_path / "web-runtime").resolve())),
        start_worker=False,
        profiles=ProfileResolver(FixedProbe()),
    )


@pytest.fixture
def web_client(web_app):
    with TestClient(web_app) as client:
        yield client


class SemanticParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def test_web_shell_and_assets_are_local_and_work_without_network(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_network(*_args, **_kwargs):
        raise AssertionError("external network access is not allowed")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    responses = {
        "/": web_client.get("/"),
        "/assets/styles.css": web_client.get("/assets/styles.css"),
        "/assets/app.js": web_client.get("/assets/app.js"),
        "/assets/api.js": web_client.get("/assets/api.js"),
        "/assets/dom.js": web_client.get("/assets/dom.js"),
    }
    assert all(response.status_code == 200 for response in responses.values())
    assert responses["/"].headers["content-type"].startswith("text/html")
    assert responses["/assets/styles.css"].headers["content-type"].startswith("text/css")
    assert "javascript" in responses["/assets/app.js"].headers["content-type"]
    for response in responses.values():
        assert re.search(r"https?://|//cdn", response.text, re.IGNORECASE) is None
    csp = responses["/"].headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "'unsafe-inline'" not in csp
    assert web_client.get("/assets/../api.py").status_code == 404
    assert web_client.get("/api/openapi.json").status_code == 200
    assert web_client.get("/api/docs").status_code == 404


def test_web_shell_has_semantic_landmarks_labels_and_live_regions(web_client: TestClient) -> None:
    parser = SemanticParser()
    parser.feed(web_client.get("/").text)
    tags = parser.tags
    names = [tag for tag, _attrs in tags]
    assert {"aside", "nav", "main", "header", "section", "table", "dialog"}.issubset(names)
    html = next(attrs for tag, attrs in tags if tag == "html")
    assert html["lang"] == "pt-BR"
    links = [attrs for tag, attrs in tags if tag == "a"]
    assert any(attrs.get("href") == "#main-content" for attrs in links)
    assert any(attrs.get("aria-current") == "page" for attrs in links)
    labelled_ids = {
        attrs["for"] for tag, attrs in tags if tag == "label" and attrs.get("for") is not None
    }
    controls = [
        attrs for tag, attrs in tags if tag in {"input", "select"} and attrs.get("type") != "hidden"
    ]
    assert all(
        attrs.get("id") in labelled_ids or attrs.get("type") == "checkbox" for attrs in controls
    )
    live_regions = [attrs for _tag, attrs in tags if attrs.get("aria-live")]
    assert any(attrs.get("aria-live") == "polite" for attrs in live_regions)
    assert any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in tags)


def test_frontend_uses_safe_dom_modular_javascript_and_persistent_sse(
    web_client: TestClient,
) -> None:
    app_source = web_client.get("/assets/app.js").text
    api_source = web_client.get("/assets/api.js").text
    dom_source = web_client.get("/assets/dom.js").text
    combined = "\n".join((app_source, api_source, dom_source))
    for unsafe_sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert unsafe_sink not in combined
    assert "textContent" in combined
    assert "document.createElement" in combined
    assert "new EventSource(`${API_ROOT}/jobs/" in api_source
    assert "event.lastEventId" in api_source
    assert 'new Event("local-api-offline")' in api_source
    assert 'state.streamStates.set(jobId, "reconnecting")' in app_source
    assert "connectActiveJobs();" in app_source
    assert "player.currentTime = segment.start_seconds" in app_source
    assert "download.click()" in app_source


def test_ui_facing_flow_preserves_text_and_integrates_library_queue_search_and_export(
    web_client: TestClient,
) -> None:
    hostile_subject = '<img src=x onerror="alert(1)">'
    hostile_title = "Aula <script>alert(1)</script>"
    subject_response = web_client.post("/api/subjects", json={"name": hostile_subject})
    assert subject_response.status_code == 201
    subject = subject_response.json()
    upload = web_client.post(
        "/api/recordings",
        data={
            "title": hostile_title,
            "subject_id": subject["id"],
            "lesson_date": "2026-09-10",
        },
        files={"file": ("aula.wav", _wav_bytes(), "audio/wav")},
    )
    assert upload.status_code == 201
    recording = upload.json()
    assert recording["title"] == hostile_title
    assert hostile_title not in web_client.get("/").text
    results = web_client.get("/api/search", params={"q": "Aula"}).json()
    assert results[0]["recording_id"] == recording["id"]

    _write_fake_model(web_client.app.state.config.paths.models / "small")
    queued = web_client.post(
        "/api/jobs",
        json={
            "recording_id": recording["id"],
            "model_name": "small",
            "language": "pt",
            "profile": "cpu",
            "beam_size": 5,
            "vad_filter": True,
            "word_timestamps": True,
        },
    )
    assert queued.status_code == 202
    cancelled = web_client.post(f"/api/jobs/{queued.json()['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"

    job = web_client.app.state.repository.update_job_status(queued.json()["id"], JobStatus.PENDING)
    web_client.app.state.repository.update_job_status(job.id, JobStatus.RUNNING)
    web_client.app.state.repository.update_job_status(job.id, JobStatus.SUCCEEDED)
    transcript = web_client.app.state.repository.add_transcript(
        Transcript(
            recording_id=recording["id"],
            job_id=job.id,
            language="pt",
            language_probability=0.95,
            text="Texto sintético para validar a leitura.",
            segments=(
                Segment(
                    ordinal=0,
                    start_seconds=0,
                    end_seconds=0.1,
                    text="Texto sintético para validar a leitura.",
                    words=(
                        Word(
                            text="Texto",
                            start_seconds=0,
                            end_seconds=0.1,
                            probability=0.98,
                        ),
                    ),
                ),
            ),
        )
    )
    transcript_response = web_client.get(f"/api/transcripts/{transcript.id}")
    assert transcript_response.json()["segments"][0]["start_seconds"] == 0
    media = web_client.get(
        f"/api/recordings/{recording['id']}/media", headers={"Range": "bytes=0-9"}
    )
    assert media.status_code == 206
    exported = web_client.post(f"/api/transcripts/{transcript.id}/exports", json={"format": "txt"})
    assert exported.status_code == 201
    assert web_client.get(f"/api/exports/{exported.json()['id']}").status_code == 200


def test_runtime_reports_stopped_worker_to_interface(web_client: TestClient) -> None:
    runtime = web_client.get("/api/runtime")
    assert runtime.status_code == 200
    assert runtime.json()["worker_running"] is False
    assert runtime.json()["recommended_profile"] in {"cpu", "cuda"}


def test_openapi_keeps_web_shell_outside_versioned_api(web_client: TestClient) -> None:
    schema = web_client.get("/api/openapi.json").json()
    assert schema["info"]["version"] == "0.6.1"
    assert "/" not in schema["paths"]
    assert all(path.startswith("/api/") for path in schema["paths"])
