# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import shutil
import sys
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from installer import session_hooks, setup_hook
from tests.helpers import SetupHookPaths, expected_statusline_command

LEGACY_NAME = "usag"


def test_windows_cli_output_reconfigures_both_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stream:
        def __init__(self) -> None:
            self.encodings: list[str] = []

        def reconfigure(self, *, encoding: str) -> None:
            self.encodings.append(encoding)

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr(setup_hook, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    setup_hook.configure_windows_utf8_output()

    assert stdout.encodings == ["utf-8"]
    assert stderr.encodings == ["utf-8"]


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


def test_save_settings_preserves_symlink_and_updates_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings_link = tmp_path / ".claude" / "settings.json"
    settings_target = tmp_path / "dotfiles" / "settings.json"
    settings_link.parent.mkdir()
    settings_target.parent.mkdir()
    settings_target.write_text('{"original": true}\n', encoding="utf-8")
    settings_link.symlink_to(settings_target)
    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings_link)

    setup_hook._save_settings({"updated": True})

    assert settings_link.is_symlink()
    assert json.loads(settings_target.read_text(encoding="utf-8")) == {"updated": True}


def test_append_self_heal_log_writes_under_settings_lock(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
) -> None:
    lock_fds: list[int] = []

    @contextmanager
    def record_lock(lock_fd: int) -> Iterator[None]:
        lock_fds.append(lock_fd)
        yield

    monkeypatch.setattr(session_hooks, "_exclusive_lock", record_lock)

    session_hooks._append_self_heal_log("test_action", "test detail")

    data = json.loads(setup_paths.settings.read_text(encoding="utf-8"))
    assert lock_fds
    assert (setup_paths.settings.parent / "usage-settings.lock").exists()
    assert data["usage"]["selfHealLog"][-1]["action"] == "test_action"


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
        "installer.setup_hook.os.path.exists",
        lambda path: path == "/usr/bin/python3",
    )

    assert setup_hook._find_system_python() == "/usr/bin/python3"


def test_find_system_python_uses_current_interpreter_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\\Program Files\\Python\\python.exe")

    assert setup_hook._find_system_python() == r"C:\\Program Files\\Python\\python.exe"


def test_find_system_python_skips_unusable_windows_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    candidates = {
        "python": r"C:\\Users\\test\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe",
        "py": r"C:\\Program Files\\Python\\py.exe",
    }
    monkeypatch.setattr(shutil, "which", candidates.get)
    monkeypatch.setattr(
        setup_hook,
        "_is_working_python",
        lambda path: path == candidates["py"],
    )

    assert setup_hook._find_system_python() == candidates["py"]


def test_find_system_python_uses_working_windows_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    candidate = r"C:\\Program Files\\Python\\python.exe"
    monkeypatch.setattr(shutil, "which", lambda name: candidate if name == "python" else None)
    monkeypatch.setattr(setup_hook, "_is_working_python", lambda path: path == candidate)

    assert setup_hook._find_system_python() == candidate


def test_find_system_python_avoids_non_ascii_windows_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\\專案\\usage\\.venv\\Scripts\\python.exe")
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: r"C:\\Program Files\\Python\\python.exe" if name == "python" else None,
    )
    monkeypatch.setattr(setup_hook, "_is_working_python", lambda _path: True)

    assert setup_hook._find_system_python() == r"C:\\Program Files\\Python\\python.exe"


def test_setup_fails_when_no_windows_python_is_available(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(SystemExit, match="Python"):
        setup_hook.setup()

    assert not setup_paths.settings.exists()


def test_setup_fails_for_non_ascii_windows_hook_target(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    hook_target = tmp_path / "使用者" / ".claude" / "usage-statusline.py"
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", hook_target)

    with pytest.raises(SystemExit, match="ASCII"):
        setup_hook.setup()

    assert not setup_paths.settings.exists()


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


def test_agy_windows_command_path_converts_ampersand_path_to_short_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = r"C:\Users\R&D\Python\python.exe"
    short_path = r"C:\Users\R~1\PYTHON~1\python.exe"
    monkeypatch.setattr(setup_hook, "_get_windows_short_path", lambda _path: short_path)

    assert setup_hook._agy_windows_command_path(value, "Python interpreter") == short_path


def test_agy_windows_command_path_rejects_unsafe_short_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = r"C:\Users\R&D\Python\python.exe"
    short_path = r"C:\Users\R&D\PYTHON~1\python.exe"
    monkeypatch.setattr(setup_hook, "_get_windows_short_path", lambda _path: short_path)

    with pytest.raises(RuntimeError, match=r"still contains unsafe cmd\.exe characters '&'"):
        setup_hook._agy_windows_command_path(value, "Python interpreter")


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


def test_windows_statusline_migration_rewrites_non_ascii_interpreter(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        setup_hook, "_find_system_python", lambda: r"C:\\Program Files\\Python\\python.exe"
    )
    setup_paths.settings.write_text(
        json.dumps(
            {
                "statusLine": {
                    "type": "command",
                    "command": (
                        r"C:/Users/USER/Desktop/GitHub專案/usage/.venv/Scripts/python.exe "
                        f"{setup_paths.hook_target}"
                    ),
                }
            }
        ),
        encoding="utf-8",
    )

    setup_hook._migrate_windows_statusline_command_if_needed()

    data = json.loads(setup_paths.settings.read_text(encoding="utf-8"))
    command = data["statusLine"]["command"]
    assert command == expected_statusline_command(setup_paths.hook_target)
    assert command.isascii()


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


def test_setup_codex_adds_tui_before_existing_subtable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        "[tui.model_availability_nux]\nseen = true\n", encoding="utf-8"
    )
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)

    setup_hook._setup_codex()

    content = codex_config.read_text(encoding="utf-8")
    parsed = tomllib.loads(content)
    assert content.index("[tui]") < content.index("[tui.model_availability_nux]")
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE
    assert parsed["tui"]["model_availability_nux"]["seen"] is True
    assert setup_hook.is_codex_setup()


