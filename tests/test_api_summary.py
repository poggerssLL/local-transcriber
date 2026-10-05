"""Deterministic unit and integration tests for transcript summarization API endpoints.

Tests the following routes in Local Transcriber:
  - GET  /api/transcripts/{transcript_id}/summary
  - POST /api/transcripts/{transcript_id}/summary
  - GET  /api/transcripts/{transcript_id}/summary/download
"""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from local_transcriber.api import create_app
from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.models import (
    JobPhase,
    JobStatus,
    Segment,
    Transcript,
    TranscriptionJob,
    Word,
)
from local_transcriber.summarizer import (
    ExecutiveSummary,
    FlashcardEntry,
    GlossaryEntry,
    OllamaUnavailableError,
    TimelineEntry,
    TranscriptSummary,
)

# ---------------------------------------------------------------------------
# Test Helpers and Fixtures
# ---------------------------------------------------------------------------


def _wav_bytes(*, frames: int = 400) -> bytes:
    """Generate minimal valid PCM WAV bytes for audio upload tests."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * frames)
    return output.getvalue()


@pytest.fixture
def app(tmp_path: Path):
    """Create test application instance with isolated temporary runtime directory."""
    config = AppConfig(RuntimePaths((tmp_path / "runtime").resolve()))
    return create_app(
        config,
        start_worker=False,
        sse_poll_interval=0.01,
        sse_heartbeat_interval=0.02,
    )


@pytest.fixture
def client(app):
    """Yield TestClient with security middleware active."""
    with TestClient(app) as current:
        yield current


def _seed_subject_and_recording(client: TestClient) -> tuple[str, str]:
    """Create a subject and upload a recording, returning (subject_id, recording_id)."""
    sub_res = client.post("/api/subjects", json={"name": "Sistemas de Controle"})
    assert sub_res.status_code == 201
    subject_id = sub_res.json()["id"]

    rec_res = client.post(
        "/api/recordings",
        data={
            "title": "Aula 01 - Modelagem",
            "subject_id": subject_id,
            "lesson_date": "2026-09-18",
        },
        files={"file": ("aula01.wav", _wav_bytes(), "audio/wav")},
    )
    assert rec_res.status_code == 201
    return subject_id, rec_res.json()["id"]


def _seed_transcript(app, recording_id: str) -> Transcript:
    """Insert a succeeded transcription job and associated transcript directly into repository."""
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
    return repository.add_transcript(
        Transcript(
            recording_id=recording_id,
            job_id=job.id,
            language="pt",
            text=(
                "Na aula de hoje iniciamos a modelagem de sistemas dinâmicos. "
                "Discutimos amortecedores e molas."
            ),
            segments=(
                Segment(
                    ordinal=0,
                    start_seconds=0.0,
                    end_seconds=15.0,
                    text="Na aula de hoje iniciamos a modelagem de sistemas dinâmicos.",
                    words=(Word(text="modelagem", start_seconds=5.0, end_seconds=6.0),),
                ),
                Segment(
                    ordinal=1,
                    start_seconds=15.0,
                    end_seconds=30.0,
                    text="Discutimos amortecedores e molas.",
                    words=(Word(text="amortecedores", start_seconds=16.0, end_seconds=18.0),),
                ),
            ),
        )
    )


def _make_dummy_summary_dict(transcript_id: str) -> dict:
    """Build a complete valid summary dictionary conforming to TranscriptSummary schema."""
    summary = TranscriptSummary(
        schema_version="1.0.0",
        provenance={
            "source_file": "transcript.md",
            "transcript_id": transcript_id,
            "model_name": "qwen2.5:3b",
        },
        executive=ExecutiveSummary(
            paragraphs=[
                "Esta aula abordou os princípios de modelagem física e representação por EDO."
            ],
            core_thesis=(
                "Sistemas dinâmicos lineares podem ser decompostos em elementos de inércia."
            ),
        ),
        timeline=[
            TimelineEntry(
                timestamp="00:00:00",
                seconds=0.0,
                topic="Introdução à Modelagem",
                summary="Apresentação do escopo do curso.",
                slide_ref="Slide 1",
            ),
            TimelineEntry(
                timestamp="00:00:15",
                seconds=15.0,
                topic="Elementos Mecânicos",
                summary="Comportamento de amortecedores e molas.",
                slide_ref="Slide 2",
            ),
        ],
        glossary=[
            GlossaryEntry(
                term="Amortecedor Viscoso",
                definition="Dispositivo mecânico que dissipa energia cinética em calor.",
                first_timestamp="00:00:15",
            )
        ],
        flashcards=[
            FlashcardEntry(
                id="card-01",
                question="O que representa o coeficiente de amortecimento viscoso?",
                answer="Constante de proporcionalidade entre força dissipativa e velocidade.",
                timestamp="00:00:15",
            )
        ],
        spoken_summary="Olá! Discutimos as bases para modelar amortecedores e molas.",
    )
    return summary.to_dict()


# ---------------------------------------------------------------------------
# Test Cases: GET /api/transcripts/{transcript_id}/summary
# ---------------------------------------------------------------------------


def test_get_summary_not_found_returns_404(client: TestClient) -> None:
    """GET summary for nonexistent transcript or unsummarized transcript must return 404."""
    # Case A: Transcript does not exist
    res_missing = client.get("/api/transcripts/nonexistent-transcript-id/summary")
    assert res_missing.status_code == 404
    assert res_missing.json()["detail"] == "resumo não encontrado"

    # Case B: Transcript exists, but summary sidecar does not exist yet
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    res_unsummarized = client.get(f"/api/transcripts/{transcript.id}/summary")
    assert res_unsummarized.status_code == 404
    assert res_unsummarized.json()["detail"] == "resumo não encontrado"


def test_get_summary_existing_sidecar_returns_200(client: TestClient) -> None:
    """GET summary when .resumo.json exists returns structured 200 payload matching schema."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    # Seed the sidecar JSON file into exports/{transcript_id}/transcript.resumo.json
    paths: RuntimePaths = client.app.state.config.paths
    export_dir = paths.exports / transcript.id
    export_dir.mkdir(parents=True, exist_ok=True)
    json_path = export_dir / "transcript.resumo.json"

    dummy_data = _make_dummy_summary_dict(transcript.id)
    json_path.write_text(json.dumps(dummy_data, ensure_ascii=False), encoding="utf-8")

    response = client.get(f"/api/transcripts/{transcript.id}/summary")
    assert response.status_code == 200
    payload = response.json()

    assert payload["schema_version"] == "1.0.0"
    assert payload["executive"]["core_thesis"] == dummy_data["executive"]["core_thesis"]
    assert len(payload["timeline"]) == 2
    assert payload["timeline"][0]["topic"] == "Introdução à Modelagem"
    assert len(payload["glossary"]) == 1
    assert payload["glossary"][0]["term"] == "Amortecedor Viscoso"
    assert len(payload["flashcards"]) == 1
    assert payload["flashcards"][0]["id"] == "card-01"
    assert payload["spoken_summary"] == dummy_data["spoken_summary"]


