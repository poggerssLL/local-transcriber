"""Structured summary generation for local transcripts via local Ollama LLM.

Implements temporal Map-Reduce chunking, robust transcript parsing,
typed dataclass domain models, sidecar JSON export, and rich Markdown rendering.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Regular expressions for matching transcript timestamps
_TIMESTAMP_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?"
    r"(?:\[|`|\()?(\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?)(?:\]|`|\))?"
    r"(?:\s*-->\s*(?:\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?))?"
    r"[:\s-]*(.*)$"
)

_INLINE_TIMESTAMP_RE = re.compile(
    r"(?:\[|`|\()(\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?)(?:\]|`|\))"
)


class OllamaUnavailableError(RuntimeError):
    """Raised when the Ollama service is unavailable, unreachable, or returns an error."""


@dataclass(frozen=True, slots=True)
class SummaryConfig:
    """Configuration for transcript summarization pipeline."""

    ollama_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen2.5:3b"
    chunk_duration_minutes: int = 20
    timeout: int = 120
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if not self.ollama_url.strip():
            raise ValueError("ollama_url cannot be empty")
        if not self.model_name.strip():
            raise ValueError("model_name cannot be empty")
        if self.chunk_duration_minutes <= 0:
            raise ValueError("chunk_duration_minutes must be positive")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """A chronological topic entry in the transcript timeline."""

    timestamp: str
    seconds: float
    topic: str
    summary: str
    slide_ref: str | None = None


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    """A technical or key term definition extracted from the transcript."""

    term: str
    definition: str
    first_timestamp: str


@dataclass(frozen=True, slots=True)
class FlashcardEntry:
    """A question-and-answer study card for knowledge retention."""

    id: str
    question: str
    answer: str
    timestamp: str


@dataclass(frozen=True, slots=True)
class ExecutiveSummary:
    """High-level executive synthesis of the lecture or meeting."""

    paragraphs: list[str]
    core_thesis: str


@dataclass(frozen=True, slots=True)
class TranscriptSummary:
    """Complete structured summary package for a transcript."""

    schema_version: str
    provenance: dict[str, Any]
    executive: ExecutiveSummary
    timeline: list[TimelineEntry]
    glossary: list[GlossaryEntry]
    flashcards: list[FlashcardEntry]
    spoken_summary: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize complete summary model to a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranscriptSummary:
        """Deserialize a TranscriptSummary instance from a dictionary."""
        exec_data = data.get("executive") or {}
        raw_paragraphs = exec_data.get("paragraphs") or []
        if isinstance(raw_paragraphs, str):
            paragraphs = [p.strip() for p in raw_paragraphs.split("\n\n") if p.strip()]
        else:
            paragraphs = [str(p) for p in raw_paragraphs]

        executive = ExecutiveSummary(
            paragraphs=paragraphs,
            core_thesis=str(exec_data.get("core_thesis") or ""),
        )

        timeline = [
            TimelineEntry(
                timestamp=str(t.get("timestamp") or "00:00:00"),
                seconds=float(t.get("seconds") or 0.0),
                topic=str(t.get("topic") or ""),
                summary=str(t.get("summary") or ""),
                slide_ref=t.get("slide_ref"),
            )
            for t in data.get("timeline") or []
        ]

        glossary = [
            GlossaryEntry(
                term=str(g.get("term") or ""),
                definition=str(g.get("definition") or ""),
                first_timestamp=str(g.get("first_timestamp") or "00:00:00"),
            )
            for g in data.get("glossary") or []
        ]

        flashcards = [
            FlashcardEntry(
                id=str(f.get("id") or ""),
                question=str(f.get("question") or ""),
                answer=str(f.get("answer") or ""),
                timestamp=str(f.get("timestamp") or "00:00:00"),
            )
            for f in data.get("flashcards") or []
        ]

        return cls(
            schema_version=str(data.get("schema_version") or "1.0.0"),
            provenance=dict(data.get("provenance") or {}),
            executive=executive,
            timeline=timeline,
            glossary=glossary,
            flashcards=flashcards,
            spoken_summary=str(data.get("spoken_summary") or ""),
        )


@dataclass(frozen=True, slots=True)
class ParsedSegment:
    """Individual parsed segment with timestamp and spoken text."""

    timestamp: str
    seconds: float
    text: str


@dataclass(frozen=True, slots=True)
class TranscriptChunk:
    """Chronological chunk of transcript segments for map-phase LLM analysis."""

    index: int
    start_time: str
    end_time: str
    start_seconds: float
    end_seconds: float
    text: str
    segments: tuple[ParsedSegment, ...] = ()


def parse_timestamp_seconds(timestamp_str: str) -> float:
    """Convert timestamp strings like 'HH:MM:SS', 'HH:MM:SS.mmm' or 'MM:SS' to seconds."""
    cleaned = timestamp_str.strip().replace(",", ".")
    parts = cleaned.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def format_timestamp_clock(seconds: float) -> str:
    """Format seconds into HH:MM:SS clock string."""
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _clean_markdown_escapes(text: str) -> str:
    """Clean markdown escapes often found in exported transcript segments."""
    cleaned = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\\([`*_[\]{}()#+.!|>~-])", r"\1", cleaned).strip()


def _extract_json(text: str) -> dict[str, Any]:
    """Robustly extract and parse a JSON object from LLM response text."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        cleaned = cleaned[start_idx : end_idx + 1]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise ValueError(f"Failed to decode JSON from model response: {err}") from err


