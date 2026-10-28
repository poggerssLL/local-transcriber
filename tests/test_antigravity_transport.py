"""Unit and integration tests for Antigravity transport and CLI execution."""

from __future__ import annotations

import io
import json
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from local_transcriber.antigravity_client import (
    DEFAULT_ANTIGRAVITY_MODEL,
    AntigravityTransport,
    find_antigravity_cli,
)
from local_transcriber.api import create_app
from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.exceptions import (
    AntigravityInferenceError,
    AntigravityUnavailableError,
)
from local_transcriber.models import (
    JobPhase,
    JobStatus,
    Segment,
    Transcript,
    TranscriptionJob,
    Word,
)
from local_transcriber.summarizer import SummaryConfig, TranscriptSummarizer


def test_find_antigravity_cli_via_which() -> None:
    with patch("shutil.which", return_value="C:\\fake\\agy.exe"):
        assert find_antigravity_cli() == "C:\\fake\\agy.exe"


def test_find_antigravity_cli_via_localappdata(tmp_path: Path) -> None:
    fake_agy = tmp_path / "agy" / "bin" / "agy.exe"
    fake_agy.parent.mkdir(parents=True)
    fake_agy.write_text("binary", encoding="utf-8")

    with patch("shutil.which", return_value=None):
        with patch.dict("os.environ", {"LOCALAPPDATA": str(tmp_path)}):
            assert find_antigravity_cli() == str(fake_agy)


def test_find_antigravity_cli_not_found() -> None:
    with patch("shutil.which", return_value=None):
        with patch.dict("os.environ", {"LOCALAPPDATA": "C:\\nonexistent_dir_12345"}):
            assert find_antigravity_cli() is None


def test_transport_initialization_missing_cli_raises() -> None:
    with patch("local_transcriber.antigravity_client.find_antigravity_cli", return_value=None):
        with pytest.raises(AntigravityUnavailableError, match="não foi encontrado"):
            AntigravityTransport()


def test_transport_initialization_and_provenance() -> None:
    transport = AntigravityTransport(
        cli_path="C:\\mock\\agy.exe",
        model_name="gemini-3.8-flash-medium",
        timeout=120.0,
    )
    assert transport.provider_name == "antigravity"
    assert transport.model_name == "gemini-3.8-flash-medium"
    assert transport.provenance_metadata() == {
        "provider": "antigravity",
        "model_name": "gemini-3.8-flash-medium",
        "cli_path": "C:\\mock\\agy.exe",
    }


def test_generate_success_extracts_json_response() -> None:
    transport = AntigravityTransport(cli_path="C:\\mock\\agy.exe")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps({"response": "Erick, texto do resumo"})
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        result = transport.generate("resuma o texto", system_prompt="Voce e professor")
        assert result == "Erick, texto do resumo"

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "C:\\mock\\agy.exe"
        assert "--model" in cmd
        assert DEFAULT_ANTIGRAVITY_MODEL in cmd
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "[INSTRUÇÕES DO SISTEMA]" in mock_run.call_args[1]["input"]


def test_generate_failure_raises_inference_error() -> None:
    transport = AntigravityTransport(cli_path="C:\\mock\\agy.exe")

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = "Model quota exceeded"
    mock_proc.stdout = ""

    with patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(AntigravityInferenceError, match="Model quota exceeded"):
            transport.generate("teste")


def test_generate_timeout_raises_inference_error() -> None:
    transport = AntigravityTransport(cli_path="C:\\mock\\agy.exe")

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["agy"], timeout=10.0),
    ):
        with pytest.raises(AntigravityInferenceError, match="Tempo limite excedido"):
            transport.generate("teste")