# ---------------------------------------------------------------------------
# Test Cases: POST /api/transcripts/{transcript_id}/summary
# ---------------------------------------------------------------------------


def test_post_summary_missing_transcript_returns_404(client: TestClient) -> None:
    """POST summary for nonexistent transcript must return HTTP 404."""
    response = client.post("/api/transcripts/nonexistent-id/summary")
    assert response.status_code == 404
    assert "transcript not found" in response.json()["detail"]


def test_post_summary_auto_exports_markdown_and_generates_summary(client: TestClient) -> None:
    """POST summary auto-exports transcript to markdown, invokes summarizer, and returns 200."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    # Verify no markdown export exists prior to summary call
    paths: RuntimePaths = client.app.state.config.paths
    export_dir = paths.exports / transcript.id
    md_export_path = export_dir / "transcript.md"
    assert not md_export_path.exists()

    # Mock Ollama map and reduce responses
    map_response = json.dumps(
        {
            "chunk_summary": "Introdução à dinâmica veicular e modelagem.",
            "timeline": [
                {
                    "timestamp": "00:00:00",
                    "seconds": 0.0,
                    "topic": "Abertura",
                    "summary": "Boas vindas aos alunos.",
                    "slide_ref": "Slide 1",
                }
            ],
            "glossary": [
                {
                    "term": "Dinâmica",
                    "definition": "Estudo das forças e seus efeitos sobre os corpos.",
                    "first_timestamp": "00:00:00",
                }
            ],
            "flashcards": [
                {
                    "question": "O que é dinâmica?",
                    "answer": "Ramo da mecânica clássica focado no movimento e suas causas.",
                    "timestamp": "00:00:00",
                }
            ],
        }
    )

    reduce_response = json.dumps(
        {
            "core_thesis": "A modelagem matemática viabiliza o controle preditivo.",
            "paragraphs": ["A aula estabeleceu os princípios mecânicos."],
            "spoken_summary": "Resumo falado da aula sobre modelagem mecânica.",
        }
    )

    call_index = 0

    def fake_call_ollama(
        self, prompt: str, system_prompt: str | None = None, json_format: bool = False
    ) -> str:
        nonlocal call_index
        call_index += 1
        return map_response if call_index == 1 else reduce_response

    with patch("local_transcriber.summarizer.TranscriptSummarizer._call_ollama", fake_call_ollama):
        response = client.post(f"/api/transcripts/{transcript.id}/summary")

    assert response.status_code == 200
    payload = response.json()

    # Verify response schema
    assert payload["schema_version"] == "1.0.0"
    assert payload["executive"]["core_thesis"] == (
        "A modelagem matemática viabiliza o controle preditivo."
    )
    assert len(payload["timeline"]) == 1
    assert payload["timeline"][0]["topic"] == "Abertura"
    assert len(payload["glossary"]) == 1
    assert payload["glossary"][0]["term"] == "Dinâmica"
    assert len(payload["flashcards"]) == 1
    assert payload["spoken_summary"] == "Resumo falado da aula sobre modelagem mecânica."

    # Verify physical files created on disk
    assert md_export_path.is_file(), "Transcript markdown file must be auto-exported"
    resumo_md_path = export_dir / "transcript.resumo.md"
    resumo_json_path = export_dir / "transcript.resumo.json"
    assert resumo_md_path.is_file(), "Markdown summary (.resumo.md) must be created"
    assert resumo_json_path.is_file(), "JSON summary sidecar (.resumo.json) must be created"

    # Verify subsequent GET returns the generated summary
    get_res = client.get(f"/api/transcripts/{transcript.id}/summary")
    assert get_res.status_code == 200
    assert get_res.json()["executive"]["core_thesis"] == payload["executive"]["core_thesis"]


def test_post_summary_ollama_offline_returns_503(client: TestClient) -> None:
    """When Ollama is unreachable, POST summary must return HTTP 503 with safe message."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    offline_error = OllamaUnavailableError(
        "Serviço Ollama indisponível: Não foi possível conectar ao serviço Ollama."
    )

    with patch(
        "local_transcriber.summarizer.TranscriptSummarizer.summarize",
        side_effect=offline_error,
    ):
        response = client.post(f"/api/transcripts/{transcript.id}/summary")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "serviço ollama indisponível" in detail.lower()
    assert "não foi possível conectar" in detail.lower()
    # Ensure no absolute filesystem paths are leaked
    root_str = str(client.app.state.config.paths.root)
    assert root_str not in detail


