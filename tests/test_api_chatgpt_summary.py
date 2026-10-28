"""Deterministic validation tests for ChatGPT OAuth and summary API endpoints."""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from local_transcriber.api import create_app
from local_transcriber.chatgpt_auth import ChatGPTTokens
from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.models import (
    JobPhase,
    JobStatus,
    Segment,
    Transcript,
    TranscriptionJob,
    Word,
)


def _wav_bytes(*, frames: int = 400) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * frames)
    return output.getvalue()


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


def _seed_transcript(app, client: TestClient) -> str:
    sub_res = client.post("/api/subjects", json={"name": "Automação"})
    assert sub_res.status_code == 201
    subject_id = sub_res.json()["id"]

    rec_res = client.post(
        "/api/recordings",
        data={
            "title": "Aula 01",
            "subject_id": subject_id,
            "lesson_date": "2026-10-24",
        },
        files={"file": ("aula01.wav", _wav_bytes(), "audio/wav")},
    )
    assert rec_res.status_code == 201
    recording_id = rec_res.json()["id"]

    repository = app.state.repository
    job = repository.add_job(
        TranscriptionJob(
            recording_id=recording_id,
            engine="fake",
            model_name="small",
            status=JobStatus.SUCCEEDED,
            phase=JobPhase.COMPLETED,
            progress_percent=100,
        )
    )
    transcript = repository.add_transcript(
        Transcript(
            recording_id=recording_id,
            job_id=job.id,
            language="pt",
            language_probability=0.99,
            text="00:00:10 Introdução a sensores e atuadores na indústria.",
            segments=(
                Segment(
                    ordinal=0,
                    start_seconds=10.0,
                    end_seconds=20.0,
                    text="Introdução a sensores e atuadores na indústria.",
                    words=(
                        Word(
                            text="Introdução",
                            start_seconds=10.0,
                            end_seconds=15.0,
                            probability=0.95,
                        ),
                    ),
                ),
            ),
        )
    )
    return transcript.id


def test_auth_status_not_connected(client: TestClient) -> None:
    res = client.get("/api/auth/chatgpt/status")
    assert res.status_code == 200
    data = res.json()
    assert data["connected"] is False
    assert data["expired"] is True
    assert data["email"] is None


def test_auth_login_generates_auth_url(client: TestClient) -> None:
    res = client.get("/api/auth/chatgpt/login")
    assert res.status_code == 200
    data = res.json()
    assert "auth_url" in data
    assert "state" in data
    assert "https://auth.openai.com/api/accounts/authorize?" in data["auth_url"]
    assert "chatgpt.tokens.use.direct" in data["auth_url"]
    assert "resource.invoke" in data["auth_url"]
    assert "resource=https%3A%2F%2Fapi.openai.com%2Fv1" in data["auth_url"]
    assert "redirect_uri=http%3A%2F%2F127.0.0.1" in data["auth_url"]


def test_auth_login_redirect_uri_validation(client: TestClient) -> None:
    # 1. Non-127.0.0.1 domain rejected
    res_evil = client.get("/api/auth/chatgpt/login?redirect_uri=http://evil.com/callback")
    assert res_evil.status_code == 400
    assert "redirect_uri inválido" in res_evil.json()["detail"]

    # 2. Localhost rejected (SIWC specification requires strictly 127.0.0.1)
    res_lh = client.get(
        "/api/auth/chatgpt/login?redirect_uri=http://localhost:8765/api/auth/chatgpt/callback"
    )
    assert res_lh.status_code == 400
    assert "redirect_uri inválido" in res_lh.json()["detail"]

    # 3. Valid 127.0.0.1 callback accepted
    res_ok = client.get(
        "/api/auth/chatgpt/login?redirect_uri=http://127.0.0.1:8765/api/auth/chatgpt/callback"
    )
    assert res_ok.status_code == 200


