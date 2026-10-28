"""ChatGPT client and Responses API transport for transcript summarization.

Implements the official Responses API integration for ChatGPT subscribers:
- Checks account model catalog (/v1/models) with OAuth token; verifies 'gpt-6-luna' presence
- Exclusively uses /v1/responses with store:false, stream:true, reasoning.effort:'low'
- Streams Server-Sent Events (SSE) until terminal event 'response.completed'
- Strictly handles 'response.failed', 'response.incomplete', 401, 403, 429, 503
- Prohibits silent model/account substitution and silent fallback to local engines
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .chatgpt_auth import ChatGPTAuthManager
from .exceptions import (
    ChatGPTAuthError,
    ChatGPTInferenceError,
    ChatGPTLimitError,
    ChatGPTModelUnavailableError,
    ChatGPTServiceUnavailableError,
)

LOGGER = logging.getLogger(__name__)

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
LUNA_MODEL_NAME = "gpt-6-luna"
LUNA_REASONING_EFFORT = "low"


class ChatGPTTransport:
    """LLM transport using authenticated ChatGPT subscriber plan via Responses API."""

    def __init__(
        self,
        auth_manager: ChatGPTAuthManager,
        *,
        model_name: str = LUNA_MODEL_NAME,
        reasoning_effort: str = LUNA_REASONING_EFFORT,
        models_url: str = OPENAI_MODELS_URL,
        responses_url: str = OPENAI_RESPONSES_URL,
        timeout: float = 600.0,
    ) -> None:
        self.auth_manager = auth_manager
        self._model_name = model_name
        self.reasoning_effort = reasoning_effort
        self.models_url = models_url
        self.responses_url = responses_url
        self.timeout = timeout
        self._verified_models: set[str] | None = None

    @property
    def provider_name(self) -> str:
        return "chatgpt"

    @property
    def model_name(self) -> str:
        return self._model_name

    def provenance_metadata(self) -> dict[str, Any]:
        """Metadata for summary provenance."""
        return {
            "provider": self.provider_name,
            "model_name": self.model_name,
            "reasoning_effort": self.reasoning_effort,
        }

    def fetch_available_models(self, access_token: str) -> list[str]:
        """Query /v1/models using OAuth token to inspect account catalog.

        Conforms to official Sign in with ChatGPT contract:
        Returns models array with objects containing slug and visibility.
        """
        req = urllib.request.Request(
            self.models_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "LocalTranscriber/0.7.1",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # Official SIWC contract: {"models": [{"slug": "...", "visibility": "..."}]}
                if isinstance(data.get("models"), list):
                    model_ids = [
                        str(m.get("slug"))
                        for m in data["models"]
                        if isinstance(m, dict) and m.get("slug")
                    ]
                    return model_ids
                # Standard OpenAI fallback: {"data": [{"id": "..."}]}
                if isinstance(data.get("data"), list):
                    model_ids = [
                        str(m.get("id") or m.get("slug"))
                        for m in data["data"]
                        if isinstance(m, dict) and (m.get("id") or m.get("slug"))
                    ]
                    return model_ids
                return []
        except urllib.error.HTTPError as err:
            err_body = ""
            try:
                err_body = err.read().decode("utf-8")
            except Exception:
                pass
            if err.code in (401, 403):
                raise ChatGPTAuthError(
                    f"Acesso negado ao consultar modelos da conta ChatGPT "
                    f"(HTTP {err.code}): {err_body}"
                ) from err
            if err.code == 429:
                raise ChatGPTLimitError(
                    f"Limite de requisições excedido ao consultar modelos (HTTP 429): {err_body}"
                ) from err
            if err.code == 503:
                raise ChatGPTServiceUnavailableError(
                    f"Serviço de modelos da OpenAI indisponível (HTTP 503): {err_body}"
                ) from err
            raise ChatGPTAuthError(
                f"Erro HTTP {err.code} ao consultar catálogo de modelos: {err_body}"
            ) from err
        except Exception as err:
            raise ChatGPTServiceUnavailableError(
                f"Não foi possível conectar ao catálogo de modelos da OpenAI: {err}"
            ) from err

    def verify_model_available(self, access_token: str) -> None:
        """Verify that gpt-6-luna is in the user's available model catalog."""
        if self._verified_models is not None and self._model_name in self._verified_models:
            return

        available_models = self.fetch_available_models(access_token)
        self._verified_models = set(available_models)

        if self._model_name not in self._verified_models:
            raise ChatGPTModelUnavailableError(
                f"O modelo '{self._model_name}' não está disponível na sua conta ChatGPT. "
                "A conta autorizada não possui acesso ao modelo solicitado."
            )

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_format: bool = False,
    ) -> str:
        """Send complete transcript block to /v1/responses with streaming and low reasoning.

        Consumes SSE stream until 'response.completed'.
        Does NOT silently fall back to Ollama or substitute models on error.
        """
        token = self.auth_manager.get_valid_token()
        self.verify_model_available(token)

        # Build payload for /v1/responses
        input_messages: list[dict[str, str]] = []
        if system_prompt:
            input_messages.append({"role": "developer", "content": system_prompt})
        input_messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self._model_name,
            "reasoning": {
                "effort": self.reasoning_effort,
            },
            "store": False,
            "stream": True,
            "input": input_messages,
        }

        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.responses_url,
            data=body_bytes,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "LocalTranscriber/0.7.1",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                if status != 200:
                    raise ChatGPTServiceUnavailableError(
                        f"ChatGPT retornou status HTTP {status} em {self.responses_url}."
                    )
                return self._consume_sse_stream(resp)

        except urllib.error.HTTPError as err:
            err_body = ""
            try:
                err_body = err.read().decode("utf-8")
            except Exception:
                pass

            if err.code in (401, 403):
                raise ChatGPTAuthError(
                    f"Falha de autorização ChatGPT (HTTP {err.code}): {err_body}"
                ) from err
            if err.code == 429:
                raise ChatGPTLimitError(
                    f"Limite de taxa ou cota do plano ChatGPT excedido (HTTP 429): {err_body}"
                ) from err
            if err.code in (500, 502, 503, 504):
                raise ChatGPTServiceUnavailableError(
                    f"Serviço ChatGPT indisponível (HTTP {err.code}): {err_body}"
                ) from err
            raise ChatGPTInferenceError(
                f"Erro HTTP {err.code} na inferência do ChatGPT: {err_body}"
            ) from err

        except TimeoutError as err:
            raise ChatGPTServiceUnavailableError(
                f"Tempo limite excedido ({self.timeout}s) ao aguardar resposta do ChatGPT."
            ) from err

        except Exception as err:
            if isinstance(
                err,
                (
                    ChatGPTAuthError,
                    ChatGPTLimitError,
                    ChatGPTServiceUnavailableError,
                    ChatGPTInferenceError,
                    ChatGPTModelUnavailableError,
                ),
            ):
                raise
            raise ChatGPTServiceUnavailableError(
                f"Falha de conexão com a API do ChatGPT: {err}"
            ) from err

    def _consume_sse_stream(self, resp: Any) -> str:
        """Consume SSE stream line by line until response.completed."""
        accumulated_text: list[str] = []
        current_event: str | None = None
        current_data_lines: list[str] = []
        completed = False
        received_deltas = False

        for line_bytes in resp:
            line = line_bytes.decode("utf-8").rstrip("\r\n")
            if not line:
                # Dispatch event
                if current_event and current_data_lines:
                    data_str = "\n".join(current_data_lines)
                    text_delta, is_done, has_delta = self._handle_sse_event(
                        current_event, data_str, received_deltas=received_deltas
                    )
                    if has_delta:
                        received_deltas = True
                    if text_delta:
                        accumulated_text.append(text_delta)
                    if is_done:
                        completed = True
                        break
                current_event = None
                current_data_lines = []
                continue

            if line.startswith("event:"):
                current_event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                current_data_lines.append(line[len("data:") :].strip())

        # Handle final event if no trailing newline
        if not completed and current_event and current_data_lines:
            data_str = "\n".join(current_data_lines)
            text_delta, is_done, has_delta = self._handle_sse_event(
                current_event, data_str, received_deltas=received_deltas
            )
            if has_delta:
                received_deltas = True
            if text_delta:
                accumulated_text.append(text_delta)
            if is_done:
                completed = True

        if not completed:
            raise ChatGPTInferenceError(
                "O fluxo SSE do ChatGPT encerrou prematuramente sem evento 'response.completed'."
            )

        full_output = "".join(accumulated_text).strip()
        if not full_output:
            raise ChatGPTInferenceError(
                "O modelo ChatGPT concluiu a requisição mas não retornou conteúdo "
                "textual de resposta."
            )

        return full_output

    def _handle_sse_event(
        self, event_name: str, data_str: str, *, received_deltas: bool = False
    ) -> tuple[str | None, bool, bool]:
        """Handle individual SSE event payload.

        Returns (text_delta, is_terminal_done, is_delta_event).
        Prevents duplicate text when output_item.done or response.completed arrives
        after streaming incremental deltas.
        """
        try:
            data = json.loads(data_str) if data_str else {}
        except json.JSONDecodeError:
            data = {}

        if event_name in ("response.failed", "error"):
            err_obj = data.get("error") or data.get("response", {}).get("error") or {}
            msg = err_obj.get("message") or "Erro desconhecido durante geração."
            code = err_obj.get("code") or "failed"
            raise ChatGPTInferenceError(
                f"Geração rejeitada ou interrompida pelo ChatGPT (código '{code}'): {msg}"
            )

        if event_name == "response.incomplete":
            details = (
                data.get("incomplete_details")
                or data.get("response", {}).get("incomplete_details")
                or {}
            )
            reason = details.get("reason") or "limite_atingido"
            raise ChatGPTInferenceError(
                f"Resposta do ChatGPT incompleta: geração interrompida devido a '{reason}'."
            )

        # Official Responses API streaming event for text deltas: response.output_text.delta
        # (also accept response.text.delta for backward compatibility)
        if event_name in ("response.output_text.delta", "response.text.delta"):
            delta = data.get("delta") or data.get("text") or ""
            return str(delta), False, True

        # When output item finishes: DO NOT duplicate if deltas were already received!
        if event_name in ("response.output_item.done", "response.text.done"):
            if received_deltas:
                return None, False, False
            # Fallback if no deltas were streamed incrementally
            item = data.get("item") or {}
            content_list = item.get("content") or []
            if isinstance(content_list, list):
                texts = [
                    c.get("text")
                    for c in content_list
                    if isinstance(c, dict)
                    and c.get("type") in ("text", "output_text")
                    and c.get("text")
                ]
                if texts:
                    return "".join(texts), False, False
            return None, False, False

        if event_name == "response.completed":
            if received_deltas:
                return None, True, False
            # Check if output contains text when deltas were not captured
            resp_obj = data.get("response") or {}
            output_items = resp_obj.get("output") or []
            fallback_texts: list[str] = []
            for item in output_items:
                if isinstance(item, dict):
                    content_list = item.get("content") or []
                    for c in content_list:
                        if (
                            isinstance(c, dict)
                            and c.get("type") in ("text", "output_text")
                            and c.get("text")
                        ):
                            fallback_texts.append(str(c["text"]))
            if fallback_texts:
                return "".join(fallback_texts), True, False
            return None, True, False

        return None, False, False