def test_summarizer_with_antigravity_transport(tmp_path: Path) -> None:
    transcript_file = tmp_path / "aula.json"
    transcript_payload = {
        "recording_id": "rec-1",
        "language": "pt",
        "duration_seconds": 120.0,
        "segments": [
            {
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "text": "Introdução aos grafos e matriz de adjacência.",
            },
            {
                "start_seconds": 60.0,
                "end_seconds": 120.0,
                "text": "Conclusão sobre caminhamento e busca em largura.",
            },
        ],
    }
    transcript_file.write_text(json.dumps(transcript_payload), encoding="utf-8")

    map_payload = {
        "chunk_summary": "Conceitos de grafos e matrizes.",
        "timeline": [
            {
                "timestamp": "00:00:00",
                "seconds": 0.0,
                "topic": "Grafos",
                "summary": "Introdução aos grafos.",
            }
        ],
        "glossary": [
            {
                "term": "Grafo",
                "definition": "Conjunto de vértices e arestas.",
                "first_timestamp": "00:00:00",
            }
        ],
        "flashcards": [
            {
                "question": "O que é um grafo?",
                "answer": "Vértices e arestas.",
                "timestamp": "00:00:00",
            }
        ],
    }

    reduce_payload = {
        "core_thesis": "Grafos e buscas em largura e profundidade.",
        "paragraphs": ["Parágrafo explicativo da aula sobre grafos."],
        "spoken_summary": "Roteiro falado pedagógico de estudo sobre grafos.",
    }

    transport = AntigravityTransport(cli_path="C:\\mock\\agy.exe")

    proc_map = MagicMock()
    proc_map.returncode = 0
    proc_map.stdout = json.dumps(
        {
            "response": f"Erick,\n\n```json\n{json.dumps(map_payload)}\n```\n",
        }
    )
    proc_map.stderr = ""

    proc_reduce = MagicMock()
    proc_reduce.returncode = 0
    proc_reduce.stdout = json.dumps(
        {
            "response": f"Erick,\n\n```json\n{json.dumps(reduce_payload)}\n```\n",
        }
    )
    proc_reduce.stderr = ""

    with patch("subprocess.run", side_effect=[proc_map, proc_reduce]):
        summarizer = TranscriptSummarizer(
            config=SummaryConfig(model_name="gemini-3.8-flash-low"),
            transport=transport,
        )
        md_path = summarizer.summarize(transcript_file, output_dir=tmp_path)
        assert md_path.is_file()

        json_path = tmp_path / "aula.resumo.json"
        assert json_path.is_file()

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["provenance"]["provider"] == "antigravity"
        assert data["provenance"]["model_name"] == "gemini-3.8-flash-low"
        assert data["executive"]["core_thesis"] == "Grafos e buscas em largura e profundidade."


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


def test_api_antigravity_status(client: TestClient) -> None:
    with patch("local_transcriber.api.find_antigravity_cli", return_value="C:\\fake\\agy.exe"):
        res = client.get("/api/auth/antigravity/status")
        assert res.status_code == 200
        data = res.json()
        assert data["available"] is True
        assert data["cli_path"] == "C:\\fake\\agy.exe"
        assert data["default_model"] == "gemini-3.8-flash-low"
        assert "gemini-3.8-flash-low" in data["models"]


def test_api_summary_with_antigravity_success(app, client: TestClient) -> None:
    sub_res = client.post("/api/subjects", json={"name": "Computação"})
    assert sub_res.status_code == 201
    subject_id = sub_res.json()["id"]

    rec_res = client.post(
        "/api/recordings",
        data={
            "title": "Aula Grafos",
            "subject_id": subject_id,
            "lesson_date": "2026-10-24",
        },
        files={"file": ("grafos.wav", _wav_bytes(), "audio/wav")},
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
            text="00:00:10 Introdução a grafos e conectividade.",
            segments=(
                Segment(
                    ordinal=0,
                    start_seconds=10.0,
                    end_seconds=20.0,
                    text="Introdução a grafos e conectividade.",
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

    map_resp = json.dumps(
        {
            "chunk_summary": "Introdução a grafos e conectividade.",
            "timeline": [
                {
                    "timestamp": "00:00:10",
                    "seconds": 10.0,
                    "topic": "Grafos",
                    "summary": "Conceitos básicos.",
                }
            ],
            "glossary": [
                {
                    "term": "Vértice",
                    "definition": "Nó do grafo.",
                    "first_timestamp": "00:00:10",
                }
            ],
            "flashcards": [
                {
                    "question": "O que é um vértice?",
                    "answer": "Um elemento do grafo.",
                    "timestamp": "00:00:10",
                }
            ],
        }
    )

    reduce_resp = json.dumps(
        {
            "core_thesis": "Grafos modelam redes e conexões.",
            "paragraphs": ["A aula apresentou conceitos fundamentais de grafos."],
            "spoken_summary": "Hoje estudamos a teoria dos grafos.",
        }
    )

    with (
        patch("local_transcriber.api.find_antigravity_cli", return_value="C:\\mock\\agy.exe"),
        patch(
            "local_transcriber.antigravity_client.AntigravityTransport.generate",
            side_effect=[map_resp, reduce_resp],
        ),
    ):
        res = client.post(
            f"/api/transcripts/{transcript.id}/summary",
            json={"provider": "antigravity"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["schema_version"] == "1.0.0"
        assert data["provenance"]["provider"] == "antigravity"
        assert data["provenance"]["model_name"] == "gemini-3.8-flash-low"
        assert data["executive"]["core_thesis"] == "Grafos modelam redes e conexões."
