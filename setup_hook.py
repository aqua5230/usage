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
import io
import json
import os
import re
import shlex
import shutil
import stat
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

# Ceiling C — opt-in SessionStart hook that injects "where you left off" into a new
# session. Off by default: enabled only via the menu toggle, never by self_heal.
RESUME_HOOK_TARGET = Path(os.path.expanduser("~/.claude/usage-session-resume.py"))
RESUME_PROMPT_SIDECAR = Path(os.path.expanduser("~/.claude/usage-resume-prompt.json"))
RESUME_HOOK_VERSION = "1.6"
RESUME_MATCHER = "startup|clear"
RESUME_LANGS = ("zh-TW", "zh-CN", "en", "ja", "ko")
_RESUME_MARKER = "usage-session-resume"
_RESUME_MARKERS = (_RESUME_MARKER, "usage_session_resume")
_RESUME_DIAGNOSIS_CAUSE_KEYS = (
    "repeated_reads",
    "polluter_dirs",
    "anomaly_session",
    "noisy_bash",
    "repeated_bash",
)
TERSE_HOOK_TARGET = Path(os.path.expanduser("~/.claude/usage-terse-mode.py"))
TERSE_PROMPT_SIDECAR = Path(os.path.expanduser("~/.claude/usage-terse-prompt.json"))
TERSE_HOOK_VERSION = "1.0"
TERSE_MATCHER = "startup|clear"
TERSE_LANGS = ("zh-TW", "zh-CN", "en", "ja", "ko")
_TERSE_MARKER = "usage-terse-mode"
_TERSE_MARKERS = (_TERSE_MARKER, "usage_terse_mode")
# Codex CLI shares the same terse-mode script (its SessionStart hook I/O schema matches Claude
# Code's). Installed into the user-global ~/.codex so one toggle covers both tools.
CODEX_TERSE_HOOK_TARGET = Path(os.path.expanduser("~/.codex/usage-terse-mode.py"))
CODEX_HOOKS_JSON = Path(os.path.expanduser("~/.codex/hooks.json"))
CODEX_TERSE_MATCHER = "startup|resume|clear"
_FEATURES_HOOKS_REGEX = re.compile(r"(?m)^[ \t]*hooks\s*=\s*[A-Za-z0-9_]+")


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
        parts = shlex.split(command)
    except ValueError:
        return True
    for part in parts:
        if "statusline" not in part or not part.endswith(".py"):
            continue
        return Path(os.path.expanduser(part)).exists()
    return True


def _find_system_python() -> str:
    if os.path.exists("/usr/bin/python3"):
        return "/usr/bin/python3"
    executable = sys.executable
    if ".app/Contents" not in executable:
        return executable
    return shutil.which("python3") or "python3"


def _shell_arg(value: str) -> str:
    return shlex.quote(value)


def _forwarder_command() -> str:
    python = _find_system_python()
    return f"{shlex.quote(python)} {shlex.quote(str(FORWARDER_TARGET))}"


def _uses_bundled_app_python(command: str) -> bool:
    return ".app/Contents" in command


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

    entries = _session_start_list(data)
    if entries:
        new_command = _resume_command()
        resume_changed = False
        for entry in entries:
            if not isinstance(entry, dict) or not _is_resume_entry(entry):
                continue
            hooks = entry.get("hooks")
            if not isinstance(hooks, list):
                continue
            for hook in hooks:
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command")
                if not isinstance(command, str) or not _uses_bundled_app_python(command):
                    continue
                if command != new_command:
                    hook["command"] = new_command
                    changed = True
                    resume_changed = True
        if resume_changed:
            details.append("resume")

    if not changed:
        return
    _save_settings(data)
    _append_self_heal_log("migrate_bundled_python", ", ".join(details))


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


def _resolve_resume_source() -> Path:
    paths = [
        Path(__file__).resolve().parent / "usage_session_resume.py",
        Path(sys.executable).resolve().parent.parent / "Resources" / "usage_session_resume.py",
    ]
    for path in paths:
        if path.exists():
            return path
    tried = ", ".join(str(path) for path in paths)
    raise SystemExit(_t("setup_resume_source_missing", tried=tried))


def _resolve_terse_source() -> Path:
    paths = [
        Path(__file__).resolve().parent / "usage_terse_mode.py",
        Path(sys.executable).resolve().parent.parent / "Resources" / "usage_terse_mode.py",
    ]
    for path in paths:
        if path.exists():
            return path
    tried = ", ".join(str(path) for path in paths)
    raise SystemExit(_t("setup_terse_source_missing", tried=tried))


