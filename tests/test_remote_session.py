"""Unit tests for RemoteSessionManager and Tailscale Serve (Phase 8J Stage 1 Hardened).

All tests run deterministically with mocked CLI runners and process inspectors.
No real network connections or external processes are invoked.
"""

from __future__ import annotations

import ctypes
import io
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from local_transcriber import cli
from local_transcriber import remote_session as session_module
from local_transcriber.config import RuntimePaths
from local_transcriber.remote_gateway import (
    CONFIG_FILENAME,
    REMOTE_DIRNAME,
    RemoteGatewayConfig,
    RemoteGatewayDisabledError,
)
from local_transcriber.remote_session import (
    ProcessVerifier,
    RemoteSessionConflictError,
    RemoteSessionError,
    RemoteSessionManager,
    RemoteSessionOwnershipError,
    RemoteSessionState,
    TailscaleCli,
    TailscaleError,
    TailscaleNotRunningError,
    check_gateway_readiness,
    get_serve_proxy_target,
    has_funnel,
)


@pytest.fixture
def temp_runtime(tmp_path: Path) -> RuntimePaths:
    root = tmp_path / "runtime"
    paths = RuntimePaths(root=root)
    paths.ensure_directories()
    return paths


@pytest.fixture
def enabled_gateway_config(temp_runtime: RuntimePaths) -> RemoteGatewayConfig:
    remote_path = temp_runtime.root / REMOTE_DIRNAME
    remote_path.mkdir(parents=True, exist_ok=True)
    cfg_data = {
        "enabled": True,
        "allowed_identities": ["aluno@example.com"],
        "allowed_hosts": ["notebook.tailnet.ts.net"],
        "allowed_origins": ["https://notebook.tailnet.ts.net"],
        "subject_id": str(uuid4()),
        "model_name": "small",
        "profile": "auto",
        "language": None,
    }
    (remote_path / CONFIG_FILENAME).write_text(json.dumps(cfg_data), encoding="utf-8")
    return RemoteGatewayConfig.from_mapping(cfg_data)


def fake_tailscale_runner(
    *,
    status_code: int = 0,
    status_json: dict[str, Any] | None = None,
    serve_status_json: dict[str, Any] | None = None,
    serve_status_code: int = 0,
    serve_status_raw: str | None = None,
    fail_command: str | None = None,
) -> tuple[Any, list[list[str]]]:
    commands_run: list[list[str]] = []
    current_serve: dict[str, Any] = (
        json.loads(json.dumps(serve_status_json)) if serve_status_json is not None else {}
    )

    default_status = {
        "BackendState": "Running",
        "Self": {
            "DNSName": "notebook.tailnet.ts.net.",
            "HostName": "notebook",
            "TailscaleIPs": ["100.64.0.1"],
        },
        "MagicDNSSuffix": "tailnet.ts.net",
    }

    def runner(args: list[str]) -> tuple[int, str, str]:
        commands_run.append(list(args))
        if fail_command and fail_command in args:
            return 1, "", f"Simulated failure for {fail_command}"
        if args == ["status", "--json"]:
            payload = status_json if status_json is not None else default_status
            return status_code, json.dumps(payload), ""
        if args == ["serve", "status", "--json"]:
            if serve_status_code != 0:
                return serve_status_code, "", "serve status error"
            if serve_status_raw is not None:
                return 0, serve_status_raw, ""
            return 0, json.dumps(current_serve), ""
        if len(args) >= 4 and args[0] == "serve" and args[1] == "--bg":
            target = args[3]
            port_flag = args[2]
            port = port_flag.split("=", 1)[1] if "=" in port_flag else "443"
            current_serve.setdefault("TCP", {})[port] = {"HTTPS": True}
            current_serve.setdefault("Web", {})[f"notebook.tailnet.ts.net:{port}"] = {
                "Handlers": {"/": {"Proxy": target}},
            }
            return 0, "serve updated", ""
        if len(args) >= 3 and args[0] == "serve" and args[2] == "off":
            port_flag = args[1]
            port = port_flag.split("=", 1)[1] if "=" in port_flag else "443"
            if "TCP" in current_serve and port in current_serve["TCP"]:
                del current_serve["TCP"][port]
            if "Web" in current_serve:
                for k in list(current_serve["Web"].keys()):
                    if k.endswith(f":{port}") or k == port:
                        del current_serve["Web"][k]
            return 0, "serve updated", ""
        return 0, "", ""

    return runner, commands_run


def fake_process_inspector(
    processes: dict[int, dict[str, Any]],
) -> Any:
    def inspector(pid: int) -> dict[str, Any] | None:
        return processes.get(pid)

    return inspector


def fake_process_terminator(
    terminated_list: list[tuple[int, bool]],
    processes: dict[int, dict[str, Any]],
) -> Any:
    def terminator(pid: int, force: bool) -> bool:
        terminated_list.append((pid, force))
        processes.pop(pid, None)
        return True

    return terminator


def serve_config(target="http://127.0.0.1:8766", host="notebook.tailnet.ts.net"):
    return {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {f"{host}:443": {"Handlers": {"/": {"Proxy": target}}}},
    }


def recovery_state(**changes):
    return replace(
        RemoteSessionState(
            session_id="synthetic-session",
            created_at=1000.0,
            gateway_pid=4321,
            gateway_port=8766,
            gateway_host="127.0.0.1",
            https_port=443,
            https_url="https://notebook.tailnet.ts.net/",
            dns_name="notebook.tailnet.ts.net",
            process_creation_time=12345.0,
            command_marker="--session-id=synthetic-session",
            mode="background",
        ),
        **changes,
    )