def test_setup_codex_inserts_into_existing_tui_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text("[tui]\nanimations = false\n", encoding="utf-8")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)

    setup_hook._setup_codex()

    content = codex_config.read_text(encoding="utf-8")
    parsed = tomllib.loads(content)
    assert content.count("[tui]") == 1
    assert parsed["tui"]["animations"] is False
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE
    assert setup_hook.is_codex_setup()


def test_insert_tui_status_line_after_top_level_dotted_key() -> None:
    content = "tui.animations = false\n"

    updated = setup_hook._insert_tui_status_line(
        content, setup_hook._status_line_toml(setup_hook.CODEX_STATUS_LINE)
    )

    parsed = tomllib.loads(updated)
    assert parsed["tui"]["animations"] is False
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE


def test_insert_tui_status_line_before_table_after_dotted_key() -> None:
    content = "tui.animations = false\n\n[features]\nhooks = true\n"

    updated = setup_hook._insert_tui_status_line(
        content, setup_hook._status_line_toml(setup_hook.CODEX_STATUS_LINE)
    )

    parsed = tomllib.loads(updated)
    assert updated.index("tui.status_line") < updated.index("[features]")
    assert parsed["tui"]["animations"] is False
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE
    assert parsed["features"]["hooks"] is True


def test_insert_tui_status_line_before_subtable_after_other_table() -> None:
    content = (
        "[features]\nhooks = true\n"
        "[tui.model_availability_nux]\nseen = true\n"
    )

    updated = setup_hook._insert_tui_status_line(
        content, setup_hook._status_line_toml(setup_hook.CODEX_STATUS_LINE)
    )

    parsed = tomllib.loads(updated)
    assert updated.index("[tui]") < updated.index("[tui.model_availability_nux]")
    assert parsed["features"]["hooks"] is True
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE
    assert parsed["tui"]["model_availability_nux"]["seen"] is True


def test_insert_tui_status_line_keeps_quoted_dotted_key_unchanged() -> None:
    content = 'tui."my key" = 1\n'

    updated = setup_hook._insert_tui_status_line(
        content, setup_hook._status_line_toml(setup_hook.CODEX_STATUS_LINE)
    )

    tomllib.loads(updated)
    assert updated == content


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


@pytest.mark.parametrize("backup_before", [None, b'{"status_line": ["original"]}\n'])
def test_setup_codex_upgrades_legacy_status_line_without_changing_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backup_before: bytes | None
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        f'[tui]\nstatus_line = {json.dumps(setup_hook.LEGACY_CODEX_STATUS_LINES[0])}\n',
        encoding="utf-8",
    )
    if backup_before is not None:
        codex_backup.write_bytes(backup_before)
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)

    setup_hook._setup_codex()

    parsed = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE
    if backup_before is None:
        assert not codex_backup.exists()
    else:
        assert codex_backup.read_bytes() == backup_before


def test_setup_codex_backs_up_custom_status_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text('[tui]\nstatus_line = ["model"]\n', encoding="utf-8")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)

    setup_hook._setup_codex()

    parsed = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE
    assert json.loads(codex_backup.read_text(encoding="utf-8")) == {"status_line": ["model"]}


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
status_line = [
    "project",
    "five-hour-limit",
    "weekly-limit",
    "context-remaining",
    "model-with-reasoning",
]

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


def test_unsetup_codex_restores_backup_from_legacy_status_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    legacy_backup = tmp_path / ".codex" / "tt-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        f'[tui]\nstatus_line = {json.dumps(setup_hook.LEGACY_CODEX_STATUS_LINES[0])}\n',
        encoding="utf-8",
    )
    codex_backup.write_text(json.dumps({"status_line": ["original"]}), encoding="utf-8")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)
    monkeypatch.setattr(setup_hook, "LEGACY_CODEX_BACKUP", legacy_backup)

    setup_hook._unsetup_codex()

    assert tomllib.loads(codex_config.read_text(encoding="utf-8"))["tui"]["status_line"] == [
        "original"
    ]
    assert not codex_backup.exists()


