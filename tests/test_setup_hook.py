# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

import session_hooks
import setup_hook
from tests.helpers import SetupHookPaths, expected_statusline_command

LEGACY_NAME = "usag"


@pytest.fixture
def setup_paths(patch_setup_hook_paths: Callable[..., SetupHookPaths]) -> SetupHookPaths:
    return patch_setup_hook_paths(legacy_name=LEGACY_NAME)


def test_setup_creates_new_settings_with_usage_statusline(setup_paths: SetupHookPaths) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target

    exit_code = setup_hook.setup()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert data["statusLine"]["type"] == "command"
    assert data["statusLine"]["command"] == expected_statusline_command(hook_target)
    assert hook_target.exists()


def test_setup_backs_up_existing_statusline_and_is_idempotent(
    setup_paths: SetupHookPaths,
) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    original = {"type": "command", "command": "echo original"}
    settings.write_text(json.dumps({"statusLine": original}), encoding="utf-8")

    assert setup_hook.setup() == 0
    assert setup_hook.setup() == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == expected_statusline_command(
        setup_hook.FORWARDER_TARGET
    )
    assert data["usage"]["previousStatusLine"] == original
    assert hook_target.exists()
    assert setup_hook.FORWARDER_TARGET.exists()


def test_unsetup_restores_backup_and_removes_hook_files(setup_paths: SetupHookPaths) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    status_file = setup_paths.status_file
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
    setup_paths: SetupHookPaths,
) -> None:
    _ = setup_paths

    assert setup_hook.unsetup() == 0
    assert setup_hook._is_usage_hook({"command": "python3 /tmp/usage-statusline.py"})
    assert not setup_hook._is_usage_hook({"command": "python3 /tmp/other.py"})


def test_migration_removes_legacy_files_and_moves_backup(setup_paths: SetupHookPaths) -> None:
    settings = setup_paths.settings
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


def test_migrate_legacy_usage_skips_bad_utf8_settings(setup_paths: SetupHookPaths) -> None:
    settings = setup_paths.settings
    settings.write_bytes(b"\xff\xfe{")

    setup_hook._migrate_from_legacy_usage()

    assert settings.read_bytes() == b"\xff\xfe{"


def test_load_settings_bad_utf8_raises_system_exit(setup_paths: SetupHookPaths) -> None:
    settings = setup_paths.settings
    settings.write_bytes(b"\xff\xfe{")

    with pytest.raises(SystemExit, match="settings.json"):
        setup_hook._load_settings()


@pytest.mark.skipif(
    sys.platform == "win32", reason="exercises POSIX shell quoting via /bin/sh"
)
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


def test_find_system_python_prefers_usr_bin_over_bundled_app_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", "/Applications/usage.app/Contents/MacOS/python")
    monkeypatch.setattr(
        "setup_hook.os.path.exists",
        lambda path: path == "/usr/bin/python3",
    )

    assert setup_hook._find_system_python() == "/usr/bin/python3"


def test_find_system_python_uses_current_interpreter_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\\Program Files\\Python\\python.exe")

    assert setup_hook._find_system_python() == r"C:\\Program Files\\Python\\python.exe"


def test_windows_hook_commands_use_double_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        setup_hook, "_find_system_python", lambda: r"C:\Program Files\Python\python.exe"
    )
    monkeypatch.setattr(
        setup_hook,
        "HOOK_TARGET",
        Path(r"C:\Users\test user\.claude\usage-statusline.py"),
    )
    monkeypatch.setattr(
        setup_hook,
        "FORWARDER_TARGET",
        Path(r"C:\Users\test user\.claude\usage-statusline-forwarder.py"),
    )

    assert setup_hook._statusline_command() == (
        '"C:/Program Files/Python/python.exe" '
        '"C:/Users/test user/.claude/usage-statusline.py"'
    )
    assert setup_hook._forwarder_command() == (
        '"C:/Program Files/Python/python.exe" '
        '"C:/Users/test user/.claude/usage-statusline-forwarder.py"'
    )


