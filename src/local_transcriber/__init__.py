"""Public API for the Local Transcriber persistence core."""

from .config import AppConfig, RuntimePaths
from .database import SCHEMA_VERSION, Database
from .exporters import ExportFormat, TranscriptExporter, render_transcript
from .media import (
    ALLOWED_EXTENSIONS,
    DuplicateMediaError,
    InvalidMediaError,
    MediaImportError,
    MediaImportSettings,
    MediaInfo,
    MediaInspector,
    MediaLibrary,
    MediaTooLargeError,
    UnsupportedMediaError,
    sanitize_filename,
)
from .models import (
    ExportedArtifact,
    JobStatus,
    Recording,
    RecordingSearchResult,
    Segment,
    Subject,
    Transcript,
    TranscriptionJob,
    TranscriptionMetrics,
    TranscriptionSettings,
    Word,
)
from .repository import Repository

__all__ = [
    "AppConfig",
    "ALLOWED_EXTENSIONS",
    "Database",
    "DuplicateMediaError",
    "ExportFormat",
    "ExportedArtifact",
    "InvalidMediaError",
    "JobStatus",
    "MediaImportError",
    "MediaImportSettings",
    "MediaInfo",
    "MediaInspector",
    "MediaLibrary",
    "MediaTooLargeError",
    "Recording",
    "RecordingSearchResult",
    "Repository",
    "RuntimePaths",
    "SCHEMA_VERSION",
    "Segment",
    "Subject",
    "Transcript",
    "TranscriptExporter",
    "TranscriptionJob",
    "TranscriptionMetrics",
    "TranscriptionSettings",
    "UnsupportedMediaError",
    "Word",
    "render_transcript",
    "sanitize_filename",
]
