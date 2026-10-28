"""Deterministic validation tests for LLM transport isolation in Map-Reduce summarization."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_transcriber.chatgpt_client import ChatGPTTransport
from local_transcriber.exceptions import ChatGPTInferenceError
from local_transcriber.summarizer import (
    OllamaTransport,
    SummaryConfig,
    TranscriptSummarizer,
)


def _sample_transcript_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "aula_controle.transcription.md"
    file_path.write_text(
        """# Aula de Controle Realimentado
## Segmentos
- `00:00:10.000` Introdução ao controle em malha fechada e realimentação de estados.
- `00:15:00.000` Análise de estabilidade pelo critério de Routh-Hurwitz.
""",
        encoding="utf-8",
    )
    return file_path


def test_summarizer_with_chatgpt_transport(tmp_path: Path) -> None:
    source_file = _sample_transcript_file(tmp_path)

    mock_chatgpt_transport = MagicMock(spec=ChatGPTTransport)
    mock_chatgpt_transport.provider_name = "chatgpt"
    mock_chatgpt_transport.model_name = "gpt-6-luna"
    mock_chatgpt_transport.provenance_metadata.return_value = {
        "provider": "chatgpt",
        "model_name": "gpt-6-luna",
        "reasoning_effort": "low",
    }

    # Responses for map and reduce
    map_response = json.dumps(
        {
            "chunk_summary": "Conceitos de malha fechada e estabilidade linear.",
            "timeline": [
                {
                    "timestamp": "00:00:10",
                    "seconds": 10.0,
                    "topic": "Malha Fechada",
                    "summary": "Diagrama de blocos e realimentação.",
                }
            ],
            "glossary": [
                {
                    "term": "Malha Fechada",
                    "definition": "Sistema onde a ação de controle depende da saída.",
                    "first_timestamp": "00:00:10",
                }
            ],
            "flashcards": [
                {
                    "question": "O que caracteriza um sistema em malha fechada?",
                    "answer": "A presença de realimentação do sinal de saída.",
                    "timestamp": "00:00:10",
                }
            ],
        }
    )

    reduce_response = json.dumps(
        {
            "core_thesis": "A realimentação assegura a estabilidade e a robustez do controle.",
            "paragraphs": [
                "A aula apresentou os conceitos formais de estabilidade linear em malha fechada."
            ],
            "spoken_summary": "Olá! Hoje revisamos os fundamentos essenciais de controle.",
        }
    )

    mock_chatgpt_transport.generate.side_effect = [map_response, reduce_response]

    config = SummaryConfig(chunk_duration_minutes=20, timeout=30)
    summarizer = TranscriptSummarizer(config=config, transport=mock_chatgpt_transport)

    events: list[dict] = []
    md_path = summarizer.summarize(source_file, progress_callback=events.append)

    assert md_path.is_file()
    json_path = md_path.with_name("aula_controle.resumo.json")
    assert json_path.is_file()

    # Verify JSON structure conforms to schema 1.0.0
    summary_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert summary_data["schema_version"] == "1.0.0"
    assert summary_data["provenance"]["provider"] == "chatgpt"
    assert summary_data["provenance"]["model_name"] == "gpt-6-luna"
    assert summary_data["provenance"]["reasoning_effort"] == "low"
    assert (
        summary_data["executive"]["core_thesis"]
        == "A realimentação assegura a estabilidade e a robustez do controle."
    )

    # Verify Markdown contains provider and model
    md_content = md_path.read_text(encoding="utf-8")
    assert 'provider: "chatgpt"' in md_content
    assert 'model: "gpt-6-luna"' in md_content
    assert 'schema_version: "1.0.0"' in md_content

    # Verify progress events
    assert any(e.get("phase") == "parsing" for e in events)
    assert any(e.get("phase") == "completed" for e in events)


def test_summarizer_failure_does_not_persist_partial_sidecar_or_fallback(tmp_path: Path) -> None:
    source_file = _sample_transcript_file(tmp_path)

    mock_chatgpt_transport = MagicMock(spec=ChatGPTTransport)
    mock_chatgpt_transport.provider_name = "chatgpt"
    mock_chatgpt_transport.model_name = "gpt-6-luna"
    mock_chatgpt_transport.provenance_metadata.return_value = {
        "provider": "chatgpt",
        "model_name": "gpt-6-luna",
    }
    mock_chatgpt_transport.generate.side_effect = ChatGPTInferenceError("Falha de quota OpenAI")

    summarizer = TranscriptSummarizer(transport=mock_chatgpt_transport)

    events: list[dict] = []
    with pytest.raises(ChatGPTInferenceError, match="Falha de quota OpenAI"):
        summarizer.summarize(source_file, progress_callback=events.append)

    # Must NOT have created sidecars
    md_sidecar = tmp_path / "aula_controle.resumo.md"
    json_sidecar = tmp_path / "aula_controle.resumo.json"
    assert not md_sidecar.exists()
    assert not json_sidecar.exists()


def test_ollama_transport_provenance(tmp_path: Path) -> None:
    config = SummaryConfig(model_name="qwen2.5:3b", ollama_url="http://127.0.0.1:11434")
    transport = OllamaTransport(config)

    assert transport.provider_name == "ollama"
    assert transport.model_name == "qwen2.5:3b"
    prov = transport.provenance_metadata()
    assert prov["provider"] == "ollama"
    assert prov["model_name"] == "qwen2.5:3b"
    assert prov["ollama_url"] == "http://127.0.0.1:11434"
