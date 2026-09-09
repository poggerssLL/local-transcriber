from pathlib import Path

import pytest

from local_transcriber.config import AppConfig, RuntimePaths, normalize_relative_path


def test_default_runtime_path_uses_local_app_data(tmp_path: Path) -> None:
    config = AppConfig.from_env({"LOCALAPPDATA": str(tmp_path)})
    assert config.paths.root == (tmp_path / "LocalTranscriber").resolve()
    assert not config.paths.root.exists()


def test_override_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        AppConfig.from_env({"LOCAL_TRANSCRIBER_DATA_DIR": "relative/path"})


@pytest.mark.parametrize(
    "value", ["../secret", "media/../secret", "/absolute", "C:/secret", "a\\b", ""]
)
def test_unsafe_relative_paths_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_relative_path(value)


def test_runtime_directories_and_safe_resolution(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path.resolve())
    paths.ensure_directories()
    assert paths.database.parent == paths.root
    assert paths.resolve_relative("media/aula.mp3") == paths.media / "aula.mp3"
    assert all(path.is_dir() for path in (paths.root, paths.media, paths.exports, paths.models))
