"""Comprehensive validation tests for summarizer.py implementation."""

import json
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_transcriber.summarizer import (
    ExecutiveSummary,
    FlashcardEntry,
    GlossaryEntry,
    OllamaUnavailableError,
    ParsedSegment,
    SummaryConfig,
    TimelineEntry,
    TranscriptSummarizer,
    TranscriptSummary,
    format_timestamp_clock,
    main,
    parse_timestamp_seconds,
)


def test_models_instantiation() -> None:
    config = SummaryConfig()
    assert config.ollama_url == "http://127.0.0.1:11434"
    assert config.model_name == "qwen2.5:3b"
    assert config.chunk_duration_minutes == 20
    assert config.timeout == 120

    tl = TimelineEntry(
        timestamp="00:15:30",
        seconds=930.0,
        topic="Introdução aos Sensores",
        summary="Conceitos de instrumentação",
        slide_ref="Slide 4",
    )
    assert tl.timestamp == "00:15:30"
    assert tl.seconds == 930.0

    glossary = GlossaryEntry(
        term="Transdutor",
        definition="Dispositivo que converte grandeza física em sinal elétrico",
        first_timestamp="00:02:15",
    )
    assert glossary.term == "Transdutor"

    card = FlashcardEntry(
        id="card-01",
        question="O que é um transdutor piezoelétrico?",
        answer="Gera tensão elétrica sob tensão mecânica",
        timestamp="00:18:40",
    )
    assert card.id == "card-01"

    exec_summary = ExecutiveSummary(
        paragraphs=["Parágrafo 1 de teste", "Parágrafo 2 de teste"],
        core_thesis="A instrumentação é a base do controle de processos industriais.",
    )
    assert len(exec_summary.paragraphs) == 2

    summary = TranscriptSummary(
        schema_version="1.0.0",
        provenance={"source_file": "aula01.mp3", "model": "qwen2.5:3b"},
        executive=exec_summary,
        timeline=[tl],
        glossary=[glossary],
        flashcards=[card],
        spoken_summary="Olá! Na aula de hoje aprendemos sobre instrumentação.",
    )
    assert summary.schema_version == "1.0.0"

    # Test round trip to_dict and from_dict
    data = summary.to_dict()
    restored = TranscriptSummary.from_dict(data)
    assert restored.schema_version == summary.schema_version
    assert restored.executive.core_thesis == summary.executive.core_thesis
    assert len(restored.timeline) == 1
    assert restored.timeline[0].topic == "Introdução aos Sensores"
    assert len(restored.glossary) == 1
    assert len(restored.flashcards) == 1
    assert restored.spoken_summary == summary.spoken_summary


def test_timestamp_helpers() -> None:
    assert parse_timestamp_seconds("00:00:00") == 0.0
    assert parse_timestamp_seconds("00:01:30") == 90.0
    assert parse_timestamp_seconds("01:02:03.500") == 3723.5
    assert parse_timestamp_seconds("01:02:03,500") == 3723.5
    assert parse_timestamp_seconds("15:30") == 930.0

    assert format_timestamp_clock(0.0) == "00:00:00"
    assert format_timestamp_clock(90.0) == "00:01:30"
    assert format_timestamp_clock(3723.5) == "01:02:03"


def test_parse_transcript_markdown() -> None:
    md_content = """# Transcrição da Aula
**Idioma:** pt

## Texto
Olá a todos. Vamos iniciar a modelagem.

## Segmentos
- `00:00:00.100` Olá a todos, bem-vindos.
- `00:05:30.000` Vamos falar sobre amortecedores e molas.
- `00:25:10.500` Concluímos a equação diferencial do sistema.
"""
    summarizer = TranscriptSummarizer()
    segments = summarizer.parse_transcript(md_content)
    assert len(segments) == 3
    assert segments[0].timestamp == "00:00:00"
    assert segments[0].text == "Olá a todos, bem-vindos."
    assert segments[1].timestamp == "00:05:30"
    assert segments[2].timestamp == "00:25:10"


