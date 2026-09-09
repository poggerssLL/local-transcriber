"""Engine abstraction and synchronous local transcription orchestration."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from .config import RuntimePaths
from .models import (
    JobStatus,
    Segment,
    Transcript,
    TranscriptionJob,
    TranscriptionMetrics,
    TranscriptionSettings,
    Word,
)
from .models_manager import ModelManager
from .repository import Repository


class RuntimeProfileError(RuntimeError):
    """The requested execution profile cannot run on this installation."""


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    cpu_compute_types: frozenset[str]
    cuda_device_count: int
    cuda_compute_types: frozenset[str]
    cuda_error: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    requested: str
    device: str
    compute_type: str
    reason: str


class RuntimeProbe(Protocol):
    def inspect(self) -> RuntimeCapabilities: ...


class CTranslate2RuntimeProbe:
    def inspect(self) -> RuntimeCapabilities:
        module = import_module("ctranslate2")
        cpu_types = frozenset(module.get_supported_compute_types("cpu"))
        try:
            cuda_count = int(module.get_cuda_device_count())
            cuda_types = frozenset()
            cuda_error = None
            if cuda_count:
                cuda_error = self._windows_cuda_library_error()
                if cuda_error is None:
                    cuda_types = frozenset(module.get_supported_compute_types("cuda"))
            else:
                cuda_error = "CTranslate2 did not find a usable CUDA device"
        except (OSError, RuntimeError) as error:
            cuda_count = 0
            cuda_types = frozenset()
            cuda_error = _single_line(error) or type(error).__name__
        return RuntimeCapabilities(cpu_types, cuda_count, cuda_types, cuda_error)

    @staticmethod
    def _windows_cuda_library_error() -> str | None:
        if os.name != "nt":
            return None
        import ctypes

        missing = []
        for library in ("cublas64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll"):
            try:
                ctypes.WinDLL(library)
            except OSError:
                missing.append(library)
        if missing:
            return "required CUDA libraries are not loadable: " + ", ".join(missing)
        return None


class ProfileResolver:
    def __init__(self, probe: RuntimeProbe | None = None) -> None:
        self.probe = probe or CTranslate2RuntimeProbe()

    def resolve(self, requested: str) -> ResolvedProfile:
        requested = requested.strip().lower()
        if requested not in {"auto", "cpu", "cuda"}:
            raise ValueError("profile must be auto, cpu, or cuda")
        capabilities = self.probe.inspect()
        if requested == "cpu":
            if "int8" not in capabilities.cpu_compute_types:
                raise RuntimeProfileError("CTranslate2 CPU runtime does not support int8")
            return ResolvedProfile("cpu", "cpu", "int8", "CPU int8 explicitly requested")
        cuda_ready = (
            capabilities.cuda_device_count > 0 and "int8_float16" in capabilities.cuda_compute_types
        )
        if requested == "cuda":
            if not cuda_ready:
                detail = capabilities.cuda_error or "int8_float16 is not supported by CUDA runtime"
                raise RuntimeProfileError(
                    "CUDA profile is unavailable: "
                    f"{detail}. Verify the NVIDIA driver, CUDA 12, cuDNN 9, and CTranslate2."
                )
            return ResolvedProfile("cuda", "cuda", "int8_float16", "CUDA runtime probe passed")
        if cuda_ready:
            return ResolvedProfile("auto", "cuda", "int8_float16", "CUDA runtime probe passed")
        if "int8" not in capabilities.cpu_compute_types:
            raise RuntimeProfileError("neither CUDA int8_float16 nor CPU int8 is available")
        detail = capabilities.cuda_error or "CUDA int8_float16 is not supported"
        return ResolvedProfile("auto", "cpu", "int8", f"CPU fallback: {detail}")


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    stage: str
    message: str
    completed_segments: int = 0


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass(frozen=True, slots=True)
class TranscriptionRequest:
    media_path: Path
    model_path: Path
    settings: TranscriptionSettings


@dataclass(frozen=True, slots=True)
class EngineOutput:
    text: str
    segments: tuple[Segment, ...]
    language: str | None
    language_probability: float | None
    audio_duration_seconds: float


class TranscriptionEngine(Protocol):
    name: str

    def transcribe(
        self, request: TranscriptionRequest, progress: ProgressCallback | None = None
    ) -> EngineOutput: ...


ModelFactory = Callable[[Path, str, str], Any]


class FasterWhisperEngine:
    name = "faster-whisper"

    def __init__(self, *, model_factory: ModelFactory | None = None) -> None:
        self._model_factory = model_factory or self._create_model

    def transcribe(
        self, request: TranscriptionRequest, progress: ProgressCallback | None = None
    ) -> EngineOutput:
        settings = request.settings
        if settings.device is None or settings.compute_type is None:
            raise ValueError("transcription settings must contain a resolved runtime profile")
        model = self._model_factory(request.model_path, settings.device, settings.compute_type)
        raw_segments, info = model.transcribe(
            str(request.media_path),
            language=settings.language,
            beam_size=settings.beam_size,
            word_timestamps=settings.word_timestamps,
            vad_filter=settings.vad_filter,
        )
        segments = self._consume_segments(raw_segments, progress)
        text = " ".join(segment.text for segment in segments).strip()
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        if duration <= 0 and segments:
            duration = max(segment.end_seconds for segment in segments)
        language = getattr(info, "language", None) or settings.language
        probability = getattr(info, "language_probability", None)
        return EngineOutput(text, segments, language, probability, duration)

    @staticmethod
    def _consume_segments(
        raw_segments: Iterable[Any], progress: ProgressCallback | None
    ) -> tuple[Segment, ...]:
        converted: list[Segment] = []
        for raw_segment in raw_segments:
            text = str(raw_segment.text).strip()
            if not text:
                continue
            words = []
            for raw_word in getattr(raw_segment, "words", None) or ():
                if raw_word.start is None or raw_word.end is None or not str(raw_word.word).strip():
                    continue
                words.append(
                    Word(
                        text=str(raw_word.word).strip(),
                        start_seconds=float(raw_word.start),
                        end_seconds=float(raw_word.end),
                        probability=getattr(raw_word, "probability", None),
                    )
                )
            converted.append(
                Segment(
                    ordinal=len(converted),
                    start_seconds=float(raw_segment.start),
                    end_seconds=float(raw_segment.end),
                    text=text,
                    words=tuple(words),
                )
            )
            if progress is not None:
                progress(ProgressEvent("segment", "segment decoded", len(converted)))
        return tuple(converted)

    @staticmethod
    def _create_model(model_path: Path, device: str, compute_type: str) -> Any:
        from faster_whisper import WhisperModel

        return WhisperModel(
            str(model_path),
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )


EngineFactory = Callable[[ResolvedProfile], TranscriptionEngine]


class TranscriptionService:
    def __init__(
        self,
        repository: Repository,
        paths: RuntimePaths,
        *,
        models: ModelManager | None = None,
        profiles: ProfileResolver | None = None,
        engine_factory: EngineFactory | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.models = models or ModelManager(paths)
        self.profiles = profiles or ProfileResolver()
        self.engine_factory = engine_factory or (lambda _profile: FasterWhisperEngine())
        self.clock = clock

    def transcribe(
        self,
        recording_id: str,
        settings: TranscriptionSettings | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> Transcript:
        requested = settings or TranscriptionSettings()
        recording = self.repository.get_recording(recording_id)
        if recording is None:
            raise KeyError(f"recording not found: {recording_id}")
        model_path = self.models.require_installed(requested.model_name)
        media_path = self.paths.resolve_relative(recording.relative_path)
        if not media_path.is_file():
            raise FileNotFoundError("managed media file is missing")
        resolved = self.profiles.resolve(requested.profile)
        effective = replace(requested, device=resolved.device, compute_type=resolved.compute_type)
        job = self.repository.add_job(
            TranscriptionJob(
                recording_id=recording.id,
                engine=effective.engine,
                model_name=effective.model_name,
            )
        )
        self.repository.update_job_status(job.id, JobStatus.RUNNING)
        started = self.clock()
        try:
            if progress is not None:
                progress(ProgressEvent("started", resolved.reason))
            output = self.engine_factory(resolved).transcribe(
                TranscriptionRequest(media_path, model_path, effective), progress
            )
            elapsed = max(0.0, self.clock() - started)
            duration = output.audio_duration_seconds or recording.duration_seconds or 0.0
            transcript = Transcript(
                recording_id=recording.id,
                job_id=job.id,
                language=output.language,
                language_probability=output.language_probability,
                text=output.text,
                segments=output.segments,
                settings=effective,
                metrics=TranscriptionMetrics(
                    audio_duration_seconds=duration,
                    processing_duration_seconds=elapsed,
                    segment_count=len(output.segments),
                    word_count=sum(len(segment.words) for segment in output.segments),
                ),
            )
            self.repository.complete_transcription(job.id, transcript)
        except BaseException as error:
            message = self._sanitize_error(error, media_path, model_path)
            try:
                self.repository.update_job_status(job.id, JobStatus.FAILED, error_message=message)
            except BaseException:
                pass
            raise
        if progress is not None:
            progress(ProgressEvent("completed", "transcript published", len(output.segments)))
        return transcript

    def _sanitize_error(self, error: BaseException, *paths: Path) -> str:
        message = _single_line(error)
        for path in (self.paths.root, *paths):
            message = message.replace(str(path), "<runtime>")
        return f"{type(error).__name__}: {message or 'transcription failed'}"[:500]


def _single_line(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()
