# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import os
import shlex
import sqlite3
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Final

from i18n import packaged_resource_path
from installer import setup_hook

SEPARATOR = "-" * 29
RATE_LIMIT_FRESH_SECONDS: Final = 15 * 60

STATUS_FILE: Final = "status_file"
CODEX_SESSIONS: Final = "codex_sessions"
CODEX_STATE: Final = "codex_state"
HOOK_STATE: Final = "hook_state"
HOOK_VERSION: Final = "hook_version"
HOOK_SCRIPT: Final = "hook_script"
STATUS_COMMAND: Final = "status_command"
FORWARDER_SCRIPT: Final = "forwarder_script"
FORWARDER_PROMPT: Final = "forwarder_prompt"
EXTERNAL_HOOKS: Final = "external_hooks"
CODEX_LOGS: Final = "codex_logs"
CODEX_RATE_LIMITS: Final = "codex_rate_limits"
CODEX_HISTORY: Final = "codex_history"
CLAUDE_COST: Final = "claude_cost"

CHECK_LABELS: Final = {
    STATUS_FILE: "status file",
    CODEX_SESSIONS: "codex jsonl",
    CODEX_STATE: "codex state",
    HOOK_STATE: "hook state",
    HOOK_VERSION: "hook version",
    HOOK_SCRIPT: "hook script",
    STATUS_COMMAND: "status command",
    FORWARDER_SCRIPT: "forwarder script",
    FORWARDER_PROMPT: "forwarder prompt",
    EXTERNAL_HOOKS: "external hooks",
    CODEX_LOGS: "codex logs",
    CODEX_RATE_LIMITS: "codex rate limits",
    CODEX_HISTORY: "codex history",
    CLAUDE_COST: "claude cost",
}


@dataclass(slots=True)
class CheckResult:
    code: str
    status: str
    detail: str


@dataclass(slots=True)
class DoctorReport:
    version: str
    checks: list[tuple[str, CheckResult]]
    self_heal_log: list[str]


def collect() -> DoctorReport:
    checks = [
        ("core", _field(STATUS_FILE, _status_file)),
        ("core", _field(CODEX_SESSIONS, _codex_sessions)),
        ("core", _field(CODEX_STATE, _codex_state)),
        ("core", _field(CODEX_HISTORY, _codex_history)),
        ("hook", _field(HOOK_STATE, _hook_state)),
        ("hook", _field(HOOK_VERSION, _hook_version)),
        ("hook", _field(HOOK_SCRIPT, lambda: _script_status(setup_hook.HOOK_TARGET))),
        ("hook", _field(STATUS_COMMAND, _status_command)),
        ("optional", _field(FORWARDER_SCRIPT, _forwarder_script_status)),
        ("optional", _field(FORWARDER_PROMPT, _forwarder_prompt)),
        ("optional", _field(EXTERNAL_HOOKS, _external_hooks)),
        ("optional", _field(CODEX_LOGS, _codex_logs)),
        ("optional", _field(CODEX_RATE_LIMITS, _codex_rate_limits)),
        ("optional", _field(CLAUDE_COST, _claude_cost)),
    ]
    return DoctorReport(
        version=_text_field(_current_version),
        checks=checks,
        self_heal_log=_self_heal_log_lines(),
    )


def render(report: DoctorReport | None = None) -> str:
    current = report if report is not None else collect()
    lines = [
        f"usage v{current.version}",
        SEPARATOR,
    ]
    for section in ("core", "hook", "optional"):
        lines.append(f"[{section}]")
        lines.extend(
            f"{(CHECK_LABELS[check.code] + ':'):<19}{check.detail}"
            for check_section, check in current.checks
            if check_section == section
        )
        lines.append(SEPARATOR)
    lines.extend(["self-heal log (last 5):", *current.self_heal_log])
    return "\n".join(lines) + "\n"