def test_unsetup_codex_keeps_backup_when_restore_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    legacy_backup = tmp_path / ".codex" / "tt-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        f'[tui]\nstatus_line = {json.dumps(setup_hook.CODEX_STATUS_LINE)}\n',
        encoding="utf-8",
    )
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


def test_unsetup_codex_bad_utf8_backup_keeps_config_and_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    legacy_backup = tmp_path / ".codex" / "tt-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        f'[tui]\nstatus_line = {json.dumps(setup_hook.CODEX_STATUS_LINE)}\n',
        encoding="utf-8",
    )
    codex_backup.write_bytes(b"\xff\xfe{")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)
    monkeypatch.setattr(setup_hook, "LEGACY_CODEX_BACKUP", legacy_backup)

    config_before = codex_config.read_bytes()
    backup_before = codex_backup.read_bytes()

    setup_hook._unsetup_codex()

    assert codex_config.read_bytes() == config_before
    assert codex_backup.read_bytes() == backup_before


def test_unsetup_codex_keeps_foreign_status_line_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    legacy_backup = tmp_path / ".codex" / "tt-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_bytes(b'[tui]\nstatus_line = ["personal"]\n')
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)
    monkeypatch.setattr(setup_hook, "LEGACY_CODEX_BACKUP", legacy_backup)
    config_before = codex_config.read_bytes()

    setup_hook._unsetup_codex()

    assert codex_config.read_bytes() == config_before


def test_unsetup_codex_restores_valid_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_backup = tmp_path / ".codex" / "usage-backup.json"
    legacy_backup = tmp_path / ".codex" / "tt-backup.json"
    codex_config.parent.mkdir()
    codex_config.write_text(
        f'[tui]\nstatus_line = {json.dumps(setup_hook.CODEX_STATUS_LINE)}\n',
        encoding="utf-8",
    )
    codex_backup.write_text(json.dumps({"status_line": ["original"]}), encoding="utf-8")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_backup)
    monkeypatch.setattr(setup_hook, "LEGACY_CODEX_BACKUP", legacy_backup)

    setup_hook._unsetup_codex()

    assert tomllib.loads(codex_config.read_text(encoding="utf-8"))["tui"]["status_line"] == [
        "original"
    ]
    assert not codex_backup.exists()


def test_is_codex_setup_recognizes_legacy_status_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    codex_config.write_text(
        f'[tui]\nstatus_line = {json.dumps(setup_hook.LEGACY_CODEX_STATUS_LINES[0])}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)

    assert setup_hook.is_codex_setup()


def test_self_heal_upgrades_only_legacy_codex_status_line(
    monkeypatch: pytest.MonkeyPatch,
    setup_paths: SetupHookPaths,
    tmp_path: Path,
) -> None:
    codex_config = tmp_path / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(session_hooks, "CODEX_CONFIG", codex_config)
    monkeypatch.setattr(session_hooks, "_load_settings", lambda: {"statusLine": {}})
    monkeypatch.setattr(session_hooks, "_detect_current_state", lambda *_args: "us-direct")
    monkeypatch.setattr(session_hooks, "is_setup", lambda: True)
    monkeypatch.setattr(session_hooks, "needs_update", lambda: False)
    monkeypatch.setattr(session_hooks, "_statusline_command_target_exists", lambda: True)
    monkeypatch.setattr(session_hooks, "_self_heal_resume", lambda: None)
    monkeypatch.setattr(session_hooks, "_self_heal_terse_mode", lambda: None)
    monkeypatch.setattr(setup_hook, "AGY_SETTINGS", tmp_path / ".gemini" / "settings.json")
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        session_hooks, "_append_self_heal_log", lambda action, detail: logs.append((action, detail))
    )
    codex_config.write_text(
        f'[tui]\nstatus_line = {json.dumps(setup_hook.LEGACY_CODEX_STATUS_LINES[0])}\n',
        encoding="utf-8",
    )

    session_hooks.self_heal()

    parsed = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    assert parsed["tui"]["status_line"] == setup_hook.CODEX_STATUS_LINE
    assert logs == [("setup_codex", "upgraded Codex status line segments")]

    codex_config.write_text('[tui]\nstatus_line = ["model"]\n', encoding="utf-8")
    config_before = codex_config.read_bytes()
    logs.clear()

    session_hooks.self_heal()

    assert codex_config.read_bytes() == config_before
    assert logs == []


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
    resume_target = tmp_path / ".claude" / "usage-session-resume.py"
    monkeypatch.setattr(session_hooks, "RESUME_HOOK_TARGET", resume_target)
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
    assert hooks[0]["command"] == expected_statusline_command(resume_target)
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
    resume_target = tmp_path / ".claude" / "usage-session-resume.py"
    monkeypatch.setattr(session_hooks, "RESUME_HOOK_TARGET", resume_target)
    resume_command = session_hooks._resume_command()
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
                            "hooks": [{"type": "command", "command": resume_command}],
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
    assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == resume_command
    assert "usage" not in data
