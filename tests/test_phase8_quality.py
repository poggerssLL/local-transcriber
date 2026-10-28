"""Synthetic regressions: technical/lexical success must not hide failed quality."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from local_transcriber.summarizer import (
    ExecutiveSummary,
    TimelineEntry,
    TranscriptSummarizer,
    TranscriptSummary,
)

_spec = importlib.util.spec_from_file_location(
    "phase8_quality", Path(__file__).resolve().parents[1] / "scripts/validate-phase8-quality.py"
)
assert _spec is not None and _spec.loader is not None
quality = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(quality)


def factual_summary() -> TranscriptSummary:
    return TranscriptSummary(
        schema_version="1.0.0",
        provenance={},
        executive=ExecutiveSummary(paragraphs=[" ".join(quality.FACTS)], core_thesis="Controle"),
        timeline=[
            TimelineEntry(
                timestamp=f"00:00:{i * 10:02d}",
                seconds=i * 10,
                topic="Controle",
                summary=quality.FACTS[i],
            )
            for i in range(3)
        ],
        glossary=[],
        flashcards=[],
        spoken_summary="",
    )


def test_indicators_never_claim_semantic_approval() -> None:
    result = quality.summary_indicators(factual_summary())
    assert result["indicators_passed"]
    assert result["manual_semantic_review_required"]


def test_lexical_coverage_does_not_approve_empty_timeline() -> None:
    summary = factual_summary()
    summary.timeline.clear()
    result = quality.summary_indicators(summary)
    assert all(result["fact_group_indicators"])
    assert not result["indicators_passed"]


def test_repeated_paragraphs_rejected_despite_fact_coverage() -> None:
    summary = factual_summary()
    summary.executive.paragraphs.append(summary.executive.paragraphs[0])
    assert not quality.summary_indicators(summary)["indicators_passed"]


def test_nonfinite_and_inconsistent_timestamps_are_rejected() -> None:
    for timestamp, seconds in (("00:00:10", float("nan")), ("00:02:00", 10)):
        summary = factual_summary()
        summary.timeline[1] = TimelineEntry(timestamp, seconds, "Controle", "Referência")
        assert not quality.summary_indicators(summary)["indicators_passed"]


def test_missing_critical_number_is_rejected() -> None:
    summary = factual_summary()
    summary.executive.paragraphs[0] = summary.executive.paragraphs[0].replace(
        "vinte e cinco", "alta"
    )
    summary.timeline.clear()
    result = quality.summary_indicators(summary)
    assert not result["numeric_reference_present"]
    assert not result["indicators_passed"]


def test_speech_reference_normalizes_number_and_accent_but_counts_omission() -> None:
    assert (
        quality.word_error_rate("Referência de vinte e cinco graus.", "Referencia de 25 graus") == 0
    )
    assert quality.word_error_rate("O sensor mede a temperatura", "O sensor mede") == 0.4


def test_reduce_removes_exact_duplicates_but_keeps_distinct_facts() -> None:
    summarizer = TranscriptSummarizer()
    data = {
        "core_thesis": "Controle",
        "paragraphs": [
            "Sensor mede temperatura.",
            " SENSOR   mede temperatura. ",
            "A referência é 25 graus.",
        ],
        "spoken_summary": "Controle",
    }
    with patch.object(summarizer, "_call_ollama", return_value=json.dumps(data)):
        executive, _ = summarizer._reduce_synthesis(["Controle sintético"], [], [])
    assert executive.paragraphs == ["Sensor mede temperatura.", "A referência é 25 graus."]


def test_map_prompt_specifies_item_keys_and_source_timestamps() -> None:
    summarizer = TranscriptSummarizer()
    segments = summarizer.parse_transcript(quality.SOURCE)
    chunk = summarizer.chunk_by_time(segments)[0]
    with patch.object(summarizer, "_call_ollama", return_value='{"timeline":[]}') as call:
        summarizer._map_chunk(chunk)
    prompt = call.call_args.kwargs["system_prompt"]
    assert '"timestamp"' in prompt and '"topic"' in prompt and '"summary"' in prompt
    assert "ressalvas" in prompt
