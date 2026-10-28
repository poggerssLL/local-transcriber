"""Antigravity CLI client and LLM transport for transcript summarization.

Leverages the local Antigravity CLI (agy) and the user's active Google AI Pro session
to generate structured pedagogical summaries via Gemini (e.g. gemini-3.8-flash-low / medium / high).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .exceptions import AntigravityInferenceError, AntigravityUnavailableError
from .summarizer import LLMTransport

LOGGER = logging.getLogger(__name__)

DEFAULT_ANTIGRAVITY_MODEL = "gemini-3.8-flash-low"
DEFAULT_AGY_TIMEOUT = 600.0


def find_antigravity_cli() -> str | None:
    """Find the path to the agy executable on the local system."""
    # 1. Search PATH
    which_path = shutil.which("agy")
    if which_path:
        return which_path

    # 2. Check standard Windows LocalAppData path
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "agy" / "bin" / "agy.exe"
        if candidate.is_file():
            return str(candidate)

    return None


class AntigravityTransport(LLMTransport):
    """LLM transport using the local Antigravity CLI with authenticated Google AI Pro session."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_ANTIGRAVITY_MODEL,
        cli_path: str | None = None,
        timeout: float = DEFAULT_AGY_TIMEOUT,
    ) -> None:
        resolved_cli = cli_path or find_antigravity_cli()
        if not resolved_cli:
            raise AntigravityUnavailableError(
                "O executável Antigravity ('agy') não foi encontrado no sistema. "
                "Certifique-se de que o Antigravity CLI está instalado e acessível."
            )
        self.cli_path = resolved_cli
        self._model_name = model_name
        self.timeout = timeout

    @property
    def provider_name(self) -> str:
        return "antigravity"

    @property
    def model_name(self) -> str:
        return self._model_name

    def provenance_metadata(self) -> dict[str, Any]:
        """Metadata for summary provenance."""
        return {
            "provider": self.provider_name,
            "model_name": self.model_name,
            "cli_path": self.cli_path,
        }

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_format: bool = False,
    ) -> str:
        """Call agy CLI via stdin pipe with robust error handling and timeout."""
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"[INSTRUÇÕES DO SISTEMA]\n{system_prompt}\n\n[TAREFA]\n{prompt}"

        if json_format:
            full_prompt += (
                "\n\nResponda estritamente com um objeto JSON válido, "
                "sem texto introdutório, cumprimentos ou comentários adicionais."
            )

        cmd = [
            self.cli_path,
            "--model",
            self._model_name,
            "--disable-slash-commands",
            "--output-format",
            "json",
        ]

        try:
            proc = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as err:
            raise AntigravityInferenceError(
                f"Tempo limite excedido ({self.timeout}s) ao aguardar resposta do Antigravity."
            ) from err
        except OSError as err:
            raise AntigravityInferenceError(
                f"Erro ao executar o Antigravity CLI em '{self.cli_path}': {err}"
            ) from err

        if proc.returncode != 0:
            err_msg = (
                proc.stderr.strip() or proc.stdout.strip() or f"Código de saída {proc.returncode}"
            )
            raise AntigravityInferenceError(f"Falha na inferência do Antigravity: {err_msg}")

        stdout_clean = proc.stdout.strip()
        if not stdout_clean:
            raise AntigravityInferenceError("O Antigravity retornou saída vazia.")

        try:
            data = json.loads(stdout_clean)
            response_text = str(data.get("response") or "")
        except json.JSONDecodeError:
            response_text = stdout_clean

        if not response_text:
            raise AntigravityInferenceError(
                "Resposta do Antigravity não contém texto de inferência."
            )

        return response_text
