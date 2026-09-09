"""Managed media import, validation, inspection, and deletion."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import uuid4

import av
from av.error import FFmpegError

from .config import RuntimePaths
from .models import Recording, Subject
from .repository import Repository

ALLOWED_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".m4a", ".ogg", ".mp4", ".mkv", ".webm"})
_CONTAINER_ALIASES = {
    ".wav": frozenset({"wav"}),
    ".mp3": frozenset({"mp3"}),
    ".flac": frozenset({"flac"}),
    ".m4a": frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}),
    ".mp4": frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}),
    ".ogg": frozenset({"ogg"}),
    ".mkv": frozenset({"matroska", "webm"}),
    ".webm": frozenset({"matroska", "webm"}),
}
_INVALID_FILENAME = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class MediaImportError(ValueError):
    """Base error for rejected media imports."""


class UnsupportedMediaError(MediaImportError):
    """The name or encoded media is not supported."""


class InvalidMediaError(MediaImportError):
    """The input is not decodable media with an audio stream."""


class MediaTooLargeError(MediaImportError):
    """The input exceeded the configured byte limit."""


class DuplicateMediaError(MediaImportError):
    """The exact media bytes were imported previously."""

    def __init__(self, existing: Recording) -> None:
        self.existing = existing
        super().__init__(f"media already imported as recording {existing.id}")


@dataclass(frozen=True, slots=True)
class MediaImportSettings:
    max_size_bytes: int = 4 * 1024 * 1024 * 1024
    chunk_size_bytes: int = 1024 * 1024
    allowed_extensions: frozenset[str] = ALLOWED_EXTENSIONS

    def __post_init__(self) -> None:
        if self.max_size_bytes < 1:
            raise ValueError("max_size_bytes must be positive")
        if self.chunk_size_bytes < 1:
            raise ValueError("chunk_size_bytes must be positive")
        normalized = frozenset(
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in self.allowed_extensions
        )
        if not normalized:
            raise ValueError("at least one media extension must be allowed")
        object.__setattr__(self, "allowed_extensions", normalized)


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration_seconds: float
    container_format: str
    audio_codec: str
    sample_rate: int | None
    channels: int | None


def sanitize_filename(value: str, *, max_length: int = 120) -> str:
    """Create a portable filename while discarding any supplied directory."""
    basename = PurePosixPath(unicodedata.normalize("NFKC", value).replace("\\", "/")).name
    basename = _INVALID_FILENAME.sub("_", basename)
    basename = re.sub(r"\s+", " ", basename).strip(" .")
    if not basename:
        basename = "media"
    path = Path(basename)
    suffix = path.suffix.lower()
    stem = path.stem.strip(" .") or "media"
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    available = max(1, max_length - len(suffix))
    return f"{stem[:available].rstrip(' .')}{suffix}"


class MediaInspector:
    """Inspect media through the same FFmpeg libraries exposed by PyAV."""

    def inspect(self, path: Path) -> MediaInfo:
        try:
            with av.open(str(path), mode="r") as container:
                audio_stream = next(
                    (stream for stream in container.streams if stream.type == "audio"), None
                )
                if audio_stream is None:
                    raise InvalidMediaError("media does not contain an audio stream")

                decoded_frame = None
                for packet in container.demux(audio_stream):
                    for frame in packet.decode():
                        decoded_frame = frame
                        break
                    if decoded_frame is not None:
                        break
                if decoded_frame is None:
                    raise InvalidMediaError("audio stream contains no decodable frames")

                duration = self._duration(container, audio_stream)
                if duration is None or duration <= 0:
                    duration = self._decoded_duration(path, audio_stream.index)
                if duration <= 0:
                    raise InvalidMediaError("audio duration could not be determined")

                codec_context = audio_stream.codec_context
                return MediaInfo(
                    duration_seconds=duration,
                    container_format=container.format.name,
                    audio_codec=codec_context.name,
                    sample_rate=codec_context.sample_rate or None,
                    channels=codec_context.channels or None,
                )
        except InvalidMediaError:
            raise
        except (FFmpegError, OSError, ValueError) as error:
            raise InvalidMediaError("file is not valid decodable media") from error

    @staticmethod
    def _duration(
        container: av.container.InputContainer, stream: av.audio.stream.AudioStream
    ) -> float | None:
        if stream.duration is not None and stream.time_base is not None:
            return float(stream.duration * stream.time_base)
        if container.duration is not None:
            return float(container.duration / av.time_base)
        return None

    @staticmethod
    def _decoded_duration(path: Path, audio_stream_index: int) -> float:
        duration = 0.0
        with av.open(str(path), mode="r") as container:
            stream = container.streams[audio_stream_index]
            for packet in container.demux(stream):
                for frame in packet.decode():
                    if frame.sample_rate:
                        duration += frame.samples / frame.sample_rate
        return duration


class MediaLibrary:
    def __init__(
        self,
        repository: Repository,
        paths: RuntimePaths,
        *,
        settings: MediaImportSettings | None = None,
        inspector: MediaInspector | None = None,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.settings = settings or MediaImportSettings()
        self.inspector = inspector or MediaInspector()

    def create_subject(self, name: str) -> Subject:
        return self.repository.add_subject(Subject(name=name))

    def import_file(
        self,
        source: str | Path,
        *,
        title: str,
        subject_id: str,
        lesson_date: date,
    ) -> Recording:
        source_path = Path(source).expanduser().resolve(strict=True)
        if not source_path.is_file():
            raise MediaImportError("source must be a regular file")
        with source_path.open("rb") as stream:
            return self.import_stream(
                stream,
                original_name=source_path.name,
                title=title,
                subject_id=subject_id,
                lesson_date=lesson_date,
            )

    def import_stream(
        self,
        stream: BinaryIO,
        *,
        original_name: str,
        title: str,
        subject_id: str,
        lesson_date: date,
    ) -> Recording:
        if self.repository.get_subject(subject_id) is None:
            raise KeyError(f"subject not found: {subject_id}")
        safe_name = sanitize_filename(original_name)
        extension = Path(safe_name).suffix.lower()
        if extension not in self.settings.allowed_extensions:
            raise UnsupportedMediaError(f"unsupported media extension: {extension or '<none>'}")

        self.paths.ensure_directories()
        incoming = self.paths.media / ".incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        temporary = incoming / f"{uuid4()}.part"
        try:
            sha256, size_bytes = self._copy_and_hash(stream, temporary)
            duplicate = self.repository.find_recording_by_sha256(sha256)
            if duplicate is not None:
                raise DuplicateMediaError(duplicate)
            media_info = self.inspector.inspect(temporary)
            detected_formats = frozenset(media_info.container_format.lower().split(","))
            if not detected_formats & _CONTAINER_ALIASES[extension]:
                raise UnsupportedMediaError(
                    f"detected container {media_info.container_format!r} does not match {extension}"
                )

            recording_id = str(uuid4())
            relative_path = PurePosixPath(
                "media", str(lesson_date.year), recording_id, safe_name
            ).as_posix()
            destination = self.paths.resolve_relative(relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, destination)

            recording = Recording(
                id=recording_id,
                title=title,
                subject_id=subject_id,
                lesson_date=lesson_date,
                original_name=safe_name,
                sha256=sha256,
                size_bytes=size_bytes,
                media_format=extension.removeprefix("."),
                duration_seconds=media_info.duration_seconds,
                relative_path=relative_path,
            )
            try:
                return self.repository.add_recording(recording)
            except BaseException:
                destination.unlink(missing_ok=True)
                self._remove_empty_parents(destination.parent)
                raise
        finally:
            temporary.unlink(missing_ok=True)
            self._remove_empty_parents(incoming)

    def list_recordings(self, subject_id: str | None = None) -> list[Recording]:
        return self.repository.list_recordings(subject_id)

    def delete_recording(self, recording_id: str) -> bool:
        recording = self.repository.get_recording(recording_id)
        if recording is None:
            return False
        media_path = self.paths.resolve_relative(recording.relative_path)
        staged = media_path.with_name(f".{media_path.name}.{uuid4()}.deleting")
        if media_path.exists():
            os.replace(media_path, staged)
        try:
            deleted = self.repository.delete_recording(recording_id)
        except BaseException:
            if staged.exists():
                os.replace(staged, media_path)
            raise
        if staged.exists():
            staged.unlink()
        self._remove_empty_parents(media_path.parent)
        return deleted

    def _copy_and_hash(self, stream: BinaryIO, destination: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        total = 0
        with destination.open("xb") as output:
            while True:
                chunk = stream.read(self.settings.chunk_size_bytes)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise MediaImportError("media stream must return bytes")
                total += len(chunk)
                if total > self.settings.max_size_bytes:
                    raise MediaTooLargeError(f"media exceeds {self.settings.max_size_bytes} bytes")
                digest.update(chunk)
                output.write(chunk)
        return digest.hexdigest(), total

    def _remove_empty_parents(self, directory: Path) -> None:
        while directory != self.paths.media and self.paths.media in directory.parents:
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent
