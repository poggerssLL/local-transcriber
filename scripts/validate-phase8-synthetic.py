"""Opt-in host validation using synthetic inputs and an existing local model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import time
import urllib.request
import wave
from pathlib import Path

from local_transcriber.models import TranscriptionSettings
from local_transcriber.summarizer import SummaryConfig, TranscriptSummarizer, TranscriptSummary
from local_transcriber.transcription import (
    CTranslate2RuntimeProbe,
    FasterWhisperEngine,
    TranscriptionRequest,
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("redirect_refused")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--ollama-timeout", type=int, default=180, choices=range(1, 601))
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    if root.exists():
        parser.error("runtime-root must be a new, exclusively owned directory")
    model = args.model_path.resolve(strict=True)
    if not all((model / name).is_file() for name in ("config.json", "model.bin", "tokenizer.json")):
        parser.error("existing model is incomplete; downloads are forbidden")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    )
    root.mkdir(parents=True)
    result = {"synthetic_only": True, "profiles": {}, "ollama": {}}
    audio = root / "synthetic-tone.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(
            b"".join(
                struct.pack("<h", int(800 * math.sin(2 * math.pi * 440 * i / 16000)))
                for i in range(32000)
            )
        )
    audio_before = hashlib.sha256(audio.read_bytes()).digest()
    if not args.summary_only:
        CTranslate2RuntimeProbe().inspect()  # Registers installed Windows CUDA DLL directories.
    profiles = () if args.summary_only else (("cpu", "int8"), ("cuda", "int8_float16"))
    for device, compute in profiles:
        started = time.monotonic()
        events = []
        try:
            settings = TranscriptionSettings(
                model_name="small",
                language="pt",
                beam_size=1,
                word_timestamps=False,
                vad_filter=False,
                profile=device,
                device=device,
                compute_type=compute,
            )
            output = FasterWhisperEngine().transcribe(
                TranscriptionRequest(audio, model, settings), events.append
            )
            result["profiles"][device] = {
                "status": "passed",
                "seconds": round(time.monotonic() - started, 3),
                "compute_type": compute,
                "segments": len(output.segments),
                "nonempty_text": bool(output.text.strip()),
                "audio_seconds": output.audio_duration_seconds,
                "events": [event.phase for event in events],
            }
        except Exception as exc:
            result["profiles"][device] = {"status": "failed", "error_type": type(exc).__name__}
        (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(device, result["profiles"][device], flush=True)
    result["audio_preserved"] = hashlib.sha256(audio.read_bytes()).digest() == audio_before
    source = root / "synthetic.transcription.md"
    source.write_text(
        """# Aula sintética: controle de temperatura
[00:00:00] Um sensor mede a temperatura de uma estufa fictícia.
[00:00:30] A referência é a temperatura desejada de vinte e cinco graus.
[00:01:00] O controlador compara a leitura do sensor com a referência.
[00:01:30] A diferença é o erro, usado para regular o aquecimento.
[00:02:00] A realimentação permite corrigir desvios sem ignorar o sensor.
[00:02:30] Nesta demonstração não há dados reais nem equipamentos conectados.
""",
        encoding="utf-8",
    )
    source_before = source.read_bytes()
    events = []
    started = time.monotonic()
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as response:
            tags = json.load(response)
        if not any(item.get("name") == "qwen2.5:3b" for item in tags.get("models", [])):
            raise RuntimeError("existing_ollama_model_missing")
        summarizer = TranscriptSummarizer(SummaryConfig(timeout=args.ollama_timeout, temperature=0))
        output = summarizer.summarize(source, root / "summary", events.append)
        sidecar = output.with_suffix(".json")
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        summary = TranscriptSummary.from_dict(payload)
        text = output.read_text(encoding="utf-8").casefold()
        if not text.strip() or not summary.executive.core_thesis.strip():
            raise RuntimeError("empty_summary_artifact")
        if source.read_bytes() != source_before:
            raise RuntimeError("synthetic_source_changed")
        expected = ("sensor", "temperatura", "referência", "erro", "realimentação")
        result["ollama"] = {
            "status": "passed",
            "seconds": round(time.monotonic() - started, 3),
            "source_preserved": source.read_bytes() == source_before,
            "markdown_nonempty": bool(text.strip()),
            "core_thesis_nonempty": bool(summary.executive.core_thesis.strip()),
            "topic_coverage": sum(word in text for word in expected),
            "expected_topic_count": len(expected),
            "progress_phases": [event.get("phase") for event in events],
        }
    except Exception as exc:
        result["ollama"] = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "progress_phases": [event.get("phase") for event in events],
            "seconds": round(time.monotonic() - started, 3),
            "source_preserved": source.read_bytes() == source_before,
        }
    (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("ollama", result["ollama"], flush=True)
    return (
        0
        if all(v["status"] == "passed" for v in result["profiles"].values())
        and result["ollama"]["status"] == "passed"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