@pytest.fixture
def lifecycle(temp_runtime, enabled_gateway_config, monkeypatch):
    """No subprocesses/sockets: a mutable daemon and process table for fault injection."""
    daemon = {
        "config": {},
        "query_error": False,
        "off_error": False,
        "activation": "ok",
        "off_no_effect": False,
        "off_query_error": False,
    }
    commands = []
    processes = {}
    terminated = []
    base_runner, _ = fake_tailscale_runner()

    def runner(args):
        commands.append(args)
        if args == ["status", "--json"]:
            return base_runner(args)
        if args == ["serve", "status", "--json"]:
            if daemon["query_error"]:
                return 1, "", "query failed"
            return 0, json.dumps(daemon["config"]), ""
        if "--bg" in args:
            # The durable journal must predate a network effect, including failures.
            assert manager.load_session().phase == "activating"
            if daemon["activation"] != "fail_without_effect":
                for key, entries in serve_config().items():
                    daemon["config"].setdefault(key, {}).update(entries)
            if daemon["activation"] == "uncertain_query":
                daemon["query_error"] = True
            if daemon["activation"] != "ok":
                return 1, "", "activation result uncertain"
            return 0, "", ""
        assert args == ["serve", "--https=443", "off"]
        if daemon["off_error"]:
            return 1, "", "off failed"
        if not daemon["off_no_effect"]:
            daemon["config"].get("TCP", {}).pop("443", None)
            for key in list(daemon["config"].get("Web", {})):
                if key.endswith(":443"):
                    del daemon["config"]["Web"][key]
            daemon["config"] = {key: value for key, value in daemon["config"].items() if value}
        if daemon["off_query_error"]:
            daemon["query_error"] = True
        return 0, "", ""

    def spawn(args, **kwargs):
        assert manager.load_session().phase == "prepared"
        processes[4321] = {"creation_time": 12345.0, "command_line": " ".join(args)}
        return SimpleNamespace(
            pid=4321,
            poll=lambda: None if 4321 in processes else 0,
            terminate=lambda: processes.pop(4321, None),
            wait=lambda timeout: 0,
        )

    verifier = ProcessVerifier(
        inspector=fake_process_inspector(processes),
        terminator=fake_process_terminator(terminated, processes),
    )
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
        process_verifier=verifier,
        gateway_probe=lambda *args: True,
    )
    monkeypatch.setattr(session_module, "_is_port_in_use", lambda *args: False)
    monkeypatch.setattr(session_module.subprocess, "Popen", spawn)
    return SimpleNamespace(
        manager=manager,
        daemon=daemon,
        commands=commands,
        processes=processes,
        terminated=terminated,
    )


@pytest.mark.parametrize(
    "failure", ["query_error", "off_error", "off_no_effect", "off_query_error"]
)
def test_stop_network_failure_preserves_and_recovers(lifecycle, failure):
    ctx = lifecycle
    state = ctx.manager.start(check_core=False)
    before = ctx.manager.session_file.read_bytes()
    ctx.daemon[failure] = True
    with pytest.raises(RemoteSessionError):
        ctx.manager.stop()
    assert ctx.manager.session_file.read_bytes() == before
    assert ctx.processes and not ctx.terminated
    ctx.daemon[failure] = False
    ctx.daemon["query_error"] = False
    assert ctx.manager.stop()
    assert not ctx.processes
    assert ctx.manager.load_session() is None
    assert not ctx.manager.stop()
    assert state.phase == "active"


@pytest.mark.parametrize("failure", ["query_error", "off_error", "off_no_effect"])
def test_stale_start_preserves_recovery_on_network_failure(lifecycle, failure):
    ctx = lifecycle
    ctx.manager.save_session(recovery_state())
    before = ctx.manager.session_file.read_bytes()
    ctx.daemon["config"] = serve_config()
    ctx.daemon[failure] = True
    with pytest.raises(RemoteSessionError):
        ctx.manager.start(check_core=False)
    assert ctx.manager.session_file.read_bytes() == before
    assert not ctx.processes
    assert not any("--bg" in cmd for cmd in ctx.commands)
    ctx.daemon[failure] = False
    assert ctx.manager.stop()


@pytest.mark.parametrize("activation", ["fail_without_effect", "fail_with_effect"])
def test_activation_error_rolls_back_only_proven_mapping(lifecycle, activation):
    ctx = lifecycle
    ctx.daemon["activation"] = activation
    with pytest.raises(TailscaleError):
        ctx.manager.start(check_core=False)
    assert ctx.daemon["config"] == {}
    assert not ctx.processes
    assert ctx.manager.load_session() is None
    assert (["serve", "--https=443", "off"] in ctx.commands) == (activation == "fail_with_effect")


@pytest.mark.parametrize("failure", ["query", "off", "termination"])
def test_activation_rollback_failure_retains_journal(lifecycle, monkeypatch, failure):
    ctx = lifecycle
    ctx.daemon["activation"] = "uncertain_query" if failure == "query" else "fail_with_effect"
    ctx.daemon["off_error"] = failure == "off"
    if failure == "termination":
        monkeypatch.setattr(ctx.manager.verifier, "terminate_verified_pid", lambda *a, **k: False)
    with pytest.raises(RemoteSessionError, match="rollback incomplete"):
        ctx.manager.start(check_core=False)
    journal = ctx.manager.load_session()
    assert journal.phase == "activating"
    assert journal.gateway_pid == 4321
    assert ctx.processes
    ctx.daemon["query_error"] = ctx.daemon["off_error"] = False
    if failure != "termination":
        assert ctx.manager.stop()


