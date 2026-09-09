"""Explicit, runtime-local management of Faster Whisper models."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .config import RuntimePaths

SUPPORTED_MODELS = ("tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo")
_REQUIRED_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")


class ModelError(RuntimeError):
    """Base error for explicit model management."""


class ModelNotInstalledError(ModelError):
    """The requested model is not complete in the managed runtime."""


class ModelDownloadConfirmationError(ModelError):
    """A model download was requested without explicit confirmation."""


@dataclass(frozen=True, slots=True)
class ModelStatus:
    name: str
    installed: bool
    path: Path


Downloader = Callable[..., str | Path]


class ModelManager:
    def __init__(self, paths: RuntimePaths, *, downloader: Downloader | None = None) -> None:
        self.paths = paths
        self._downloader = downloader

    def list_models(self) -> list[ModelStatus]:
        return [self.status(name) for name in SUPPORTED_MODELS]

    def status(self, name: str) -> ModelStatus:
        name = self._validate_name(name)
        path = self.paths.models / name
        installed = path.is_dir() and all(
            (path / filename).is_file() for filename in _REQUIRED_MODEL_FILES
        )
        return ModelStatus(name=name, installed=installed, path=path)

    def require_installed(self, name: str) -> Path:
        status = self.status(name)
        if not status.installed:
            raise ModelNotInstalledError(
                f"model {name!r} is not installed; run "
                f"'local-transcriber models download {name} --confirm' first"
            )
        return status.path

    def download(self, name: str, *, confirm: bool) -> Path:
        name = self._validate_name(name)
        if not confirm:
            raise ModelDownloadConfirmationError("model download requires --confirm")
        existing = self.status(name)
        if existing.installed:
            return existing.path

        self.paths.models.mkdir(parents=True, exist_ok=True)
        temporary = self.paths.models / f".{name}.{uuid4()}.download"
        cache = self.paths.models / ".cache"
        temporary.mkdir()
        try:
            downloader = self._downloader or self._default_downloader
            downloaded = Path(
                downloader(name, output_dir=str(temporary), cache_dir=str(cache))
            ).resolve(strict=False)
            if downloaded != temporary.resolve() and downloaded.is_dir():
                for child in downloaded.iterdir():
                    os.replace(child, temporary / child.name)
            if not all((temporary / filename).is_file() for filename in _REQUIRED_MODEL_FILES):
                raise ModelError("downloaded model is incomplete")
            destination = self.paths.models / name
            if destination.exists():
                raise ModelError(f"incomplete model directory already exists: {destination.name}")
            temporary.rename(destination)
            return destination
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    @staticmethod
    def _default_downloader(name: str, **kwargs: str) -> str:
        from faster_whisper.utils import download_model

        return download_model(name, **kwargs)

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = name.strip().lower()
        if normalized not in SUPPORTED_MODELS:
            supported = ", ".join(SUPPORTED_MODELS)
            raise ValueError(f"unsupported model {name!r}; supported models: {supported}")
        return normalized
