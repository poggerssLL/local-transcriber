"""Typed runtime configuration and safe path handling."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DATA_DIR_ENV = "LOCAL_TRANSCRIBER_DATA_DIR"


def _absolute_path(value: str | Path, *, name: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path.resolve(strict=False)


def normalize_relative_path(value: str) -> str:
    """Return a portable, traversal-free relative path for persisted file metadata."""
    if not value or "\\" in value:
        raise ValueError("relative path must be non-empty and use '/' separators")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("relative path must stay below the runtime directory")
    if ":" in path.parts[0]:
        raise ValueError("relative path must not contain a drive prefix")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", _absolute_path(self.root, name="runtime root"))

    @property
    def database(self) -> Path:
        return self.root / "local_transcriber.sqlite3"

    @property
    def media(self) -> Path:
        return self.root / "media"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def models(self) -> Path:
        return self.root / "models"

    def resolve_relative(self, value: str) -> Path:
        relative = normalize_relative_path(value)
        candidate = (self.root / Path(*PurePosixPath(relative).parts)).resolve(strict=False)
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("resolved path escapes the runtime directory")
        return candidate

    def ensure_directories(self) -> None:
        for path in (self.root, self.media, self.exports, self.models):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class AppConfig:
    paths: RuntimePaths

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AppConfig:
        values = os.environ if env is None else env
        configured = values.get(DATA_DIR_ENV)
        if configured:
            root = _absolute_path(configured, name=DATA_DIR_ENV)
        else:
            local_app_data = values.get("LOCALAPPDATA")
            if not local_app_data:
                raise ValueError("LOCALAPPDATA is required when no data directory override is set")
            root = _absolute_path(local_app_data, name="LOCALAPPDATA") / "LocalTranscriber"
        return cls(paths=RuntimePaths(root))
