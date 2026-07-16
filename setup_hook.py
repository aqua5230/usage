# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Install or remove usage's statusLine hook for Claude Code.

Claude Code calls the command configured in ~/.claude/settings.json statusLine
and sends session JSON on stdin whenever it refreshes the status line. The
installer copies usage_statusline.py to ~/.claude/usage-statusline.py and points
statusLine at it, so the main app can read a local status file.

The previous statusLine is backed up under settings["usage"]["previousStatusLine"]
and restored by unsetup.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from i18n import t as _t

CLAUDE_SETTINGS = Path(os.path.expanduser("~/.claude/settings.json"))
HOOK_TARGET = Path(os.path.expanduser("~/.claude/usage-statusline.py"))
FORWARDER_TARGET = Path(os.path.expanduser("~/.claude/usage-statusline-forwarder.py"))
STATUS_FILE = Path(os.path.expanduser("~/.claude/usage-status.json"))
CODEX_CONFIG = Path(os.path.expanduser("~/.codex/config.toml"))
CODEX_BACKUP = Path(os.path.expanduser("~/.codex/usage-backup.json"))
# LEGACY_TT_* / tokenTracker / tt-* below are MIGRATION-ONLY constants for users
# upgrading from the third-party tool stormzhang/token-tracker. They are NOT links
# to any in-repo module or external directory. Do not investigate or "go look" for
# a token-tracker source. It does not exist in this repository or on this machine.
LEGACY_CODEX_BACKUP = Path(os.path.expanduser("~/.codex/tt-backup.json"))
CODEX_STATUS_LINE = [
    "project",
    "five-hour-limit",
    "weekly-limit",
    "context-remaining",
    "model-with-reasoning",
]
LEGACY_NAME = "usag"
LEGACY_HOOK_TARGET = Path(os.path.expanduser(f"~/.claude/{LEGACY_NAME}-statusline.py"))
LEGACY_STATUS_FILE = Path(os.path.expanduser(f"~/.claude/{LEGACY_NAME}-status.json"))
LEGACY_TT_HOOK_TARGET = Path(os.path.expanduser("~/.claude/tt-statusline.py"))
BACKUP_KEY = "usage"
LEGACY_TT_BACKUP_KEY = "tokenTracker"
LEGACY_BACKUP_KEY = LEGACY_NAME
PREV_SL_KEY = "previousStatusLine"
HOOK_VERSION = "1.0"
_SL_REGEX = re.compile(r"(?m)^[ \t]*status_line\s*=\s*\[.*?\]", re.DOTALL)
_TABLE_REGEX = re.compile(r"(?m)^[ \t]*\[[^\]\n]+\][ \t]*(?:#.*)?$")


def configure_windows_utf8_output() -> None:
    """Prevent Windows legacy console encodings from rejecting CLI messages."""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            # Test runners and embedders may replace the TextIOWrapper streams.
            cast(Any, stream).reconfigure(encoding="utf-8")


def _resolve_hook_source() -> Path:
    paths = [
        Path(__file__).resolve().parent / "usage_statusline.py",
        Path(sys.executable).resolve().parent.parent / "Resources" / "usage_statusline.py",
    ]
    for path in paths:
        if path.exists():
            return path
    tried = ", ".join(str(path) for path in paths)
    raise SystemExit(_t("setup_hook_source_missing", tried=tried))


def _resolve_forwarder_source() -> Path:
    paths = [
        Path(__file__).resolve().parent / "usage_statusline_forwarder.py",
        (
            Path(sys.executable).resolve().parent.parent
            / "Resources"
            / "usage_statusline_forwarder.py"
        ),
    ]
    for path in paths:
        if path.exists():
            return path
    tried = ", ".join(str(path) for path in paths)
    raise SystemExit(_t("setup_forwarder_source_missing", tried=tried))


def _statusline_command() -> str:
    # Prefer a standalone system python, not a venv; the hook is stdlib-only.
    python = _find_system_python()
    return f"{_shell_arg(python)} {_shell_arg(str(HOOK_TARGET))}"


def _statusline_command_target_exists() -> bool:
    settings = _load_settings()
    sl = settings.get("statusLine")
    if not isinstance(sl, dict):
        return True
    command = sl.get("command")
    if not isinstance(command, str):
        return True
    try:
        parts = shlex.split(command, posix=sys.platform != "win32")
    except ValueError:
        return True
    for part in parts:
        part = part.strip('"')
        if "statusline" not in part or not part.endswith(".py"):
            continue
        return Path(os.path.expanduser(part)).exists()
    return True