@pytest.mark.parametrize("phase", ["prepared", "gateway", "activating", "active"])
@pytest.mark.parametrize("failure", ["write", "replace"])
def test_persistence_failures_at_each_phase(lifecycle, monkeypatch, phase, failure):
    ctx = lifecycle
    original_dump = session_module.json.dump
    original_replace = Path.replace
    attempts = []

    def dump(value, handle, **kwargs):
        attempts.append(value["phase"])
        if value["phase"] == phase and failure == "write":
            handle.write('{"partial":')
            raise OSError("injected write failure")
        return original_dump(value, handle, **kwargs)

    def replace_file(path, target):
        if attempts[-1] == phase and failure == "replace":
            raise OSError("injected replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(session_module.json, "dump", dump)
    monkeypatch.setattr(Path, "replace", replace_file)
    with pytest.raises(RemoteSessionError):
        ctx.manager.start(check_core=False)
    assert not ctx.processes
    assert ctx.daemon["config"] == {}
    if phase == "prepared":
        # A failed initial write is evidence, not an absent journal.
        assert list(ctx.manager.session_file.parent.glob("session.json.*.tmp"))
        with pytest.raises(RemoteSessionError, match="Incomplete session journal"):
            ctx.manager.load_session()
        assert not any("--bg" in cmd for cmd in ctx.commands)
    else:
        assert ctx.manager.load_session() is None
    assert (["serve", "--https=443", "off"] in ctx.commands) == (phase == "active")


def test_active_write_and_rollback_failure_keep_previous_intent(lifecycle, monkeypatch):
    ctx = lifecycle
    original_save = ctx.manager.save_session

    def save(state):
        if state.phase == "active":
            raise OSError("disk failure after activation")
        original_save(state)

    monkeypatch.setattr(ctx.manager, "save_session", save)
    ctx.daemon["off_error"] = True
    with pytest.raises(RemoteSessionError, match="rollback incomplete"):
        ctx.manager.start(check_core=False)
    assert ctx.manager.load_session().phase == "activating"
    assert ctx.daemon["config"] == serve_config()
    ctx.daemon["off_error"] = False
    assert ctx.manager.stop()


def test_unrelated_port_survives_start_and_stop(lifecycle):
    ctx = lifecycle
    unrelated = {
        "TCP": {"8443": {"TCPForward": "127.0.0.1:3000"}},
        "Web": {"third.ts.net:8444": {"Handlers": {"/": {"Path": "/static"}}}},
    }
    ctx.daemon["config"] = json.loads(json.dumps(unrelated))
    ctx.manager.start(check_core=False)
    assert ctx.manager.stop()
    assert ctx.daemon["config"] == unrelated


def test_uncertain_activation_with_third_party_preserves_all_evidence(lifecycle, monkeypatch):
    ctx = lifecycle

    def activate(*args, **kwargs):
        ctx.daemon["config"] = unsafe_serve_configs()[3]  # root proxy plus static route
        raise TailscaleError("uncertain activation")

    monkeypatch.setattr(ctx.manager.tailscale, "enable_serve", activate)
    with pytest.raises(RemoteSessionError, match="rollback incomplete"):
        ctx.manager.start(check_core=False)
    assert ctx.manager.load_session().phase == "activating"
    assert not any("off" in cmd for cmd in ctx.commands)
    assert ctx.processes


def test_fsync_failure_prevents_process_and_network_effects(lifecycle, monkeypatch):
    ctx = lifecycle

    def fail(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr(session_module.os, "fsync", fail)
    with pytest.raises(RemoteSessionError, match="no process started"):
        ctx.manager.start(check_core=False)
    assert not ctx.processes
    assert not any("--bg" in cmd for cmd in ctx.commands)
    assert list(ctx.manager.session_file.parent.glob("session.json.*.tmp"))


def unsafe_serve_configs():
    base = serve_config()
    route = json.loads(json.dumps(base))
    route["Web"]["notebook.tailnet.ts.net:443"]["Handlers"]["/third"] = {"Path": "/static"}
    host = json.loads(json.dumps(base))
    host["Web"]["third.ts.net:443"] = {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}
    return [
        {"TCP": {"443": {"TCPForward": "127.0.0.1:3000"}}},
        {"TCP": {"443": {"HTTPS": True}}},
        {"Web": {"notebook.tailnet.ts.net:443": {"Handlers": {"/": {"Text": "third"}}}}},
        route,
        host,
        {**base, "Services": {"svc:third": base}},
        {**base, "Unknown": {}},
        {"TCP": []},
        {"Web": {"invalid": {}}},
        {"TCP": {"443": None}},
        {"TCP": {"443": {"HTTPS": 1}}, "Web": base["Web"]},
        {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {"wrong.ts.net:443": base["Web"]["notebook.tailnet.ts.net:443"]},
        },
    ]


@pytest.mark.parametrize("config", unsafe_serve_configs())
def test_start_rejects_nonexclusive_or_unknown_serve(lifecycle, config):
    ctx = lifecycle
    ctx.daemon["config"] = config
    with pytest.raises(RemoteSessionConflictError):
        ctx.manager.start(check_core=False)
    assert ctx.daemon["config"] == config
    assert not any("--bg" in cmd or "off" in cmd for cmd in ctx.commands)
    assert not ctx.processes


@pytest.mark.parametrize("config", unsafe_serve_configs())
def test_stop_never_deletes_third_party_handlers(lifecycle, config):
    ctx = lifecycle
    ctx.manager.save_session(recovery_state())
    ctx.daemon["config"] = config
    with pytest.raises(RemoteSessionConflictError):
        ctx.manager.stop()
    assert ctx.manager.session_file.exists()
    assert ctx.daemon["config"] == config
    assert not any("off" in cmd for cmd in ctx.commands)


@pytest.mark.parametrize("raw", ["{broken", "null", "[]", "{}", '{"gateway_pid": "bad"}'])
def test_corrupt_session_blocks_mutations_and_reports_status(lifecycle, raw):
    ctx = lifecycle
    ctx.manager.session_file.write_text(raw)
    for operation in (ctx.manager.stop, lambda: ctx.manager.start(check_core=False)):
        with pytest.raises(RemoteSessionError, match="Invalid session state"):
            operation()
        assert ctx.manager.session_file.read_text() == raw
    assert not ctx.commands
    assert "Invalid session state" in ctx.manager.status().error


def test_prepared_journal_requires_manual_reconciliation(lifecycle):
    ctx = lifecycle
    ctx.manager.save_session(
        recovery_state(gateway_pid=0, process_creation_time=None, phase="prepared")
    )
    with pytest.raises(RemoteSessionOwnershipError, match="manual recovery"):
        ctx.manager.stop()
    assert ctx.manager.session_file.exists()
    assert "Incomplete session" in ctx.manager.status().error
    assert not ctx.commands


@pytest.mark.parametrize("phase", ["gateway", "activating"])
def test_recovery_from_interrupted_start(lifecycle, phase):
    ctx = lifecycle
    ctx.manager.save_session(recovery_state(phase=phase))
    ctx.daemon["config"] = serve_config() if phase == "activating" else {}
    # A new manager after restart reads the durable record, with no in-memory startup state.
    recovered = RemoteSessionManager(ctx.manager.paths, ctx.manager.tailscale, ctx.manager.verifier)
    assert recovered.stop()
    assert recovered.load_session() is None
    assert ctx.daemon["config"] == {}


@pytest.mark.parametrize("holder_action", ["start", "stop"])
@pytest.mark.parametrize("contender_action", ["start", "stop"])
def test_concurrent_lifecycle_operations_are_excluded(
    temp_runtime,
    monkeypatch,
    holder_action,
    contender_action,
):
    holder = RemoteSessionManager(temp_runtime)
    contender = RemoteSessionManager(temp_runtime)
    entered, release = threading.Event(), threading.Event()
    outcomes = []

    def blocked_load():
        entered.set()
        assert release.wait(5)
        raise RemoteSessionError("synthetic checkpoint")

    monkeypatch.setattr(holder, "load_session", blocked_load)

    def run():
        try:
            getattr(holder, holder_action)()
        except RemoteSessionError as error:
            outcomes.append(str(error))

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(RemoteSessionConflictError, match="currently in progress"):
            getattr(contender, contender_action)()
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert outcomes == ["synthetic checkpoint"]
    assert contender.stop() is False  # OS lock released even after failure.


def test_win32_ctypes_signatures_preserve_64bit_handle(monkeypatch):
    from ctypes import wintypes

    high_handle = 0x12345678ABCDEF01
    seen = []
    factory = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)

    @factory(wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    def open_process(access, inherit, pid):
        return high_handle

    @factory(wintypes.BOOL, wintypes.HANDLE, *([wintypes.LPFILETIME] * 4))
    def times(handle, creation, exit_time, kernel, user):
        seen.append(("times", handle))
        creation.contents.dwHighDateTime = 123
        creation.contents.dwLowDateTime = 456
        return True

    @factory(wintypes.BOOL, wintypes.HANDLE)
    def close(handle):
        seen.append(("close", handle))
        return True

    kernel = SimpleNamespace(OpenProcess=open_process, GetProcessTimes=times, CloseHandle=close)
    monkeypatch.setattr(session_module.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    monkeypatch.setattr(
        session_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="python --session-id=synthetic-session"
        ),
    )
    result = ProcessVerifier._default_inspector(4321)
    assert open_process.restype is wintypes.HANDLE
    assert open_process.argtypes == [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    assert times.argtypes == [wintypes.HANDLE] + [wintypes.LPFILETIME] * 4
    assert times.restype is wintypes.BOOL
    assert close.argtypes == [wintypes.HANDLE]
    assert close.restype is wintypes.BOOL
    assert seen == [("times", high_handle), ("close", high_handle)]
    assert result["creation_time"] == float((123 << 32) | 456)


@pytest.mark.parametrize("payload", ["", "null", "[]", "true"])
def test_serve_status_rejects_empty_and_nonobject(payload):
    with pytest.raises(TailscaleError):
        TailscaleCli(runner=lambda args: (0, payload, "")).serve_status()


# ==============================================================================
# TailscaleCli Tests
# ==============================================================================


def test_tailscale_status_parsing():
    runner, commands = fake_tailscale_runner()
    cli_client = TailscaleCli(runner=runner)

    status = cli_client.status()
    assert status.running is True
    assert status.dns_name == "notebook.tailnet.ts.net"
    assert status.hostname == "notebook"
    assert status.tailscale_ips == ("100.64.0.1",)
    assert commands == [["status", "--json"]]


def test_tailscale_not_running_error():
    runner, _ = fake_tailscale_runner(status_json={"BackendState": "Stopped"})
    cli_client = TailscaleCli(runner=runner)

    with pytest.raises(TailscaleNotRunningError, match="not running"):
        cli_client.status()


def test_tailscale_status_failure_code():
    runner, _ = fake_tailscale_runner(status_code=1)
    cli_client = TailscaleCli(runner=runner)

    with pytest.raises(TailscaleNotRunningError):
        cli_client.status()


def test_tailscale_serve_status_strict_failure_code():
    runner, _ = fake_tailscale_runner(serve_status_code=1)
    cli_client = TailscaleCli(runner=runner)

    with pytest.raises(TailscaleError, match="Failed to query Tailscale Serve status"):
        cli_client.serve_status()


def test_tailscale_serve_status_strict_invalid_json():
    runner, _ = fake_tailscale_runner(serve_status_raw="invalid { json")
    cli_client = TailscaleCli(runner=runner)

    with pytest.raises(TailscaleError, match="Failed to parse Tailscale Serve status JSON"):
        cli_client.serve_status()


def test_tailscale_serve_status_success():
    expected = {"TCP": {"443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8766"}}}}}
    runner, _ = fake_tailscale_runner(serve_status_json=expected)
    cli_client = TailscaleCli(runner=runner)

    assert cli_client.serve_status() == expected