def _resume_command() -> str:
    python = _find_system_python()
    source = _resolve_resume_source()
    return f"{shlex.quote(python)} {shlex.quote(str(source))}"


def _terse_command() -> str:
    python = _find_system_python()
    source = _resolve_terse_source()
    return f"{shlex.quote(python)} {shlex.quote(str(source))}"


def _copy_resume_script() -> None:
    source = _resolve_resume_source()
    RESUME_HOOK_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, RESUME_HOOK_TARGET)
    RESUME_HOOK_TARGET.chmod(
        RESUME_HOOK_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )


def _copy_terse_script() -> None:
    source = _resolve_terse_source()
    TERSE_HOOK_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, TERSE_HOOK_TARGET)
    TERSE_HOOK_TARGET.chmod(
        TERSE_HOOK_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )


def _write_resume_sidecar() -> None:
    """Mirror i18n.json's rw_prompt/rw_none into a sidecar the stdlib hook can read,
    so the injected wording stays single-sourced and the hook needs no app imports."""
    from i18n import I18N_PATH

    try:
        bundle = json.loads(I18N_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(bundle, dict):
        return
    en_raw = bundle.get("en")
    en: dict[str, Any] = en_raw if isinstance(en_raw, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for lang in RESUME_LANGS:
        table_raw = bundle.get(lang)
        table: dict[str, Any] = table_raw if isinstance(table_raw, dict) else {}
        prompt = table.get("report_rw_prompt") or en.get("report_rw_prompt")
        none_label = table.get("report_rw_none") or en.get("report_rw_none")
        lead = table.get("report_rw_inject_lead") or en.get("report_rw_inject_lead") or ""
        empty = table.get("report_rw_empty") or en.get("report_rw_empty") or ""
        uncommitted = table.get("report_rw_uncommitted") or en.get("report_rw_uncommitted") or ""
        diagnosis_reminder = (
            table.get("report_rw_diagnosis_reminder")
            or en.get("report_rw_diagnosis_reminder")
            or ""
        )
        diagnosis_reminder_explain = (
            table.get("report_rw_diagnosis_reminder_explain")
            or en.get("report_rw_diagnosis_reminder_explain")
            or ""
        )
        diagnosis_default_cause = (
            table.get("report_rw_diagnosis_cause_default")
            or en.get("report_rw_diagnosis_cause_default")
            or ""
        )
        if isinstance(prompt, str) and isinstance(none_label, str):
            diagnosis_causes = {
                key: (
                    table.get(f"report_rw_diagnosis_cause_{key}")
                    or en.get(f"report_rw_diagnosis_cause_{key}")
                    or diagnosis_default_cause
                )
                for key in _RESUME_DIAGNOSIS_CAUSE_KEYS
            }
            out[lang] = {
                "prompt": prompt,
                "none": none_label,
                "lead": lead,
                "empty": empty,
                "uncommitted": uncommitted,
                "diagnosis_reminder": diagnosis_reminder,
                "diagnosis_reminder_explain": diagnosis_reminder_explain,
                "diagnosis_default_cause": diagnosis_default_cause,
                "diagnosis_causes": diagnosis_causes,
            }
    if out:
        RESUME_PROMPT_SIDECAR.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            RESUME_PROMPT_SIDECAR, json.dumps(out, ensure_ascii=False, indent=2) + "\n"
        )


def _write_terse_sidecar() -> None:
    from i18n import I18N_PATH

    try:
        bundle = json.loads(I18N_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(bundle, dict):
        return
    en_raw = bundle.get("en")
    en: dict[str, Any] = en_raw if isinstance(en_raw, dict) else {}
    out: dict[str, dict[str, str]] = {}
    for lang in TERSE_LANGS:
        table_raw = bundle.get(lang)
        table: dict[str, Any] = table_raw if isinstance(table_raw, dict) else {}
        instruction = table.get("terse_mode_instruction") or en.get("terse_mode_instruction")
        if isinstance(instruction, str) and instruction:
            out[lang] = {"instruction": instruction}
    if out:
        TERSE_PROMPT_SIDECAR.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            TERSE_PROMPT_SIDECAR, json.dumps(out, ensure_ascii=False, indent=2) + "\n"
        )


def _is_resume_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(h, dict)
        and isinstance(h.get("command"), str)
        and any(marker in h["command"] for marker in _RESUME_MARKERS)
        for h in hooks
    )


