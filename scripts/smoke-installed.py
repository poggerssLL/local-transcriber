"""Smoke-test an installed package with a new synthetic runtime and no models."""

from __future__ import annotations

import argparse
import importlib.resources
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    import os

    import local_transcriber

    package = Path(local_transcriber.__file__).resolve()
    if not package.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Test requires a non-editable installation in this virtual environment")
    web = importlib.resources.files("local_transcriber").joinpath("web")
    for name in ("index.html", "styles.css", "app.js", "api.js", "async_state.js", "dom.js"):
        if not web.joinpath(name).is_file():
            raise RuntimeError(f"Missing packaged web asset: {name}")
    env = {**os.environ, "LOCAL_TRANSCRIBER_DATA_DIR": str(root), "WEB_CONCURRENCY": "1"}
    env.pop("PYTHONPATH", None)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True, cwd=root, env=env)
    models = subprocess.run(
        [sys.executable, "-m", "local_transcriber", "models", "list"],
        check=True,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    statuses = [line.split("\t") for line in models.stdout.splitlines() if line]
    if not statuses or any(len(row) != 2 or row[1] != "not-installed" for row in statuses):
        raise RuntimeError("Expected a fresh runtime without models")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://127.0.0.1:{port}"
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with (root / "server.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "local_transcriber", "serve", "--port", str(port)],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        try:
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Installed server exited before becoming ready")
                try:
                    with opener.open(base_url + "/api/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Installed server did not become ready") from None
                    time.sleep(0.2)
            with opener.open(base_url + "/", timeout=5) as response:
                if "Local Transcriber" not in response.read().decode("utf-8"):
                    raise RuntimeError("Installed interface missing")
            request = urllib.request.Request(
                base_url + "/api/subjects",
                data=b'{"name":"Synthetic installation check"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with opener.open(request, timeout=5) as response:
                subject = json.load(response)
            if not subject.get("id") or not (root / "local_transcriber.sqlite3").is_file():
                raise RuntimeError("Installed persistence check failed")
            result = {
                "status": "passed",
                "package_in_venv": True,
                "web_assets": 6,
                "health": health,
                "synthetic_subject_persisted": True,
                "models_downloaded": False,
                "inference_tested": False,
                "other_computer_tested": False,
            }
            (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result))
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
