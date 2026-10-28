"""Opt-in 8G: native synthetic speech and bounded summary quality indicators.

Artifacts stay in a new caller-owned directory. Indicator success is not a
semantic approval: the resulting summary still needs an independent fact review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import time
import unicodedata
import urllib.request
import wave
from pathlib import Path

from local_transcriber.models import TranscriptionSettings
from local_transcriber.summarizer import (
    SummaryConfig,
    TranscriptSummarizer,
    TranscriptSummary,
    parse_timestamp_seconds,
)
from local_transcriber.transcription import (
    CTranslate2RuntimeProbe,
    FasterWhisperEngine,
    TranscriptionRequest,
)

FACTS = (
    "Um sensor mede a temperatura de uma estufa fictícia.",
    "A referência é a temperatura desejada de vinte e cinco graus.",
    "O controlador compara a leitura do sensor com a referência.",
    "A diferença é o erro, usado para regular o aquecimento.",
    "A realimentação permite corrigir desvios sem ignorar o sensor.",
    "Nesta demonstração não há dados reais nem equipamentos conectados.",
)
ANCHORS = ("estufa", "desejada", "controlador", "diferenca", "realimentacao", "demonstracao")
FACT_GROUPS = (
    ("sensor", "temperatura", "estufa"),
    ("referencia", "vinte e cinco", "grau"),
    ("controlador", "compara", "referencia"),
    ("erro", "diferenca", "aquec"),
    ("realimentacao", "corrig", "desvio"),
    ("nao", "rea", "conect"),
)
SOURCE = (
    "# Aula sintética: controle de temperatura\n"
    + "\n".join(f"[00:{i // 2:02d}:{(i % 2) * 30:02d}] {fact}" for i, fact in enumerate(FACTS))
    + "\n"
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\b25\b", "vinte e cinco", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def word_error_rate(reference: str, hypothesis: str) -> float:
    expected, actual = normalize(reference).split(), normalize(hypothesis).split()
    previous = list(range(len(actual) + 1))
    for i, token in enumerate(expected, 1):
        current = [i]
        for j, candidate in enumerate(actual, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (token != candidate))
            )
        previous = current
    return previous[-1] / max(1, len(expected))


def summary_indicators(summary: TranscriptSummary) -> dict:
    paragraphs = [normalize(p) for p in summary.executive.paragraphs if p.strip()]
    text = normalize(
        " ".join(
            [
                summary.executive.core_thesis,
                *summary.executive.paragraphs,
                summary.spoken_summary,
                *(t.topic + " " + t.summary for t in summary.timeline),
            ]
        )
    )
    similarities = []
    for i, paragraph in enumerate(paragraphs):
        for other in paragraphs[i + 1 :]:
            left, right = set(paragraph.split()), set(other.split())
            similarities.append(len(left & right) / max(1, len(left | right)))
    times = [entry.seconds for entry in summary.timeline]
    temporal = (
        len(times) >= 3
        and all(math.isfinite(t) and 0 <= t <= 150 for t in times)
        and all(a < b for a, b in zip(times, times[1:], strict=False))
        and all(abs(parse_timestamp_seconds(e.timestamp) - e.seconds) < 1 for e in summary.timeline)
    )
    coverage = [all(term in text for term in group) for group in FACT_GROUPS]
    result = {
        "fact_group_indicators": coverage,
        "numeric_reference_present": "vinte e cinco" in text,
        "exact_duplicate_paragraphs": len(paragraphs) - len(set(paragraphs)),
        "max_paragraph_jaccard": round(max(similarities, default=0), 4),
        "timeline_count": len(times),
        "timeline_valid": temporal,
        "manual_semantic_review_required": True,
    }
    result["indicators_passed"] = (
        all(coverage)
        and bool(paragraphs)
        and temporal
        and result["exact_duplicate_paragraphs"] == 0
        and result["max_paragraph_jaccard"] < 0.8
    )
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("redirect_refused")


def make_speech(root: Path) -> tuple[Path, list[tuple[float, float]]]:
    """Use an installed pt-BR Windows voice; no TTS installation or fallback."""
    if os.name != "nt":
        raise RuntimeError("windows_voice_required")
    (root / "facts.json").write_text(json.dumps(FACTS, ensure_ascii=False), encoding="utf-8")
    script = root / "synthesize.ps1"
    script.write_text(
        """param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = 'Stop'
