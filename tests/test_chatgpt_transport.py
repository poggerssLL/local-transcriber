"""Deterministic validation tests for ChatGPT Responses API client and transport."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_transcriber.chatgpt_auth import ChatGPTAuthManager, ChatGPTTokens
from local_transcriber.chatgpt_client import ChatGPTTransport
from local_transcriber.exceptions import (
    ChatGPTAuthError,
    ChatGPTInferenceError,
    ChatGPTLimitError,
    ChatGPTModelUnavailableError,
    ChatGPTServiceUnavailableError,
)


@pytest.fixture
def auth_mgr(tmp_path: Path) -> ChatGPTAuthManager:
    mgr = ChatGPTAuthManager(tmp_path / "auth")
    tokens = ChatGPTTokens(
        access_token="mock_valid_token_xyz",
        refresh_token="mock_refresh_token_123",
        id_token=None,
        expires_at=9999999999.0,  # far future
        client_id="oaiapp_test",
        ext_agent_host_id=mgr.host_id,
    )
    mgr.store.save(tokens)
    return mgr


def test_model_catalog_check_accepts_luna(auth_mgr: ChatGPTAuthManager) -> None:
    transport = ChatGPTTransport(auth_mgr)

    fixture_path = Path(__file__).parent / "fixtures" / "chatgpt_models_contract.json"
    mock_models_resp = json.loads(fixture_path.read_text(encoding="utf-8"))

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_models_resp).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        transport.verify_model_available("mock_valid_token_xyz")
        # Should not raise


def test_model_catalog_check_rejects_when_luna_absent(auth_mgr: ChatGPTAuthManager) -> None:
    transport = ChatGPTTransport(auth_mgr)

    mock_models_resp = {
        "models": [
            {"slug": "gpt-4o", "visibility": "public"},
            {"slug": "gpt-4o-mini", "visibility": "public"},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_models_resp).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ChatGPTModelUnavailableError, match="gpt-6-luna"):
            transport.verify_model_available("mock_valid_token_xyz")


def test_responses_api_payload_and_sse_streaming_completed(auth_mgr: ChatGPTAuthManager) -> None:
    transport = ChatGPTTransport(auth_mgr)

    # Mock /v1/models response conforming to SIWC contract
    mock_models_data = {"models": [{"slug": "gpt-6-luna", "visibility": "public"}]}

    # Mock SSE stream for /v1/responses using official response.output_text.delta
    sse_lines = [
        b"event: response.output_text.delta\r\n",
        b'data: {"delta": "{\\"chunk_summary\\": \\"Resumo dos sistemas\\""}\r\n',
        b"\r\n",
        b"event: response.output_text.delta\r\n",
        b'data: {"delta": ", \\"timeline\\": []}"}\r\n',
        b"\r\n",
        b"event: response.completed\r\n",
        b'data: {"response": {"status": "completed"}}\r\n',
        b"\r\n",
    ]

    sent_requests: list[urllib.request.Request] = []

    def mock_urlopen(req, timeout=None):
        sent_requests.append(req)
        if "v1/models" in req.full_url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_models_data).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp

        if "v1/responses" in req.full_url:
            resp = MagicMock()
            resp.status = 200
            resp.__iter__.return_value = iter(sse_lines)
            resp.__enter__.return_value = resp
            return resp
        raise ValueError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        output = transport.generate(
            prompt="Analise este bloco cronológico.",
            system_prompt="Você é um pedagogo técnico.",
            json_format=True,
        )

        assert '{"chunk_summary": "Resumo dos sistemas", "timeline": []}' in output

        # Verify request to /v1/responses
        resp_req = next(r for r in sent_requests if "v1/responses" in r.full_url)
        assert resp_req.get_header("Authorization") == "Bearer mock_valid_token_xyz"
        assert resp_req.get_header("Accept") == "text/event-stream"

        body = json.loads(resp_req.data.decode("utf-8"))
        assert body["model"] == "gpt-6-luna"
        assert body["reasoning"] == {"effort": "low"}
        assert body["store"] is False
        assert body["stream"] is True
        assert body["input"][0]["role"] == "developer"
        assert body["input"][0]["content"] == "Você é um pedagogo técnico."
        assert body["input"][1]["role"] == "user"
        assert body["input"][1]["content"] == "Analise este bloco cronológico."


def test_sse_prevents_duplication_when_output_item_done_follows_deltas(
    auth_mgr: ChatGPTAuthManager,
) -> None:
    transport = ChatGPTTransport(auth_mgr)
    mock_models_data = {"models": [{"slug": "gpt-6-luna", "visibility": "public"}]}

    full_text = "Síntese textual sem duplicatas."
    sse_lines = [
        b"event: response.output_text.delta\r\n",
        b'data: {"delta": "S\xc3\xadntese textual "}\r\n',
        b"\r\n",
        b"event: response.output_text.delta\r\n",
        b'data: {"delta": "sem duplicatas."}\r\n',
        b"\r\n",
        b"event: response.output_item.done\r\n",
        (
            b'data: {"item": {"content": [{"type": "output_text", '
            b'"text": "S\xc3\xadntese textual sem duplicatas."}]}}\r\n'
        ),
        b"\r\n",
        b"event: response.completed\r\n",
        (
            b'data: {"response": {"output": [{"content": [{"type": "output_text", '
            b'"text": "S\xc3\xadntese textual sem duplicatas."}]}]}}\r\n'
        ),
        b"\r\n",
    ]

    def mock_urlopen(req, timeout=None):
        if "v1/models" in req.full_url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_models_data).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp
        resp = MagicMock()
        resp.status = 200
        resp.__iter__.return_value = iter(sse_lines)
        resp.__enter__.return_value = resp
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        output = transport.generate("Prompt")
        # Must be exactly the single instance, not multiplied!
        assert output == full_text


def test_sse_streaming_failed_event(auth_mgr: ChatGPTAuthManager) -> None:
    transport = ChatGPTTransport(auth_mgr)
    mock_models_data = {"data": [{"id": "gpt-6-luna"}]}

    failed_data = json.dumps({"error": {"code": "server_error", "message": "Falha interna"}})
    sse_lines = [
        b"event: response.failed\r\n",
        f"data: {failed_data}\r\n".encode(),
        b"\r\n",
    ]

    def mock_urlopen(req, timeout=None):
        if "v1/models" in req.full_url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_models_data).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp
        resp = MagicMock()
        resp.status = 200
        resp.__iter__.return_value = iter(sse_lines)
        resp.__enter__.return_value = resp
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with pytest.raises(ChatGPTInferenceError, match="Falha interna"):
            transport.generate("Prompt de teste")


def test_sse_streaming_incomplete_event(auth_mgr: ChatGPTAuthManager) -> None:
    transport = ChatGPTTransport(auth_mgr)
    mock_models_data = {"data": [{"id": "gpt-6-luna"}]}

    sse_lines = [
        b"event: response.incomplete\r\n",
        b'data: {"incomplete_details": {"reason": "max_output_tokens"}}\r\n',
        b"\r\n",
    ]

    def mock_urlopen(req, timeout=None):
        if "v1/models" in req.full_url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_models_data).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp
        resp = MagicMock()
        resp.status = 200
        resp.__iter__.return_value = iter(sse_lines)
        resp.__enter__.return_value = resp
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with pytest.raises(ChatGPTInferenceError, match="max_output_tokens"):
            transport.generate("Prompt de teste")


def test_http_status_errors(auth_mgr: ChatGPTAuthManager) -> None:
    transport = ChatGPTTransport(auth_mgr)
    mock_models_data = {"data": [{"id": "gpt-6-luna"}]}

    # 1. HTTP 401 Unauthorized
    def mock_urlopen_401(req, timeout=None):
        if "v1/models" in req.full_url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_models_data).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error": "invalid_token"}')
        )

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_401):
        with pytest.raises(ChatGPTAuthError):
            transport.generate("Prompt")

    # 2. HTTP 429 Rate Limit
    def mock_urlopen_429(req, timeout=None):
        if "v1/models" in req.full_url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_models_data).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b'{"error": "rate_limit"}')
        )

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_429):
        with pytest.raises(ChatGPTLimitError):
            transport.generate("Prompt")

    # 3. HTTP 503 Service Unavailable
    def mock_urlopen_503(req, timeout=None):
        if "v1/models" in req.full_url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(mock_models_data).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp
        raise urllib.error.HTTPError(
            req.full_url, 503, "Service Unavailable", {}, io.BytesIO(b'{"error": "unavailable"}')
        )

    with patch("urllib.request.urlopen", side_effect=mock_urlopen_503):
        with pytest.raises(ChatGPTServiceUnavailableError):
            transport.generate("Prompt")
