"""Private temporary remote session manager using Tailscale Serve (Phase 8J - Stage 1 Hardened).

Controls the lifecycle of a temporary remote session that bridges a mobile device
(e.g. iPad) to the loopback Remote Gateway (127.0.0.1:8766) over Tailscale Serve.

Invariants and boundaries:
- Strictly private Tailnet; Tailscale Funnel is never enabled and actively blocked.
- Core API (127.0.0.1:8765) runs separately with a single transcription worker.
- Remote Gateway (127.0.0.1:8766) is isolated on loopback, has no worker and no UI.
- Control plane is local-only; session operations are never exposed over the gateway.
- Scoped lifecycle: stopping a session only disables the specific Tailscale Serve
  mapping and the gateway process owned by this session. It never runs global
  'tailscale serve reset' or 'tailscale down', and never interrupts the core server
  or ongoing transcription jobs.
- Fail-closed process verification: never terminates a process by PID alone without
  verifying process identity (exact command line argument and exact creation time).
- Serialized start and stop operations via file locks.
- Strictly observational status inspection.
- Preserves recovery metadata on any stop or termination failure.
"""

from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from .config import RuntimePaths
from .remote_gateway import (
    CONFIG_FILENAME,
    DEFAULT_PORT,
    REMOTE_PREFIX,
    RemoteGatewayDisabledError,
    load_remote_config,
    remote_dir,
)

SESSION_FILENAME = "session.json"
SESSION_LOCK_FILENAME = ".session.lock"
STOP_FILENAME = ".stop_requested"
DEFAULT_HTTPS_PORT = 443
DEFAULT_CORE_PORT = 8765
DEFAULT_STARTUP_TIMEOUT = 30.0

LOGGER = logging.getLogger(__name__)


class RemoteSessionError(RuntimeError):
    """Base exception for remote session operations."""


class TailscaleError(RemoteSessionError):
    """Error interacting with the Tailscale CLI or service."""


class TailscaleNotFoundError(TailscaleError):
    """Tailscale CLI binary was not found on the system."""


class TailscaleNotRunningError(TailscaleError):
    """Tailscale daemon is not running, logged in or connected to a tailnet."""


class RemoteSessionConflictError(RemoteSessionError):
    """A port, proxy or active session conflict was detected."""


class RemoteSessionOwnershipError(RemoteSessionError):
    """Cannot prove ownership of a process or session; failing closed."""


def _validate_port(port: int, name: str = "port") -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{name} must be an integer between 1 and 65535")


def _has_exact_argument(command_line: str, expected_marker: str) -> bool:
    """Check that command_line contains expected_marker as an exact argument, not a substring."""
    try:
        tokens = shlex.split(command_line, posix=False)
    except Exception:
        tokens = command_line.split()
    cleaned = [t.strip("\"'") for t in tokens]
    if expected_marker in cleaned:
        return True
    if "=" in expected_marker:
        flag, val = expected_marker.split("=", 1)
        for i, t in enumerate(cleaned):
            if t == flag and i + 1 < len(cleaned) and cleaned[i + 1] == val:
                return True
    return False


def has_funnel(data: dict[str, Any]) -> bool:
    """Check if Tailscale Funnel is enabled or configured anywhere in the Serve config."""
    if not isinstance(data, dict):
        return False
    if data.get("Funnel") or data.get("AllowFunnel"):
        return True
    web = data.get("Web")
    if isinstance(web, dict):
        for entry in web.values():
            if isinstance(entry, dict) and (entry.get("Funnel") or entry.get("AllowFunnel")):
                return True
    tcp = data.get("TCP")
    if isinstance(tcp, dict):
        for entry in tcp.values():
            if isinstance(entry, dict) and (entry.get("Funnel") or entry.get("AllowFunnel")):
                return True
    return False


