"""Unit and synthetic validation tests for the zero-touch launcher scripts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_cmd_launcher_properties():
    cmd_file = ROOT / "Iniciar-LocalTranscriber-Remoto.cmd"
    assert cmd_file.is_file(), "Iniciar-LocalTranscriber-Remoto.cmd must exist at repository root"
    content = cmd_file.read_text(encoding="utf-8")
    assert "chcp 65001" in content
    assert "powershell.exe" in content
    assert "start-all-remote.ps1" in content

    local_cmd = ROOT / "Iniciar-LocalTranscriber.cmd"
    assert local_cmd.is_file(), "Iniciar-LocalTranscriber.cmd must exist at repository root"
    local_content = local_cmd.read_text(encoding="utf-8")
    assert "chcp 65001" in local_content
    assert "start-local-transcriber.ps1" in local_content

    alias_cmd = ROOT / "Iniciar-LocalTranscriber-Local.cmd"
    assert alias_cmd.is_file(), "Iniciar-LocalTranscriber-Local.cmd must exist at repository root"


def test_start_all_remote_script_properties():
    ps1_file = ROOT / "scripts" / "start-all-remote.ps1"
    assert ps1_file.is_file(), "scripts/start-all-remote.ps1 must exist"
    content = ps1_file.read_text(encoding="utf-8")
    assert "System.Text.UTF8Encoding" in content
    assert "tailscale status --json" in content
    assert "subjects list" in content
    assert "remote-session" in content
    assert "remote-session stop" in content
    assert "api/health" in content
    assert "Read-Host" in content
    assert "finally" in content


def test_start_local_script_properties():
    ps1_file = ROOT / "scripts" / "start-local-transcriber.ps1"
    assert ps1_file.is_file(), "scripts/start-local-transcriber.ps1 must exist"
    content = ps1_file.read_text(encoding="utf-8")
    assert "OpenBrowser" in content
    assert "api/health" in content
    assert "Read-Host" in content
    assert "serve" in content


def test_utf8_no_bom_roundtrip(tmp_path: Path):
    # Verify PowerShell [System.Text.UTF8Encoding]::new($false) produces UTF-8 without BOM
    target_json = tmp_path / "gateway.json"
    target_str = str(target_json).replace("\\", "\\\\")
    ps_cmd = (
        "$utf8NoBom = [System.Text.UTF8Encoding]::new($false); "
        "$data = @{ enabled = $true; allowed_identities = @('u@ex.com') } | ConvertTo-Json; "
        f"[System.IO.File]::WriteAllText('{target_str}', $data, $utf8NoBom)"
    )
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert target_json.is_file()

    # Read binary bytes: must NOT start with UTF-8 BOM \xef\xbb\xbf
    raw_bytes = target_json.read_bytes()
    assert not raw_bytes.startswith(b"\xef\xbb\xbf"), "gateway.json must NOT contain a UTF-8 BOM"

    # Strict json.loads without BOM handling
    parsed = json.loads(raw_bytes.decode("ascii", errors="ignore"))
    assert parsed["enabled"] is True
    assert parsed["allowed_identities"] == ["u@ex.com"]