def test_tailscale_enable_serve_success():
    runner, commands = fake_tailscale_runner()
    cli_client = TailscaleCli(runner=runner)

    cli_client.enable_serve("http://127.0.0.1:8766", https_port=443)
    assert commands == [["serve", "--bg", "--https=443", "http://127.0.0.1:8766"]]


def test_tailscale_enable_serve_invalid_port():
    runner, _ = fake_tailscale_runner()
    cli_client = TailscaleCli(runner=runner)

    with pytest.raises(ValueError, match="https_port must be an integer"):
        cli_client.enable_serve("http://127.0.0.1:8766", https_port=70000)


def test_tailscale_enable_serve_failure():
    runner, _ = fake_tailscale_runner(fail_command="serve")
    cli_client = TailscaleCli(runner=runner)

    with pytest.raises(TailscaleError, match="Failed to enable Tailscale Serve"):
        cli_client.enable_serve("http://127.0.0.1:8766", https_port=443)


def test_tailscale_disable_serve_never_uses_reset():
    runner, commands = fake_tailscale_runner()
    cli_client = TailscaleCli(runner=runner)

    cli_client.disable_serve(https_port=443)
    assert commands == [["serve", "--https=443", "off"]]
    for cmd in commands:
        assert "reset" not in cmd
        assert "down" not in cmd


