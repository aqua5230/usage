# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Install, configure, and repair usage's session companion hooks."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import setup_hook
from i18n import t as _t
from setup_hook import (
    BACKUP_KEY,
    HOOK_VERSION,
    _atomic_write_text,
    _copy_forwarder_script,
    _copy_hook_script,
    _detect_current_state,
    _ensure_table_line,
    _find_system_python,
    _forwarder_command,
    _installed_hook_version,
    _load_settings,
    _read_codex_config,
    _save_settings,
    _shell_arg,
    _statusline_command,
    _statusline_command_target_exists,
    _uses_bundled_app_python,
    is_setup,
    needs_update,
    setup,
    update_hook,
)

CLAUDE_SETTINGS = setup_hook.CLAUDE_SETTINGS
CODEX_CONFIG = setup_hook.CODEX_CONFIG

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
# Per-message tail reminder — a UserPromptSubmit hook installed alongside the SessionStart
# terse hook. Re-injects a one-line nudge on every prompt so the terse style holds across a
# long conversation. Claude Code only — Codex CLI has no UserPromptSubmit equivalent.
TERSE_REMINDER_HOOK_TARGET = Path(os.path.expanduser("~/.claude/usage-terse-reminder.py"))
TERSE_REMINDER_MATCHER = ""
_TERSE_REMINDER_MARKER = "usage-terse-reminder"
_TERSE_REMINDER_MARKERS = (_TERSE_REMINDER_MARKER, "usage_terse_reminder")


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


def _resolve_terse_reminder_source() -> Path:
    paths = [
        Path(__file__).resolve().parent / "usage_terse_reminder.py",
        (
            Path(sys.executable).resolve().parent.parent
            / "Resources"
            / "usage_terse_reminder.py"
        ),
    ]
    for path in paths:
        if path.exists():
            return path
    tried = ", ".join(str(path) for path in paths)
    raise SystemExit(_t("setup_terse_source_missing", tried=tried))


def _resume_command() -> str:
    python = _find_system_python()
    source = _resolve_resume_source()
    return f"{_shell_arg(python)} {_shell_arg(str(source))}"


def _terse_command() -> str:
    python = _find_system_python()
    source = _resolve_terse_source()
    return f"{_shell_arg(python)} {_shell_arg(str(source))}"


def _terse_reminder_command() -> str:
    python = _find_system_python()
    source = _resolve_terse_reminder_source()
    return f"{_shell_arg(python)} {_shell_arg(str(source))}"


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


def _copy_terse_reminder_script() -> None:
    source = _resolve_terse_reminder_source()
    TERSE_REMINDER_HOOK_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, TERSE_REMINDER_HOOK_TARGET)
    TERSE_REMINDER_HOOK_TARGET.chmod(
        TERSE_REMINDER_HOOK_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
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
        reminder = table.get("terse_reminder_instruction") or en.get("terse_reminder_instruction")
        if isinstance(instruction, str) and instruction:
            entry = {"instruction": instruction}
            if isinstance(reminder, str) and reminder:
                entry["reminder"] = reminder
            out[lang] = entry
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


def _user_prompt_submit_list(settings: dict[str, Any]) -> list[Any] | None:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return None
    ups = hooks.get("UserPromptSubmit")
    return ups if isinstance(ups, list) else None


def _is_terse_reminder_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(h, dict)
        and isinstance(h.get("command"), str)
        and any(marker in h["command"] for marker in _TERSE_REMINDER_MARKERS)
        for h in hooks
    )


def _strip_terse_reminder_hooks(entry: object) -> object | None:
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
            and any(marker in h["command"] for marker in _TERSE_REMINDER_MARKERS)
        )
    ]
    if len(kept) == len(hooks):
        return entry
    if not kept:
        return None
    return {**entry, "hooks": kept}