def test_auth_callback_error_and_invalid_state(client: TestClient) -> None:
    # 1. Error passed by IdP without valid state rejected on state check
    res_err_nostate = client.get(
        "/api/auth/chatgpt/callback?error=access_denied&error_description=Cancelado"
    )
    assert res_err_nostate.status_code == 400
    assert "Estado ausente" in res_err_nostate.text

    # 2. Error passed with nonexistent state
    res_err_badstate = client.get(
        "/api/auth/chatgpt/callback?error=access_denied&error_description=Cancelado&state=unknown_state"
    )
    assert res_err_badstate.status_code == 400
    assert "Estado expirado ou inválido" in res_err_badstate.text

    # 3. Error passed with valid pending state
    login_res = client.get("/api/auth/chatgpt/login")
    valid_state = login_res.json()["state"]
    res_err_valid_state = client.get(
        f"/api/auth/chatgpt/callback?error=access_denied&error_description=Cancelado&state={valid_state}"
    )
    assert res_err_valid_state.status_code == 400
    assert "Cancelado" in res_err_valid_state.text


def test_auth_callback_ttl_expiration(app, client: TestClient) -> None:
    import time

    login_res = client.get("/api/auth/chatgpt/login")
    state = login_res.json()["state"]

    # Simulate expired pending auth (created > 600s ago)
    app.state.chatgpt_pending_auth[state]["created_at"] = time.time() - 700.0

    res = client.get(f"/api/auth/chatgpt/callback?code=mock_code&state={state}")
    assert res.status_code == 400
    assert "Estado expirado ou inválido" in res.text


def test_auth_callback_html_escaping(app, client: TestClient) -> None:
    # Test escaping in error message
    login_res = client.get("/api/auth/chatgpt/login")
    state = login_res.json()["state"]

    res_err = client.get(
        f"/api/auth/chatgpt/callback?error=invalid_request&error_description=<script>alert('xss')</script>&state={state}"
    )
    assert res_err.status_code == 400
    assert "<script>" not in res_err.text
    assert "&lt;script&gt;" in res_err.text

    # Test escaping in user email
    login_res2 = client.get("/api/auth/chatgpt/login")
    state2 = login_res2.json()["state"]

    mock_tokens = ChatGPTTokens(
        access_token="at_mock",
        refresh_token="rt_mock",
        id_token=None,
        expires_at=9999999999.0,
        client_id="oaiapp_app",
        ext_agent_host_id="urn:uuid:test-host",
        user_email="<script>evil@example.com</script>",
    )

    with patch.object(app.state.chatgpt_auth_manager, "exchange_code", return_value=mock_tokens):
        res_ok = client.get(f"/api/auth/chatgpt/callback?code=mock_code&state={state2}")
        assert res_ok.status_code == 200
        assert "<script>evil" not in res_ok.text
        assert "&lt;script&gt;evil@example.com&lt;/script&gt;" in res_ok.text


def test_auth_status_does_not_report_has_luna_true_on_failure(app, client: TestClient) -> None:
    tokens = ChatGPTTokens(
        access_token="at_mock",
        refresh_token="rt_mock",
        id_token=None,
        expires_at=9999999999.0,
        client_id="oaiapp_app",
        ext_agent_host_id="urn:uuid:test-host",
        user_email="student@univ.edu",
    )
    app.state.chatgpt_auth_manager.store.save(tokens)

    # When model check raises network or service error
    with patch(
        "local_transcriber.chatgpt_client.ChatGPTTransport.fetch_available_models",
        side_effect=RuntimeError("OpenAI API unreachable"),
    ):
        res = client.get("/api/auth/chatgpt/status")
        assert res.status_code == 200
        data = res.json()
        assert data["connected"] is True
        assert data["has_luna"] is False
        assert data["model"] is None