def _find_system_python() -> str:
    if sys.platform == "win32":
        executable = sys.executable
        if executable and not getattr(sys, "frozen", False):
            return executable
        return shutil.which("python") or "python"
    if os.path.exists("/usr/bin/python3"):
        return "/usr/bin/python3"
    executable = sys.executable
    if ".app/Contents" not in executable:
        return executable
    return shutil.which("python3") or "python3"


def _shell_arg(value: str) -> str:
    if sys.platform == "win32":
        # Claude Code runs statusLine commands through Git Bash when it is
        # installed.  Backslashes are escape characters there, while forward
        # slashes also work in PowerShell, so emit the portable Windows form.
        value = value.replace("\\", "/")
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def _forwarder_command() -> str:
    python = _find_system_python()
    return f"{_shell_arg(python)} {_shell_arg(str(FORWARDER_TARGET))}"


def _uses_bundled_app_python(command: str) -> bool:
    return ".app/Contents" in command


def _migrate_windows_statusline_command_if_needed(
    settings: dict[str, Any] | None = None,
) -> None:
    """Replace legacy backslash paths in usage-owned Windows statusLine commands."""
    if sys.platform != "win32":
        return
    data = _load_settings() if settings is None else settings
    sl = data.get("statusLine")
    if not isinstance(sl, dict):
        return
    command = sl.get("command")
    if not isinstance(command, str) or "\\" not in command:
        return
    if "usage-statusline-forwarder" in command:
        new_command = _forwarder_command()
    elif "usage-statusline" in command:
        new_command = _statusline_command()
    else:
        return
    if command == new_command:
        return
    sl["command"] = new_command
    _save_settings(data)
    _append_hook_repair_log("migrate_windows_statusline", "backslash paths -> forward slashes")


def _append_hook_repair_log(action: str, detail: str) -> None:
    settings = _load_settings()
    usage_settings = settings.get(BACKUP_KEY)
    if not isinstance(usage_settings, dict):
        usage_settings = {}
        settings[BACKUP_KEY] = usage_settings
    log = usage_settings.get("selfHealLog")
    if not isinstance(log, list):
        log = []
    log.append(
        {
            "timestamp": (
                datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ),
            "action": action,
            "detail": detail,
        }
    )
    usage_settings["selfHealLog"] = log[-20:]
    _save_settings(settings)


def _migrate_bundled_python_commands_if_needed(
    settings: dict[str, Any] | None = None,
) -> None:
    data = _load_settings() if settings is None else settings
    changed = False
    details: list[str] = []

    sl = data.get("statusLine")
    if isinstance(sl, dict):
        command = sl.get("command")
        if isinstance(command, str) and _uses_bundled_app_python(command):
            if "usage-statusline-forwarder" in command:
                new_command = _forwarder_command()
                if command != new_command:
                    sl["command"] = new_command
                    changed = True
                    details.append("statusLine=forwarder")
            elif "usage-statusline" in command:
                new_command = _statusline_command()
                if command != new_command:
                    sl["command"] = new_command
                    changed = True
                    details.append("statusLine=direct")

    if not changed:
        return
    _save_settings(data)
    _append_hook_repair_log("migrate_bundled_python", ", ".join(details))


def _is_usage_hook(sl: object) -> bool:
    if not isinstance(sl, dict):
        return False
    cmd = sl.get("command")
    return isinstance(cmd, str) and "usage-statusline" in cmd


def _is_legacy_tt_hook(sl: object) -> bool:
    if not isinstance(sl, dict):
        return False
    cmd = sl.get("command")
    return isinstance(cmd, str) and "tt-statusline" in cmd


def _detect_current_state(settings: dict[str, Any] | None = None) -> str:
    """Return 'none' | 'us-direct' | 'us-forwarder' | 'legacy-tt' | 'external'."""
    data = _load_settings() if settings is None else settings
    sl = data.get("statusLine")
    if not isinstance(sl, dict):
        return "none"
    cmd = sl.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return "none"
    if "usage-statusline-forwarder" in cmd:
        return "us-forwarder"
    if "usage-statusline" in cmd:
        return "us-direct"
    if "tt-statusline" in cmd:
        return "legacy-tt"
    return "external"


def current_hook_state() -> str:
    """Return the installed Claude statusLine hook state."""
    return _detect_current_state()