def render_json(report: DoctorReport | None = None) -> str:
    import json

    current = report if report is not None else collect()
    summary = {"ok": 0, "warn": 0, "error": 0}
    checks = []
    for section, check in current.checks:
        summary[check.status] += 1
        checks.append(
            {
                "section": section,
                "code": check.code,
                "status": check.status,
                "detail": check.detail,
            }
        )
    return json.dumps(
        {
            "version": current.version,
            "checks": checks,
            "self_heal_log": current.self_heal_log,
            "summary": summary,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def exit_code(report: DoctorReport) -> int:
    return int(any(check.status == "error" for _, check in report.checks))


def _field(code: str, func: Callable[[], CheckResult]) -> CheckResult:
    try:
        return func()
    except Exception as exc:
        return CheckResult(code=code, status="error", detail=f"error: {exc}")


def _text_field(func: Callable[[], str]) -> str:
    try:
        return func()
    except Exception as exc:
        return f"error: {exc}"


def _current_version() -> str:
    try:
        return metadata.version("usage-cli")
    except metadata.PackageNotFoundError:
        pyproject = packaged_resource_path(
            "pyproject.toml", Path(__file__).with_name("pyproject.toml")
        )
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        if isinstance(version, str):
            return version
        raise RuntimeError("project.version missing from pyproject.toml") from None


def _hook_state() -> CheckResult:
    state = setup_hook._detect_current_state()
    status = "ok" if state in {"us-direct", "us-forwarder"} else "warn"
    return CheckResult(code=HOOK_STATE, status=status, detail=state)


def _hook_version() -> CheckResult:
    installed = setup_hook._installed_hook_version()
    if installed is None:
        return CheckResult(
            code=HOOK_VERSION,
            status="warn",
            detail=f"not installed (current {setup_hook.HOOK_VERSION})",
        )
    suffix = (
        "current"
        if installed == setup_hook.HOOK_VERSION
        else f"current {setup_hook.HOOK_VERSION}"
    )
    status = "ok" if installed == setup_hook.HOOK_VERSION else "warn"
    return CheckResult(code=HOOK_VERSION, status=status, detail=f"{installed} ({suffix})")


def _script_status(path: Path) -> CheckResult:
    display = _display_path(path)
    exists = path.exists()
    return CheckResult(
        code=HOOK_SCRIPT,
        status="ok" if exists else "warn",
        detail=f"{display}  [{'ok' if exists else 'missing'}]",
    )


def _forwarder_script_status() -> CheckResult:
    path = setup_hook.FORWARDER_TARGET
    display = _display_path(path)
    if path.exists():
        return CheckResult(
            code=FORWARDER_SCRIPT,
            status="ok",
            detail=f"{display}  [ok]",
        )
    state = setup_hook._detect_current_state()
    status = "warn" if state == "us-forwarder" else "ok"
    detail = "missing" if state == "us-forwarder" else f"not needed in {state} mode"
    return CheckResult(
        code=FORWARDER_SCRIPT,
        status=status,
        detail=f"{display}  [{detail}]",
    )


def _status_file() -> CheckResult:
    path = setup_hook.STATUS_FILE
    display = _display_path(path)
    if not path.exists():
        return CheckResult(code=STATUS_FILE, status="warn", detail=f"{display}  [missing]")
    return CheckResult(
        code=STATUS_FILE,
        status="ok",
        detail=f"{display}  (wrote {_ago(path.stat().st_mtime)} ago)",
    )


def _status_command() -> CheckResult:
    settings = setup_hook._load_settings()
    sl = settings.get("statusLine")
    command = sl.get("command") if isinstance(sl, dict) else None
    if not isinstance(command, str):
        return CheckResult(code=STATUS_COMMAND, status="warn", detail="not configured")
    if (
        sys.platform == "win32"
        and "usage-statusline" in command
        and "\\" in command
    ):
        return CheckResult(
            code=STATUS_COMMAND,
            status="warn",
            detail=(
                "Windows Git Bash-incompatible paths; run usage --setup, then restart Claude Code"
            ),
        )
    return CheckResult(code=STATUS_COMMAND, status="ok", detail="ok")


def _external_hooks() -> CheckResult:
    state = setup_hook._detect_current_state()
    if state != "external":
        return CheckResult(code=EXTERNAL_HOOKS, status="ok", detail="none detected")
    settings = setup_hook._load_settings()
    sl = settings.get("statusLine")
    command = sl.get("command") if isinstance(sl, dict) else None
    if not isinstance(command, str):
        return CheckResult(
            code=EXTERNAL_HOOKS,
            status="warn",
            detail="external (unrecognized)",
        )
    keyword = _external_keyword(command)
    return CheckResult(
        code=EXTERNAL_HOOKS,
        status="warn",
        detail=keyword if keyword else "external (unrecognized)",
    )


def _forwarder_prompt() -> CheckResult:
    settings = setup_hook._load_settings()
    usage = settings.get(setup_hook.BACKUP_KEY)
    if isinstance(usage, dict) and usage.get("forwarderModePromptDismissed") is True:
        return CheckResult(code=FORWARDER_PROMPT, status="ok", detail="acked")
    return CheckResult(code=FORWARDER_PROMPT, status="ok", detail="not acked")


def _self_heal_log_lines() -> list[str]:
    try:
        settings = setup_hook._load_settings()
        usage = settings.get(setup_hook.BACKUP_KEY)
        log = usage.get("selfHealLog") if isinstance(usage, dict) else None
        if not isinstance(log, list) or not log:
            return ["  none"]
        lines: list[str] = []
        for item in log[-5:]:
            if not isinstance(item, dict):
                continue
            timestamp = str(item.get("timestamp", "unknown"))
            action = str(item.get("action", "unknown"))
            detail = str(item.get("detail", ""))
            lines.append(f"  {timestamp}  {action:<22} {detail}".rstrip())
        return lines or ["  none"]
    except Exception as exc:
        return [f"  error: {exc}"]


def _codex_sessions() -> CheckResult:
    from loaders import codex_loader

    sessions_dir = codex_loader.SESSIONS_DIR
    if not sessions_dir.is_dir():
        return CheckResult(
            code=CODEX_SESSIONS,
            status="warn",
            detail="0 files, missing sessions dir",
        )
    count = 0
    newest_mtime = 0.0
    for path in sessions_dir.rglob("*.jsonl"):
        count += 1
        try:
            newest_mtime = max(newest_mtime, path.stat().st_mtime)
        except OSError:
            continue
    if newest_mtime <= 0:
        return CheckResult(
            code=CODEX_SESSIONS,
            status="warn",
            detail=f"{count} files, no readable mtimes",
        )
    return CheckResult(
        code=CODEX_SESSIONS,
        status="ok",
        detail=f"{count} files, latest wrote {_ago(newest_mtime)} ago",
    )


def _codex_logs() -> CheckResult:
    from loaders import codex_loader

    logs_db = codex_loader.LOGS_DB
    if not logs_db.exists():
        return CheckResult(
            code=CODEX_LOGS,
            status="warn",
            detail=f"{_display_path(logs_db)}  [missing], rate_limit rows: 0",
        )
    rows = _codex_rate_limit_log_count(logs_db)
    return CheckResult(
        code=CODEX_LOGS,
        status="ok",
        detail=f"{_display_path(logs_db)}  [ok], rate_limit rows: {rows}",
    )


def _codex_rate_limit_log_count(logs_db: Path) -> int:
    query = (
        "SELECT count(*) FROM logs "
        "WHERE feedback_log_body LIKE '%codex.rate_limits%' "
        "OR feedback_log_body LIKE '%usage_limit_reached%'"
    )
    with sqlite3.connect(f"{logs_db.resolve().as_uri()}?mode=ro", uri=True) as conn:
        value = conn.execute(query).fetchone()[0]
    return int(value)


def _codex_state() -> CheckResult:
    from loaders import codex_loader

    state_db = codex_loader.STATE_DB
    exists = state_db.exists()
    return CheckResult(
        code=CODEX_STATE,
        status="ok" if exists else "warn",
        detail=f"{_display_path(state_db)}  [{'ok' if exists else 'missing'}]",
    )


def _codex_history() -> CheckResult:
    from loaders import codex_loader

    has_jsonl_entries = codex_loader.has_recent_jsonl_entries(hours_back=7 * 24)
    has_sqlite_turns = codex_loader.has_recent_thread_history_turns(hours_back=7 * 24)
    if has_jsonl_entries is False and has_sqlite_turns is True:
        return CheckResult(
            code=CODEX_HISTORY,
            status="warn",
            detail=(
                "Codex may have moved conversation history to SQLite; "
                "usage's jsonl source may no longer be valid"
            ),
        )
    if has_jsonl_entries is None or has_sqlite_turns is None:
        return CheckResult(code=CODEX_HISTORY, status="ok", detail="unavailable")
    return CheckResult(code=CODEX_HISTORY, status="ok", detail="jsonl active")


def _codex_rate_limits() -> CheckResult:
    from loaders import codex_loader

    rate_limits = codex_loader.load_rate_limits()
    if rate_limits is None:
        return CheckResult(code=CODEX_RATE_LIMITS, status="warn", detail="none")
    five = "yes" if rate_limits.five_hour_pct is not None else "no"
    weekly = "yes" if rate_limits.seven_day_pct is not None else "no"
    updated = _rate_limits_updated_age(rate_limits.updated_at)
    has_limit = rate_limits.five_hour_pct is not None or rate_limits.seven_day_pct is not None
    status = "ok" if has_limit and _rate_limits_are_fresh(rate_limits.updated_at) else "warn"
    return CheckResult(
        code=CODEX_RATE_LIMITS,
        status=status,
        detail=f"5h: {five}, weekly: {weekly}, updated: {updated}",
    )


def _claude_cost() -> CheckResult:
    import json

    import pricing
    from loaders import history_loader

    try:
        status_data = json.loads(setup_hook.STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return CheckResult(code=CLAUDE_COST, status="ok", detail="unavailable")

    cost = status_data.get("cost") if isinstance(status_data, dict) else None
    official_cost = cost.get("total_cost_usd") if isinstance(cost, dict) else None
    session_id = status_data.get("session_id") if isinstance(status_data, dict) else None
    if (
        not isinstance(official_cost, int | float)
        or official_cost <= 0
        or not isinstance(session_id, str)
        or not session_id
    ):
        return CheckResult(code=CLAUDE_COST, status="ok", detail="unavailable")

    entries = [
        entry
        for entry in history_loader.load_entries()
        if entry.session_id == session_id
    ]
    if not entries:
        return CheckResult(code=CLAUDE_COST, status="ok", detail="unavailable")

    calculated_cost = sum(pricing.calculate_cost(entry) for entry in entries)
    absolute_difference = abs(official_cost - calculated_cost)
    relative_difference = absolute_difference / official_cost
    unpriced_models = sorted(
        {entry.model for entry in entries if not pricing.is_model_priced(entry.model)}
    )
    detail = (
        f"official ${official_cost:.2f}, usage ${calculated_cost:.2f}, "
        f"difference {relative_difference:.1%}"
    )
    if unpriced_models:
        detail += f"; unpriced models: {', '.join(unpriced_models)}"
    status = "warn" if relative_difference > 0.2 and absolute_difference > 1.0 else "ok"
    return CheckResult(code=CLAUDE_COST, status=status, detail=detail)


def _rate_limits_are_fresh(updated_at: str) -> bool:
    if not updated_at:
        return False
    timestamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    age_seconds = datetime.now(UTC).timestamp() - timestamp.timestamp()
    return 0 <= age_seconds <= RATE_LIMIT_FRESH_SECONDS


def _rate_limits_updated_age(updated_at: str) -> str:
    if not updated_at:
        return "unknown"
    timestamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    return f"{_ago(timestamp.timestamp())} ago"


def _external_keyword(command: str) -> str | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    for part in parts:
        token = part.lower()
        basename = Path(part).name.lower()
        for keyword in ("ccusage", "lord-kali"):
            if keyword in token or keyword in basename:
                return keyword
    return None


def _display_path(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    if text == home:
        return "~"
    if text.startswith(home + os.sep):
        return "~" + text[len(home) :]
    return text


def _ago(mtime: float) -> str:
    seconds = max(0, int(datetime.now(UTC).timestamp() - mtime))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"