def test_tailscale_disable_serve_failure():
    runner, _ = fake_tailscale_runner(fail_command="serve")
    cli_client = TailscaleCli(runner=runner)

    with pytest.raises(TailscaleError, match="Failed to disable Tailscale Serve"):
        cli_client.disable_serve(https_port=443)


# ==============================================================================
# ProcessVerifier Tests (PID Reuse & Identity Protection)
# ==============================================================================


def test_process_verifier_ownership_success():
    processes = {
        1234: {
            "pid": 1234,
            "creation_time": 1000.0,
            "command_line": "python -m local_transcriber.cli remote-gateway serve --session-id=abc",
        }
    }
    verifier = ProcessVerifier(inspector=fake_process_inspector(processes))

    assert verifier.verify_ownership(1234, 1000.0, "--session-id=abc") is True


def test_process_verifier_rejects_none_expected_metadata_fail_closed():
    processes = {
        1234: {
            "pid": 1234,
            "creation_time": 1000.0,
            "command_line": "python -m local_transcriber.cli remote-gateway serve --session-id=abc",
        }
    }
    verifier = ProcessVerifier(inspector=fake_process_inspector(processes))

    assert verifier.verify_ownership(1234, None, None) is False
    assert verifier.verify_ownership(1234, 1000.0, None) is False
    assert verifier.verify_ownership(1234, None, "--session-id=abc") is False


def test_process_verifier_rejects_missing_actual_metadata_fail_closed():
    processes = {
        1234: {
            "pid": 1234,
            "creation_time": None,
            "command_line": None,
        }
    }
    verifier = ProcessVerifier(inspector=fake_process_inspector(processes))

    assert verifier.verify_ownership(1234, 1000.0, "--session-id=abc") is False


def test_process_verifier_fails_on_creation_time_mismatch():
    processes = {
        1234: {
            "pid": 1234,
            "creation_time": 2000.0,
            "command_line": "python -m local_transcriber.cli remote-gateway serve --session-id=abc",
        }
    }
    verifier = ProcessVerifier(inspector=fake_process_inspector(processes))

    assert verifier.verify_ownership(1234, 1000.0, "--session-id=abc") is False


def test_process_verifier_exact_marker_rejects_substring():
    processes = {
        1234: {
            "pid": 1234,
            "creation_time": 1000.0,
            "command_line": (
                "python -m local_transcriber.cli remote-gateway serve --session-id=abcdef"
            ),
        }
    }
    verifier = ProcessVerifier(inspector=fake_process_inspector(processes))

    assert verifier.verify_ownership(1234, 1000.0, "--session-id=abc") is False
    assert verifier.verify_ownership(1234, 1000.0, "--session-id=abcdef") is True