def get_serve_proxy_target(
    data: dict[str, Any], https_port: int, *, dns_name: str | None = None
) -> str | None:
    """Prove a port is free or is exactly one HTTPS root proxy.

    Unknown schemas, static/TCP handlers, extra hosts/routes and service-scoped
    configurations are conflicts, never evidence that a port is free.
    """

    def conflict() -> None:
        raise RemoteSessionConflictError(
            "Cannot prove exclusive ownership of Tailscale Serve port configuration."
        )

    if not isinstance(data, dict) or set(data) - {"TCP", "Web", "AllowFunnel"}:
        conflict()
    tcp = data.get("TCP", {})
    web = data.get("Web", {})
    funnel = data.get("AllowFunnel", {})
    if not all(isinstance(item, dict) for item in (tcp, web, funnel)):
        conflict()
    if any(value is not False for value in funnel.values()):
        conflict()
    for key, entry in tcp.items():
        if not isinstance(key, str) or not key.isdecimal() or not isinstance(entry, dict):
            conflict()
        if not 1 <= int(key) <= 65535 or str(int(key)) != key:
            conflict()
    relevant = []
    for key, entry in web.items():
        if not isinstance(key, str) or ":" not in key or not isinstance(entry, dict):
            conflict()
        host, port = key.rsplit(":", 1)
        if not host or not port.isdecimal() or not 1 <= int(port) <= 65535:
            conflict()
        if str(int(port)) != port:
            conflict()
        if int(port) == https_port:
            relevant.append((host, entry))
    tcp_entry = tcp.get(str(https_port))
    if tcp_entry is None and not relevant:
        return None
    if (
        not isinstance(tcp_entry, dict)
        or set(tcp_entry) != {"HTTPS"}
        or tcp_entry["HTTPS"] is not True
        or len(relevant) != 1
    ):
        conflict()
    host, entry = relevant[0]
    if dns_name is not None and host != dns_name:
        conflict()
    if set(entry) != {"Handlers"} or not isinstance(entry["Handlers"], dict):
        conflict()
    handlers = entry["Handlers"]
    if set(handlers) != {"/"} or not isinstance(handlers["/"], dict):
        conflict()
    handler = handlers["/"]
    if set(handler) != {"Proxy"} or not isinstance(handler["Proxy"], str):
        conflict()
    return handler["Proxy"]


def check_gateway_readiness(
    host: str,
    port: int,
    *,
    allowed_host: str,
    allowed_identity: str,
    timeout: float = 2.0,
) -> bool:
    """Check gateway HTTP readiness over loopback using authenticated headers."""
    import http.client

    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        headers = {
            "Host": allowed_host,
            "Tailscale-User-Login": allowed_identity,
        }
        conn.request("GET", f"{REMOTE_PREFIX}/health", headers=headers)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        if response.status == 200:
            try:
                data = json.loads(body)
                return data.get("status") == "ok"
            except Exception:
                return False
        return False
    except (OSError, TimeoutError, http.client.HTTPException):
        return False


