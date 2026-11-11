#!/usr/bin/env python3
"""Opt-in, stdlib-only Python 3.9 UserPromptSubmit quota reminder."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

__version__ = "1.10"
CLAUDE_STATUS = Path.home() / ".claude/usage-status.json"
QUOTA_SNAPSHOT = Path.home() / ".usage/quota_snapshot.json"
SERVICE_SNAPSHOT = Path.home() / ".usage/service_status_snapshot.json"
STATE_PATH = Path.home() / ".usage/quota_aware_state.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _account_uuid() -> Optional[str]:
    configured = [
        Path(part.strip()).expanduser()
        for part in os.environ.get("CLAUDE_CONFIG_DIR", "").split(",")
        if part.strip()
    ]
    path = configured[0] / ".claude.json" if configured else Path.home() / ".claude.json"
    account = _read(path).get("oauthAccount")
    uuid = account.get("accountUuid") if isinstance(account, dict) else None
    return uuid if isinstance(uuid, str) and uuid else None


def _account_reminder(session_id: str, now: float, state: dict[str, Any]) -> tuple[str, bool, bool]:
    previous = state.get("accounts", {})
    records = {
        key: value
        for key, value in (previous.items() if isinstance(previous, dict) else [])
        if isinstance(value, dict)
        and isinstance(value.get("uuid"), str)
        and value["uuid"]
        and (_number(value.get("at")) or 0) >= now - 7 * 86400
    }
    changed = records != previous
    message = ""
    uuid = _account_uuid()
    seen = records.get(session_id)
    if uuid is not None and (seen is None or seen["uuid"] != uuid):
        records[session_id] = {"uuid": uuid, "at": now}
        if seen is not None:
            message = (
                "Claude Code account changed since earlier in this conversation (/login). "
                "Earlier Claude Code quota notices no longer apply; "
                "the new account's quota shows up after your next reply."
            )
            for window in ("five_hour", "seven_day"):
                state.pop(json.dumps([session_id, "Claude Code", window]), None)
            records[session_id]["changed_at"] = now
            # The status line re-stamps the old account's cached numbers on every redraw,
            # so only numbers that differ from these count as the new account's.
            records[session_id]["old_limits"] = _read(CLAUDE_STATUS).get("rate_limits")
        seen = records[session_id]
        changed = True
    pending = False
    if seen is not None and (changed_at := _number(seen.get("changed_at"))) is not None:
        status = _read(CLAUDE_STATUS)
        received = _number(status.get("_received_at_ts"))
        pending = (
            received is None
            or received <= changed_at
            or status.get("rate_limits") == seen.get("old_limits")
        )
        if not pending:
            del seen["changed_at"]
            seen.pop("old_limits", None)
            changed = True
    if records or "accounts" in state:
        state["accounts"] = records
    return message, changed, pending


def _generated_at(value: Any) -> float:
    if not isinstance(value, str):
        raise ValueError("Invalid generated_at")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Missing generated_at timezone")
    return parsed.timestamp()


def _windows(session_id: str, now: float) -> list[tuple[str, str, float, float, str]]:
    windows: list[tuple[str, str, float, float, str]] = []

    def add(
        tool: str, data: Any, *, claude: bool = False, generated: float = 0, updated_at: Any = None
    ) -> None:
        if not isinstance(data, dict):
            return
        suffix = ""
        try:
            age = now - _generated_at(updated_at)
            if age >= 3600:
                suffix = f" (last updated {int(age // 3600)}h ago; it may have reset since)"
        except (ValueError, OverflowError):
            pass
        for name in ("five_hour", "seven_day"):
            window = data.get(name)
            if not isinstance(window, dict):
                continue
            used = _number(window.get("used_percentage" if claude else "used_percent"))
            reset = _number(window.get("resets_at"))
            if reset is None and generated:
                remaining = _number(window.get("resets_in_seconds"))
                if remaining is not None:
                    reset = generated + remaining
            if used is not None and reset is not None and reset > now:
                windows.append((tool, name, used, reset, suffix))

    status = _read(CLAUDE_STATUS)
    # A session that has not replied yet carries the previous session's windows, which can
    # be another account's after a /login switch. Older status line hooks omit the field.
    if status.get("_rate_limits_session_id", session_id) == session_id:
        add("Claude Code", status.get("rate_limits"), claude=True)
    snapshot = _read(QUOTA_SNAPSHOT)
    try:
        generated = _generated_at(snapshot.get("generated_at"))
    except (ValueError, OverflowError):
        return windows
    if now - generated > 900:
        return windows
    agents = snapshot.get("agents")
    if not isinstance(agents, dict):
        return windows
    codex = agents.get("codex")
    if isinstance(codex, dict) and codex.get("available"):
        add("Codex", codex, updated_at=codex.get("updated_at"))
    muse = agents.get("muse")
    if isinstance(muse, dict) and muse.get("available"):
        add("Muse", muse, updated_at=muse.get("updated_at"))
    agy = agents.get("antigravity")
    if isinstance(agy, dict) and agy.get("available") and isinstance(agy.get("groups"), list):
        for group in agy["groups"]:
            if isinstance(group, dict) and isinstance(group.get("name"), str):
                add(
                    "Antigravity (" + group["name"] + ")",
                    group,
                    generated=generated,
                    updated_at=agy.get("updated_at"),
                )
    return windows


def _services(now: float) -> list[dict[str, Any]]:
    snapshot = _read(SERVICE_SNAPSHOT)
    try:
        generated = _generated_at(snapshot.get("generated_at"))
    except (ValueError, OverflowError):
        return []
    if now - generated > 900:
        return []
    services = snapshot.get("services")
    if not isinstance(services, list):
        return []
    return [
        entry
        for entry in services
        if isinstance(entry, dict)
        and entry.get("source") in ("fetched", "cache")
        # Same statuses the menu bar alerts on; "unknown" and maintenance are neither an
        # incident nor a recovery.
        and entry.get("status")
        in ("operational", "degraded_performance", "partial_outage", "major_outage")
        and isinstance(entry.get("is_abnormal"), bool)
        and all(
            isinstance(entry.get(key), str) for key in ("service_name", "status", "description")
        )
    ]


def _service_reminders(
    session_id: str, now: float, state: dict[str, Any]
) -> tuple[list[str], bool]:
    previous = state.get("services", {})
    records = {
        key: value
        for key, value in (previous.items() if isinstance(previous, dict) else [])
        if isinstance(value, dict)
        and isinstance(value.get("status"), str)
        and (_number(value.get("at")) or 0) >= now - 7 * 86400
    }
    changed = records != previous
    messages = []
    for entry in _services(now):
        name = entry["service_name"]
        label = {"Claude": "Claude Code / Claude API", "Codex": "Codex API"}.get(name, name)
        key = json.dumps([session_id, name])
        seen = records.get(key)
        if not entry["is_abnormal"]:
            if seen is not None:
                # The app also clears is_abnormal for long-running minor issues it suppresses.
                messages.append(
                    f"{label} official status is back to operational; "
                    "the earlier incident notice no longer applies."
                    if entry["status"] == "operational"
                    else f"{label} official status is still {entry['status']}, but it looks like "
                    "a long-running minor issue; treat the service as usable and the earlier "
                    "incident notice as no longer applying."
                )
                del records[key]
                changed = True
        elif seen is None or seen["status"] != entry["status"]:
            message = f"{label} official status: {entry['status']} ({entry['description']}). "
            if name == "Codex":
                message += (
                    "If a codex exec dispatch fails or hangs, suspect this incident first: "
                    "don't retry repeatedly or debug the task brief; switch to another agent "
                    "or tell the user. If you are not sending work to Codex, don't mention it."
                )
            else:
                message += (
                    "Slow responses, API errors, or failed subagents in this session may come "
                    "from this incident, not from the code; say so if it happens. "
                    "Otherwise don't mention it."
                )
            messages.append(message)
            records[key] = {"status": entry["status"], "at": now}
            changed = True
    if records or "services" in state:
        state["services"] = records
    return messages, changed


def _save(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=STATE_PATH.parent, suffix=".tmp", delete=False
    ) as handle:
        temporary = handle.name
        json.dump(state, handle)
    try:
        os.replace(temporary, STATE_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _local(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, timezone.utc).astimezone()


def _usage(used: float, reset: float, now: float) -> str:
    minutes = max(1, math.ceil((reset - now) / 60))
    hours, minutes = divmod(minutes, 60)
    duration = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    at = _local(reset)
    clock = f"{at:%H:%M}" if at.date() == _local(now).date() else f"{at:%a %H:%M}"
    return f"{used:g}% used, resets in {duration} (at {clock} local time)"


def _claude_pending(session_id: str) -> bool:
    # Claude Code's quota is tied to this session only after its first reply (see _windows),
    # so an overview sent before that would leave out the quota this session runs on.
    owner = _read(CLAUDE_STATUS).get("_rate_limits_session_id")
    return isinstance(owner, str) and owner != session_id


def _overview_reminder(
    session_id: str,
    now: float,
    state: dict[str, Any],
    windows: list[tuple[str, str, float, float, str]],
) -> tuple[str, bool]:
    previous = state.get("overview", {})
    records = {
        key: value
        for key, value in (previous.items() if isinstance(previous, dict) else [])
        if (shown := _number(value)) is not None and shown >= now - 7 * 86400
    }
    changed = records != previous
    tools: dict[str, list[str]] = {}
    if session_id not in records and not _claude_pending(session_id):
        for tool, window, used, reset, suffix in windows:
            if suffix:
                continue
            if tool.startswith("Antigravity ("):
                tool = f'Antigravity CLI (agy) model group "{tool[len("Antigravity (") : -1]}"'
            label = "5-hour" if window == "five_hour" else "weekly"
            tools.setdefault(tool, []).append(f"{label} {_usage(used, reset, now)}")
    block = ""
    if tools:
        lines = [f"{tool}: {'; '.join(usage)}." for tool, usage in tools.items()]
        block = (
            "[usage quota overview] Quota at the start of this conversation:\n"
            + "\n".join(lines)
            + f"\nCurrent local time: {_local(now):%a %H:%M}.\n"
            "Use this only to choose which tool or agent to send work to and whether to wait "
            "for a reset; plenty of quota is not a reason to do more than the user asked. "
            "Don't mention it unless the user asks or it changes a decision."
        )
        records[session_id] = now
        changed = True
    if records or "overview" in state:
        state["overview"] = records
    return block, changed


def reminder(session_id: str, now: float) -> str:
    state: dict[str, Any] = {
        key: value
        for key, value in _read(STATE_PATH).items()
        if key in ("services", "overview", "accounts")
        or (
            isinstance(value, dict)
            and _number(value.get("resets_at")) is not None
            and _number(value.get("level")) is not None
        )
    }
    messages = []
    limited = set()
    account_line, accounts_changed, account_pending = _account_reminder(session_id, now, state)
    windows = _windows(session_id, now)
    if account_pending:
        windows = [entry for entry in windows if entry[0] != "Claude Code"]
    overview_block, overview_changed = _overview_reminder(session_id, now, state, windows)
    current = {(tool, window): (used, reset) for tool, window, used, reset, _suffix in windows}
    reset_lines = [account_line] if account_line else []
    quota_changed = False
    for key, seen in list(state.items()):
        if key in ("services", "overview", "accounts"):
            continue
        try:
            parts = json.loads(key)
        except ValueError:
            parts = None
        if not (
            isinstance(parts, list)
            and len(parts) == 3
            and all(isinstance(part, str) for part in parts)
            and parts[0] == session_id
            and parts[2] in ("five_hour", "seven_day")
        ):
            if seen["resets_at"] < now - 7 * 86400:
                del state[key]
                quota_changed = True
            continue
        _, tool, window = parts
        if account_pending and tool == "Claude Code":
            continue
        latest = current.get((tool, window))
        if seen["resets_at"] > now and not (
            latest is not None and latest[1] - seen["resets_at"] >= 600
        ):
            continue
        label = "5-hour" if window == "five_hour" else "weekly"
        if tool.startswith("Antigravity ("):
            tool = f'Antigravity CLI (agy) model group "{tool[len("Antigravity (") : -1]}"'
        usage = f" (now {latest[0]:g}% used)" if latest is not None else ""
        reset_lines.append(
            f"{tool} {label} quota has reset{usage}. "
            f"The earlier {tool} {label} quota notice no longer applies."
        )
        del state[key]
        quota_changed = True
    for tool, window, used, reset, suffix in windows:
        thresholds = (80, 90, 95) if window == "five_hour" else (95,)
        level = max((threshold for threshold in thresholds if used >= threshold), default=0)
        if level:
            limited.add(tool)
        # Antigravity's reset is derived from a seconds countdown and drifts by up to about a
        # minute between snapshots, so a reset within 10 minutes is the same window.
        key = json.dumps([session_id, tool, window])
        seen = state.get(key, {})
        announced = seen.get("level", 0) if abs(seen.get("resets_at", 0) - reset) < 600 else 0
        if not level or level <= announced:
            continue
        label = "5-hour" if window == "five_hour" else "weekly"
        usage = _usage(used, reset, now)
        if tool.startswith("Antigravity ("):
            group = tool[len("Antigravity (") : -1]
            messages.append(
                f'Antigravity CLI (agy) model group "{group}": {label} quota: {usage}. '
                "Only limits work sent to agy with those models."
            )
        else:
            scope = "work run in Claude Code" if tool == "Claude Code" else f"work sent to {tool}"
            messages.append(f"{tool} {label} quota: {usage}. Only limits {scope}.")
        messages[-1] += suffix
        state[key] = {"resets_at": reset, "level": level}
    service_messages, services_changed = _service_reminders(session_id, now, state)
    service_block = (
        "[usage service status] " + "\n".join(service_messages) if service_messages else ""
    )
    if messages or quota_changed or services_changed or overview_changed or accounts_changed:
        _save(state)
    if not messages:
        quota_block = "[usage quota] " + "\n".join(reset_lines) if reset_lines else ""
        return "\n\n".join(block for block in (overview_block, quota_block, service_block) if block)
    # A spent agy model group reads as "Antigravity is used up" unless the groups that
    # still have quota are named next to it.
    open_groups: dict[str, float] = {}
    for tool, _window, used, _reset, _suffix in windows:
        if tool.startswith("Antigravity (") and tool not in limited:
            group = tool[len("Antigravity (") : -1]
            open_groups[group] = max(used, open_groups.get(group, 0.0))
    if open_groups and any(tool.startswith("Antigravity (") for tool in limited):
        usable = "; ".join(f'"{group}" {used:g}% used' for group, used in open_groups.items())
        messages.append(
            f"Other agy model groups still have quota: {usable}. Work sent to agy with "
            "those models is unaffected, so Antigravity as a whole is not used up."
        )
    own = {
        window: _usage(used, reset, now)
        for tool, window, used, reset, _suffix in windows
        if tool == "Claude Code"
    }
    own_status = (
        f"5-hour {own.get('five_hour', 'unknown')}; weekly {own.get('seven_day', 'unknown')}."
        if own
        else "unknown."
    )
    quota_block = (
        "[usage quota] " + "\n".join(reset_lines + messages) + "\n"
        "Quotas for other tools or model groups do not limit this Claude Code session. "
        "Before starting a large task (many files, long runs, subagents) that will use one "
        "of these quotas, tell the user the remaining quota and reset time, and ask whether "
        "to do a smaller part now or wait for the reset. Otherwise, just proceed and don't "
        "mention quota.\n"
        f"Current local time: {_local(now):%a %H:%M}.\n"
        f"Claude Code's own quota: {own_status} This Claude Code session runs on this quota."
    )
    return "\n\n".join(block for block in (overview_block, quota_block, service_block) if block)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return
        output = reminder(session_id, datetime.now(timezone.utc).timestamp())
        if output:
            print(output)
    except Exception:
        # Hooks must never block a user's prompt, including failed state writes.
        return


if __name__ == "__main__":
    main()