def test_process_verifier_exact_marker_accepts_split_flags():
    processes = {
        1234: {
            "pid": 1234,
            "creation_time": 1000.0,
            "command_line": "python -m local_transcriber.cli remote-gateway serve --session-id abc",
        }
    }
    verifier = ProcessVerifier(inspector=fake_process_inspector(processes))

    assert verifier.verify_ownership(1234, 1000.0, "--session-id=abc") is True


def test_terminate_verified_pid_fails_closed():
    processes = {
        9999: {
            "pid": 9999,
            "creation_time": 5000.0,
            "command_line": "unrelated_service.exe",
        }
    }
    terminated = []
    verifier = ProcessVerifier(
        inspector=fake_process_inspector(processes),
        terminator=fake_process_terminator(terminated, processes),
    )

    with pytest.raises(RemoteSessionOwnershipError, match="Refusing to terminate"):
        verifier.terminate_verified_pid(9999, 1000.0, "--session-id=abc")

    assert len(terminated) == 0
    assert 9999 in processes


# ==============================================================================
# Helper Function Tests (Funnel, Proxy Target Extraction)
# ==============================================================================


def test_has_funnel_detection():
    assert has_funnel({}) is False
    assert has_funnel({"Funnel": {"443": True}}) is True
    assert has_funnel({"AllowFunnel": True}) is True
    assert has_funnel({"Web": {"node:443": {"Funnel": True}}}) is True
    assert has_funnel({"TCP": {"443": {"Funnel": True}}}) is True


def test_get_serve_proxy_target_extraction():
    assert get_serve_proxy_target({}, 443) is None
    assert get_serve_proxy_target(serve_config(), 443) == "http://127.0.0.1:8766"


# ==============================================================================
# RemoteSessionManager Lifecycle Tests
# ==============================================================================


def test_session_manager_fails_if_gateway_disabled(temp_runtime: RuntimePaths):
    runner, _ = fake_tailscale_runner()
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
    )

    with pytest.raises(RemoteGatewayDisabledError):
        manager.start(check_core=False)


def test_session_manager_fails_if_core_unreachable(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    runner, _ = fake_tailscale_runner()
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
    )
    monkeypatch.setattr(
        "local_transcriber.remote_session.check_core_api", lambda *args, **kwargs: False
    )

    with pytest.raises(RemoteSessionError, match="Core API service is not running"):
        manager.start(check_core=True)


def test_session_manager_refuses_when_funnel_active(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    runner, _ = fake_tailscale_runner(serve_status_json={"Funnel": {"443": True}})
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
    )
    monkeypatch.setattr(
        "local_transcriber.remote_session.check_core_api", lambda *args, **kwargs: True
    )

    with pytest.raises(RemoteSessionConflictError, match="Funnel is strictly prohibited"):
        manager.start(check_core=False)


def test_session_manager_refuses_when_serve_already_mapped(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    existing_serve = serve_config("http://127.0.0.1:3000")
    runner, _ = fake_tailscale_runner(serve_status_json=existing_serve)
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
    )
    monkeypatch.setattr(
        "local_transcriber.remote_session.check_core_api", lambda *args, **kwargs: True
    )

    with pytest.raises(RemoteSessionConflictError, match="already mapped to http://127.0.0.1:3000"):
        manager.start(check_core=False)


def test_session_manager_start_and_status(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    runner, ts_commands = fake_tailscale_runner()
    processes: dict[int, dict[str, Any]] = {}
    terminated: list[tuple[int, bool]] = []

    verifier = ProcessVerifier(
        inspector=fake_process_inspector(processes),
        terminator=fake_process_terminator(terminated, processes),
    )
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
        process_verifier=verifier,
    )

    fake_pid = 4321
    fake_proc = SimpleNamespace(
        pid=fake_pid,
        poll=lambda: None,
        communicate=lambda: ("", ""),
        terminate=lambda: None,
        wait=lambda timeout=None: None,
    )

    monkeypatch.setattr(
        "local_transcriber.remote_session._is_port_in_use",
        lambda h, p: False if h == "127.0.0.1" and p == 8766 and not processes else True,
    )
    monkeypatch.setattr(
        "local_transcriber.remote_session.check_gateway_readiness",
        lambda *args, **kwargs: True,
    )

    def delayed_process(*args, **kwargs):
        processes[fake_pid] = {
            "pid": fake_pid,
            "creation_time": 12345.0,
            "command_line": " ".join(str(item) for item in args[0]),
        }
        return fake_proc

    monkeypatch.setattr("subprocess.Popen", delayed_process)
    monkeypatch.setattr(
        "local_transcriber.remote_session.check_core_api", lambda *args, **kwargs: True
    )

    state = manager.start(check_core=False, port=8766, https_port=443, background=True)

    assert state.gateway_pid == fake_pid
    assert state.gateway_port == 8766
    assert state.https_url == "https://notebook.tailnet.ts.net/"
    assert manager.is_active() is True

    # Test observational status
    status = manager.status()
    assert status.active is True
    assert status.session_id == state.session_id
    assert status.https_url == "https://notebook.tailnet.ts.net/"
    assert status.gateway_pid == fake_pid


