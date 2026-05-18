from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import setup_hook

LEGACY_NAME = "usag"


def _patch_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path, Path]:
    claude_dir = tmp_path / ".claude"
    settings = claude_dir / "settings.json"
    hook_target = claude_dir / "usage-statusline.py"
    status_file = claude_dir / "usage-status.json"
    hook_source = tmp_path / "hook_source.py"
    hook_source.write_text("print('hook')\n", encoding="utf-8")
    claude_dir.mkdir()
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", hook_target)
    monkeypatch.setattr(setup_hook, "STATUS_FILE", status_file)
    monkeypatch.setattr(
        setup_hook,
        "LEGACY_HOOK_TARGET",
        claude_dir / f"{LEGACY_NAME}-statusline.py",
    )
    monkeypatch.setattr(setup_hook, "LEGACY_STATUS_FILE", claude_dir / f"{LEGACY_NAME}-status.json")
    monkeypatch.setattr(setup_hook, "_resolve_hook_source", lambda: hook_source)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/python3")
    return settings, hook_target, status_file


def test_setup_creates_new_settings_with_usage_statusline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, hook_target, _ = _patch_paths(monkeypatch, tmp_path)

    exit_code = setup_hook.setup()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert data["statusLine"]["type"] == "command"
    assert str(hook_target) in data["statusLine"]["command"]
    assert hook_target.exists()


def test_setup_backs_up_existing_statusline_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, hook_target, _ = _patch_paths(monkeypatch, tmp_path)
    original = {"type": "command", "command": "echo original"}
    settings.write_text(json.dumps({"statusLine": original}), encoding="utf-8")

    assert setup_hook.setup() == 0
    assert setup_hook.setup() == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == f"/usr/bin/python3 {hook_target}"
    assert data["usage"]["previousStatusLine"] == original


def test_unsetup_restores_backup_and_removes_hook_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, hook_target, status_file = _patch_paths(monkeypatch, tmp_path)
    previous = {"type": "command", "command": "echo original"}
    settings.write_text(
        json.dumps(
            {
                "statusLine": {"type": "command", "command": f"/usr/bin/python3 {hook_target}"},
                "usage": {"previousStatusLine": previous},
            }
        ),
        encoding="utf-8",
    )
    hook_target.write_text("print('hook')\n", encoding="utf-8")
    status_file.write_text("{}", encoding="utf-8")

    exit_code = setup_hook.unsetup()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert data["statusLine"] == previous
    assert "usage" not in data
    assert not hook_target.exists()
    assert not status_file.exists()


def test_unsetup_without_install_is_safe_and_is_usage_hook_detects_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_paths(monkeypatch, tmp_path)

    assert setup_hook.unsetup() == 0
    assert setup_hook._is_usage_hook({"command": "python3 /tmp/usage-statusline.py"})
    assert not setup_hook._is_usage_hook({"command": "python3 /tmp/other.py"})


def test_migration_removes_legacy_files_and_moves_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _, _ = _patch_paths(monkeypatch, tmp_path)
    legacy_hook = setup_hook.LEGACY_HOOK_TARGET
    legacy_status = setup_hook.LEGACY_STATUS_FILE
    legacy_hook.write_text("legacy hook\n", encoding="utf-8")
    legacy_status.write_text("{}", encoding="utf-8")
    previous = {"type": "command", "command": "echo original"}
    settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": f"python3 {legacy_hook}",
                },
                LEGACY_NAME: {"previousStatusLine": previous},
            }
        ),
        encoding="utf-8",
    )

    setup_hook._migrate_from_legacy_usage()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert not legacy_hook.exists()
    assert not legacy_status.exists()
    assert "statusLine" not in data
    assert LEGACY_NAME not in data
    assert data["usage"]["previousStatusLine"] == previous


def test_statusline_command_quotes_paths_with_spaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """專案 clone 在含空格的路徑（例如中文資料夾）時，
    產生的 statusLine command 必須能被 /bin/sh -c 正確解析。"""
    import shlex
    import subprocess

    spaced_dir = tmp_path / "claude code小工具"
    spaced_dir.mkdir()
    spaced_python = spaced_dir / "python3"
    spaced_python.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    spaced_python.chmod(0o755)

    spaced_hook = spaced_dir / "usage-statusline.py"
    spaced_hook.write_text("import sys; sys.exit(0)\n", encoding="utf-8")

    monkeypatch.setattr(shutil, "which", lambda _: str(spaced_python))
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", spaced_hook)

    cmd = setup_hook._statusline_command()

    # 兩段路徑都應該被 shlex 安全處理過
    tokens = shlex.split(cmd)
    assert tokens == [str(spaced_python), str(spaced_hook)]

    # /bin/sh -c 真的能跑（即不會被空格切碎）
    result = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