@contextmanager
def _session_lock(lock_file: Path) -> Iterator[None]:
    """Hold an exclusive file lock during start and stop operations to prevent concurrency."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_file.open("a+b")
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as error:
        handle.close()
        raise RemoteSessionConflictError(
            "Another remote-session start or stop operation is currently in progress."
        ) from error
    try:
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


@dataclass(frozen=True, slots=True)
class TailscaleStatus:
    """Current status of the local Tailscale client."""

    running: bool
    dns_name: str | None
    hostname: str | None
    tailscale_ips: tuple[str, ...]
    magic_dns_suffix: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RemoteSessionState:
    """Persisted metadata of an active remote session."""

    session_id: str
    created_at: float
    gateway_pid: int
    gateway_port: int
    gateway_host: str
    https_port: int
    https_url: str
    dns_name: str
    process_creation_time: float | None
    command_marker: str
    mode: str
    core_port: int = DEFAULT_CORE_PORT
    phase: str = "active"

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> RemoteSessionState:
        if not isinstance(raw, dict):
            raise ValueError("Session state must be an object")
        for key in ("gateway_pid", "gateway_port", "https_port", "core_port"):
            if type(raw.get(key)) is not int:
                raise ValueError("Invalid session integer metadata")
        for key in ("session_id", "command_marker", "dns_name", "https_url", "mode"):
            if not isinstance(raw.get(key), str) or not raw[key]:
                raise ValueError("Missing session ownership metadata")
        if raw.get("gateway_host") != "127.0.0.1" or raw["gateway_pid"] < 0:
            raise ValueError("Invalid gateway metadata")
        _validate_port(raw["gateway_port"])
        _validate_port(raw["https_port"])
        if raw["core_port"] != DEFAULT_CORE_PORT:
            raise ValueError("Invalid core port")
        phase = raw.get("phase", "active")
        if phase not in {"prepared", "gateway", "activating", "active"}:
            raise ValueError("Unknown session recovery phase")
        if not math.isfinite(float(raw["created_at"])):
            raise ValueError("Invalid creation time")
        creation = raw.get("process_creation_time")
        if creation is not None and not math.isfinite(float(creation)):
            raise ValueError("Invalid process creation time")
        if phase != "prepared" and (raw["gateway_pid"] <= 0 or creation is None):
            raise ValueError("Incomplete process ownership metadata")
        return cls(
            session_id=str(raw["session_id"]),
            created_at=float(raw["created_at"]),
            gateway_pid=int(raw["gateway_pid"]),
            gateway_port=int(raw["gateway_port"]),
            gateway_host=str(raw.get("gateway_host", "127.0.0.1")),
            https_port=int(raw.get("https_port", DEFAULT_HTTPS_PORT)),
            https_url=str(raw["https_url"]),
            dns_name=str(raw["dns_name"]),
            process_creation_time=(
                float(raw["process_creation_time"])
                if raw.get("process_creation_time") is not None
                else None
            ),
            command_marker=str(raw.get("command_marker", "")),
            mode=str(raw.get("mode", "foreground")),
            core_port=int(raw.get("core_port", DEFAULT_CORE_PORT)),
            phase=phase,
        )

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SessionStatus:
    """Operational status report for CLI and external queries."""

    active: bool
    session_id: str | None = None
    started_at: str | None = None
    gateway_url: str | None = None
    https_url: str | None = None
    tailscale_status: str | None = None
    core_status: str | None = None
    gateway_pid: int | None = None
    mode: str | None = None
    error: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


TailscaleRunner = Callable[[list[str]], tuple[int, str, str]]


class TailscaleCli:
    """Wrapper for the local Tailscale CLI client.

    Never invokes 'serve reset' or 'down'. Uses scoped flags for serve lifecycle.
    """

    def __init__(
        self,
        executable: str | Path | None = None,
        runner: TailscaleRunner | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._executable = executable
        self._runner = runner
        self.timeout = timeout

    def find_cli(self) -> Path | None:
        if self._executable is not None:
            path = Path(self._executable)
            return path if path.is_file() else None

        found = shutil.which("tailscale")
        if found:
            return Path(found)

        standard_windows_paths = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Tailscale"
            / "tailscale.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Tailscale"
            / "tailscale.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Tailscale" / "tailscale.exe",
        ]
        for candidate in standard_windows_paths:
            if candidate.is_file():
                return candidate
        return None

    def _run_command(self, args: list[str]) -> tuple[int, str, str]:
        if self._runner is not None:
            return self._runner(args)

        cli_path = self.find_cli()
        if cli_path is None:
            raise TailscaleNotFoundError(
                "Tailscale CLI binary was not found. Install Tailscale and ensure it is in PATH."
            )

        cmd = [str(cli_path), *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except FileNotFoundError as error:
            raise TailscaleNotFoundError(f"Tailscale executable not found: {cli_path}") from error
        except subprocess.TimeoutExpired as error:
            raise TailscaleError(f"Tailscale command timed out: {' '.join(args)}") from error

    def status(self) -> TailscaleStatus:
        """Inspect the current Tailscale backend status via 'tailscale status --json'."""
        code, stdout, stderr = self._run_command(["status", "--json"])
        if code != 0:
            err_msg = stderr.strip() or stdout.strip()
            raise TailscaleNotRunningError(
                f"Tailscale status check failed (exit code {code}): {err_msg}"
            )
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise TailscaleError("Failed to parse Tailscale status JSON response") from error

        backend_state = data.get("BackendState")
        if backend_state != "Running":
            raise TailscaleNotRunningError(
                f"Tailscale backend is not running (state: {backend_state}). Log in first."
            )

        self_info = data.get("Self", {})
        raw_dns = self_info.get("DNSName", "")
        dns_name = raw_dns.rstrip(".") if raw_dns else None
        hostname = self_info.get("HostName")
        ips = tuple(self_info.get("TailscaleIPs", []))
        magic_dns = data.get("MagicDNSSuffix")

        return TailscaleStatus(
            running=True,
            dns_name=dns_name,
            hostname=hostname,
            tailscale_ips=ips,
            magic_dns_suffix=magic_dns,
            raw=data,
        )

    def serve_status(self) -> dict[str, Any]:
        """Query the current Tailscale Serve configuration via 'tailscale serve status --json'.

        Strict fail-closed: raises TailscaleError on non-zero exit code or malformed JSON.
        """
        code, stdout, stderr = self._run_command(["serve", "status", "--json"])
        if code != 0:
            err_msg = stderr.strip() or stdout.strip()
            raise TailscaleError(f"Failed to query Tailscale Serve status (code {code}): {err_msg}")
        if not stdout.strip():
            raise TailscaleError("Empty Tailscale Serve status response.")
        try:
            data = json.loads(stdout)
            if not isinstance(data, dict):
                raise TailscaleError("Tailscale Serve status must be an object.")
            return data
        except json.JSONDecodeError as error:
            raise TailscaleError(
                f"Failed to parse Tailscale Serve status JSON: {stdout.strip()[:100]}"
            ) from error

    def enable_serve(self, target_url: str, *, https_port: int = DEFAULT_HTTPS_PORT) -> None:
        """Enable Tailscale Serve forwarding HTTPS traffic to a local loopback target.

        Uses '--bg --https=<port>' for background mapping. Never enables Funnel.
        """
        _validate_port(https_port, "https_port")
        args = ["serve", "--bg", f"--https={https_port}", target_url]
        code, stdout, stderr = self._run_command(args)
        if code != 0:
            err_msg = stderr.strip() or stdout.strip()
            raise TailscaleError(f"Failed to enable Tailscale Serve: {err_msg}")

    def disable_serve(self, *, https_port: int = DEFAULT_HTTPS_PORT) -> None:
        """Disable Tailscale Serve for the specific HTTPS port.

        Uses 'tailscale serve --https=<port> off'. Never calls 'serve reset'.
        """
        _validate_port(https_port, "https_port")
        args = ["serve", f"--https={https_port}", "off"]
        code, stdout, stderr = self._run_command(args)
        if code != 0:
            err_msg = stderr.strip() or stdout.strip()
            raise TailscaleError(
                f"Failed to disable Tailscale Serve on port {https_port} (code {code}): {err_msg}"
            )


ProcessInspector = Callable[[int], dict[str, Any] | None]
ProcessTerminator = Callable[[int, bool], bool]


class ProcessVerifier:
    """Verifies that a PID belongs to this application before terminating it.

    Protects against PID reuse by checking creation time and command-line markers.
    """

    def __init__(
        self,
        inspector: ProcessInspector | None = None,
        terminator: ProcessTerminator | None = None,
    ) -> None:
        self._inspector = inspector or self._default_inspector
        self._terminator = terminator or self._default_terminator

    @staticmethod
    def _default_inspector(pid: int) -> dict[str, Any] | None:
        if pid <= 0:
            return None

        if sys.platform == "win32":
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            # Explicit Win32 64-bit argument and return types to prevent pointer truncation
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE

            kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                wintypes.LPFILETIME,
                wintypes.LPFILETIME,
                wintypes.LPFILETIME,
                wintypes.LPFILETIME,
            ]
            kernel32.GetProcessTimes.restype = wintypes.BOOL

            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return None
            creation_val: float | None = None
            try:
                creation = wintypes.FILETIME()
                exit_time = wintypes.FILETIME()
                kernel_time = wintypes.FILETIME()
                user_time = wintypes.FILETIME()
                ok = kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel_time),
                    ctypes.byref(user_time),
                )
                if ok:
                    creation_val = float((creation.dwHighDateTime << 32) | creation.dwLowDateTime)
            finally:
                kernel32.CloseHandle(handle)

            cmd_line = None
            try:
                res = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5.0,
                )
                if res.returncode == 0 and res.stdout.strip():
                    cmd_line = res.stdout.strip()
            except Exception:
                pass

            return {
                "pid": pid,
                "creation_time": creation_val,
                "command_line": cmd_line,
            }
        else:
            try:
                os.kill(pid, 0)
            except OSError:
                return None
            cmd_line = None
            cmd_file = Path(f"/proc/{pid}/cmdline")
            if cmd_file.is_file():
                try:
                    cmd_line = (
                        cmd_file.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
                    )
                except OSError:
                    pass
            creation_time = None
            stat_file = Path(f"/proc/{pid}/stat")
            if stat_file.is_file():
                try:
                    parts = stat_file.read_text().split()
                    if len(parts) > 21:
                        creation_time = float(parts[21])
                except Exception:
                    pass
            return {"pid": pid, "creation_time": creation_time, "command_line": cmd_line}

    @staticmethod
    def _default_terminator(pid: int, force: bool) -> bool:
        if sys.platform == "win32":
            flag = "/F" if force else ""
            res = subprocess.run(
                ["taskkill", "/PID", str(pid), *([flag] if flag else [])],
                capture_output=True,
                check=False,
            )
            return res.returncode == 0
        else:
            sig = signal.SIGKILL if force else signal.SIGTERM
            try:
                os.kill(pid, sig)
                return True
            except OSError:
                return False

    def is_pid_alive(self, pid: int) -> bool:
        info = self._inspector(pid)
        return info is not None

    def verify_ownership(
        self,
        pid: int,
        expected_creation_time: float | None,
        expected_marker: str | None,
    ) -> bool:
        """Verify that the target PID matches expected ownership metadata.

        Strictly fail-closed: returns False if PID does not exist or if expected metadata
        is missing, or if creation time or exact command marker does not match.
        """
        if pid <= 0:
            return False
        if expected_creation_time is None or expected_marker is None:
            LOGGER.warning(
                "Refusing ownership verification: expected metadata is None (fail-closed)"
            )
            return False

        info = self._inspector(pid)
        if info is None:
            return False

        actual_creation = info.get("creation_time")
        if actual_creation is None or actual_creation != expected_creation_time:
            LOGGER.warning(
                "PID %d creation time mismatch: expected %s, found %s",
                pid,
                expected_creation_time,
                actual_creation,
            )
            return False

        actual_cmd = info.get("command_line")
        if not actual_cmd or not _has_exact_argument(actual_cmd, expected_marker):
            LOGGER.warning(
                "PID %d command line does not contain exact expected argument %r: %r",
                pid,
                expected_marker,
                actual_cmd,
            )
            return False

        return True

    def terminate_verified_pid(
        self,
        pid: int,
        expected_creation_time: float | None,
        expected_marker: str | None,
        *,
        timeout_seconds: float = 5.0,
        force: bool = False,
    ) -> bool:
        """Terminate a process only after proving ownership. Fails closed if unverified."""
        if not self.verify_ownership(pid, expected_creation_time, expected_marker):
            raise RemoteSessionOwnershipError(
                f"Cannot prove ownership of PID {pid}. Refusing to terminate unverified process."
            )

        self._terminator(pid, False)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not self.is_pid_alive(pid):
                return True
            time.sleep(0.2)

        if force:
            LOGGER.warning("PID %d did not terminate gracefully; issuing forced termination", pid)
            self._terminator(pid, True)
            time.sleep(0.2)
            return not self.is_pid_alive(pid)

        return not self.is_pid_alive(pid)


def check_core_api(
    host: str = "127.0.0.1", port: int = DEFAULT_CORE_PORT, timeout: float = 1.0
) -> bool:
    """Probe whether the Core API service is listening on loopback."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _is_port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except (OSError, TimeoutError):
        return False


