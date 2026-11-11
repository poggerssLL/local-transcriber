"""Downloads use a fake provider, never the network or personal runtime."""

from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from local_transcriber.api import create_app
from local_transcriber.config import AppConfig, RuntimePaths
from local_transcriber.models_manager import ModelManager


def wait_download(client, name):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        status = client.get("/api/models/downloads").json().get(name, {})
        if status.get("state") in {"failed", "succeeded"}:
            return status
        sleep(0.01)
    pytest.fail("Download did not finish")


def test_confirmation_origin_catalog_and_bounded_download(tmp_path):
    started, release = Event(), Event()
    calls = []

    def downloader(name, *, output_dir, cache_dir):
        from pathlib import Path

        calls.append(name)
        started.set()
        assert release.wait(5)
        for filename in ("config.json", "model.bin", "tokenizer.json"):
            (Path(output_dir) / filename).write_text("{}")
        return output_dir

    config = AppConfig(RuntimePaths(tmp_path / "runtime"))
    manager = ModelManager(config.paths, downloader=downloader)
    with TestClient(
        create_app(config, model_manager=manager, start_worker=False), base_url="http://127.0.0.1"
    ) as client:
        url = "/api/models/small/download"
        headers = {"Origin": "http://127.0.0.1"}
        assert client.get("/api/models/downloads").json() == {}
        assert client.post(url, json={"confirm": True}).status_code == 403
        for origin in ("https://evil.example", "http://127.0.0.1:9000"):
            assert (
                client.post(url, json={"confirm": True}, headers={"Origin": origin}).status_code
                == 403
            )
        assert client.post(url, json={"confirm": False}, headers=headers).status_code == 400
        assert (
            client.post(
                "/api/models/not-a-model/download", json={"confirm": True}, headers=headers
            ).status_code
            == 422
        )
        assert not calls
        try:
            assert client.post(url, json={"confirm": True}, headers=headers).status_code == 202
            assert started.wait(2)
            assert client.get("/api/health").status_code == 200
            assert (
                client.post(
                    "/api/models/base/download", json={"confirm": True}, headers=headers
                ).status_code
                == 409
            )
            assert not manager.status("small").installed
        finally:
            release.set()
        assert wait_download(client, "small")["state"] == "succeeded"
        assert manager.status("small").installed
        assert client.post(url, json={"confirm": True}, headers=headers).status_code == 202
        assert calls == ["small"]


def test_failed_download_is_sanitized_and_can_be_retried(tmp_path):
    calls = []

    def downloader(name, **kwargs):
        calls.append(name)
        raise OSError("secret token and personal path")

    config = AppConfig(RuntimePaths(tmp_path / "runtime"))
    manager = ModelManager(config.paths, downloader=downloader)
    with TestClient(
        create_app(config, model_manager=manager, start_worker=False), base_url="http://127.0.0.1"
    ) as client:
        for _ in range(2):
            assert (
                client.post(
                    "/api/models/tiny/download",
                    json={"confirm": True},
                    headers={"Origin": "http://127.0.0.1"},
                ).status_code
                == 202
            )
            status = wait_download(client, "tiny")
            assert status["state"] == "failed"
            assert "secret" not in status["message"]
        assert calls == ["tiny", "tiny"]
        assert not manager.status("tiny").installed
        assert not list(config.paths.models.glob("*.download"))