def _register_terse_reminder(settings: dict[str, Any]) -> None:
    """Idempotently add the per-message UserPromptSubmit reminder entry to ``settings``
    (in memory — caller persists). Strips any prior reminder entry first so a repeat
    enable never duplicates it."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    ups = hooks.get("UserPromptSubmit")
    if not isinstance(ups, list):
        ups = []
        hooks["UserPromptSubmit"] = ups
    ups[:] = [e for e in (_strip_terse_reminder_hooks(e) for e in ups) if e is not None]
    ups.append(
        {
            "matcher": TERSE_REMINDER_MATCHER,
            "hooks": [{"type": "command", "command": _terse_reminder_command()}],
        }
    )


def _codex_terse_command() -> str:
    python = _find_system_python()
    return f"{_shell_arg(python)} {_shell_arg(str(CODEX_TERSE_HOOK_TARGET))}"


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


def is_terse_reminder_enabled() -> bool:
    try:
        settings = _load_settings()
    except SystemExit:
        return False
    entries = _user_prompt_submit_list(settings)
    if not entries:
        return False
    return any(_is_terse_reminder_entry(e) for e in entries)


def enable_session_resume() -> int:
    setup_hook.configure_windows_utf8_output()
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
    setup_hook.configure_windows_utf8_output()
    if not CLAUDE_SETTINGS.parent.exists():
        print(_t("setup_no_agents"), file=sys.stderr)
        return 1
    _copy_terse_script()
    _copy_terse_reminder_script()
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
    _register_terse_reminder(settings)
    _save_settings(settings)
    if CODEX_CONFIG.exists():
        _setup_codex_terse()
    print(_t("terse_mode_enabled_msg"))
    print(_t("setup_claude_restart_required"))
    return 0


def disable_session_resume() -> int:
    setup_hook.configure_windows_utf8_output()
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
    setup_hook.configure_windows_utf8_output()
    if CLAUDE_SETTINGS.parent.exists():
        settings = _load_settings()
        changed = False

        session_start = _session_start_list(settings)
        if session_start is not None:
            kept = [e for e in (_strip_terse_hooks(e) for e in session_start) if e is not None]
            if kept != session_start:
                hooks = settings["hooks"]
                if kept:
                    hooks["SessionStart"] = kept
                else:
                    hooks.pop("SessionStart", None)
                changed = True

        ups = _user_prompt_submit_list(settings)
        if ups is not None:
            kept_ups = [
                e for e in (_strip_terse_reminder_hooks(e) for e in ups) if e is not None
            ]
            if kept_ups != ups:
                hooks = settings["hooks"]
                if kept_ups:
                    hooks["UserPromptSubmit"] = kept_ups
                else:
                    hooks.pop("UserPromptSubmit", None)
                changed = True

        if changed:
            hooks = settings.get("hooks")
            if isinstance(hooks, dict) and not hooks:
                settings.pop("hooks", None)
            _save_settings(settings)
            print(_t("terse_mode_disabled_msg"))
    for path in (TERSE_HOOK_TARGET, TERSE_REMINDER_HOOK_TARGET, TERSE_PROMPT_SIDECAR):
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
    _self_heal_terse_reminder()
    _self_heal_codex_terse()


def _self_heal_terse_reminder() -> None:
    """Backfill the per-message reminder hook when terse mode is on but the
    UserPromptSubmit entry or its script is missing — e.g. a user who enabled terse
    mode before this hook existed upgrades and self-heal installs it."""
    script_missing = not TERSE_REMINDER_HOOK_TARGET.exists()
    entry_missing = not is_terse_reminder_enabled()
    if not (script_missing or entry_missing):
        return
    _copy_terse_reminder_script()
    settings = _load_settings()
    _register_terse_reminder(settings)
    _save_settings(settings)
    parts: list[str] = []
    if script_missing:
        parts.append("script")
    if entry_missing:
        parts.append("entry")
    _append_self_heal_log("restore_terse_reminder_hook", f"missing={','.join(parts)}")


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
        source = _resolve_resume_source().as_posix()
        target = RESUME_HOOK_TARGET.as_posix()
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
        setup_hook._migrate_windows_statusline_command_if_needed(settings)
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
