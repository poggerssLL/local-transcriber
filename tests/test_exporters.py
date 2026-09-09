import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from local_transcriber import (
    Database,
    ExportFormat,
    Recording,
    Repository,
    RuntimePaths,
    Segment,
    Subject,
    Transcript,
    TranscriptExporter,
    TranscriptionJob,
    TranscriptionMetrics,
    TranscriptionSettings,
    Word,
    render_transcript,
)


@pytest.fixture
def transcript() -> Transcript:
    return Transcript(
        id="transcript-fixed",
        recording_id="recording-fixed",
        job_id="job-fixed",
        language="pt",
        text="Olá, português!\r\nMarkdown: *forte* & <tag>.",
        settings=TranscriptionSettings(model_name="small", language="pt", beam_size=3),
        metrics=TranscriptionMetrics(
            audio_duration_seconds=3662,
            processing_duration_seconds=1831,
            segment_count=2,
            word_count=2,
        ),
        segments=(
            Segment(
                id="segment-1",
                ordinal=1,
                start_seconds=3661.9996,
                end_seconds=3662.5,
                text="Fim & <crédito>",
                words=(Word(id="word-1", text="Fim", start_seconds=3662, end_seconds=3662.2),),
            ),
            Segment(
                id="segment-0",
                ordinal=0,
                start_seconds=0.001,
                end_seconds=1.2345,
                text="Olá, *mundo*!",
                words=(Word(id="word-0", text="Olá", start_seconds=0.001, end_seconds=0.4),),
            ),
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize("export_format", list(ExportFormat))
def test_all_exporters_are_deterministic_utf8(
    transcript: Transcript, export_format: ExportFormat
) -> None:
    first = render_transcript(transcript, export_format)
    second = render_transcript(transcript, export_format)
    assert first == second
    assert "Olá" in first.decode("utf-8")
    assert b"C:\\" not in first


def test_srt_timestamps_and_order(transcript: Transcript) -> None:
    rendered = render_transcript(transcript, ExportFormat.SRT).decode()
    assert rendered.startswith("1\n00:00:00,001 --> 00:00:01,235\nOlá")
    assert "2\n01:01:02,000 --> 01:01:02,500\nFim" in rendered


def test_webvtt_and_markdown_escape_content(transcript: Transcript) -> None:
    webvtt = render_transcript(transcript, ExportFormat.WEBVTT).decode()
    markdown = render_transcript(transcript, ExportFormat.MARKDOWN).decode()
    assert webvtt.startswith("WEBVTT\n\n")
    assert "Fim &amp; &lt;crédito&gt;" in webvtt
    assert "\\*forte\\* &amp; &lt;tag&gt;\\." in markdown
    assert "Olá, \\*mundo\\*\\!" in markdown


def test_json_is_structured_ordered_and_has_no_paths(transcript: Transcript) -> None:
    rendered = render_transcript(transcript, ExportFormat.JSON).decode()
    payload = json.loads(rendered)
    result = payload["transcript"]
    assert [segment["ordinal"] for segment in result["segments"]] == [0, 1]
    assert result["settings"]["language"] == "pt"
    assert result["metrics"]["realtime_factor"] == 0.5
    assert "relative_path" not in rendered
    assert ":\\" not in rendered


def test_export_writes_relative_artifact_and_metadata(
    tmp_path: Path, transcript: Transcript
) -> None:
    paths = RuntimePaths((tmp_path / "runtime").resolve())
    database = Database(paths.database)
    database.initialize()
    repository = Repository(database)
    subject = repository.add_subject(Subject(name="Português"))
    recording = repository.add_recording(
        Recording(
            id=transcript.recording_id,
            title="Aula",
            subject_id=subject.id,
            lesson_date=datetime(2026, 1, 1).date(),
            original_name="aula.wav",
            sha256="c" * 64,
            size_bytes=10,
            media_format="wav",
            relative_path="media/aula.wav",
        )
    )
    repository.add_job(
        TranscriptionJob(
            id=transcript.job_id,
            recording_id=recording.id,
            engine="test",
            model_name="artificial",
        )
    )
    repository.add_transcript(transcript)

    artifact = TranscriptExporter(repository, paths).export(transcript, ExportFormat.JSON)
    exported = paths.resolve_relative(artifact.relative_path)
    assert exported.read_bytes() == render_transcript(transcript, ExportFormat.JSON)
    assert not Path(artifact.relative_path).is_absolute()
    assert artifact.size_bytes == exported.stat().st_size
    assert len(artifact.sha256) == 64
    assert repository.get_transcript(transcript.id) == transcript