def test_parse_transcript_bracketed_and_srt() -> None:
    text_content = """
    [00:01:10] Introdução ao tema de vibrações.
    [00:12:45] Cálculo da frequência natural.
    """
    summarizer = TranscriptSummarizer()
    segments = summarizer.parse_transcript(text_content)
    assert len(segments) == 2
    assert segments[0].timestamp == "00:01:10"
    assert segments[1].timestamp == "00:12:45"

    srt_content = """1
00:00:01,000 --> 00:00:04,000
Primeira fala do professor.

2
00:00:05,000 --> 00:00:08,000
Segunda fala explicativa.
"""
    segments_srt = summarizer.parse_transcript(srt_content)
    assert len(segments_srt) == 2
    assert segments_srt[0].timestamp == "00:00:01"
    assert segments_srt[1].timestamp == "00:00:05"


def test_parse_transcript_json() -> None:
    payload = {
        "transcript": {
            "segments": [
                {"start_seconds": 0.5, "text": "Início da aula"},
                {"start_seconds": 3600.0, "text": "Uma hora de aula"},
            ]
        }
    }
    summarizer = TranscriptSummarizer()
    segments = summarizer.parse_transcript(json.dumps(payload))
    assert len(segments) == 2
    assert segments[0].timestamp == "00:00:00"
    assert segments[1].timestamp == "01:00:00"


def test_chunk_by_time() -> None:
    summarizer = TranscriptSummarizer(SummaryConfig(chunk_duration_minutes=20))
    segments = [
        ParsedSegment(timestamp="00:00:00", seconds=0.0, text="Minuto 0"),
        ParsedSegment(timestamp="00:10:00", seconds=600.0, text="Minuto 10"),
        ParsedSegment(timestamp="00:19:59", seconds=1199.0, text="Minuto 19"),
        ParsedSegment(timestamp="00:20:01", seconds=1201.0, text="Minuto 20 (Chunk 2)"),
        ParsedSegment(timestamp="00:35:00", seconds=2100.0, text="Minuto 35 (Chunk 2)"),
        ParsedSegment(timestamp="00:45:00", seconds=2700.0, text="Minuto 45 (Chunk 3)"),
    ]
    chunks = summarizer.chunk_by_time(segments, max_minutes=20)
    assert len(chunks) == 3
    assert chunks[0].index == 0
    assert chunks[0].start_time == "00:00:00"
    assert len(chunks[0].segments) == 3

    assert chunks[1].index == 1
    assert chunks[1].start_time == "00:20:01"
    assert len(chunks[1].segments) == 2

    assert chunks[2].index == 2
    assert chunks[2].start_time == "00:45:00"
    assert len(chunks[2].segments) == 1


def test_ollama_resilience_errors() -> None:
    summarizer = TranscriptSummarizer()

    # 1. Connection error / URLError
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with pytest.raises(OllamaUnavailableError, match="Não foi possível conectar"):
            summarizer._call_ollama("prompt", "system")

    # 2. HTTP 404 Model Not Found
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_error = urllib.error.HTTPError(
            url="http://127.0.0.1:11434/api/generate",
            code=404,
            msg="Not Found",
            hdrs={},  # type: ignore[arg-type]
            fp=MagicMock(read=lambda: b'{"error":"model not found"}'),
        )
        mock_urlopen.side_effect = mock_error
        with pytest.raises(OllamaUnavailableError, match="não encontrado no Ollama"):
            summarizer._call_ollama("prompt", "system")

    # 3. TimeoutError
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = TimeoutError("Timed out")
        with pytest.raises(OllamaUnavailableError, match="Tempo limite excedido"):
            summarizer._call_ollama("prompt", "system")


