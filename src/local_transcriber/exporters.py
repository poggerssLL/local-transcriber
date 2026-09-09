"""Deterministic transcript renderers and managed export persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .config import RuntimePaths
from .models import ExportedArtifact, Segment, Transcript
from .repository import Repository


class ExportFormat(StrEnum):
    TXT = "txt"
    MARKDOWN = "md"
    SRT = "srt"
    WEBVTT = "vtt"
    JSON = "json"


_MEDIA_TYPES = {
    ExportFormat.TXT: "text/plain; charset=utf-8",
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportFormat.SRT: "application/x-subrip; charset=utf-8",
    ExportFormat.WEBVTT: "text/vtt; charset=utf-8",
    ExportFormat.JSON: "application/json; charset=utf-8",
}


def render_transcript(transcript: Transcript, export_format: ExportFormat | str) -> bytes:
    """Render a transcript to stable UTF-8 bytes without filesystem information."""
    export_format = ExportFormat(export_format)
    renderers = {
        ExportFormat.TXT: _render_txt,
        ExportFormat.MARKDOWN: _render_markdown,
        ExportFormat.SRT: _render_srt,
        ExportFormat.WEBVTT: _render_webvtt,
        ExportFormat.JSON: _render_json,
    }
    return renderers[export_format](transcript).encode("utf-8")


def _ordered_segments(transcript: Transcript) -> list[Segment]:
    return sorted(transcript.segments, key=lambda segment: (segment.ordinal, segment.id))


def _clean_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _render_txt(transcript: Transcript) -> str:
    return f"{_clean_text(transcript.text)}\n"


def _markdown_escape(value: str) -> str:
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    escaped = escaped.replace("\\", "\\\\")
    return re.sub(r"([`*_[\]{}()#+.!|>~-])", r"\\\1", escaped)


def _render_markdown(transcript: Transcript) -> str:
    language = _markdown_escape(transcript.language or "não informado")
    lines = ["# Transcrição", "", f"**Idioma:** {language}", "", "## Texto", ""]
    lines.extend(_markdown_escape(line) for line in _clean_text(transcript.text).split("\n"))
    if transcript.segments:
        lines.extend(["", "## Segmentos", ""])
        for segment in _ordered_segments(transcript):
            timestamp = _format_timestamp(segment.start_seconds, decimal_separator=".")
            lines.append(f"- `{timestamp}` {_markdown_escape(_clean_text(segment.text))}")
    return "\n".join(lines) + "\n"


def _milliseconds(seconds: float) -> int:
    return int((Decimal(str(seconds)) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _format_timestamp(seconds: float, *, decimal_separator: str) -> str:
    total_milliseconds = _milliseconds(seconds)
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    total_minutes, second = divmod(total_seconds, 60)
    hour, minute = divmod(total_minutes, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}{decimal_separator}{milliseconds:03d}"


def _render_srt(transcript: Transcript) -> str:
    cues = []
    for number, segment in enumerate(_ordered_segments(transcript), start=1):
        start = _format_timestamp(segment.start_seconds, decimal_separator=",")
        end = _format_timestamp(segment.end_seconds, decimal_separator=",")
        cues.append(f"{number}\n{start} --> {end}\n{_clean_text(segment.text)}")
    return "\n\n".join(cues) + ("\n" if cues else "")


def _webvtt_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_webvtt(transcript: Transcript) -> str:
    cues = []
    for segment in _ordered_segments(transcript):
        start = _format_timestamp(segment.start_seconds, decimal_separator=".")
        end = _format_timestamp(segment.end_seconds, decimal_separator=".")
        cues.append(f"{start} --> {end}\n{_webvtt_escape(_clean_text(segment.text))}")
    body = "\n\n".join(cues)
    return f"WEBVTT\n\n{body}\n" if body else "WEBVTT\n"


def _render_json(transcript: Transcript) -> str:
    metrics = None
    if transcript.metrics is not None:
        metrics = asdict(transcript.metrics)
        metrics["realtime_factor"] = transcript.metrics.realtime_factor
    payload = {
        "schema_version": 1,
        "transcript": {
            "id": transcript.id,
            "recording_id": transcript.recording_id,
            "job_id": transcript.job_id,
            "language": transcript.language,
            "language_probability": transcript.language_probability,
            "text": transcript.text,
            "settings": asdict(transcript.settings),
            "metrics": metrics,
            "segments": [
                {
                    "id": segment.id,
                    "ordinal": segment.ordinal,
                    "start_seconds": segment.start_seconds,
                    "end_seconds": segment.end_seconds,
                    "text": segment.text,
                    "words": [asdict(word) for word in segment.words],
                }
                for segment in _ordered_segments(transcript)
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class TranscriptExporter:
    """Write rendered transcripts below the managed exports directory."""

    def __init__(self, repository: Repository, paths: RuntimePaths) -> None:
        self.repository = repository
        self.paths = paths

    def export(self, transcript: Transcript, export_format: ExportFormat | str) -> ExportedArtifact:
        export_format = ExportFormat(export_format)
        content = render_transcript(transcript, export_format)
        relative_path = PurePosixPath(
            "exports", transcript.id, f"transcript.{export_format.value}"
        ).as_posix()
        destination = self.paths.resolve_relative(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4()}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, destination)
            artifact = ExportedArtifact(
                transcript_id=transcript.id,
                kind=export_format.value,
                relative_path=relative_path,
                media_type=_MEDIA_TYPES[export_format],
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
            try:
                return self.repository.add_artifact(artifact)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
        finally:
            temporary.unlink(missing_ok=True)

    def exported_path(self, artifact: ExportedArtifact) -> Path:
        return self.paths.resolve_relative(artifact.relative_path)