def _strip_resume_hooks(entry: object) -> object | None:
    """Return ``entry`` with usage-owned resume hooks removed.

    Removes only the resume hook *item*, not the whole entry, so a user who put their
    own hook in the same SessionStart entry doesn't lose it when we disable. Returns
    ``None`` when nothing but our hook was in the entry, ``entry`` unchanged when it
    held no resume hook.
    """
    if not isinstance(entry, dict):
        return entry
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return entry
    kept = [
        h
        for h in hooks
        if not (
            isinstance(h, dict)
            and isinstance(h.get("command"), str)
            and any(marker in h["command"] for marker in _RESUME_MARKERS)
        )
    ]
    if len(kept) == len(hooks):
        return entry
    if not kept:
        return None
    return {**entry, "hooks": kept}


def _is_terse_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(h, dict)
        and isinstance(h.get("command"), str)
        and any(marker in h["command"] for marker in _TERSE_MARKERS)
        for h in hooks
    )


def _strip_terse_hooks(entry: object) -> object | None:
    if not isinstance(entry, dict):
        return entry
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return entry
    kept = [
        h
        for h in hooks
        if not (
            isinstance(h, dict)
            and isinstance(h.get("command"), str)
            and any(marker in h["command"] for marker in _TERSE_MARKERS)
        )
    ]
    if len(kept) == len(hooks):
        return entry
    if not kept:
        return None
    return {**entry, "hooks": kept}


def _codex_terse_command() -> str:
    python = _find_system_python()
    return f"{shlex.quote(python)} {shlex.quote(str(CODEX_TERSE_HOOK_TARGET))}"


def _load_codex_hooks() -> dict[str, Any]:
    if not CODEX_HOOKS_JSON.exists():
        return {}
    try:
        data = json.loads(CODEX_HOOKS_JSON.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_codex_hooks(data: dict[str, Any]) -> None:
    _atomic_write_text(
        CODEX_HOOKS_JSON, json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    )


def _codex_session_start_list(data: dict[str, Any]) -> list[Any] | None:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return None
    session_start = hooks.get("SessionStart")
    return session_start if isinstance(session_start, list) else None


def _is_codex_terse_installed() -> bool:
    entries = _codex_session_start_list(_load_codex_hooks())
    if not entries:
        return False
    return any(_is_terse_entry(e) for e in entries)


def _copy_codex_terse_script() -> None:
    source = _resolve_terse_source()
    CODEX_TERSE_HOOK_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, CODEX_TERSE_HOOK_TARGET)
    CODEX_TERSE_HOOK_TARGET.chmod(
        CODEX_TERSE_HOOK_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )


def _setup_codex_terse() -> None:
    """Install the terse hook into the user-global ~/.codex. No-op when config.toml can't be
    read — the [features] hooks flag is the gate, so without a readable config the hook
    wouldn't fire anyway. Stays silent: Codex is an opt-in add-on to the Claude toggle."""
    result = _read_codex_config()
    if result is None:
        return
    content, parsed = result
    _copy_codex_terse_script()

    features = parsed.get("features")
    if not (isinstance(features, dict) and features.get("hooks") is True):
        new_content = _ensure_table_line(
            content, "features", _FEATURES_HOOKS_REGEX, "hooks = true"
        )
        if new_content != content:
            _atomic_write_text(CODEX_CONFIG, new_content)

    data = _load_codex_hooks()
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        session_start = []
        hooks["SessionStart"] = session_start
    session_start[:] = [
        e for e in (_strip_terse_hooks(e) for e in session_start) if e is not None
    ]
    session_start.append(
        {
            "matcher": CODEX_TERSE_MATCHER,
            "hooks": [{"type": "command", "command": _codex_terse_command(), "timeout": 5}],
        }
    )
    _save_codex_hooks(data)