def test_summarize_end_to_end_mocked() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_file = tmp_path / "aula_mecanica.transcription.md"
        source_file.write_text(
            """# Aula de Sistemas Mecânicos
## Segmentos
- `00:00:10.000` Introdução à modelagem de sistemas mecânicos vibratórios.
- `00:15:00.000` Apresentação da segunda lei de Newton aplicada a massas concentradas.
- `00:30:00.000` Dedução da equação diferencial com amortecimento viscoso.
""",
            encoding="utf-8",
        )

        # Mock Ollama map responses and reduce response
        map_response_chunk1 = json.dumps({
            "chunk_summary": "Introdução teórica às leis de Newton e modelagem.",
            "timeline": [
                {
                    "timestamp": "00:00:10",
                    "seconds": 10.0,
                    "topic": "Fundamentos de Modelagem",
                    "summary": "Conceituação de sistemas concentrados.",
                    "slide_ref": "Slide 1",
                },
                {
                    "timestamp": "00:15:00",
                    "seconds": 900.0,
                    "topic": "2ª Lei de Newton",
                    "summary": "Diagrama de corpo livre e forças atuantes.",
                    "slide_ref": "Slide 5",
                },
            ],
            "glossary": [
                {
                    "term": "Diagrama de Corpo Livre",
                    "definition": "Representação gráfica de todas as forças atuando no corpo.",
                    "first_timestamp": "00:15:00",
                }
            ],
            "flashcards": [
                {
                    "question": "Qual é o primeiro passo para modelar um sistema mecânico?",
                    "answer": "Identificar os graus de liberdade e traçar o diagrama.",
                    "timestamp": "00:15:00",
                }
            ],
        })

        map_response_chunk2 = json.dumps({
            "chunk_summary": "Dedução das equações diferenciais e amortecimento.",
            "timeline": [
                {
                    "timestamp": "00:30:00",
                    "seconds": 1800.0,
                    "topic": "Amortecimento Viscoso",
                    "summary": "Aplicação do coeficiente e obtenção da EDO.",
                    "slide_ref": "Slide 10",
                }
            ],
            "glossary": [
                {
                    "term": "Amortecedor Viscoso",
                    "definition": "Elemento que dissipa energia pela velocidade relativa.",
                    "first_timestamp": "00:30:00",
                }
            ],
            "flashcards": [
                {
                    "question": "Como se relaciona a força com a velocidade?",
                    "answer": "A força é proporcional à velocidade relativa (F = c * v).",
                    "timestamp": "00:30:00",
                }
            ],
        })

        reduce_response = json.dumps({
            "core_thesis": "A modelagem matemática rigorosa parte do isolamento de corpos.",
            "paragraphs": [
                "A aula estabeleceu os princípios fundamentais da dinâmica aplicada.",
                "Foi demonstrado passo a passo como converter interações físicas em EDOs.",
            ],
            "spoken_summary": "Olá! Nesta sessão abordamos a modelagem mecânica clássica.",
        })

        summarizer = TranscriptSummarizer(SummaryConfig(chunk_duration_minutes=20))

        call_count = 0

        def fake_call_ollama(
            prompt: str,
            system_prompt: str | None = None,
            json_format: bool = False,
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return map_response_chunk1
            elif call_count == 2:
                return map_response_chunk2
            return reduce_response

        with patch.object(summarizer, "_call_ollama", side_effect=fake_call_ollama):
            md_path = summarizer.summarize(source_file)
            assert md_path.is_file()
            assert md_path.name == "aula_mecanica.resumo.md"

            json_path = md_path.parent / "aula_mecanica.resumo.json"
            assert json_path.is_file()

            # Verify sidecar JSON
            sidecar_data = json.loads(json_path.read_text(encoding="utf-8"))
            assert sidecar_data["schema_version"] == "1.0.0"
            assert sidecar_data["provenance"]["source_file"] == "aula_mecanica.transcription.md"
            assert len(sidecar_data["timeline"]) == 3
            assert len(sidecar_data["glossary"]) == 2
            assert len(sidecar_data["flashcards"]) == 2
            assert "A modelagem matemática" in sidecar_data["executive"]["core_thesis"]

            # Verify Markdown file content
            md_content = md_path.read_text(encoding="utf-8")
            assert "---" in md_content
            assert 'schema_version: "1.0.0"' in md_content
            assert "# Resumo Estruturado: aula_mecanica.transcription.md" in md_content
            assert "> **Tese Central:**" in md_content
            assert "## Resumo Executivo" in md_content
            assert "## Roteiro Falado (Podcast / Áudio)" in md_content
            assert "## Linha do Tempo" in md_content
            assert "## Glossário de Termos Técnicos" in md_content
            assert "## Flashcards de Fixação" in md_content
            assert "Diagrama de Corpo Livre" in md_content
            assert "Amortecedor Viscoso" in md_content


def test_cli_execution() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        source = tmp_path / "sample.md"
        source.write_text("- `00:01:00.000` Teste de CLI", encoding="utf-8")

        with patch("local_transcriber.summarizer.TranscriptSummarizer.summarize") as mock_sum:
            mock_sum.return_value = tmp_path / "sample.resumo.md"
            exit_code = main([str(source)])
            assert exit_code == 0
            mock_sum.assert_called_once()

        # Test CLI error when file does not exist
        exit_code_missing = main([str(tmp_path / "nonexistent.md")])
        assert exit_code_missing == 1
