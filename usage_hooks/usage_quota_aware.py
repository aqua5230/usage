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

__version__ = "1.7"
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


def reminder(session_id: str, now: float) -> str:
    state: dict[str, Any] = {
        key: value
        for key, value in _read(STATE_PATH).items()
        if key == "services"
        or (
            isinstance(value, dict)
            and (_number(value.get("resets_at")) or 0) > now
            and _number(value.get("level")) is not None
        )
    }
    messages = []
    limited = set()
    windows = _windows(session_id, now)
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
    if messages or services_changed:
        _save(state)
    if not messages:
        return service_block
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
        "[usage quota] " + "\n".join(messages) + "\n"
        "Quotas for other tools or model groups do not limit this Claude Code session. "
        "Before starting a large task (many files, long runs, subagents) that will use one "
        "of these quotas, tell the user the remaining quota and reset time, and ask whether "
        "to do a smaller part now or wait for the reset. Otherwise, just proceed and don't "
        "mention quota.\n"
        f"Current local time: {_local(now):%a %H:%M}.\n"
        f"Claude Code's own quota: {own_status} This Claude Code session runs on this quota."
    )
    return quota_block + ("\n\n" + service_block if service_block else "")


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
