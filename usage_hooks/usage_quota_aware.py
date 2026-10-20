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

__version__ = "1.3"
CLAUDE_STATUS = Path.home() / ".claude/usage-status.json"
QUOTA_SNAPSHOT = Path.home() / ".usage/quota_snapshot.json"
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


def _windows(now: float) -> list[tuple[str, str, float, float]]:
    windows: list[tuple[str, str, float, float]] = []

    def add(tool: str, data: Any, *, claude: bool = False, generated: float = 0) -> None:
        if not isinstance(data, dict):
            return
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
                windows.append((tool, name, used, reset))

    add("Claude Code", _read(CLAUDE_STATUS).get("rate_limits"), claude=True)
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
        add("Codex", codex)
    muse = agents.get("muse")
    if isinstance(muse, dict) and muse.get("available"):
        add("Muse", muse)
    agy = agents.get("antigravity")
    if isinstance(agy, dict) and agy.get("available") and isinstance(agy.get("groups"), list):
        for group in agy["groups"]:
            if isinstance(group, dict) and isinstance(group.get("name"), str):
                add("Antigravity (" + group["name"] + ")", group, generated=generated)
    return windows


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


def _usage(used: float, reset: float, now: float) -> str:
    minutes = max(1, math.ceil((reset - now) / 60))
    hours, minutes = divmod(minutes, 60)
    duration = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    return f"{used:g}% used, resets in {duration}"


def reminder(session_id: str, now: float) -> str:
    state = {
        key: value
        for key, value in _read(STATE_PATH).items()
        if isinstance(value, dict)
        and (_number(value.get("resets_at")) or 0) > now
        and _number(value.get("level")) is not None
    }
    messages = []
    limited = set()
    windows = _windows(now)
    for tool, window, used, reset in windows:
        thresholds = (80, 90, 95) if window == "five_hour" else (95,)
        level = max((threshold for threshold in thresholds if used >= threshold), default=0)
        if level:
            limited.add(tool)
        # Antigravity's reset is derived from whole-second fields and can drift by a second
        # between snapshots; key on the minute so the same window is not announced twice.
        key = json.dumps([session_id, tool, window, round(reset / 60)])
        if not level or level <= state.get(key, {}).get("level", 0):
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
        state[key] = {"resets_at": reset, "level": level}
    if not messages:
        return ""
    _save(state)
    # A spent agy model group reads as "Antigravity is used up" unless the groups that
    # still have quota are named next to it.
    open_groups: dict[str, float] = {}
    for tool, _window, used, _reset in windows:
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
        for tool, window, used, reset in windows
        if tool == "Claude Code"
    }
    own_status = (
        f"5-hour {own.get('five_hour', 'unknown')}; weekly {own.get('seven_day', 'unknown')}."
        if own
        else "unknown."
    )
    return (
        "[usage quota] " + "\n".join(messages) + "\n"
        "Quotas for other tools or model groups do not limit this Claude Code session. "
        "Before starting a large task (many files, long runs, subagents) that will use one "
        "of these quotas, tell the user the remaining quota and reset time, and ask whether "
        "to do a smaller part now or wait for the reset. Otherwise, just proceed and don't "
        "mention quota.\n"
        f"Claude Code's own quota: {own_status} This Claude Code session runs on this quota."
    )


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