class RemoteSessionManager:
    """Manages the full lifecycle of a private temporary remote session."""

    def __init__(
        self,
        paths: RuntimePaths,
        tailscale_cli: TailscaleCli | None = None,
        process_verifier: ProcessVerifier | None = None,
        gateway_probe: Callable[..., bool] | None = None,
    ) -> None:
        self.paths = paths
        self.tailscale = tailscale_cli or TailscaleCli()
        self.verifier = process_verifier or ProcessVerifier()
        self._gateway_probe = gateway_probe

    @property
    def session_file(self) -> Path:
        return remote_dir(self.paths) / SESSION_FILENAME

    @property
    def session_lock_file(self) -> Path:
        return remote_dir(self.paths) / SESSION_LOCK_FILENAME

    @property
    def stop_sentinel_file(self) -> Path:
        return remote_dir(self.paths) / STOP_FILENAME

    def load_session(self) -> RemoteSessionState | None:
        path = self.session_file
        if not path.exists():
            if list(path.parent.glob(f"{SESSION_FILENAME}.*.tmp")):
                raise RemoteSessionError("Incomplete session journal; recovery evidence preserved.")
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return RemoteSessionState.from_mapping(raw)
        except (OSError, TypeError, json.JSONDecodeError, KeyError, ValueError) as error:
            raise RemoteSessionError(
                "Invalid session state; recovery evidence preserved. Inspect locally before retry."
            ) from error

    def save_session(self, state: RemoteSessionState) -> None:
        directory = remote_dir(self.paths)
        directory.mkdir(parents=True, exist_ok=True)
        path = self.session_file
        temp_path = directory / f"{SESSION_FILENAME}.{uuid4()}.tmp"
        # Never delete a failed write: it may be the newest recovery evidence.
        with temp_path.open("x", encoding="utf-8") as handle:
            json.dump(state.to_mapping(), handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)

    def clear_session(self) -> None:
        for pending in self.session_file.parent.glob(f"{SESSION_FILENAME}.*.tmp"):
            pending.unlink()
        self.session_file.unlink(missing_ok=True)
        self.stop_sentinel_file.unlink(missing_ok=True)

    def is_active(self) -> bool:
        state = self.load_session()
        if state is None:
            return False
        return self.verifier.is_pid_alive(state.gateway_pid)

    def start(
        self,
        *,
        port: int = DEFAULT_PORT,
        https_port: int = DEFAULT_HTTPS_PORT,
        background: bool = False,
        check_core: bool = True,
        timeout: float = DEFAULT_STARTUP_TIMEOUT,
    ) -> RemoteSessionState:
        """Start the temporary remote session: gateway process + Tailscale Serve.

        Journals intent before effects; rolls back selectively or retains recovery
        evidence on failure. Serialized via file lock.
        """
        _validate_port(port, "port")
        _validate_port(https_port, "https_port")

        with _session_lock(self.session_lock_file):
            # 1. Check if a session is already active
            existing = self.load_session()
            if existing is not None:
                if self.verifier.is_pid_alive(existing.gateway_pid):
                    raise RemoteSessionConflictError(
                        f"A remote session is already active (PID {existing.gateway_pid}, "
                        f"session {existing.session_id}, URL: {existing.https_url}). "
                        "Stop it first with 'local-transcriber remote-session stop'."
                    )
                self._stop_state(existing, force=False)

            # 2. Preflight: Remote Gateway configuration
            try:
                gw_config = load_remote_config(self.paths)
            except RemoteGatewayDisabledError as error:
                raise RemoteGatewayDisabledError(
                    "Remote Gateway is disabled or not configured. Create and enable "
                    f"{remote_dir(self.paths) / CONFIG_FILENAME} before starting a session."
                ) from error

            # 3. Preflight: Core API probe (Loopback 8765 single worker)
            if check_core and not check_core_api(port=DEFAULT_CORE_PORT):
                raise RemoteSessionError(
                    f"Core API service is not running on 127.0.0.1:{DEFAULT_CORE_PORT}. "
                    "Start the core service first using 'local-transcriber serve' or "
                    "'scripts/start-local-transcriber.ps1', because the remote gateway relies "
                    "on the core queue worker to process transcription jobs."
                )

            # 4. Preflight: Tailscale status & node name
            ts_status = self.tailscale.status()
            if not ts_status.dns_name:
                raise TailscaleError(
                    "Tailscale node does not have a MagicDNS name configured. "
                    "Ensure MagicDNS is enabled in your tailnet."
                )
            dns_name = ts_status.dns_name.lower()

            allowed_hosts = {h.lower() for h in gw_config.allowed_hosts}
            if dns_name not in allowed_hosts and (
                ts_status.hostname and ts_status.hostname.lower() not in allowed_hosts
            ):
                LOGGER.warning(
                    "Tailscale DNS name %r is not in gateway allowed_hosts (%s). "
                    "Requests through Tailscale Serve will be rejected by the gateway.",
                    dns_name,
                    sorted(allowed_hosts),
                )

            # 5. Strict Tailscale Serve inspection BEFORE start
            serve_data = self.tailscale.serve_status()
            if has_funnel(serve_data):
                raise RemoteSessionConflictError(
                    "Tailscale Funnel is active or configured in Tailscale Serve. "
                    "Funnel is strictly prohibited."
                )
            existing_proxy = get_serve_proxy_target(serve_data, https_port)
            if existing_proxy is not None:
                raise RemoteSessionConflictError(
                    f"Tailscale Serve port {https_port} is already mapped to {existing_proxy}. "
                    "Refusing to overwrite existing mapping."
                )

            # 6. Preflight: Port availability
            if _is_port_in_use("127.0.0.1", port):
                raise RemoteSessionConflictError(
                    f"Gateway loopback port {port} is already in use by another process. "
                    "Choose a different port or terminate the conflicting process."
                )

            session_id = str(uuid4())
            command_marker = f"--session-id={session_id}"
            https_url = (
                f"https://{dns_name}/" if https_port == 443 else f"https://{dns_name}:{https_port}/"
            )

            # Journal intent BEFORE spawning. A crash before recording the PID
            # leaves a prepared record, requiring manual process reconciliation.
            state = RemoteSessionState(
                session_id=session_id,
                created_at=time.time(),
                gateway_pid=0,
                gateway_port=port,
                gateway_host="127.0.0.1",
                https_port=https_port,
                https_url=https_url,
                dns_name=dns_name,
                process_creation_time=None,
                command_marker=command_marker,
                mode="background" if background else "foreground",
                phase="prepared",
            )
            try:
                self.save_session(state)
            except OSError as error:
                raise RemoteSessionError(
                    "Could not persist session intent; no process started."
                ) from error

            process = None
            activation_attempted = False
            try:
                cmd = [
                    sys.executable,
                    "-m",
                    "local_transcriber.cli",
                    "remote-gateway",
                    "serve",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    command_marker,
                ]
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                state = replace(state, gateway_pid=process.pid)
                ctime_deadline = time.time() + 2.0
                while time.time() < ctime_deadline:
                    proc_info = self.verifier._inspector(process.pid)
                    if proc_info and proc_info.get("creation_time") is not None:
                        state = replace(
                            state, process_creation_time=proc_info["creation_time"], phase="gateway"
                        )
                        break
                    time.sleep(0.05)
                self.save_session(state)
                if state.process_creation_time is None:
                    raise RemoteSessionError("Could not obtain gateway process creation time.")

                probe_host = next(iter(gw_config.allowed_hosts))
                probe_identity = next(iter(gw_config.allowed_identities))
                deadline = time.time() + timeout
                while time.time() < deadline:
                    if process.poll() is not None:
                        raise RemoteSessionError("Remote Gateway exited before readiness.")
                    if self._gateway_probe is not None:
                        ready = self._gateway_probe("127.0.0.1", port, probe_host, probe_identity)
                    else:
                        ready = _is_port_in_use("127.0.0.1", port) and check_gateway_readiness(
                            "127.0.0.1",
                            port,
                            allowed_host=probe_host,
                            allowed_identity=probe_identity,
                        )
                    if ready:
                        break
                    time.sleep(0.2)
                else:
                    raise RemoteSessionError("Timed out waiting for Remote Gateway readiness.")

                # Recheck immediately before mutation; other Tailscale clients do
                # not share this application's lock.
                current = self.tailscale.serve_status()
                if has_funnel(current) or get_serve_proxy_target(current, https_port) is not None:
                    raise RemoteSessionConflictError("Serve configuration changed during startup.")
                state = replace(state, phase="activating")
                self.save_session(state)
                activation_attempted = True
                self.tailscale.enable_serve(f"http://127.0.0.1:{port}", https_port=https_port)
                current = self.tailscale.serve_status()
                target = get_serve_proxy_target(current, https_port, dns_name=dns_name)
                if has_funnel(current) or target != f"http://127.0.0.1:{port}":
                    raise RemoteSessionConflictError("Serve activation could not be verified.")
                state = replace(state, phase="active")
                self.save_session(state)
                return state
            except BaseException as error:
                try:
                    if activation_attempted:
                        self._stop_state(state, force=True)
                    else:
                        if process is not None:
                            # The original Popen object retains the OS process
                            # handle; never fall back to an unverified PID kill.
                            if process.poll() is None:
                                process.terminate()
                            process.wait(timeout=5.0)
                        self.clear_session()
                except Exception as rollback_error:
                    raise RemoteSessionError(
                        "Startup failed; rollback incomplete; session file preserved for recovery."
                    ) from rollback_error
                if isinstance(error, OSError):
                    raise RemoteSessionError(
                        "Could not persist session; startup rolled back."
                    ) from error
                raise

    def status(self) -> SessionStatus:
        """Inspect the current session state and live health checks.

        Strictly observational (read-only): never mutates network mapping or deletes state.
        """
        try:
            state = self.load_session()
        except RemoteSessionError as error:
            return SessionStatus(active=False, error=str(error))
        if state is None:
            return SessionStatus(active=False)
        if state.phase != "active":
            return SessionStatus(active=False, error="Incomplete session; recovery required.")

        pid_alive = self.verifier.is_pid_alive(state.gateway_pid)
        if not pid_alive:
            return SessionStatus(
                active=False,
                session_id=state.session_id,
                gateway_pid=state.gateway_pid,
                error="Gateway process is not running (stale session file present). "
                "Run 'local-transcriber remote-session stop' to clean up.",
            )

        if not self.verifier.verify_ownership(
            state.gateway_pid, state.process_creation_time, state.command_marker
        ):
            return SessionStatus(
                active=False,
                session_id=state.session_id,
                gateway_pid=state.gateway_pid,
                error=(
                    f"PID {state.gateway_pid} ownership check failed "
                    "(creation time or marker mismatch)."
                ),
            )

        core_active = check_core_api(port=state.core_port)
        core_msg = "running" if core_active else "unreachable"

        try:
            ts_status = self.tailscale.status()
            ts_msg = "connected" if ts_status.running else "disconnected"
        except Exception:
            ts_msg = "error"

        started_dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(state.created_at))
        return SessionStatus(
            active=True,
            session_id=state.session_id,
            started_at=started_dt,
            gateway_url=f"http://{state.gateway_host}:{state.gateway_port}",
            https_url=state.https_url,
            tailscale_status=ts_msg,
            core_status=core_msg,
            gateway_pid=state.gateway_pid,
            mode=state.mode,
        )

    def stop(self, *, force: bool = False) -> bool:
        """Stop the active remote session, disabling Tailscale Serve and the gateway process.

        Preserves Core API and transcription queue intact. Idempotent. Serialized via file lock.
        Preserves session metadata on any failure for safe diagnosis and recovery.
        """
        with _session_lock(self.session_lock_file):
            state = self.load_session()
            if state is None:
                return False

            self._stop_state(state, force=force)
            return True

    def _stop_state(self, state: RemoteSessionState, *, force: bool) -> None:
        """Reconcile a journal under the lifecycle lock; retain it on every failure."""
        if state.gateway_pid <= 0 or state.process_creation_time is None:
            raise RemoteSessionOwnershipError(
                "Incomplete process journal; session file preserved for manual recovery."
            )
        serve_data = self.tailscale.serve_status()
        target = get_serve_proxy_target(serve_data, state.https_port, dns_name=state.dns_name)
        expected = f"http://{state.gateway_host}:{state.gateway_port}"
        if has_funnel(serve_data) or (target is not None and target != expected):
            raise RemoteSessionConflictError(
                "Serve mapping ownership differs; session file preserved for recovery."
            )
        if target is not None:
            self.tailscale.disable_serve(https_port=state.https_port)
            # Exit code alone is not proof of the resulting network state.
            after = self.tailscale.serve_status()
            if get_serve_proxy_target(after, state.https_port) is not None:
                raise TailscaleError("Serve mapping remains; session file preserved for recovery.")
        if self.verifier.is_pid_alive(state.gateway_pid):
            terminated = self.verifier.terminate_verified_pid(
                state.gateway_pid,
                state.process_creation_time,
                state.command_marker,
                timeout_seconds=5.0,
                force=force,
            )
            if not terminated:
                raise RemoteSessionError(
                    "Gateway did not terminate; session file preserved for recovery."
                )
        self.clear_session()

    def cli_start(
        self,
        *,
        port: int = DEFAULT_PORT,
        https_port: int = DEFAULT_HTTPS_PORT,
        background: bool = False,
        check_core: bool = True,
        timeout: float = DEFAULT_STARTUP_TIMEOUT,
        out: TextIO = sys.stdout,
        err: TextIO = sys.stderr,
    ) -> int:
        """CLI action for 'remote-session start'."""
        try:
            state = self.start(
                port=port,
                https_port=https_port,
                background=background,
                check_core=check_core,
                timeout=timeout,
            )
        except RemoteGatewayDisabledError as error:
            print(f"error: {error}", file=err)
            return 1
        except (RemoteSessionError, TailscaleError, ValueError) as error:
            print(f"error: {error}", file=err)
            return 2

        print("=" * 70, file=out)
        print("Local Transcriber — Private Remote Session Active", file=out)
        print("=" * 70, file=out)
        print(f"HTTPS URL:       {state.https_url}", file=out)
        print(
            f"Gateway Backend: http://{state.gateway_host}:{state.gateway_port} (Loopback only)",
            file=out,
        )
        print(
            f"Core API:        http://127.0.0.1:{state.core_port} (Single queue worker)",
            file=out,
        )
        print(f"Session ID:      {state.session_id}", file=out)
        print("Tailnet:         Connected (Tailscale Serve, Funnel blocked)", file=out)
        print("=" * 70, file=out)

        if background:
            print("Session running in background.", file=out)
            print("To stop: local-transcriber remote-session stop", file=out)
            return 0

        print("Press Ctrl+C in this window to stop the remote session.", file=out)

        def _signal_handler(signum: int, frame: Any) -> None:
            print("\nTermination signal received; stopping remote session...", file=out)
            raise KeyboardInterrupt()

        old_sigint = signal.signal(signal.SIGINT, _signal_handler)
        old_sigterm = signal.signal(signal.SIGTERM, _signal_handler)
        old_sigbreak = None
        if hasattr(signal, "SIGBREAK"):
            old_sigbreak = signal.signal(signal.SIGBREAK, _signal_handler)

        try:
            while True:
                time.sleep(1.0)
                if not self.verifier.is_pid_alive(state.gateway_pid):
                    print("\nGateway process exited.", file=err)
                    break
                if self.stop_sentinel_file.is_file():
                    print("\nStop requested externally.", file=out)
                    break
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)
            if old_sigbreak is not None and hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, old_sigbreak)
            self.stop(force=False)
            print("Remote session stopped cleanly.", file=out)

        return 0

    def cli_status(self, *, as_json: bool = False, out: TextIO = sys.stdout) -> int:
        """CLI action for 'remote-session status'."""
        status = self.status()
        if as_json:
            print(json.dumps(status.to_mapping(), indent=2, sort_keys=True), file=out)
            return 0

        if not status.active:
            msg = "No active remote session."
            if status.error:
                msg += f" Note: {status.error}"
            print(msg, file=out)
            return 0

        print(f"Status:       Active ({status.mode})", file=out)
        print(f"Session ID:   {status.session_id}", file=out)
        print(f"Started at:   {status.started_at}", file=out)
        print(f"HTTPS URL:    {status.https_url}", file=out)
        print(f"Gateway:      {status.gateway_url} (PID {status.gateway_pid})", file=out)
        print(f"Core API:     {status.core_status}", file=out)
        print(f"Tailscale:    {status.tailscale_status}", file=out)
        return 0

    def cli_stop(
        self,
        *,
        force: bool = False,
        out: TextIO = sys.stdout,
        err: TextIO = sys.stderr,
    ) -> int:
        """CLI action for 'remote-session stop'."""
        try:
            stopped = self.stop(force=force)
            if stopped:
                print("Remote session stopped successfully.", file=out)
            else:
                print("No active remote session found.", file=out)
            return 0
        except RemoteSessionOwnershipError as error:
            print(f"error (fail-closed): {error}", file=err)
            return 3
        except RemoteSessionError as error:
            print(f"error: {error}", file=err)
            return 2