def test_session_manager_start_conflict_when_already_active(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    runner, _ = fake_tailscale_runner()
    processes = {
        5555: {
            "pid": 5555,
            "creation_time": 1000.0,
            "command_line": "python -m local_transcriber.cli remote-gateway serve",
        }
    }
    verifier = ProcessVerifier(inspector=fake_process_inspector(processes))
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
        process_verifier=verifier,
    )

    initial_state = RemoteSessionState(
        session_id=str(uuid4()),
        created_at=1000.0,
        gateway_pid=5555,
        gateway_port=8766,
        gateway_host="127.0.0.1",
        https_port=443,
        https_url="https://notebook.tailnet.ts.net/",
        dns_name="notebook.tailnet.ts.net",
        process_creation_time=1000.0,
        command_marker="remote-gateway",
        mode="background",
    )
    manager.save_session(initial_state)

    with pytest.raises(RemoteSessionConflictError, match="already active"):
        manager.start(check_core=False)


def test_session_manager_rollback_on_tailscale_failure(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    runner, _ = fake_tailscale_runner(fail_command="--bg")
    processes: dict[int, dict[str, Any]] = {}
    terminated: list[tuple[int, bool]] = []

    verifier = ProcessVerifier(
        inspector=fake_process_inspector(processes),
        terminator=fake_process_terminator(terminated, processes),
    )
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
        process_verifier=verifier,
    )

    fake_pid = 6666
    fake_proc = SimpleNamespace(
        pid=fake_pid,
        poll=lambda: None,
        communicate=lambda: ("", ""),
        terminate=lambda: None,
        wait=lambda timeout=None: None,
    )

    def delayed_process(*args, **kwargs):
        processes[fake_pid] = {
            "pid": fake_pid,
            "creation_time": 2000.0,
            "command_line": f"python -m local_transcriber.cli remote-gateway serve {args[0][-1]}",
        }
        return fake_proc

    monkeypatch.setattr("subprocess.Popen", delayed_process)
    monkeypatch.setattr(
        "local_transcriber.remote_session._is_port_in_use",
        lambda h, p: False if not processes else True,
    )
    monkeypatch.setattr(
        "local_transcriber.remote_session.check_gateway_readiness",
        lambda *args, **kwargs: True,
    )

    with pytest.raises(TailscaleError):
        manager.start(check_core=False, port=8766)

    # Gateway process was terminated and session state was cleared
    assert (fake_pid, False) in terminated or (fake_pid, True) in terminated
    assert manager.load_session() is None


def test_session_manager_status_is_strictly_observational(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
):
    runner, ts_commands = fake_tailscale_runner()
    # Process does NOT exist in inspector (simulating crashed process)
    verifier = ProcessVerifier(inspector=fake_process_inspector({}))
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
        process_verifier=verifier,
    )

    stale_state = RemoteSessionState(
        session_id=str(uuid4()),
        created_at=1000.0,
        gateway_pid=9999,
        gateway_port=8766,
        gateway_host="127.0.0.1",
        https_port=443,
        https_url="https://notebook.tailnet.ts.net/",
        dns_name="notebook.tailnet.ts.net",
        process_creation_time=1000.0,
        command_marker="--session-id=abc",
        mode="foreground",
    )
    manager.save_session(stale_state)

    # Calling status must NOT clear session and must NOT disable serve
    status = manager.status()
    assert status.active is False
    assert "Gateway process is not running" in (status.error or "")
    assert manager.session_file.exists() is True
    assert ts_commands == []


def test_session_manager_stop_refuses_if_mapped_to_external_target(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
):
    external_serve = serve_config("http://127.0.0.1:3000")
    runner, ts_commands = fake_tailscale_runner(serve_status_json=external_serve)
    processes = {
        7777: {
            "pid": 7777,
            "creation_time": 3000.0,
            "command_line": "python -m local_transcriber.cli remote-gateway serve --marker",
        }
    }
    terminated = []
    verifier = ProcessVerifier(
        inspector=fake_process_inspector(processes),
        terminator=fake_process_terminator(terminated, processes),
    )
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
        process_verifier=verifier,
    )

    manager.save_session(
        RemoteSessionState(
            session_id=str(uuid4()),
            created_at=3000.0,
            gateway_pid=7777,
            gateway_port=8766,
            gateway_host="127.0.0.1",
            https_port=443,
            https_url="https://notebook.tailnet.ts.net/",
            dns_name="notebook.tailnet.ts.net",
            process_creation_time=3000.0,
            command_marker="--marker",
            mode="background",
        )
    )

    # A foreign mapping is unresolved recovery state, never a successful stop.
    with pytest.raises(RemoteSessionConflictError):
        manager.stop()
    assert manager.session_file.exists()
    assert terminated == []
    for cmd in ts_commands:
        assert cmd != ["serve", "--https=443", "off"]


