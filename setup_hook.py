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
_SL_REGEX = re.compile(r"status_line\s*=\s*\[.*?\]", re.DOTALL)

# Ceiling C — opt-in SessionStart hook that injects "where you left off" into a new
# session. Off by default: enabled only via the menu toggle, never by self_heal.
RESUME_HOOK_TARGET = Path(os.path.expanduser("~/.claude/usage-session-resume.py"))
RESUME_PROMPT_SIDECAR = Path(os.path.expanduser("~/.claude/usage-resume-prompt.json"))
RESUME_HOOK_VERSION = "1.2"
RESUME_MATCHER = "startup|clear"
RESUME_LANGS = ("zh-TW", "zh-CN", "en", "ja", "ko")
_RESUME_MARKER = "usage-session-resume"


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
    # Prefer /usr/bin/python3 or bundled app Python, not a venv; the hook is stdlib-only.
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
    executable = sys.executable
    if ".app/Contents" in executable:
        return executable
    if os.path.exists("/usr/bin/python3"):
        return "/usr/bin/python3"
    return shutil.which("python3") or "python3"


def _shell_arg(value: str) -> str:
    return shlex.quote(value)


def _forwarder_command() -> str:
    python = _find_system_python()
    return f"{shlex.quote(python)} {shlex.quote(str(FORWARDER_TARGET))}"


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
    """Return 'none' | 'us-direct' | 'us-forwarder' | 'external'."""
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
    except (OSError, json.JSONDecodeError) as exc:
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
    except (OSError, json.JSONDecodeError) as exc:
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
    backup[PREV_SL_KEY] = existing
    print(_t("setup_statusline_backed_up", backup_key=BACKUP_KEY, prev_key=PREV_SL_KEY))


def _status_line_toml(items: list[str]) -> str:
    body = ",\n".join(f'  "{item}"' for item in items)
    return f"status_line = [\n{body},\n]"


def _replace_tui_status_line(content: str, replacement: str) -> str:
    table = re.search(r"(?m)^\[tui\]\s*$", content)
    if table is None:
        return content
    next_table = re.search(r"(?m)^\[[^\]\n]+\]\s*$", content[table.end() :])
    section_end = len(content) if next_table is None else table.end() + next_table.start()
    section = content[table.end() : section_end]
    updated_section = _SL_REGEX.sub(replacement, section, count=1)
    return content[: table.end()] + updated_section + content[section_end:]


def _remove_tui_status_line(content: str) -> str:
    table = re.search(r"(?m)^\[tui\]\s*$", content)
    if table is None:
        return content
    next_table = re.search(r"(?m)^\[[^\]\n]+\]\s*$", content[table.end() :])
    section_end = len(content) if next_table is None else table.end() + next_table.start()
    section = content[table.end() : section_end]
    updated_section = _SL_REGEX.sub("", section, count=1)
    return content[: table.end()] + updated_section + content[section_end:]


def _read_codex_config() -> tuple[str, dict[str, Any]] | None:
    try:
        content = CODEX_CONFIG.read_text(encoding="utf-8")
        parsed = tomllib.loads(content)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return content, parsed


def _codex_status_line(parsed: dict[str, Any]) -> object:
    tui = parsed.get("tui")
    return tui.get("status_line") if isinstance(tui, dict) else None


def _setup_codex() -> None:
    result = _read_codex_config()
    if not result:
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
    elif "[tui]" in content:
        content = content.replace("[tui]", f"[tui]\n{_status_line_toml(CODEX_STATUS_LINE)}")
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
        except (OSError, json.JSONDecodeError, AttributeError):
            old_items = []
        content = _replace_tui_status_line(content, _status_line_toml(old_items))
        backup_path.unlink(missing_ok=True)
        print(_t("setup_codex_restored"))
    else:
        content = _remove_tui_status_line(content)
        print(_t("setup_codex_removed"))

    _atomic_write_text(CODEX_CONFIG, content)


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


def _resume_command() -> str:
    python = _find_system_python()
    return f"{shlex.quote(python)} {shlex.quote(str(RESUME_HOOK_TARGET))}"


def _copy_resume_script() -> None:
    source = _resolve_resume_source()
    RESUME_HOOK_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, RESUME_HOOK_TARGET)
    RESUME_HOOK_TARGET.chmod(
        RESUME_HOOK_TARGET.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
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
    out: dict[str, dict[str, str]] = {}
    for lang in RESUME_LANGS:
        table_raw = bundle.get(lang)
        table: dict[str, Any] = table_raw if isinstance(table_raw, dict) else {}
        prompt = table.get("report_rw_prompt") or en.get("report_rw_prompt")
        none_label = table.get("report_rw_none") or en.get("report_rw_none")
        lead = table.get("report_rw_inject_lead") or en.get("report_rw_inject_lead") or ""
        empty = table.get("report_rw_empty") or en.get("report_rw_empty") or ""
        if isinstance(prompt, str) and isinstance(none_label, str):
            out[lang] = {"prompt": prompt, "none": none_label, "lead": lead, "empty": empty}
    if out:
        RESUME_PROMPT_SIDECAR.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            RESUME_PROMPT_SIDECAR, json.dumps(out, ensure_ascii=False, indent=2) + "\n"
        )


def _is_resume_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(h, dict) and isinstance(h.get("command"), str) and _RESUME_MARKER in h["command"]
        for h in hooks
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
    session_start[:] = [e for e in session_start if not _is_resume_entry(e)]
    session_start.append(
        {"matcher": RESUME_MATCHER, "hooks": [{"type": "command", "command": _resume_command()}]}
    )
    _save_settings(settings)
    print(_t("setup_resume_enabled", path=RESUME_HOOK_TARGET))
    print(_t("setup_claude_restart_required"))
    return 0


def disable_session_resume() -> int:
    if CLAUDE_SETTINGS.parent.exists():
        settings = _load_settings()
        session_start = _session_start_list(settings)
        if session_start is not None:
            kept = [e for e in session_start if not _is_resume_entry(e)]
            if len(kept) != len(session_start):
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


def _installed_resume_version() -> str | None:
    try:
        with RESUME_HOOK_TARGET.open(encoding="utf-8") as f:
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
    if not RESUME_HOOK_TARGET.exists() or not RESUME_PROMPT_SIDECAR.exists():
        _copy_resume_script()
        _write_resume_sidecar()
        _append_self_heal_log("restore_resume_hook", "resume script or sidecar missing")
    elif _installed_resume_version() != RESUME_HOOK_VERSION:
        old = _installed_resume_version()
        _copy_resume_script()
        _write_resume_sidecar()
        _append_self_heal_log("update_resume_hook", f"{old or 'unknown'} -> {RESUME_HOOK_VERSION}")


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

    if CODEX_CONFIG.exists():
        _unsetup_codex()

    return 0