def _teardown_codex_terse() -> None:
    """Remove only usage's own Codex SessionStart entry; leave ``[features] hooks = true``
    and any user-installed Codex hooks intact. Deletes hooks.json when nothing remains."""
    data = _load_codex_hooks()
    entries = _codex_session_start_list(data)
    if entries is not None:
        kept = [e for e in (_strip_terse_hooks(e) for e in entries) if e is not None]
        hooks = data.get("hooks")
        if isinstance(hooks, dict):
            if kept:
                hooks["SessionStart"] = kept
            else:
                hooks.pop("SessionStart", None)
            if not hooks:
                data.pop("hooks", None)
        if data:
            _save_codex_hooks(data)
        else:
            CODEX_HOOKS_JSON.unlink(missing_ok=True)
    CODEX_TERSE_HOOK_TARGET.unlink(missing_ok=True)


def _installed_codex_terse_version() -> str | None:
    try:
        with CODEX_TERSE_HOOK_TARGET.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def _self_heal_codex_terse() -> None:
    """Restore the Codex side of terse mode — but only when Claude's side is already on and
    Codex is installed. Re-runs the idempotent installer for any missing/stale artifact."""
    if not CODEX_CONFIG.exists():
        return
    result = _read_codex_config()
    if result is None:
        return
    _, parsed = result
    features = parsed.get("features")
    hooks_enabled = isinstance(features, dict) and features.get("hooks") is True

    script_missing = not CODEX_TERSE_HOOK_TARGET.exists()
    entry_missing = not _is_codex_terse_installed()
    old_version = _installed_codex_terse_version()
    version_stale = CODEX_TERSE_HOOK_TARGET.exists() and old_version != TERSE_HOOK_VERSION

    if not (script_missing or entry_missing or version_stale or not hooks_enabled):
        return

    _setup_codex_terse()
    if script_missing or entry_missing or not hooks_enabled:
        parts: list[str] = []
        if script_missing:
            parts.append("script")
        if entry_missing:
            parts.append("hooks_entry")
        if not hooks_enabled:
            parts.append("features_flag")
        _append_self_heal_log("restore_terse_hook_codex", f"missing={','.join(parts)}")
    else:
        _append_self_heal_log(
            "update_terse_hook_codex", f"{old_version or 'unknown'} -> {TERSE_HOOK_VERSION}"
        )


def _session_start_list(settings: dict[str, Any]) -> list[Any] | None:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return None
    session_start = hooks.get("SessionStart")
    return session_start if isinstance(session_start, list) else None


def is_resume_enabled() -> bool:
    try:
        settings = _load_settings()
    except SystemExit:
        return False
    entries = _session_start_list(settings)
    if not entries:
        return False
    return any(_is_resume_entry(e) for e in entries)


def is_terse_mode_enabled() -> bool:
    try:
        settings = _load_settings()
    except SystemExit:
        return False
    entries = _session_start_list(settings)
    if not entries:
        return False
    return any(_is_terse_entry(e) for e in entries)


def enable_session_resume() -> int:
    if not CLAUDE_SETTINGS.parent.exists():
        print(_t("setup_no_agents"), file=sys.stderr)
        return 1
    _copy_resume_script()
    _write_resume_sidecar()
    settings = _load_settings()
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        session_start = []
        hooks["SessionStart"] = session_start
    session_start[:] = [e for e in (_strip_resume_hooks(e) for e in session_start) if e is not None]
    session_start.append(
        {"matcher": RESUME_MATCHER, "hooks": [{"type": "command", "command": _resume_command()}]}
    )
    _save_settings(settings)
    print(_t("setup_resume_enabled", path=_resolve_resume_source()))
    print(_t("setup_claude_restart_required"))
    return 0


def enable_terse_mode() -> int:
    if not CLAUDE_SETTINGS.parent.exists():
        print(_t("setup_no_agents"), file=sys.stderr)
        return 1
    _copy_terse_script()
    _write_terse_sidecar()
    settings = _load_settings()
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        session_start = []
        hooks["SessionStart"] = session_start
    session_start[:] = [e for e in (_strip_terse_hooks(e) for e in session_start) if e is not None]
    session_start.append(
        {"matcher": TERSE_MATCHER, "hooks": [{"type": "command", "command": _terse_command()}]}
    )
    _save_settings(settings)
    if CODEX_CONFIG.exists():
        _setup_codex_terse()
    print(_t("terse_mode_enabled_msg"))
    print(_t("setup_claude_restart_required"))
    return 0