def _migrate_from_legacy_usage() -> None:
    changed = False

    for path in (LEGACY_HOOK_TARGET, LEGACY_STATUS_FILE):
        try:
            if path.exists():
                path.unlink()
                changed = True
        except OSError as exc:
            print(_t("setup_legacy_file_remove_failed", path=path, error=exc))

    settings: dict[str, Any] | None = None
    try:
        if CLAUDE_SETTINGS.exists():
            with CLAUDE_SETTINGS.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                settings = data
            else:
                print(_t("setup_legacy_settings_not_object", path=CLAUDE_SETTINGS))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(_t("setup_legacy_settings_read_failed", error=exc))

    if settings is not None:
        try:
            sl = settings.get("statusLine")
            cmd = sl.get("command") if isinstance(sl, dict) else None
            if (
                isinstance(cmd, str)
                and f"{LEGACY_NAME}-statusline" in cmd
                and "usage-statusline" not in cmd
            ):
                settings.pop("statusLine", None)
                changed = True
        except Exception as exc:
            print(_t("setup_legacy_statusline_cleanup_failed", error=exc))

        try:
            legacy_backup = settings.pop(LEGACY_BACKUP_KEY, None)
            legacy_tt_backup = settings.pop(LEGACY_TT_BACKUP_KEY, None)
            current_backup = settings.get(BACKUP_KEY)
            merged: dict[str, Any] = {}
            if isinstance(legacy_backup, dict):
                merged.update(legacy_backup)
            if isinstance(legacy_tt_backup, dict):
                merged.update(legacy_tt_backup)
            if isinstance(merged, dict) and merged:
                if isinstance(current_backup, dict):
                    settings[BACKUP_KEY] = {**merged, **current_backup}
                else:
                    settings[BACKUP_KEY] = merged
                changed = True
            elif legacy_backup is not None or legacy_tt_backup is not None:
                changed = True
        except Exception as exc:
            print(_t("setup_legacy_backup_migrate_failed", error=exc))

        if changed:
            try:
                _save_settings(settings)
            except Exception as exc:
                print(_t("setup_legacy_settings_write_failed", error=exc))

    if changed:
        print(_t("setup_legacy_migrated", name=LEGACY_NAME))


def _load_settings() -> dict[str, Any]:
    if not CLAUDE_SETTINGS.exists():
        return {}
    try:
        with CLAUDE_SETTINGS.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(_t("setup_settings_read_failed", path=CLAUDE_SETTINGS, error=exc)) from exc
    if not isinstance(data, dict):
        raise SystemExit(_t("setup_settings_not_object", path=CLAUDE_SETTINGS))
    return data


def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _save_settings(data: dict[str, Any]) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    _atomic_write_text(CLAUDE_SETTINGS, payload)