class TranscriptSummarizer:
    """Pipeline for temporal Map-Reduce summarization using a local Ollama model."""

    def __init__(self, config: SummaryConfig | None = None) -> None:
        self.config = config or SummaryConfig()

    def parse_transcript(self, text_or_path: str | Path) -> list[ParsedSegment]:
        """Parse transcript text or file into chronological ParsedSegment items.

        Supports Local Transcriber Markdown exports, bracketed timestamps [HH:MM:SS],
        SRT/WebVTT timestamp formats, and JSON export formats.
        """
        raw_text: str
        if isinstance(text_or_path, Path):
            if not text_or_path.is_file():
                raise FileNotFoundError(f"Transcript file not found: {text_or_path}")
            raw_text = text_or_path.read_text(encoding="utf-8")
        elif isinstance(text_or_path, str):
            is_potential_path = (
                "\n" not in text_or_path
                and ("/" in text_or_path or "\\" in text_or_path
                     or text_or_path.endswith((".md", ".txt", ".srt", ".vtt", ".json")))
            )
            if is_potential_path:
                path = Path(text_or_path)
                if path.is_file():
                    raw_text = path.read_text(encoding="utf-8")
                else:
                    raw_text = text_or_path
            else:
                raw_text = text_or_path
        else:
            raw_text = str(text_or_path)

        trimmed = raw_text.strip()
        if not trimmed:
            return []

        # Check for JSON format export from Local Transcriber
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                data = json.loads(trimmed)
                transcript_payload = data.get("transcript", data)
                if "segments" in transcript_payload:
                    segments: list[ParsedSegment] = []
                    for seg in transcript_payload["segments"]:
                        start_sec = float(seg.get("start_seconds") or 0.0)
                        txt = str(seg.get("text") or "").strip()
                        if txt:
                            segments.append(
                                ParsedSegment(
                                    timestamp=format_timestamp_clock(start_sec),
                                    seconds=start_sec,
                                    text=_clean_markdown_escapes(txt),
                                )
                            )
                    if segments:
                        return sorted(segments, key=lambda s: s.seconds)
            except Exception:
                pass

        # Parse text/markdown line-by-line
        lines = raw_text.splitlines()
        segments_list: list[ParsedSegment] = []
        current_ts: str | None = None
        current_sec: float | None = None
        current_text_parts: list[str] = []

        def flush_current() -> None:
            nonlocal current_ts, current_sec, current_text_parts
            if current_ts is not None and current_sec is not None:
                full_text = " ".join(current_text_parts).strip()
                if full_text:
                    segments_list.append(
                        ParsedSegment(
                            timestamp=current_ts,
                            seconds=current_sec,
                            text=_clean_markdown_escapes(full_text),
                        )
                    )
            current_text_parts = []

        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            match = _TIMESTAMP_LINE_RE.match(line_str)
            if match:
                raw_ts = match.group(1)
                text_part = match.group(2)
                sec = parse_timestamp_seconds(raw_ts)
                clock_ts = format_timestamp_clock(sec)

                flush_current()
                current_ts = clock_ts
                current_sec = sec
                if text_part:
                    current_text_parts.append(text_part)
            else:
                inline_match = _INLINE_TIMESTAMP_RE.search(line_str)
                if inline_match and not current_ts:
                    raw_ts = inline_match.group(1)
                    sec = parse_timestamp_seconds(raw_ts)
                    clock_ts = format_timestamp_clock(sec)
                    text_part = (
                        line_str[: inline_match.start()]
                        + line_str[inline_match.end() :]
                    )
                    flush_current()
                    current_ts = clock_ts
                    current_sec = sec
                    if text_part.strip():
                        current_text_parts.append(text_part.strip())
                elif current_ts is not None:
                    current_text_parts.append(line_str)

        flush_current()

        # Fallback if no timestamps were detected in raw content
        if not segments_list:
            paragraphs = [
                p.strip() for p in raw_text.split("\n\n")
                if p.strip() and not p.startswith("#")
            ]
            if not paragraphs:
                paragraphs = [
                    p.strip() for p in raw_text.splitlines()
                    if p.strip() and not p.startswith("#")
                ]

            simulated_sec = 0.0
            for p in paragraphs:
                segments_list.append(
                    ParsedSegment(
                        timestamp=format_timestamp_clock(simulated_sec),
                        seconds=simulated_sec,
                        text=_clean_markdown_escapes(p),
                    )
                )
                simulated_sec += 60.0

        return sorted(segments_list, key=lambda s: s.seconds)

    def chunk_by_time(
        self,
        segments: list[ParsedSegment],
        max_minutes: int | None = None,
    ) -> list[TranscriptChunk]:
        """Divide parsed segments into sequential time chunks bounded by max_minutes."""
        if not segments:
            return []

        limit_minutes = (
            max_minutes if max_minutes is not None
            else self.config.chunk_duration_minutes
        )
        if limit_minutes <= 0:
            raise ValueError("chunk_duration_minutes must be positive")

        max_seconds = float(limit_minutes * 60)
        chunks: list[TranscriptChunk] = []

        current_segments: list[ParsedSegment] = []
        chunk_start_sec = segments[0].seconds
        chunk_index = 0

        for segment in segments:
            if current_segments and (segment.seconds - chunk_start_sec >= max_seconds):
                start_sec = current_segments[0].seconds
                end_sec = current_segments[-1].seconds
                text_block = "\n".join(f"[{s.timestamp}] {s.text}" for s in current_segments)
                chunks.append(
                    TranscriptChunk(
                        index=chunk_index,
                        start_time=format_timestamp_clock(start_sec),
                        end_time=format_timestamp_clock(end_sec),
                        start_seconds=start_sec,
                        end_seconds=end_sec,
                        text=text_block,
                        segments=tuple(current_segments),
                    )
                )
                chunk_index += 1
                current_segments = [segment]
                chunk_start_sec = segment.seconds
            else:
                current_segments.append(segment)

        if current_segments:
            start_sec = current_segments[0].seconds
            end_sec = current_segments[-1].seconds
            text_block = "\n".join(f"[{s.timestamp}] {s.text}" for s in current_segments)
            chunks.append(
                TranscriptChunk(
                    index=chunk_index,
                    start_time=format_timestamp_clock(start_sec),
                    end_time=format_timestamp_clock(end_sec),
                    start_seconds=start_sec,
                    end_seconds=end_sec,
                    text=text_block,
                    segments=tuple(current_segments),
                )
            )

        return chunks

    def _call_ollama(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_format: bool = False,
    ) -> str:
        """Call Ollama /api/generate via pure urllib.request with robust error handling."""
        endpoint = f"{self.config.ollama_url.rstrip('/')}/api/generate"
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt
        if json_format:
            payload["format"] = "json"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=float(self.config.timeout)) as response:
                status = response.status
                if status != 200:
                    raise OllamaUnavailableError(
                        f"Ollama retornou status HTTP {status} em {endpoint}."
                    )
                raw_bytes = response.read()
                raw_text = raw_bytes.decode("utf-8")
                parsed = json.loads(raw_text)
                return str(parsed.get("response") or "")

        except urllib.error.HTTPError as err:
            err_body = ""
            try:
                err_body = err.read().decode("utf-8")
            except Exception:
                pass

            if err.code == 404:
                raise OllamaUnavailableError(
                    f"Modelo '{self.config.model_name}' não encontrado no Ollama em "
                    f"'{self.config.ollama_url}' (HTTP 404). "
                    f"Execute 'ollama pull {self.config.model_name}' para baixá-lo."
                ) from err
            raise OllamaUnavailableError(
                f"Erro HTTP {err.code} retornado pelo Ollama: {err.reason}. {err_body}".strip()
            ) from err

        except urllib.error.URLError as err:
            raise OllamaUnavailableError(
                f"Não foi possível conectar ao serviço Ollama em '{self.config.ollama_url}' "
                f"({err.reason}). Certifique-se de que o Ollama esteja em execução."
            ) from err

        except TimeoutError as err:
            raise OllamaUnavailableError(
                f"Tempo limite excedido ({self.config.timeout}s) ao aguardar resposta do Ollama "
                f"para o modelo '{self.config.model_name}'."
            ) from err

        except json.JSONDecodeError as err:
            raise OllamaUnavailableError(
                f"Resposta recebida do Ollama não é um JSON válido: {err}"
            ) from err

        except Exception as err:
            if isinstance(err, OllamaUnavailableError):
                raise
            raise OllamaUnavailableError(
                f"Falha inesperada na comunicação com Ollama: {err}"
            ) from err

    def _map_chunk(self, chunk: TranscriptChunk) -> dict[str, Any]:
        """Map phase: analyze an individual chunk to extract timeline, glossary, and flashcards."""
        system_prompt = (
            "Você é um pedagogo e sintetizador técnico de alta precisão especializado.\n"
            "Analise o trecho transcrito delimitado e extraia:\n"
            "1. chunk_summary: Resumo claro dos principais temas abordados neste trecho.\n"
            "2. timeline: Tópicos relevantes com timestamp exato [HH:MM:SS], título e descrição.\n"
            "3. glossary: Termos técnicos ou equações com termo, definição e primeiro timestamp.\n"
            "4. flashcards: Cards de estudo (pergunta e resposta conceitual) com timestamp.\n\n"
            "Responda ESTRITAMENTE em formato JSON com as chaves: "
            "'chunk_summary', 'timeline', 'glossary', 'flashcards'."
        )

        prompt = (
            f"--- BLOCO CRONOLÓGICO: {chunk.start_time} até {chunk.end_time} ---\n\n"
            f"{chunk.text}\n\n"
            "Extraia o JSON solicitado contendo chunk_summary, timeline, glossary e flashcards."
        )

        raw_response = self._call_ollama(prompt, system_prompt=system_prompt, json_format=True)
        try:
            return _extract_json(raw_response)
        except Exception:
            return {
                "chunk_summary": f"Bloco de {chunk.start_time} a {chunk.end_time}.",
                "timeline": [
                    {
                        "timestamp": chunk.start_time,
                        "seconds": chunk.start_seconds,
                        "topic": f"Sessão {chunk.start_time}",
                        "summary": "Conteúdo abordado durante este intervalo.",
                        "slide_ref": None,
                    }
                ],
                "glossary": [],
                "flashcards": [],
            }

    def _reduce_synthesis(
        self,
        chunk_summaries: list[str],
        all_timeline: list[TimelineEntry],
        all_glossary: list[GlossaryEntry],
    ) -> tuple[ExecutiveSummary, str]:
        """Reduce phase: synthesize presentation into executive summary and spoken narrative."""
        system_prompt = (
            "Você é um redator sênior e comunicador acadêmico.\n"
            "A partir dos resumos parciais dos blocos, produza a síntese global definitiva:\n"
            "1. core_thesis: Frase única sintetizando a mensagem principal ou tese central.\n"
            "2. paragraphs: De 2 a 4 parágrafos estruturados explicando o desenvolvimento.\n"
            "3. spoken_summary: Roteiro falado dinâmico em português brasileiro (300-450 palavras)"
            " ideal para áudio ou narração de podcast sintetizando o que foi transmitido.\n\n"
            "Responda ESTRITAMENTE em formato JSON com as chaves: "
            "'core_thesis', 'paragraphs', 'spoken_summary'."
        )

        timeline_topics = [
            f"- [{t.timestamp}] {t.topic}: {t.summary}"
            for t in all_timeline[:20]
        ]
        glossary_terms = [
            f"- {g.term}: {g.definition}"
            for g in all_glossary[:15]
        ]

        prompt = (
            "--- RESUMO DOS BLOCOS CRONOLÓGICOS ---\n"
            + "\n".join(f"Bloco {i+1}: {s}" for i, s in enumerate(chunk_summaries))
            + "\n\n--- PRINCIPAIS MARCOS DA LINHA DO TEMPO ---\n"
            + "\n".join(timeline_topics)
            + "\n\n--- PRINCIPAIS TERMOS DO GLOSSÁRIO ---\n"
            + "\n".join(glossary_terms)
            + "\n\nGere o JSON definitivo com 'core_thesis', 'paragraphs' e 'spoken_summary'."
        )

        raw_response = self._call_ollama(prompt, system_prompt=system_prompt, json_format=True)
        try:
            data = _extract_json(raw_response)
            default_thesis = "Síntese dos tópicos abordados."
            thesis = str(data.get("core_thesis") or data.get("tese_central") or default_thesis)
            raw_paras = data.get("paragraphs") or data.get("executive_paragraphs") or []
            if isinstance(raw_paras, str):
                paras = [p.strip() for p in raw_paras.split("\n\n") if p.strip()]
            else:
                paras = [str(p).strip() for p in raw_paras if str(p).strip()]

            if not paras:
                paras = (
                    chunk_summaries if chunk_summaries
                    else ["Conteúdo analisado com sucesso."]
                )

            spoken = str(
                data.get("spoken_summary")
                or data.get("resumo_falado")
                or " ".join(paras)
            ).strip()

            return ExecutiveSummary(paragraphs=paras, core_thesis=thesis), spoken
        except Exception:
            paras = chunk_summaries if chunk_summaries else ["Conteúdo analisado com sucesso."]
            thesis = "Apresentação estruturada de tópicos técnicos."
            spoken = " ".join(paras)
            return ExecutiveSummary(paragraphs=paras, core_thesis=thesis), spoken

    def summarize(self, source_path: Path, output_dir: Path | None = None) -> Path:
        """Execute temporal Map-Reduce summarization pipeline for a transcript file.

        Outputs '<basename>.resumo.md' and '<basename>.resumo.json' sidecar file.
        Returns the Path to the generated Markdown file.
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise FileNotFoundError(f"Arquivo de transcrição não encontrado: {source_path}")

        out_dir = Path(output_dir) if output_dir is not None else source_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = source_path.name
        if filename.endswith(".transcription.md"):
            base_name = filename[:-17]
        elif filename.endswith(".resumo.md"):
            base_name = filename[:-10]
        else:
            base_name = source_path.stem

        md_path = out_dir / f"{base_name}.resumo.md"
        json_path = out_dir / f"{base_name}.resumo.json"

        # Step 1: Parse
        segments = self.parse_transcript(source_path)
        if not segments:
            raise ValueError(f"Não foi possível extrair segmentos de: {source_path}")

        # Step 2: Temporal Chunking
        chunks = self.chunk_by_time(segments, max_minutes=self.config.chunk_duration_minutes)

        # Step 3: Map Phase across chunks
        chunk_summaries: list[str] = []
        raw_timeline_entries: list[dict[str, Any]] = []
        raw_glossary_entries: list[dict[str, Any]] = []
        raw_flashcard_entries: list[dict[str, Any]] = []

        for chunk in chunks:
            chunk_result = self._map_chunk(chunk)
            summary_text = str(chunk_result.get("chunk_summary") or "").strip()
            if summary_text:
                chunk_summaries.append(summary_text)

            for item in chunk_result.get("timeline") or []:
                if isinstance(item, dict):
                    raw_timeline_entries.append(item)

            for item in chunk_result.get("glossary") or []:
                if isinstance(item, dict):
                    raw_glossary_entries.append(item)

            for item in chunk_result.get("flashcards") or []:
                if isinstance(item, dict):
                    raw_flashcard_entries.append(item)

        # Normalize timeline
        timeline_list: list[TimelineEntry] = []
        for item in raw_timeline_entries:
            ts = str(item.get("timestamp") or "00:00:00").strip()
            sec = item.get("seconds")
            sec_val = float(sec) if sec is not None else parse_timestamp_seconds(ts)
            topic = str(item.get("topic") or item.get("titulo") or "").strip()
            summary = str(item.get("summary") or item.get("resumo") or "").strip()
            slide = item.get("slide_ref") or item.get("slide")
            if topic or summary:
                timeline_list.append(
                    TimelineEntry(
                        timestamp=format_timestamp_clock(sec_val),
                        seconds=sec_val,
                        topic=topic or "Tópico Geral",
                        summary=summary,
                        slide_ref=str(slide).strip() if slide else None,
                    )
                )
        timeline_list.sort(key=lambda t: t.seconds)

        # Normalize & deduplicate glossary
        glossary_map: dict[str, GlossaryEntry] = {}
        for item in raw_glossary_entries:
            term = str(item.get("term") or item.get("termo") or "").strip()
            definition = str(item.get("definition") or item.get("definicao") or "").strip()
            ts = str(item.get("first_timestamp") or item.get("timestamp") or "00:00:00").strip()
            if not term or not definition:
                continue
            key = term.lower()
            if key not in glossary_map:
                glossary_map[key] = GlossaryEntry(
                    term=term, definition=definition, first_timestamp=ts
                )
            elif len(definition) > len(glossary_map[key].definition):
                glossary_map[key] = GlossaryEntry(
                    term=glossary_map[key].term,
                    definition=definition,
                    first_timestamp=glossary_map[key].first_timestamp,
                )
        glossary_list = list(glossary_map.values())

        # Normalize & deduplicate flashcards
        flashcard_list: list[FlashcardEntry] = []
        seen_questions: set[str] = set()
        for idx, item in enumerate(raw_flashcard_entries, start=1):
            question = str(item.get("question") or item.get("pergunta") or "").strip()
            answer = str(item.get("answer") or item.get("resposta") or "").strip()
            ts = str(item.get("timestamp") or "00:00:00").strip()
            card_id = str(item.get("id") or f"card-{idx:02d}").strip()
            if not question or not answer:
                continue
            norm_q = question.lower()
            if norm_q in seen_questions:
                continue
            seen_questions.add(norm_q)
            flashcard_list.append(
                FlashcardEntry(id=card_id, question=question, answer=answer, timestamp=ts)
            )

        # Step 4: Reduce Phase
        executive, spoken_summary = self._reduce_synthesis(
            chunk_summaries, timeline_list, glossary_list
        )

        provenance = {
            "source_file": source_path.name,
            "model_name": self.config.model_name,
            "ollama_url": self.config.ollama_url,
            "generated_at": datetime.now(UTC).isoformat(),
            "chunk_count": len(chunks),
            "chunk_duration_minutes": self.config.chunk_duration_minutes,
            "segment_count": len(segments),
        }

        # Step 5: Assemble TranscriptSummary
        summary = TranscriptSummary(
            schema_version="1.0.0",
            provenance=provenance,
            executive=executive,
            timeline=timeline_list,
            glossary=glossary_list,
            flashcards=flashcard_list,
            spoken_summary=spoken_summary,
        )

        # Step 6: Write sidecar JSON
        json_content = json.dumps(summary.to_dict(), ensure_ascii=False, indent=2)
        json_path.write_text(json_content, encoding="utf-8")

        # Step 7: Write Markdown document
        md_content = self.render_markdown(summary)
        md_path.write_text(md_content, encoding="utf-8")

        return md_path

    def render_markdown(self, summary: TranscriptSummary) -> str:
        """Render TranscriptSummary to a Markdown document with YAML frontmatter."""
        source_name = str(summary.provenance.get("source_file") or "transcricao")
        model = str(summary.provenance.get("model_name") or self.config.model_name)
        generated_at = str(summary.provenance.get("generated_at") or "")
        core_thesis_escaped = json.dumps(summary.executive.core_thesis, ensure_ascii=False)

        lines: list[str] = [
            "---",
            f"schema_version: {json.dumps(summary.schema_version)}",
            f"source_file: {json.dumps(source_name, ensure_ascii=False)}",
            f"model: {json.dumps(model)}",
            f"generated_at: {json.dumps(generated_at)}",
            f"core_thesis: {core_thesis_escaped}",
            "---",
            "",
            f"# Resumo Estruturado: {source_name}",
            "",
            f"> **Tese Central:** {summary.executive.core_thesis}",
            "",
            "## Resumo Executivo",
            "",
        ]

        if summary.executive.paragraphs:
            for paragraph in summary.executive.paragraphs:
                lines.extend([paragraph, ""])
        else:
            lines.extend(["_Nenhum resumo executivo disponível._", ""])

        if summary.spoken_summary:
            lines.extend([
                "## Roteiro Falado (Podcast / Áudio)",
                "",
                summary.spoken_summary,
                "",
            ])

        lines.extend(["## Linha do Tempo", ""])
        if summary.timeline:
            lines.extend([
                "| Timestamp | Tópico | Resumo | Ref. Slide |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for entry in summary.timeline:
                slide = entry.slide_ref or "-"
                summary_cleaned = entry.summary.replace("\n", " ").replace("|", "\\|")
                topic_cleaned = entry.topic.replace("\n", " ").replace("|", "\\|")
                lines.append(
                    f"| `{entry.timestamp}` | {topic_cleaned} | {summary_cleaned} | {slide} |"
                )
            lines.append("")
        else:
            lines.extend(["_Nenhum marco cronológico registrado._", ""])

        lines.extend(["## Glossário de Termos Técnicos", ""])
        if summary.glossary:
            for entry in summary.glossary:
                lines.append(
                    f"- **{entry.term}** (`{entry.first_timestamp}`): {entry.definition}"
                )
            lines.append("")
        else:
            lines.extend(["_Nenhum termo técnico registrado._", ""])

        lines.extend(["## Flashcards de Fixação", ""])
        if summary.flashcards:
            for idx, card in enumerate(summary.flashcards, start=1):
                lines.extend([
                    f"### Card {idx:02d} (`{card.timestamp}`)",
                    f"- **Pergunta:** {card.question}",
                    f"- **Resposta:** {card.answer}",
                    "",
                ])
        else:
            lines.extend(["_Nenhum flashcard gerado._", ""])

        return "\n".join(lines).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for running transcript summarization."""
    parser = argparse.ArgumentParser(
        prog="python -m local_transcriber.summarizer",
        description="Gera resumos estruturados a partir de transcrições usando Ollama local.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Caminho para o arquivo de transcrição (.md, .txt, .json)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="Diretório de saída (padrão: mesmo diretório do arquivo fonte)",
    )
    parser.add_argument(
        "--model",
        "-m",
        default="qwen2.5:3b",
        help="Nome do modelo local no Ollama (padrão: qwen2.5:3b)",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:11434",
        help="URL base do Ollama (padrão: http://127.0.0.1:11434)",
    )
    parser.add_argument(
        "--chunk-minutes",
        type=int,
        default=20,
        help="Duração máxima em minutos de cada chunk temporal (padrão: 20)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Tempo limite em segundos para respostas HTTP do Ollama (padrão: 120)",
    )

    args = parser.parse_args(argv)

    config = SummaryConfig(
        ollama_url=args.ollama_url,
        model_name=args.model,
        chunk_duration_minutes=args.chunk_minutes,
        timeout=args.timeout,
    )
    summarizer = TranscriptSummarizer(config=config)

    try:
        md_file = summarizer.summarize(args.source, output_dir=args.output_dir)
        print(f"[OK] Resumo Markdown gerado: {md_file}")
        stem = md_file.stem[:-7] if md_file.stem.endswith(".resumo") else md_file.stem
        json_file = md_file.with_name(f"{stem}.resumo.json")
        if json_file.exists():
            print(f"[OK] Sidecar JSON gerado:    {json_file}")
        return 0

    except OllamaUnavailableError as err:
        print(f"[ERRO OLLAMA] {err}", file=sys.stderr)
        return 1
    except FileNotFoundError as err:
        print(f"[ERRO ARQUIVO] {err}", file=sys.stderr)
        return 1
    except ValueError as err:
        print(f"[ERRO DADOS] {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"[ERRO INESPERADO] {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