def disable_session_resume() -> int:
    if CLAUDE_SETTINGS.parent.exists():
        settings = _load_settings()
        session_start = _session_start_list(settings)
        if session_start is not None:
            kept = [e for e in (_strip_resume_hooks(e) for e in session_start) if e is not None]
            if kept != session_start:
                hooks = settings["hooks"]
                if kept:
                    hooks["SessionStart"] = kept
                else:
                    hooks.pop("SessionStart", None)
                if not hooks:
                    settings.pop("hooks", None)
                _save_settings(settings)
                print(_t("setup_resume_disabled"))
    for path in (RESUME_HOOK_TARGET, RESUME_PROMPT_SIDECAR):
        if path.exists():
            path.unlink()
    return 0


def disable_terse_mode() -> int:
    if CLAUDE_SETTINGS.parent.exists():
        settings = _load_settings()
        session_start = _session_start_list(settings)
        if session_start is not None:
            kept = [e for e in (_strip_terse_hooks(e) for e in session_start) if e is not None]
            if kept != session_start:
                hooks = settings["hooks"]
                if kept:
                    hooks["SessionStart"] = kept
                else:
                    hooks.pop("SessionStart", None)
                if not hooks:
                    settings.pop("hooks", None)
                _save_settings(settings)
                print(_t("terse_mode_disabled_msg"))
    for path in (TERSE_HOOK_TARGET, TERSE_PROMPT_SIDECAR):
        if path.exists():
            path.unlink()
    _teardown_codex_terse()
    return 0


def _installed_resume_version() -> str | None:
    try:
        with RESUME_HOOK_TARGET.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def _installed_terse_version() -> str | None:
    try:
        with TERSE_HOOK_TARGET.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def _self_heal_resume() -> None:
    """Keep the opt-in resume hook healthy *only if already enabled* — restore a missing
    script/sidecar and update a stale script. Never enables it on its own."""
    if not is_resume_enabled():
        return
    _migrate_resume_command_if_needed()
    missing = _missing_resume_artifacts()
    if missing:
        detail = _resume_restore_context(missing)
        _copy_resume_script()
        _write_resume_sidecar()
        _append_self_heal_log("restore_resume_hook", detail)
    elif _installed_resume_version() != RESUME_HOOK_VERSION:
        old = _installed_resume_version()
        _copy_resume_script()
        _write_resume_sidecar()
        _append_self_heal_log("update_resume_hook", f"{old or 'unknown'} -> {RESUME_HOOK_VERSION}")


def _missing_terse_artifacts() -> list[str]:
    missing: list[str] = []
    if not TERSE_HOOK_TARGET.exists():
        missing.append("script")
    if not TERSE_PROMPT_SIDECAR.exists():
        missing.append("sidecar")
    return missing


def _self_heal_terse_mode() -> None:
    if not is_terse_mode_enabled():
        return
    missing = _missing_terse_artifacts()
    if missing:
        _copy_terse_script()
        _write_terse_sidecar()
        _append_self_heal_log("restore_terse_hook", f"missing={','.join(missing)}")
    else:
        old = _installed_terse_version()
        if old != TERSE_HOOK_VERSION:
            _copy_terse_script()
            _write_terse_sidecar()
            _append_self_heal_log(
                "update_terse_hook", f"{old or 'unknown'} -> {TERSE_HOOK_VERSION}"
            )
    _self_heal_codex_terse()


def _migrate_resume_command_if_needed() -> None:
    settings = _load_settings()
    entries = _session_start_list(settings)
    if not entries:
        return
    old_target = str(RESUME_HOOK_TARGET)
    new_command = _resume_command()
    changed = False
    for entry in entries:
        if not isinstance(entry, dict) or not _is_resume_entry(entry):
            continue
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            command = hook.get("command")
            if not isinstance(command, str) or old_target not in command:
                continue
            hook["command"] = new_command
            changed = True
    if not changed:
        return
    _save_settings(settings)
    _append_self_heal_log(
        "migrate_resume_command",
        f"{RESUME_HOOK_TARGET} -> {_resolve_resume_source()}",
    )


def _missing_resume_artifacts() -> list[str]:
    missing: list[str] = []
    if not RESUME_HOOK_TARGET.exists():
        missing.append("script")
    if not RESUME_PROMPT_SIDECAR.exists():
        missing.append("sidecar")
    return missing


