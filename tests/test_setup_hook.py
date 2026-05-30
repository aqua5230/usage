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
    forwarder_target = claude_dir / "usage-statusline-forwarder.py"
    status_file = claude_dir / "usage-status.json"
    hook_source = tmp_path / "hook_source.py"
    forwarder_source = tmp_path / "forwarder_source.py"
    hook_source.write_text("print('hook')\n", encoding="utf-8")
    forwarder_source.write_text("print('forwarder')\n", encoding="utf-8")
    claude_dir.mkdir()
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", hook_target)
    monkeypatch.setattr(setup_hook, "FORWARDER_TARGET", forwarder_target)
    monkeypatch.setattr(setup_hook, "STATUS_FILE", status_file)
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", tmp_path / ".codex" / "config.toml")
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", tmp_path / ".codex" / "usage-backup.json")
    monkeypatch.setattr(
        setup_hook,
        "LEGACY_HOOK_TARGET",
        claude_dir / f"{LEGACY_NAME}-statusline.py",
    )
    monkeypatch.setattr(setup_hook, "LEGACY_STATUS_FILE", claude_dir / f"{LEGACY_NAME}-status.json")
    monkeypatch.setattr(setup_hook, "_resolve_hook_source", lambda: hook_source)
    monkeypatch.setattr(setup_hook, "_resolve_forwarder_source", lambda: forwarder_source)
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
    assert data["statusLine"]["command"] == f"/usr/bin/python3 {setup_hook.FORWARDER_TARGET}"
    assert data["usage"]["previousStatusLine"] == original
    assert hook_target.exists()
    assert setup_hook.FORWARDER_TARGET.exists()


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
    setup_hook.FORWARDER_TARGET.write_text("print('forwarder')\n", encoding="utf-8")
    status_file.write_text("{}", encoding="utf-8")

    exit_code = setup_hook.unsetup()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert data["statusLine"] == previous
    assert "usage" not in data
    assert not hook_target.exists()
    assert not setup_hook.FORWARDER_TARGET.exists()
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


def test_migrate_legacy_usage_skips_bad_utf8_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _, _ = _patch_paths(monkeypatch, tmp_path)
    settings.write_bytes(b"\xff\xfe{")

    setup_hook._migrate_from_legacy_usage()

    assert settings.read_bytes() == b"\xff\xfe{"


def test_load_settings_bad_utf8_raises_system_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _, _ = _patch_paths(monkeypatch, tmp_path)
    settings.write_bytes(b"\xff\xfe{")

    with pytest.raises(SystemExit, match="settings.json"):
        setup_hook._load_settings()


def test_statusline_command_quotes_paths_with_spaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess

    bin_dir = tmp_path / "含 空格" / "bin"
    hook_dir = tmp_path / "Claude Code 小工具"
    bin_dir.mkdir(parents=True)
    hook_dir.mkdir()
    argv_file = tmp_path / "argv.txt"
    fake_python = bin_dir / "python3"
    hook_file = hook_dir / "usage statusline.py"
    fake_python.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$1\" > {setup_hook._shell_arg(str(argv_file))}\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    hook_file.write_text("print('unused')\n", encoding="utf-8")

    monkeypatch.setattr(setup_hook, "_find_system_python", lambda: str(fake_python))
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", hook_file)

    cmd = setup_hook._statusline_command()

    result = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert argv_file.read_text(encoding="utf-8").strip() == str(hook_file)