def _copy_hook_script() -> None:
    hook_source = _resolve_hook_source()
    HOOK_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(hook_source, HOOK_TARGET)
    HOOK_TARGET.chmod(HOOK_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _copy_forwarder_script() -> None:
    forwarder_source = _resolve_forwarder_source()
    FORWARDER_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(forwarder_source, FORWARDER_TARGET)
    FORWARDER_TARGET.chmod(
        FORWARDER_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )


def _backup_existing_statusline(settings: dict[str, Any]) -> None:
    existing = settings.get("statusLine")
    if not existing or _is_usage_hook(existing):
        return
    backup = settings.get(BACKUP_KEY)
    if not isinstance(backup, dict):
        backup = {}
        settings[BACKUP_KEY] = backup
    if PREV_SL_KEY not in backup:
        backup[PREV_SL_KEY] = existing
        print(_t("setup_statusline_backed_up", backup_key=BACKUP_KEY, prev_key=PREV_SL_KEY))


def _status_line_toml(items: list[str]) -> str:
    if not items:
        return "status_line = []"
    body = ",\n".join(f"  {json.dumps(item, ensure_ascii=False)}" for item in items)
    return f"status_line = [\n{body},\n]"


def _find_table(content: str, name: str) -> re.Match[str] | None:
    return re.compile(rf"(?m)^[ \t]*\[{re.escape(name)}\][ \t]*(?:#.*)?$").search(content)


def _table_section(content: str, table: re.Match[str]) -> tuple[int, int]:
    """Return (start, end) offsets of ``table``'s body — from end of its header line up to
    (not including) the next top-level table header, or EOF."""
    next_table = _TABLE_REGEX.search(content[table.end() :])
    section_end = len(content) if next_table is None else table.end() + next_table.start()
    return table.end(), section_end


def _insert_table_line(content: str, name: str, line: str) -> str:
    table = _find_table(content, name)
    if table is None:
        return content
    return content[: table.end()] + f"\n{line}" + content[table.end() :]


def _replace_table_line(
    content: str, name: str, line_regex: re.Pattern[str], replacement: str
) -> str:
    table = _find_table(content, name)
    if table is None:
        return content
    start, end = _table_section(content, table)
    section = content[start:end]
    return content[:start] + line_regex.sub(replacement, section, count=1) + content[end:]


def _remove_table_line(content: str, name: str, line_regex: re.Pattern[str]) -> str:
    table = _find_table(content, name)
    if table is None:
        return content
    start, end = _table_section(content, table)
    section = content[start:end]
    return content[:start] + line_regex.sub("", section, count=1) + content[end:]


def _ensure_table_line(
    content: str, name: str, line_regex: re.Pattern[str], line: str
) -> str:
    """Make sure ``line`` is in table ``name``: replace an existing ``line_regex`` match if
    present, else insert ``line`` fresh. Appends a new ``[name]`` table at EOF when the table
    itself is absent."""
    table = _find_table(content, name)
    if table is None:
        return content.rstrip() + f"\n\n[{name}]\n{line}\n"
    start, end = _table_section(content, table)
    section = content[start:end]
    if line_regex.search(section):
        return content[:start] + line_regex.sub(line, section, count=1) + content[end:]
    return content[:start] + f"\n{line}" + content[start:]


def _find_tui_table(content: str) -> re.Match[str] | None:
    return _find_table(content, "tui")


def _insert_tui_status_line(content: str, replacement: str) -> str:
    return _insert_table_line(content, "tui", replacement)


def _replace_tui_status_line(content: str, replacement: str) -> str:
    return _replace_table_line(content, "tui", _SL_REGEX, replacement)


def _remove_tui_status_line(content: str) -> str:
    return _remove_table_line(content, "tui", _SL_REGEX)


def _read_codex_config() -> tuple[str, dict[str, Any]] | None:
    try:
        content = CODEX_CONFIG.read_text(encoding="utf-8")
        parsed = tomllib.loads(content)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    return content, parsed


def _codex_status_line(parsed: dict[str, Any]) -> object:
    tui = parsed.get("tui")
    return tui.get("status_line") if isinstance(tui, dict) else None


def _setup_codex() -> None:
    result = _read_codex_config()
    if not result:
        if CODEX_CONFIG.exists():
            print(_t("setup_codex_config_unreadable"))
        return
    content, parsed = result

    old = _codex_status_line(parsed)
    if old == CODEX_STATUS_LINE:
        print(_t("setup_codex_already_configured"))
        return

    if old is not None:
        CODEX_BACKUP.parent.mkdir(parents=True, exist_ok=True)
        CODEX_BACKUP.write_text(
            json.dumps({"status_line": old}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        content = _replace_tui_status_line(content, _status_line_toml(CODEX_STATUS_LINE))
    elif isinstance(parsed.get("tui"), dict):
        content = _insert_tui_status_line(content, _status_line_toml(CODEX_STATUS_LINE))
    else:
        content += f"\n[tui]\n{_status_line_toml(CODEX_STATUS_LINE)}\n"

    _atomic_write_text(CODEX_CONFIG, content)
    print(_t("setup_codex_configured"))
    if old is not None:
        print(_t("setup_codex_backup_written", path=CODEX_BACKUP))
    print(_t("setup_codex_restart_required"))


def _unsetup_codex() -> None:
    result = _read_codex_config()
    if not result:
        return
    content, parsed = result

    if _codex_status_line(parsed) is None:
        return

    backup_path = CODEX_BACKUP if CODEX_BACKUP.exists() else LEGACY_CODEX_BACKUP
    if backup_path.exists():
        try:
            old_items = json.loads(backup_path.read_text(encoding="utf-8")).get("status_line", [])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            old_items = []
        content = _replace_tui_status_line(content, _status_line_toml(old_items))
        # Write the restored config before deleting the backup: if the write fails, the
        # backup must survive so a later retry can still recover the original status line.
        _atomic_write_text(CODEX_CONFIG, content)
        backup_path.unlink(missing_ok=True)
        print(_t("setup_codex_restored"))
    else:
        content = _remove_tui_status_line(content)
        _atomic_write_text(CODEX_CONFIG, content)
        print(_t("setup_codex_removed"))


def _installed_hook_version() -> str | None:
    try:
        with HOOK_TARGET.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def needs_update() -> bool:
    if not HOOK_TARGET.parent.exists():
        return False
    return _installed_hook_version() != HOOK_VERSION


def update_hook() -> None:
    if not HOOK_TARGET.parent.exists():
        return
    _copy_hook_script()




def is_setup() -> bool:
    has_claude = CLAUDE_SETTINGS.parent.exists()
    has_codex = CODEX_CONFIG.exists()
    if not has_claude and not has_codex:
        return False

    if has_claude and _detect_current_state() not in {"us-direct", "us-forwarder"}:
        return False

    if has_codex:
        result = _read_codex_config()
        if not result:
            return False
        _, parsed = result
        if _codex_status_line(parsed) != CODEX_STATUS_LINE:
            return False

    return True


def is_claude_setup() -> bool:
    """Check only whether the Claude hook is installed."""
    if not CLAUDE_SETTINGS.parent.exists():
        return True
    return _detect_current_state() in {"us-direct", "us-forwarder"}


def is_codex_setup() -> bool:
    """Check only whether the Codex hook is installed."""
    if not CODEX_CONFIG.exists():
        return True
    result = _read_codex_config()
    if not result:
        return False
    _, parsed = result
    return _codex_status_line(parsed) == CODEX_STATUS_LINE


def _install_forwarder(settings: dict[str, Any]) -> None:
    """Copy usage_statusline_forwarder.py to ~/.claude/ and update settings.json."""
    _copy_hook_script()
    _copy_forwarder_script()
    _backup_existing_statusline(settings)
    settings["statusLine"] = {"type": "command", "command": _forwarder_command()}
    _save_settings(settings)


def setup(force_forwarder: bool = False) -> int:
    configure_windows_utf8_output()
    _migrate_from_legacy_usage()
    has_claude = CLAUDE_SETTINGS.parent.exists()
    has_codex = CODEX_CONFIG.exists()
    if not has_claude and not has_codex:
        print(_t("setup_no_agents"), file=sys.stderr)
        return 1

    if has_claude:
        settings = _load_settings()
        _migrate_bundled_python_commands_if_needed(settings)
        _migrate_windows_statusline_command_if_needed(settings)
        state = _detect_current_state(settings)

        if force_forwarder or state in {"external", "legacy-tt"}:
            _install_forwarder(settings)
            print(_t("setup_forwarder_installed", path=FORWARDER_TARGET))
            print(_t("setup_hook_installed", path=HOOK_TARGET))
            print(_t("setup_settings_updated", path=CLAUDE_SETTINGS))
            print(_t("setup_claude_restart_required"))
        else:
            _copy_hook_script()
            if state == "none":
                settings["statusLine"] = {"type": "command", "command": _statusline_command()}
                _save_settings(settings)
            elif state in {"us-direct", "us-forwarder"}:
                print(_t("setup_statusline_already_usage"))

            print(_t("setup_hook_installed", path=HOOK_TARGET))
            print(_t("setup_settings_updated", path=CLAUDE_SETTINGS))
            print(_t("setup_claude_restart_required"))

    if has_codex:
        _setup_codex()

    return 0


def unsetup() -> int:
    configure_windows_utf8_output()
    if CLAUDE_SETTINGS.parent.exists():
        settings = _load_settings()
        sl = settings.get("statusLine")

        if _is_usage_hook(sl) or _is_legacy_tt_hook(sl):
            backup = settings.get(BACKUP_KEY)
            legacy_backup = settings.get(LEGACY_TT_BACKUP_KEY)
            prev = backup.get(PREV_SL_KEY) if isinstance(backup, dict) else None
            if not isinstance(prev, dict) and isinstance(legacy_backup, dict):
                prev = legacy_backup.get(PREV_SL_KEY)

            if isinstance(prev, dict):
                settings["statusLine"] = prev
                print(_t("setup_claude_statusline_restored"))
            else:
                settings.pop("statusLine", None)
                print(_t("setup_claude_statusline_removed"))

            if isinstance(backup, dict):
                backup.pop(PREV_SL_KEY, None)
                if not backup:
                    del settings[BACKUP_KEY]
            if isinstance(legacy_backup, dict):
                legacy_backup.pop(PREV_SL_KEY, None)
                if not legacy_backup:
                    del settings[LEGACY_TT_BACKUP_KEY]

            _save_settings(settings)
        else:
            print(_t("setup_statusline_not_usage"))

        for path in (HOOK_TARGET, FORWARDER_TARGET, LEGACY_TT_HOOK_TARGET):
            if path.exists():
                path.unlink()
                print(_t("setup_hook_deleted", path=path))

        if STATUS_FILE.exists():
            STATUS_FILE.unlink()
            print(_t("setup_status_file_deleted", path=STATUS_FILE))


    if CODEX_CONFIG.exists():
        _unsetup_codex()

    return 0