# ---------------------------------------------------------------------------
# Test Cases: GET /api/transcripts/{transcript_id}/summary/download
# ---------------------------------------------------------------------------


def test_download_summary_not_found_returns_404(client: TestClient) -> None:
    """Download must return 404 when summary has not been generated."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    response = client.get(f"/api/transcripts/{transcript.id}/summary/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "resumo não encontrado"


def test_download_summary_markdown_default(client: TestClient) -> None:
    """Download default format ('md') returns FileResponse with attachment header."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    # Seed files
    paths: RuntimePaths = client.app.state.config.paths
    export_dir = paths.exports / transcript.id
    export_dir.mkdir(parents=True, exist_ok=True)
    md_file = export_dir / "transcript.resumo.md"
    md_file.write_text("# Resumo Estruturado\nConteúdo de teste.", encoding="utf-8")

    response = client.get(f"/api/transcripts/{transcript.id}/summary/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert f"transcript_{transcript.id}.resumo.md" in disposition
    assert "Conteúdo de teste." in response.text


def test_download_summary_json(client: TestClient) -> None:
    """Download with format=json returns FileResponse with application/json."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    # Seed sidecar JSON
    paths: RuntimePaths = client.app.state.config.paths
    export_dir = paths.exports / transcript.id
    export_dir.mkdir(parents=True, exist_ok=True)
    json_file = export_dir / "transcript.resumo.json"
    dummy_data = _make_dummy_summary_dict(transcript.id)
    json_file.write_text(json.dumps(dummy_data), encoding="utf-8")

    response = client.get(f"/api/transcripts/{transcript.id}/summary/download?format=json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert f"transcript_{transcript.id}.resumo.json" in disposition

    downloaded = response.json()
    assert downloaded["schema_version"] == "1.0.0"
    assert downloaded["executive"]["core_thesis"] == dummy_data["executive"]["core_thesis"]


def test_download_summary_invalid_format_returns_422(client: TestClient) -> None:
    """Download with unsupported format parameter must return HTTP 422."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    response = client.get(f"/api/transcripts/{transcript.id}/summary/download?format=pdf")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test Cases: Security and Isolation
# ---------------------------------------------------------------------------


def test_summary_endpoints_enforce_security_and_no_path_leak(client: TestClient) -> None:
    """Verify security headers are attached and untrusted host requests are blocked."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    # 1. Untrusted host header is refused
    untrusted = client.get(
        f"/api/transcripts/{transcript.id}/summary",
        headers={"Host": "malicious.internal"},
    )
    assert untrusted.status_code == 400

    # 2. Security headers are always attached
    trusted = client.get(f"/api/transcripts/{transcript.id}/summary")
    assert trusted.headers["x-content-type-options"] == "nosniff"
    assert trusted.headers["x-frame-options"] == "DENY"
    assert trusted.headers["cache-control"] == "no-store"
    assert trusted.headers["referrer-policy"] == "no-referrer"


# ---------------------------------------------------------------------------
# Test Cases: Real-Time SSE Streaming and Progress Polling
# ---------------------------------------------------------------------------


def test_get_summary_progress_route(client: TestClient) -> None:
    """GET /api/transcripts/{id}/summary/progress returns 404
    for nonexistent or idle/completed state.
    """
    # 1. Nonexistent transcript -> 404
    res_404 = client.get("/api/transcripts/nonexistent-id/summary/progress")
    assert res_404.status_code == 404

    # 2. Existing transcript without summary -> idle
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    res_idle = client.get(f"/api/transcripts/{transcript.id}/summary/progress")
    assert res_idle.status_code == 200
    idle_data = res_idle.json()
    assert idle_data["phase"] == "idle"
    assert idle_data["progress_percent"] == 0

    # 3. Existing transcript with summary sidecar on disk -> completed
    paths: RuntimePaths = client.app.state.config.paths
    export_dir = paths.exports / transcript.id
    export_dir.mkdir(parents=True, exist_ok=True)
    json_path = export_dir / "transcript.resumo.json"
    dummy_data = _make_dummy_summary_dict(transcript.id)
    json_path.write_text(json.dumps(dummy_data, ensure_ascii=False), encoding="utf-8")

    res_completed = client.get(f"/api/transcripts/{transcript.id}/summary/progress")
    assert res_completed.status_code == 200
    comp_data = res_completed.json()
    assert comp_data["phase"] == "completed"
    assert comp_data["progress_percent"] == 100


def test_post_summary_streaming_sse_emits_progress_and_complete(client: TestClient) -> None:
    """POST /api/transcripts/{id}/summary?stream=true streams SSE events
    including progress and complete.
    """
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    def mock_summarize(source_path, output_dir=None, progress_callback=None):
        out = Path(output_dir) if output_dir else Path(source_path).parent
        if progress_callback:
            progress_callback(
                {"phase": "parsing", "progress_percent": 5, "message": "Iniciando..."}
            )
            progress_callback(
                {
                    "phase": "map",
                    "progress_percent": 45,
                    "chunk_current": 1,
                    "chunk_total": 2,
                    "message": "Bloco 1...",
                }
            )
            progress_callback({"phase": "completed", "progress_percent": 100, "message": "Fim!"})

        stem = Path(source_path).stem
        if stem.endswith(".transcription"):
            stem = stem[:-14]
        json_file = out / f"{stem}.resumo.json"
        md_file = out / f"{stem}.resumo.md"
        data = _make_dummy_summary_dict(transcript.id)
        json_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        md_file.write_text("# Resumo", encoding="utf-8")
        return md_file

    with patch("local_transcriber.api.TranscriptSummarizer.summarize", side_effect=mock_summarize):
        response = client.post(f"/api/transcripts/{transcript.id}/summary?stream=true")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.content.decode("utf-8")

    assert "event: progress\n" in body
    assert "event: complete\n" in body
    assert "retry: 2000\n" in body
    assert '"phase":"parsing"' in body or '"phase": "parsing"' in body
    assert '"phase":"completed"' in body or '"phase": "completed"' in body
    assert "schema_version" in body  # ASCII key always present in the complete payload


def test_post_summary_streaming_via_accept_header(client: TestClient) -> None:
    """POST with Accept: text/event-stream initiates streaming response."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    def mock_summarize(source_path, output_dir=None, progress_callback=None):
        out = Path(output_dir) if output_dir else Path(source_path).parent
        if progress_callback:
            progress_callback({"phase": "parsing", "progress_percent": 5, "message": "Parsing..."})
        stem = Path(source_path).stem
        if stem.endswith(".transcription"):
            stem = stem[:-14]
        json_file = out / f"{stem}.resumo.json"
        md_file = out / f"{stem}.resumo.md"
        data = _make_dummy_summary_dict(transcript.id)
        json_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        md_file.write_text("# Resumo", encoding="utf-8")
        return md_file

    with patch("local_transcriber.api.TranscriptSummarizer.summarize", side_effect=mock_summarize):
        response = client.post(
            f"/api/transcripts/{transcript.id}/summary",
            headers={"Accept": "text/event-stream"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: complete\n" in response.text


def test_post_summary_stream_false_overrides_accept_header(client: TestClient) -> None:
    """Explicit stream=false query param returns JSON
    even if Accept header contains text/event-stream.
    """
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    def mock_summarize(source_path, output_dir=None, progress_callback=None):
        out = Path(output_dir) if output_dir else Path(source_path).parent
        stem = Path(source_path).stem
        if stem.endswith(".transcription"):
            stem = stem[:-14]
        json_file = out / f"{stem}.resumo.json"
        md_file = out / f"{stem}.resumo.md"
        data = _make_dummy_summary_dict(transcript.id)
        json_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        md_file.write_text("# Resumo", encoding="utf-8")
        return md_file

    with patch("local_transcriber.api.TranscriptSummarizer.summarize", side_effect=mock_summarize):
        response = client.post(
            f"/api/transcripts/{transcript.id}/summary?stream=false",
            headers={"Accept": "text/event-stream"},
        )

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    assert response.json()["schema_version"] == "1.0.0"


def test_post_summary_streaming_error_emits_error_event(client: TestClient) -> None:
    """Streaming failure yields event: error with sanitized message."""
    _, recording_id = _seed_subject_and_recording(client)
    transcript = _seed_transcript(client.app, recording_id)

    with patch(
        "local_transcriber.api.TranscriptSummarizer.summarize",
        side_effect=OllamaUnavailableError("Ollama service unavailable at 127.0.0.1:11434"),
    ):
        response = client.post(f"/api/transcripts/{transcript.id}/summary?stream=true")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "event: error\n" in body
    assert "Ollama service unavailable" in body
