"""Validated domain models independent from storage concerns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from math import isfinite
from pathlib import PurePosixPath
from uuid import uuid4

from .config import normalize_relative_path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


def _required(value: str, name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} must not be blank")
    return cleaned


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TranscriptionSettings:
    engine: str = "faster-whisper"
    model_name: str = "small"
    language: str | None = None
    beam_size: int = 5
    word_timestamps: bool = True
    vad_filter: bool = True
    profile: str = "auto"
    device: str | None = None
    compute_type: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine", _required(self.engine, "engine"))
        object.__setattr__(self, "model_name", _required(self.model_name, "model name"))
        if self.language is not None:
            object.__setattr__(self, "language", _required(self.language, "language"))
        if self.beam_size < 1:
            raise ValueError("beam_size must be positive")
        if self.profile not in {"auto", "cpu", "cuda"}:
            raise ValueError("profile must be auto, cpu, or cuda")
        if self.device is not None and self.device not in {"cpu", "cuda"}:
            raise ValueError("device must be cpu or cuda")
        if self.compute_type is not None:
            object.__setattr__(self, "compute_type", _required(self.compute_type, "compute type"))


@dataclass(frozen=True, slots=True)
class TranscriptionMetrics:
    audio_duration_seconds: float
    processing_duration_seconds: float
    segment_count: int
    word_count: int

    def __post_init__(self) -> None:
        _non_negative_finite(self.audio_duration_seconds, "audio_duration_seconds")
        _non_negative_finite(self.processing_duration_seconds, "processing_duration_seconds")
        if self.segment_count < 0 or self.word_count < 0:
            raise ValueError("metric counts must be non-negative")

    @property
    def realtime_factor(self) -> float | None:
        if self.audio_duration_seconds == 0:
            return None
        return self.processing_duration_seconds / self.audio_duration_seconds


@dataclass(frozen=True, slots=True)
class Subject:
    name: str
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required(self.name, "subject name"))


@dataclass(frozen=True, slots=True)
class RecordingSearchResult:
    recording_id: str
    title: str
    subject_name: str
    lesson_date: date
    excerpt: str


@dataclass(frozen=True, slots=True)
class Recording:
    title: str
    subject_id: str
    lesson_date: date
    original_name: str
    sha256: str
    size_bytes: int
    media_format: str
    relative_path: str
    duration_seconds: float | None = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _required(self.title, "recording title"))
        object.__setattr__(self, "subject_id", _required(self.subject_id, "subject id"))
        original_name = _required(self.original_name, "original name")
        if PurePosixPath(original_name.replace("\\", "/")).name != original_name:
            raise ValueError("original name must be a file name, not a path")
        object.__setattr__(self, "original_name", original_name)
        sha256 = self.sha256.lower()
        if not _SHA256.fullmatch(sha256):
            raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        object.__setattr__(self, "sha256", sha256)
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        object.__setattr__(
            self, "media_format", _required(self.media_format, "media format").lower()
        )
        if self.duration_seconds is not None:
            _non_negative_finite(self.duration_seconds, "duration_seconds")
        object.__setattr__(self, "relative_path", normalize_relative_path(self.relative_path))


@dataclass(frozen=True, slots=True)
class TranscriptionJob:
    recording_id: str
    engine: str
    model_name: str
    status: JobStatus = JobStatus.PENDING
    error_message: str | None = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recording_id", _required(self.recording_id, "recording id"))
        object.__setattr__(self, "engine", _required(self.engine, "engine"))
        object.__setattr__(self, "model_name", _required(self.model_name, "model name"))
        if not isinstance(self.status, JobStatus):
            object.__setattr__(self, "status", JobStatus(self.status))


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start_seconds: float
    end_seconds: float
    probability: float | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _required(self.text, "word text"))
        _validate_interval(self.start_seconds, self.end_seconds)
        if self.probability is not None and (
            not isfinite(self.probability) or not 0 <= self.probability <= 1
        ):
            raise ValueError("word probability must be finite and between 0 and 1")


@dataclass(frozen=True, slots=True)
class Segment:
    ordinal: int
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[Word, ...] = ()
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("segment ordinal must be non-negative")
        _validate_interval(self.start_seconds, self.end_seconds)
        object.__setattr__(self, "text", _required(self.text, "segment text"))
        object.__setattr__(self, "words", tuple(self.words))


def _validate_interval(start: float, end: float) -> None:
    if not isfinite(start) or not isfinite(end) or start < 0 or end < start:
        raise ValueError("timestamps must satisfy 0 <= start <= end")


def _non_negative_finite(value: float, name: str) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class Transcript:
    recording_id: str
    job_id: str
    language: str | None
    text: str
    language_probability: float | None = None
    segments: tuple[Segment, ...] = ()
    settings: TranscriptionSettings = field(default_factory=TranscriptionSettings)
    metrics: TranscriptionMetrics | None = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recording_id", _required(self.recording_id, "recording id"))
        object.__setattr__(self, "job_id", _required(self.job_id, "job id"))
        if self.language_probability is not None and (
            not isfinite(self.language_probability) or not 0 <= self.language_probability <= 1
        ):
            raise ValueError("language probability must be finite and between 0 and 1")
        segments = tuple(sorted(self.segments, key=lambda segment: (segment.ordinal, segment.id)))
        object.__setattr__(self, "segments", segments)
        ordinals = [segment.ordinal for segment in segments]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("segment ordinals must be unique")


@dataclass(frozen=True, slots=True)
class ExportedArtifact:
    transcript_id: str
    kind: str
    relative_path: str
    media_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "transcript_id", _required(self.transcript_id, "transcript id"))
        object.__setattr__(self, "kind", _required(self.kind, "artifact kind").lower())
        object.__setattr__(self, "relative_path", normalize_relative_path(self.relative_path))
        if self.media_type is not None:
            object.__setattr__(self, "media_type", _required(self.media_type, "media type"))
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("artifact size_bytes must be non-negative")
        if self.sha256 is not None:
            sha256 = self.sha256.lower()
            if not _SHA256.fullmatch(sha256):
                raise ValueError("artifact sha256 must contain exactly 64 hexadecimal characters")
            object.__setattr__(self, "sha256", sha256)