def test_setup_codex_replaces_only_tui_status_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        """
[other]
status_line = ["external"]

[tui]
status_line = ["old"]

[another]
status_line = ["keep"]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)

    setup_hook._setup_codex()
    content = codex_config.read_text(encoding="utf-8")

    assert '[other]\nstatus_line = ["external"]' in content
    assert '[another]\nstatus_line = ["keep"]' in content
    assert content.count("status_line = [") == 3
    assert '"five-hour-limit"' in content


def test_setup_preserves_initial_backup_on_reinstall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _, _ = _patch_paths(monkeypatch, tmp_path)
    original = {"type": "command", "command": "echo original"}
    replacement = {"type": "command", "command": "echo replacement"}
    settings.write_text(json.dumps({"statusLine": original}), encoding="utf-8")

    assert setup_hook.setup() == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    data["statusLine"] = replacement
    settings.write_text(json.dumps(data), encoding="utf-8")

    assert setup_hook.setup() == 0

    reinstalled = json.loads(settings.read_text(encoding="utf-8"))
    assert reinstalled["usage"]["previousStatusLine"] == original


def test_unsetup_codex_removes_only_tui_status_line_without_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    legacy_backup = tmp_path / ".codex" / "tt-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        """
[other]
status_line = ["external"]

[tui]
status_line = ["old"]

[another]
status_line = ["keep"]
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)
    monkeypatch.setattr(setup_hook, "LEGACY_CODEX_BACKUP", legacy_backup)

    setup_hook._unsetup_codex()
    content = codex_config.read_text(encoding="utf-8")

    assert '[other]\nstatus_line = ["external"]' in content
    assert '[another]\nstatus_line = ["keep"]' in content
    assert "[tui]\nstatus_line" not in content


def test_unsetup_codex_keeps_backup_when_restore_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    legacy_backup = tmp_path / ".codex" / "tt-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text('[tui]\nstatus_line = ["old"]\n', encoding="utf-8")
    codex_backup.write_text(json.dumps({"status_line": ["original"]}), encoding="utf-8")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)
    monkeypatch.setattr(setup_hook, "LEGACY_CODEX_BACKUP", legacy_backup)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(setup_hook, "_atomic_write_text", _boom)

    with pytest.raises(OSError):
        setup_hook._unsetup_codex()

    # A failed restore must leave the backup intact so a retry can still recover.
    assert codex_backup.exists()


def test_read_codex_config_bad_utf8_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    codex_config.write_bytes(b"\xff\xfe[tui]\n")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)

    assert setup_hook._read_codex_config() is None


def test_unsetup_codex_bad_utf8_backup_falls_back_to_empty_status_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    legacy_backup = tmp_path / ".codex" / "tt-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text('[tui]\nstatus_line = ["old"]\n', encoding="utf-8")
    codex_backup.write_bytes(b"\xff\xfe{")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)
    monkeypatch.setattr(setup_hook, "LEGACY_CODEX_BACKUP", legacy_backup)

    setup_hook._unsetup_codex()

    assert "status_line = [\n,\n]" in codex_config.read_text(encoding="utf-8")
    assert not codex_backup.exists()


def test_self_heal_installs_when_no_statusline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, hook_target, _ = _patch_paths(monkeypatch, tmp_path)

    setup_hook.self_heal()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert str(hook_target) in data["statusLine"]["command"]
    assert data["usage"]["selfHealLog"][-1]["action"] == "install_hook"


def test_self_heal_skips_external_statusline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, hook_target, _ = _patch_paths(monkeypatch, tmp_path)
    external = {"type": "command", "command": "python3 ccusage.py"}
    settings.write_text(json.dumps({"statusLine": external}), encoding="utf-8")

    setup_hook.self_heal()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data == {"statusLine": external}
    assert not hook_target.exists()


def test_self_heal_updates_owned_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, hook_target, _ = _patch_paths(monkeypatch, tmp_path)
    source = tmp_path / "hook_source.py"
    source.write_text('__version__ = "1.0"\n', encoding="utf-8")
    monkeypatch.setattr(setup_hook, "_resolve_hook_source", lambda: source)
    settings.write_text(
        json.dumps(
            {"statusLine": {"type": "command", "command": f"/usr/bin/python3 {hook_target}"}}
        ),
        encoding="utf-8",
    )
    hook_target.write_text('__version__ = "0.9"\n', encoding="utf-8")

    setup_hook.self_heal()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert hook_target.read_text(encoding="utf-8") == '__version__ = "1.0"\n'
    assert data["usage"]["selfHealLog"][-1]["action"] == "update_hook"