$voice = New-Object -ComObject SAPI.SpVoice
$installed = @($voice.GetVoices() | Where-Object { $_.GetAttribute('Language') -eq '416' })
if ($installed.Count -eq 0) { throw 'portuguese_voice_missing' }
$voice.Voice = $installed[0]
$facts = Get-Content -LiteralPath (Join-Path $Root 'facts.json') -Encoding UTF8 | ConvertFrom-Json
for ($i = 0; $i -lt $facts.Count; $i++) {
    $stream = New-Object -ComObject SAPI.SpFileStream
    try {
        $stream.Open((Join-Path $Root ('utterance-{0}.wav' -f $i)), 3, $false)
        $voice.AudioOutputStream = $stream
        [void]$voice.Speak($facts[$i], 0)
    } finally { $stream.Close() }
}
""",
        encoding="utf-8-sig",
    )
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script),
            "-Root",
            str(root),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    combined = root / "synthetic-speech.wav"
    spans, frame_count, audio_format = [], 0, None
    with wave.open(str(combined), "wb") as output:
        for i in range(len(FACTS)):
            with wave.open(str(root / f"utterance-{i}.wav"), "rb") as source:
                current = (source.getnchannels(), source.getsampwidth(), source.getframerate())
                if audio_format is None:
                    audio_format = current
                    output.setnchannels(current[0])
                    output.setsampwidth(current[1])
                    output.setframerate(current[2])
                if current != audio_format or source.getcomptype() != "NONE":
                    raise RuntimeError("voice_format_mismatch")
                start = frame_count / current[2]
                frames = source.getnframes()
                output.writeframes(source.readframes(frames))
                frame_count += frames
                spans.append((start, frame_count / current[2]))
                silence_frames = round(0.6 * current[2])
                output.writeframes(bytes(silence_frames * current[0] * current[1]))
                frame_count += silence_frames
    return combined, spans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    if root.exists():
        parser.error("runtime-root must be new and exclusively owned")
    model = args.model_path.resolve(strict=True)
    if not all((model / name).is_file() for name in ("config.json", "model.bin", "tokenizer.json")):
        parser.error("existing model incomplete; downloads forbidden")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    )
    root.mkdir(parents=True)
    result = {"synthetic_only": True, "profiles": {}, "summary": {}}

    def save() -> None:
        (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    if not args.summary_only:
        audio, spans = make_speech(root)
        before = hashlib.sha256(audio.read_bytes()).digest()
        CTranslate2RuntimeProbe().inspect()
        for device, compute in (("cpu", "int8"), ("cuda", "int8_float16")):
            started = time.monotonic()
            try:
                settings = TranscriptionSettings(
                    model_name="small",
                    language="pt",
                    beam_size=5,
                    word_timestamps=True,
                    vad_filter=False,
                    profile=device,
                    device=device,
                    compute_type=compute,
                )
                output = FasterWhisperEngine().transcribe(
                    TranscriptionRequest(audio, model, settings)
                )
                words = [word for segment in output.segments for word in segment.words]
                anchor_checks = [
                    any(
                        normalize(w.text) == anchor and start - 1 <= w.start_seconds <= end + 1
                        for w in words
                    )
                    for anchor, (start, end) in zip(ANCHORS, spans, strict=True)
                ]
                wer = word_error_rate(" ".join(FACTS), output.text)
                timing = bool(words) and all(
                    math.isfinite(w.start_seconds)
                    and math.isfinite(w.end_seconds)
                    and 0 <= w.start_seconds <= w.end_seconds <= output.audio_duration_seconds + 1
                    for w in words
                )
                (root / f"{device}.transcript.txt").write_text(output.text, encoding="utf-8")
                result["profiles"][device] = {
                    "status": "passed"
                    if wer <= 0.2 and timing and all(anchor_checks)
                    else "failed",
                    "wer": round(wer, 4),
                    "segments": len(output.segments),
                    "word_timestamps_valid": timing,
                    "anchor_range_checks": anchor_checks,
                    "seconds": round(time.monotonic() - started, 3),
                    "audio_seconds": output.audio_duration_seconds,
                }
            except Exception as exc:
                result["profiles"][device] = {"status": "failed", "error_type": type(exc).__name__}
            print(device, result["profiles"][device], flush=True)
            save()
        result["audio_preserved"] = hashlib.sha256(audio.read_bytes()).digest() == before
    source = root / "synthetic.transcription.md"
    source.write_text(SOURCE, encoding="utf-8")
    started = time.monotonic()
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
            tags = json.load(response)
        if not any(item.get("name") == "qwen2.5:3b" for item in tags.get("models", [])):
            raise RuntimeError("existing_ollama_model_missing")
        output = TranscriptSummarizer(SummaryConfig(timeout=180, temperature=0)).summarize(
            source, root / "summary"
        )
        summary = TranscriptSummary.from_dict(
            json.loads(output.with_suffix(".json").read_text("utf-8"))
        )
        result["summary"] = summary_indicators(summary)
        result["summary"]["status"] = (
            "passed" if result["summary"]["indicators_passed"] else "failed"
        )
        result["summary"]["source_preserved"] = source.read_text("utf-8") == SOURCE
        result["summary"]["seconds"] = round(time.monotonic() - started, 3)
    except Exception as exc:
        result["summary"] = {"status": "failed", "error_type": type(exc).__name__}
    print("summary", result["summary"], flush=True)
    save()
    return (
        0
        if (
            all(p["status"] == "passed" for p in result["profiles"].values())
            and result["summary"]["status"] == "passed"
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