def test_windows_statusline_migration_rewrites_legacy_backslash_paths(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        setup_hook, "_find_system_python", lambda: r"C:\Program Files\Python\python.exe"
    )
    command = (
        r"C:\Program Files\Python\python.exe "
        rf"{setup_paths.hook_target}".replace("/", "\\")
    )
    setup_paths.settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": command}}),
        encoding="utf-8",
    )

    setup_hook._migrate_windows_statusline_command_if_needed()

    data = json.loads(setup_paths.settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == expected_statusline_command(setup_paths.hook_target)
    assert data["usage"]["selfHealLog"][-1]["action"] == "migrate_windows_statusline"


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


def test_setup_codex_ignores_tui_text_outside_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        '''
note = """
[tui]
"""
# [tui]
'''.lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)

    setup_hook._setup_codex()
    content = codex_config.read_text(encoding="utf-8")
    parsed = tomllib.loads(content)

    assert content.count("[tui]") == 3
    assert parsed["note"] == "[tui]\n"
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE
    assert '"five-hour-limit"' in content


def test_setup_preserves_initial_backup_on_reinstall(
    setup_paths: SetupHookPaths,
) -> None:
    settings = setup_paths.settings
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


def test_setup_codex_warns_when_existing_config_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    codex_config.write_bytes(b"\xff\xfe[tui]\n")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)

    setup_hook._setup_codex()

    assert "Codex" in capsys.readouterr().out


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

    content = codex_config.read_text(encoding="utf-8")
    assert "status_line = []" in content
    assert tomllib.loads(content)["tui"]["status_line"] == []
    assert not codex_backup.exists()


def test_self_heal_installs_when_no_statusline(setup_paths: SetupHookPaths) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target

    session_hooks.self_heal()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data["statusLine"]["command"] == expected_statusline_command(hook_target)
    assert data["usage"]["selfHealLog"][-1]["action"] == "install_hook"


def test_self_heal_skips_external_statusline(setup_paths: SetupHookPaths) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    external = {"type": "command", "command": "python3 ccusage.py"}
    settings.write_text(json.dumps({"statusLine": external}), encoding="utf-8")

    session_hooks.self_heal()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data == {"statusLine": external}
    assert not hook_target.exists()


def test_self_heal_updates_owned_hook(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    source = setup_paths.hook_source
    source.write_text('__version__ = "1.0"\n', encoding="utf-8")
    monkeypatch.setattr(setup_hook, "_resolve_hook_source", lambda: source)
    settings.write_text(
        json.dumps(
            {"statusLine": {"type": "command", "command": f"/usr/bin/python3 {hook_target}"}}
        ),
        encoding="utf-8",
    )
    hook_target.write_text('__version__ = "0.9"\n', encoding="utf-8")

    session_hooks.self_heal()
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert hook_target.read_text(encoding="utf-8") == '__version__ = "1.0"\n'
    assert data["usage"]["selfHealLog"][-1]["action"] == "update_hook"


def test_self_heal_migrates_bundled_python_commands(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
    tmp_path: Path,
) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    resume_source = tmp_path / "usage_session_resume.py"
    resume_source.write_text('__version__ = "1.0"\n', encoding="utf-8")
    monkeypatch.setattr(session_hooks, "_resolve_resume_source", lambda: resume_source)
    settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": f"/Applications/usage.app/Contents/MacOS/python {hook_target}",
                },
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": session_hooks.RESUME_MATCHER,
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/Applications/usage.app/Contents/MacOS/python "
                                        f"{resume_source}"
                                    ),
                                }
                            ],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    session_hooks._migrate_bundled_python_commands_if_needed()

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == expected_statusline_command(hook_target)
    hooks = data["hooks"]["SessionStart"][0]["hooks"]
    assert hooks[0]["command"] == expected_statusline_command(resume_source)
    migrate_entries = [
        entry
        for entry in data["usage"]["selfHealLog"]
        if entry["action"] == "migrate_bundled_python"
    ]
    assert migrate_entries
    assert "statusLine=direct" in migrate_entries[-1]["detail"]
    assert "resume" in migrate_entries[-1]["detail"]


def test_self_heal_keeps_correct_python_commands_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
    tmp_path: Path,
) -> None:
    settings = setup_paths.settings
    hook_target = setup_paths.hook_target
    resume_source = tmp_path / "usage_session_resume.py"
    resume_source.write_text('__version__ = "1.0"\n', encoding="utf-8")
    monkeypatch.setattr(session_hooks, "_resolve_resume_source", lambda: resume_source)
    settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": f"/usr/bin/python3 {hook_target}",
                },
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": session_hooks.RESUME_MATCHER,
                            "hooks": [
                                {"type": "command", "command": f"/usr/bin/python3 {resume_source}"}
                            ],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    session_hooks._migrate_bundled_python_commands_if_needed()

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["statusLine"]["command"] == f"/usr/bin/python3 {hook_target}"
    assert (
        data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        == f"/usr/bin/python3 {resume_source}"
    )
    assert "usage" not in data
