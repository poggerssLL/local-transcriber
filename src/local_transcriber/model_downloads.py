"""Bounded explicit downloads; no network activity until start is requested."""

from __future__ import annotations

from threading import Lock, Thread

from .models_manager import ModelManager


class ModelDownloads:
    def __init__(self, models: ModelManager) -> None:
        self.models = models
        self.lock = Lock()
        self.states: dict[str, dict[str, str]] = {}
        self.thread: Thread | None = None

    def status(self) -> dict[str, dict[str, str]]:
        with self.lock:
            return {name: dict(value) for name, value in self.states.items()}

    def start(self, name: str) -> dict[str, str]:
        model = self.models.status(name)  # Validates the catalog before any work.
        name = model.name
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError("Já existe um download em andamento. Aguarde sua conclusão.")
            if model.installed:
                return {"state": "succeeded", "message": "Modelo já instalado."}
            self.states[name] = {
                "state": "downloading",
                "message": "Baixando. Mantenha o aplicativo aberto; pode levar vários minutos.",
            }
            self.thread = Thread(target=self._run, args=(name,), daemon=True)
            self.thread.start()
            return dict(self.states[name])

    def _run(self, name: str) -> None:
        try:
            self.models.download(name, confirm=True)
            result = {"state": "succeeded", "message": "Modelo instalado e pronto para uso."}
        except Exception:
            # Provider errors can contain local paths, URLs or credentials.
            result = {
                "state": "failed",
                "message": "Falha no download. Confira internet e espaço livre e tente novamente.",
            }
        with self.lock:
            self.states[name] = result
