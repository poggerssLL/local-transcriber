"""Engine abstraction and synchronous local transcription orchestration."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from .config import RuntimePaths
from .models import (
    JobPhase,
    JobStatus,
    Segment,
    Transcript,
    TranscriptionJob,
    TranscriptionMetrics,
    TranscriptionSettings,
    Word,
    utc_now,
)
from .models_manager import ModelManager
from .repository import Repository


class RuntimeProfileError(RuntimeError):
    """The requested execution profile cannot run on this installation."""


class TranscriptionCancelled(Exception):
    """Cooperative cancellation requested for a transcription job."""


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
    phase: str
    message: str
    completed_segments: int = 0
    processed_seconds: float = 0.0
    total_seconds: float | None = None
    percent: float | None = None

    @property
    def stage(self) -> str:
        """Backward-compatible alias retained for Stage 3 observers."""
        return self.phase


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
        if progress is not None:
            progress(ProgressEvent("loading_model", "model loaded"))
        raw_segments, info = model.transcribe(
            str(request.media_path),
            language=settings.language,
            beam_size=settings.beam_size,
            word_timestamps=settings.word_timestamps,
            vad_filter=settings.vad_filter,
        )
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        if progress is not None:
            progress(
                ProgressEvent(
                    "transcribing",
                    "transcription started",
                    total_seconds=duration or None,
                )
            )
        segments = self._consume_segments(raw_segments, progress, duration or None)
        text = " ".join(segment.text for segment in segments).strip()
        if duration <= 0 and segments:
            duration = max(segment.end_seconds for segment in segments)
        language = getattr(info, "language", None) or settings.language
        probability = getattr(info, "language_probability", None)
        return EngineOutput(text, segments, language, probability, duration)

    @staticmethod
    def _consume_segments(
        raw_segments: Iterable[Any],
        progress: ProgressCallback | None,
        total_seconds: float | None = None,
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
                processed = converted[-1].end_seconds
                percent = None
                if total_seconds:
                    percent = min(99.999, processed / total_seconds * 100)
                progress(
                    ProgressEvent(
                        "transcribing",
                        "segment decoded",
                        len(converted),
                        processed,
                        total_seconds,
                        percent,
                    )
                )
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
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.models = models or ModelManager(paths)
        self.profiles = profiles or ProfileResolver()
        self.engine_factory = engine_factory or (lambda _profile: FasterWhisperEngine())
        self.clock = clock
        self.now = now

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
                settings=effective,
                total_seconds=recording.duration_seconds,
            )
        )
        self.repository.update_job_status(job.id, JobStatus.RUNNING)
        started = self.clock()
        try:
            self._notify(progress, ProgressEvent("started", resolved.reason))
            output = self.engine_factory(resolved).transcribe(
                TranscriptionRequest(media_path, model_path, effective),
                lambda event: self._notify(progress, event),
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
        except Exception as error:
            message = self._sanitize_error(error, media_path, model_path)
            try:
                self.repository.update_job_status(job.id, JobStatus.FAILED, error_message=message)
            except Exception:
                pass
            raise
        self._notify(
            progress,
            ProgressEvent(
                "completed",
                "transcript published",
                len(output.segments),
                duration,
                duration,
                100.0,
            ),
        )
        return transcript

    def process_claimed_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        lease_seconds: float = 60.0,
        progress: ProgressCallback | None = None,
    ) -> Transcript | None:
        """Execute one claimed job; failures and cancellation are persisted."""
        job = self.repository.get_job(job_id)
        if job is None:
            raise KeyError(f"job not found: {job_id}")
        if job.status is not JobStatus.RUNNING or job.worker_id != worker_id:
            raise RuntimeError("job is not owned by this worker")
        requested = job.settings or TranscriptionSettings(
            engine=job.engine, model_name=job.model_name
        )
        runtime_paths: list[Path] = []
        started = self.clock()
        try:
            self._raise_if_cancelled(job_id, worker_id)
            recording = self.repository.get_recording(job.recording_id)
            if recording is None:
                raise KeyError(f"recording not found: {job.recording_id}")
            model_path = self.models.require_installed(requested.model_name)
            media_path = self.paths.resolve_relative(recording.relative_path)
            runtime_paths.extend((media_path, model_path))
            if not media_path.is_file():
                raise FileNotFoundError("managed media file is missing")
            resolved = self.profiles.resolve(requested.profile)
            effective = replace(
                requested, device=resolved.device, compute_type=resolved.compute_type
            )
            total = recording.duration_seconds
            self.repository.update_claimed_job(
                job_id,
                worker_id,
                phase=JobPhase.LOADING_MODEL,
                message=resolved.reason,
                total_seconds=total,
                percent=0.0,
                now=self.now(),
                lease_seconds=lease_seconds,
            )

            def persist_event(event: ProgressEvent) -> None:
                self._raise_if_cancelled(job_id, worker_id)
                event_total = event.total_seconds or total
                event_percent = event.percent
                if event_percent is None and event_total and event.processed_seconds:
                    event_percent = min(99.999, event.processed_seconds / event_total * 100)
                phase = (
                    JobPhase.LOADING_MODEL
                    if event.phase == "loading_model"
                    else JobPhase.TRANSCRIBING
                )
                try:
                    self.repository.update_claimed_job(
                        job_id,
                        worker_id,
                        phase=phase,
                        message=event.message,
                        completed_segments=event.completed_segments,
                        processed_seconds=event.processed_seconds,
                        total_seconds=event_total,
                        percent=event_percent,
                        now=self.now(),
                        lease_seconds=lease_seconds,
                    )
                except RuntimeError:
                    self._raise_if_cancelled(job_id, worker_id)
                    raise
                self._notify(progress, event)

            output = self.engine_factory(resolved).transcribe(
                TranscriptionRequest(media_path, model_path, effective), persist_event
            )
            self._raise_if_cancelled(job_id, worker_id)
            elapsed = max(0.0, self.clock() - started)
            duration = output.audio_duration_seconds or total or 0.0
            self.repository.update_claimed_job(
                job_id,
                worker_id,
                phase=JobPhase.FINALIZING,
                message="publishing transcript",
                completed_segments=len(output.segments),
                processed_seconds=duration,
                total_seconds=duration,
                percent=99.999,
                now=self.now(),
                lease_seconds=lease_seconds,
            )
            transcript = Transcript(
                recording_id=recording.id,
                job_id=job_id,
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
            published = self.repository.complete_transcription(
                job_id, transcript, worker_id=worker_id, now=self.now()
            )
        except TranscriptionCancelled:
            self.repository.finish_claimed_cancel(job_id, worker_id, now=self.now())
            return None
        except Exception as error:
            try:
                if self.repository.claimed_job_cancel_requested(job_id, worker_id):
                    self.repository.finish_claimed_cancel(job_id, worker_id, now=self.now())
                    return None
            except (KeyError, RuntimeError):
                pass
            message = self._sanitize_error(error, *runtime_paths)
            self.repository.fail_claimed_job(job_id, worker_id, message, now=self.now())
            return None
        self._notify(
            progress,
            ProgressEvent(
                "completed",
                "transcript published",
                len(published.segments),
                duration,
                duration,
                100.0,
            ),
        )
        return published

    def _raise_if_cancelled(self, job_id: str, worker_id: str) -> None:
        if self.repository.claimed_job_cancel_requested(job_id, worker_id):
            raise TranscriptionCancelled("transcription cancellation requested")

    @staticmethod
    def _notify(progress: ProgressCallback | None, event: ProgressEvent) -> None:
        if progress is not None:
            with suppress(Exception):
                progress(event)

    def _sanitize_error(self, error: Exception, *paths: Path) -> str:
        message = _single_line(error)
        for path in (self.paths.root, *paths):
            message = message.replace(str(path), "<runtime>")
        return f"{type(error).__name__}: {message or 'transcription failed'}"[:500]


def _single_line(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()
