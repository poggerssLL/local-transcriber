"""Click-to-start entry point for the self-contained Windows distribution."""

from __future__ import annotations

import argparse
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from .api import create_app
from .config import AppConfig
from .models_manager import ModelManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Abrir Local Transcriber")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8765, choices=range(0, 65536))
    args = parser.parse_args()
    config = AppConfig.from_env()
    # Hold the socket until uvicorn takes ownership, avoiding port selection races.
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", args.port))
    except OSError:
        listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    first_run = not any(item.installed for item in ModelManager(config.paths).list_models())

    def open_when_ready() -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(120):
            try:
                with opener.open(f"{url}/api/health", timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open(url + ("/#modelos" if first_run else "/"))
                        return
            except OSError:
                time.sleep(0.5)

    print(f"Local Transcriber: {url}")
    print("Mantenha esta janela aberta. Para encerrar, pressione Ctrl+C.")
    if first_run:
        print("Primeiro uso: abra Modelos e baixe small para comecar a transcrever.")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(config),
            host="127.0.0.1",
            port=port,
            workers=1,
            access_log=False,
            proxy_headers=False,
            server_header=False,
        )
    )
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