def test_auth_callback_success(app, client: TestClient) -> None:
    # Initiate login to populate state
    login_res = client.get("/api/auth/chatgpt/login")
    state = login_res.json()["state"]

    mock_tokens = ChatGPTTokens(
        access_token="at_mock_123",
        refresh_token="rt_mock_456",
        id_token=None,
        expires_at=9999999999.0,
        client_id="oaiapp_app_789",
        ext_agent_host_id="urn:uuid:test-host",
        user_email="student@univ.edu",
    )

    def fake_exchange(*args, **kwargs):
        app.state.chatgpt_auth_manager.store.save(mock_tokens)
        return mock_tokens

    with patch.object(app.state.chatgpt_auth_manager, "exchange_code", side_effect=fake_exchange):
        res = client.get(f"/api/auth/chatgpt/callback?code=mock_code&state={state}")
        assert res.status_code == 200
        assert "Conectado com Sucesso!" in res.text
        assert "student@univ.edu" in res.text

    # Check status now reflects connection
    status_res = client.get("/api/auth/chatgpt/status")
    assert status_res.status_code == 200
    assert status_res.json()["connected"] is True
    assert status_res.json()["email"] == "student@univ.edu"


def test_auth_logout(app, client: TestClient) -> None:
    # Save dummy tokens
    tokens = ChatGPTTokens(
        access_token="at_dummy",
        refresh_token="rt_dummy",
        id_token=None,
        expires_at=9999999999.0,
        client_id="oaiapp_test",
        ext_agent_host_id="urn:uuid:test",
    )
    app.state.chatgpt_auth_manager.store.save(tokens)

    status_before = client.get("/api/auth/chatgpt/status").json()
    assert status_before["connected"] is True

    logout_res = client.post("/api/auth/chatgpt/logout")
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "logged_out"

    status_after = client.get("/api/auth/chatgpt/status").json()
    assert status_after["connected"] is False


def test_api_summary_with_chatgpt_not_connected_raises_401(app, client: TestClient) -> None:
    transcript_id = _seed_transcript(app, client)

    res = client.post(
        f"/api/transcripts/{transcript_id}/summary",
        json={"provider": "chatgpt"},
    )
    assert res.status_code == 401
    assert "ChatGPT não conectada" in res.json()["detail"]


def test_api_summary_with_chatgpt_success(app, client: TestClient) -> None:
    transcript_id = _seed_transcript(app, client)

    tokens = ChatGPTTokens(
        access_token="at_dummy",
        refresh_token="rt_dummy",
        id_token=None,
        expires_at=9999999999.0,
        client_id="oaiapp_test",
        ext_agent_host_id="urn:uuid:test",
        user_email="user@test.org",
    )
    app.state.chatgpt_auth_manager.store.save(tokens)

    # Mock responses for map and reduce
    map_resp = json.dumps(
        {
            "chunk_summary": "Visão geral de sensores indutivos e capacitivos.",
            "timeline": [
                {
                    "timestamp": "00:00:10",
                    "seconds": 10.0,
                    "topic": "Sensores",
                    "summary": "Classificação.",
                }
            ],
            "glossary": [
                {
                    "term": "Sensor Indutivo",
                    "definition": "Sensor para metais.",
                    "first_timestamp": "00:00:10",
                }
            ],
            "flashcards": [
                {
                    "question": "O que detecta um sensor indutivo?",
                    "answer": "Materiais metálicos.",
                    "timestamp": "00:00:10",
                }
            ],
        }
    )
    reduce_resp = json.dumps(
        {
            "core_thesis": "A correta instrumentação garante confiabilidade na automação.",
            "paragraphs": [
                "A aula abordou sensores de proximidade aplicados a linhas de montagem."
            ],
            "spoken_summary": "Olá! Hoje exploramos o uso de sensores na automação industrial.",
        }
    )

    with (
        patch("local_transcriber.chatgpt_client.ChatGPTTransport.verify_model_available"),
        patch(
            "local_transcriber.chatgpt_client.ChatGPTTransport.generate",
            side_effect=[map_resp, reduce_resp],
        ),
    ):
        res = client.post(
            f"/api/transcripts/{transcript_id}/summary",
            json={"provider": "chatgpt"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["schema_version"] == "1.0.0"
        assert data["provenance"]["provider"] == "chatgpt"
        assert data["provenance"]["model_name"] == "gpt-6-luna"
        assert (
            data["executive"]["core_thesis"]
            == "A correta instrumentação garante confiabilidade na automação."
        )
        assert len(data["timeline"]) == 1
        assert len(data["glossary"]) == 1
        assert len(data["flashcards"]) == 1