def _resume_restore_context(missing: list[str]) -> str:
    parts = [f"missing={','.join(missing)}"]
    elapsed = _seconds_since_last_self_heal("restore_resume_hook")
    if elapsed is not None:
        parts.append(f"seconds_since_previous_restore={elapsed}")
    command = _installed_resume_command()
    if command:
        source = str(_resolve_resume_source())
        target = str(RESUME_HOOK_TARGET)
        if source in command:
            parts.append("registered=source")
        elif target in command:
            parts.append("registered=target")
        else:
            parts.append("registered=other")
    recent = _recent_claude_dir_changes()
    if recent:
        parts.append(f"recent_claude_entries={recent}")
    return "; ".join(parts)


def _seconds_since_last_self_heal(action: str) -> int | None:
    try:
        settings = _load_settings()
    except SystemExit:
        return None
    usage_settings = settings.get(BACKUP_KEY)
    if not isinstance(usage_settings, dict):
        return None
    log = usage_settings.get("selfHealLog")
    if not isinstance(log, list):
        return None
    for entry in reversed(log):
        if not isinstance(entry, dict) or entry.get("action") != action:
            continue
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, str):
            continue
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        return max(0, int((datetime.now(UTC) - parsed).total_seconds()))
    return None


def _installed_resume_command() -> str:
    try:
        settings = _load_settings()
    except SystemExit:
        return ""
    entries = _session_start_list(settings)
    if not entries:
        return ""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            command = hook.get("command")
            if isinstance(command, str) and any(marker in command for marker in _RESUME_MARKERS):
                return command
    return ""


def _recent_claude_dir_changes(limit: int = 6) -> str:
    root = CLAUDE_SETTINGS.parent
    try:
        entries = sorted(
            (entry for entry in root.iterdir()),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return ""
    result: list[str] = []
    now = datetime.now(UTC).timestamp()
    for entry in entries[:limit]:
        try:
            stat_result = entry.stat()
        except OSError:
            continue
        age = max(0, int(now - stat_result.st_mtime))
        kind = "dir" if entry.is_dir() else "file"
        result.append(f"{entry.name}:{kind}:{age}s")
    return ",".join(result)


def _append_self_heal_log(action: str, detail: str) -> None:
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


def _run_quietly(func: Any, *args: Any, **kwargs: Any) -> Any:
    if os.environ.get("USAGE_DEBUG") == "1":
        return func(*args, **kwargs)
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        return func(*args, **kwargs)


def _debug_self_heal_failure(action: str, exc: BaseException) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        print(f"usage self-heal {action} failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def self_heal() -> None:
    """Best-effort startup repair for usage-owned Claude statusLine hooks."""
    try:
        settings = _load_settings()
        state = _detect_current_state(settings)
        if state in {"external", "legacy-tt"}:
            return
        _migrate_bundled_python_commands_if_needed(settings)
        if not is_setup() and "statusLine" not in settings:
            exit_code = _run_quietly(setup)
            if exit_code == 0:
                _append_self_heal_log("install_hook", "initial setup")
            return
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        _debug_self_heal_failure("install_hook", exc)

    try:
        state = _detect_current_state()
        if state in {"external", "legacy-tt"}:
            return
        old_version = _installed_hook_version()
        if needs_update():
            _run_quietly(update_hook)
            detail = f"{old_version or 'not installed'} -> {HOOK_VERSION}"
            _append_self_heal_log("update_hook", detail)
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        _debug_self_heal_failure("update_hook", exc)

    try:
        state = _detect_current_state()
        if state in {"external", "legacy-tt"}:
            return
        if not _statusline_command_target_exists() and state in {"us-direct", "us-forwarder"}:
            _copy_hook_script()
            _copy_forwarder_script()
            _append_self_heal_log("restore_hook_scripts", "statusLine command target missing")
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        _debug_self_heal_failure("restore_hook_scripts", exc)

    try:
        _self_heal_resume()
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        _debug_self_heal_failure("resume_hook", exc)

    try:
        _self_heal_terse_mode()
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        _debug_self_heal_failure("terse_hook", exc)


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
    _migrate_from_legacy_usage()
    has_claude = CLAUDE_SETTINGS.parent.exists()
    has_codex = CODEX_CONFIG.exists()
    if not has_claude and not has_codex:
        print(_t("setup_no_agents"), file=sys.stderr)
        return 1

    if has_claude:
        settings = _load_settings()
        _migrate_bundled_python_commands_if_needed(settings)
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

        disable_session_resume()
        disable_terse_mode()

    if CODEX_CONFIG.exists():
        _unsetup_codex()

    return 0