def test_session_manager_stop_preserves_session_on_termination_failure(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
    monkeypatch: pytest.MonkeyPatch,
):
    runner, _ = fake_tailscale_runner()
    processes = {
        8888: {
            "pid": 8888,
            "creation_time": 4000.0,
            "command_line": "python -m local_transcriber.cli remote-gateway serve --marker",
        }
    }
    # Terminator fails to terminate
    verifier = ProcessVerifier(
        inspector=fake_process_inspector(processes),
        terminator=lambda pid, force: False,
    )
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
        process_verifier=verifier,
    )

    manager.save_session(
        RemoteSessionState(
            session_id=str(uuid4()),
            created_at=4000.0,
            gateway_pid=8888,
            gateway_port=8766,
            gateway_host="127.0.0.1",
            https_port=443,
            https_url="https://notebook.tailnet.ts.net/",
            dns_name="notebook.tailnet.ts.net",
            process_creation_time=4000.0,
            command_marker="--marker",
            mode="background",
        )
    )

    # Monkeypatch sleep in terminate_verified_pid
    monkeypatch.setattr("time.sleep", lambda s: None)

    with pytest.raises(RemoteSessionError, match="session file preserved for recovery"):
        manager.stop()

    assert manager.session_file.exists() is True


def test_session_manager_stop_idempotent_and_clean(
    temp_runtime: RuntimePaths,
    enabled_gateway_config: RemoteGatewayConfig,
):
    initial_serve = serve_config("http://127.0.0.1:8766")
    runner, ts_commands = fake_tailscale_runner(serve_status_json=initial_serve)
    processes = {
        7777: {
            "pid": 7777,
            "creation_time": 3000.0,
            "command_line": "python -m local_transcriber.cli remote-gateway serve --marker",
        }
    }
    terminated: list[tuple[int, bool]] = []
    verifier = ProcessVerifier(
        inspector=fake_process_inspector(processes),
        terminator=fake_process_terminator(terminated, processes),
    )
    manager = RemoteSessionManager(
        temp_runtime,
        tailscale_cli=TailscaleCli(runner=runner),
        process_verifier=verifier,
    )

    # 1. Stop when nothing is running
    assert manager.stop() is False

    # 2. Save active state and stop
    manager.save_session(
        RemoteSessionState(
            session_id=str(uuid4()),
            created_at=3000.0,
            gateway_pid=7777,
            gateway_port=8766,
            gateway_host="127.0.0.1",
            https_port=443,
            https_url="https://notebook.tailnet.ts.net/",
            dns_name="notebook.tailnet.ts.net",
            process_creation_time=3000.0,
            command_marker="--marker",
            mode="background",
        )
    )

    assert manager.stop() is True
    assert (7777, False) in terminated
    assert ["serve", "--https=443", "off"] in ts_commands
    assert manager.load_session() is None

    # 3. Subsequent stop call is idempotent
    assert manager.stop() is False


def test_port_validation_in_start(temp_runtime: RuntimePaths):
    runner, _ = fake_tailscale_runner()
    manager = RemoteSessionManager(temp_runtime, tailscale_cli=TailscaleCli(runner=runner))

    with pytest.raises(ValueError, match="port must be an integer"):
        manager.start(port=0)

    with pytest.raises(ValueError, match="https_port must be an integer"):
        manager.start(https_port=70000)


# ==============================================================================
# CLI Integration Tests
# ==============================================================================


def test_cli_remote_session_status_no_session(
    temp_runtime: RuntimePaths,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "local_transcriber.config.AppConfig.from_env", lambda: SimpleNamespace(paths=temp_runtime)
    )
    parser = cli.build_parser()
    args = parser.parse_args(["remote-session", "status"])

    out = io.StringIO()
    err = io.StringIO()
    rc = cli.run(args, out=out, err=err)

    assert rc == 0
    assert "No active remote session" in out.getvalue()


def test_cli_remote_session_status_json(
    temp_runtime: RuntimePaths,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "local_transcriber.config.AppConfig.from_env", lambda: SimpleNamespace(paths=temp_runtime)
    )
    parser = cli.build_parser()
    args = parser.parse_args(["remote-session", "status", "--json"])

    out = io.StringIO()
    err = io.StringIO()
    rc = cli.run(args, out=out, err=err)

    assert rc == 0
    data = json.loads(out.getvalue())
    assert data["active"] is False


def test_cli_remote_session_stop_idempotent(
    temp_runtime: RuntimePaths,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "local_transcriber.config.AppConfig.from_env", lambda: SimpleNamespace(paths=temp_runtime)
    )
    parser = cli.build_parser()
    args = parser.parse_args(["remote-session", "stop"])

    out = io.StringIO()
    err = io.StringIO()
    rc = cli.run(args, out=out, err=err)

    assert rc == 0
    assert "No active remote session found" in out.getvalue()


def test_check_gateway_readiness_unit(monkeypatch: pytest.MonkeyPatch):
    class FakeResponse:
        def __init__(self, status: int, body: bytes) -> None:
            self.status = status
            self._body = body

        def read(self) -> bytes:
            return self._body

    class FakeConn:
        def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
            self.host = host
            self.port = port

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            self.method = method
            self.path = path
            self.headers = headers

        def getresponse(self) -> FakeResponse:
            if self.headers.get("Tailscale-User-Login") == "allowed@example.com":
                return FakeResponse(200, b'{"status": "ok"}')
            return FakeResponse(401, b'{"detail": "missing remote identity"}')

        def close(self) -> None:
            pass

    monkeypatch.setattr("http.client.HTTPConnection", FakeConn)

    assert (
        check_gateway_readiness(
            "127.0.0.1",
            8766,
            allowed_host="notebook.ts.net",
            allowed_identity="allowed@example.com",
        )
        is True
    )
    assert (
        check_gateway_readiness(
            "127.0.0.1",
            8766,
            allowed_host="notebook.ts.net",
            allowed_identity="unauthorized@example.com",
        )
        is False
    )
