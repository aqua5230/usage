#!/usr/bin/env python3
"""Opt-in, stdlib-only Python 3.9 UserPromptSubmit quota reminder."""

from __future__ import annotations

import errno
import json
import math
import os
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

__version__ = "1.15"
CLAUDE_STATUS = Path.home() / ".claude/usage-status.json"
QUOTA_SNAPSHOT = Path.home() / ".usage/quota_snapshot.json"
SERVICE_SNAPSHOT = Path.home() / ".usage/service_status_snapshot.json"
MODEL_REGISTRY = Path.home() / ".usage/model_registry.json"
STATE_PATH = Path.home() / ".usage/quota_aware_state.json"
_RESERVED_STATE_KEYS = ("services", "overview", "accounts", "models")


_fcntl: Any = None
_msvcrt: Any = None
if sys.platform == "win32":
    try:
        import msvcrt
    except ImportError:
        pass
    else:
        _msvcrt = msvcrt
else:
    try:
        import fcntl
    except ImportError:
        pass
    else:
        _fcntl = fcntl

_LOCK_TIMEOUT_S = 0.5
_LOCK_POLL_INTERVAL_S = 0.001
_LOCK_CONTENDED_ERRNOS = frozenset(
    (errno.EACCES, getattr(errno, "EDEADLOCK", errno.EDEADLK), errno.EDEADLK)
)


def _acquire_msvcrt_lock(lock_fd: int) -> bool:
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            if os.fstat(lock_fd).st_size == 0:
                os.write(lock_fd, b"\0")
            os.lseek(lock_fd, 0, os.SEEK_SET)
            _msvcrt.locking(lock_fd, _msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno not in _LOCK_CONTENDED_ERRNOS or time.monotonic() >= deadline:
                return False
            time.sleep(_LOCK_POLL_INTERVAL_S)


@contextmanager
def _exclusive_lock() -> Any:
    """Bound the wait; unavailable locks must not prevent a prompt."""
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(STATE_PATH.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        yield
        return
    locked = False
    try:
        if _fcntl is not None:
            deadline = time.monotonic() + _LOCK_TIMEOUT_S
            while True:
                try:
                    _fcntl.flock(lock_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError as exc:
                    if (
                        exc.errno not in (errno.EACCES, errno.EAGAIN)
                        or time.monotonic() >= deadline
                    ):
                        break
                    time.sleep(_LOCK_POLL_INTERVAL_S)
        elif _msvcrt is not None:
            locked = _acquire_msvcrt_lock(lock_fd)
        yield
    finally:
        if locked:
            with suppress(OSError):
                if _fcntl is not None:
                    _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
                elif _msvcrt is not None:
                    os.lseek(lock_fd, 0, os.SEEK_SET)
                    _msvcrt.locking(lock_fd, _msvcrt.LK_UNLCK, 1)
        with suppress(OSError):
            os.close(lock_fd)


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


def _recorded_account_uuid(records: Any, session_id: Any) -> Optional[str]:
    if not isinstance(records, dict) or not isinstance(session_id, str) or not session_id:
        return None
    record = records.get(session_id)
    uuid = record.get("uuid") if isinstance(record, dict) else None
    return uuid if isinstance(uuid, str) and uuid else None


def _can_use_status(session_id: str, status: dict[str, Any], state: dict[str, Any]) -> bool:
    if "_rate_limits_session_id" not in status:
        return True
    owner = status.get("_rate_limits_session_id")
    if not isinstance(owner, str) or not owner:
        return False
    if owner == session_id:
        return True
    accounts = state.get("accounts")
    owner_uuid = _recorded_account_uuid(accounts, owner)
    my_uuid = _recorded_account_uuid(accounts, session_id)
    current_uuid = _account_uuid()
    return (
        owner_uuid is not None
        and my_uuid is not None
        and current_uuid is not None
        and owner_uuid == current_uuid == my_uuid
    )


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
        status = _read(CLAUDE_STATUS) if seen is not None else {}
        owner_uuid = _recorded_account_uuid(records, status.get("_rate_limits_session_id"))
        records[session_id] = {"uuid": uuid, "at": now}
        if seen is not None:
            message = (
                "Claude Code account changed since earlier in this conversation (/login). "
                "Earlier Claude Code quota notices no longer apply; "
                "the new account's quota shows up after your next reply."
            )
            for window in ("five_hour", "seven_day"):
                state.pop(json.dumps([session_id, "Claude Code", window]), None)
            if owner_uuid != uuid:
                limits = status.get("rate_limits")
                records[session_id]["old_limits"] = {
                    name: limits[name]
                    for name in ("five_hour", "seven_day")
                    if isinstance(limits, dict) and isinstance(limits.get(name), dict)
                }
        seen = records[session_id]
        changed = True
    pending = False
    if seen is not None and isinstance(seen.get("old_limits"), dict):
        limits = _read(CLAUDE_STATUS).get("rate_limits")
        old_limits = seen["old_limits"]
        for name, window in list(old_limits.items()):
            reset = _number(window.get("resets_at")) if isinstance(window, dict) else None
            if (
                not isinstance(limits, dict)
                or limits.get(name) != window
                or (reset is not None and reset <= now)
            ):
                del old_limits[name]
                changed = True
        pending = bool(old_limits)
        if not pending:
            del seen["old_limits"]
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


def _windows(
    session_id: str, now: float, state: dict[str, Any]
) -> list[tuple[str, str, float, float, str]]:
    windows: list[tuple[str, str, float, float, str]] = []

    def add(
        tool: str, data: Any, *, claude: bool = False, generated: float = 0, updated_at: Any = None
    ) -> None:
        if not isinstance(data, dict):
            return
        for name in ("five_hour", "seven_day"):
            window = data.get(name)
            if not isinstance(window, dict):
                continue
            suffix = ""
            age = None
            if "age_seconds" in window and "updated_at" not in window:
                age = _number(window["age_seconds"])
                if age is not None and generated:
                    age += max(0, now - generated)
            else:
                with suppress(ValueError, OverflowError):
                    age = now - _generated_at(window.get("updated_at", updated_at))
            if age is not None and age >= 3600:
                suffix = f" (last updated {int(age // 3600)}h ago; it may have reset since)"
            used = _number(window.get("used_percentage" if claude else "used_percent"))
            reset = _number(window.get("resets_at"))
            if reset is None and generated:
                remaining = _number(window.get("resets_in_seconds"))
                if remaining is not None:
                    reset = generated + remaining
            if used is not None and reset is not None and reset > now:
                windows.append((tool, name, used, reset, suffix))

    status = _read(CLAUDE_STATUS)
    # A session that has not replied yet carries another session's windows, which are only safe
    # to reuse when both sessions belong to the current account. Older hooks omit the field.
    if _can_use_status(session_id, status, state):
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


def _clean_model_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value if ch.isprintable() and ch != '"').strip()[:60]


def _new_models(now: float) -> list[tuple[str, float, str]]:
    payload = _read(MODEL_REGISTRY)
    if not payload:
        return []
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        return []
    raw_items = payload.get("items")
    if not isinstance(raw_items, dict):
        return []
    cutoff = now - 7 * 86400
    found: list[tuple[str, float, str]] = []
    for key, entry in raw_items.items():
        if not isinstance(key, str) or not key or not isinstance(entry, dict):
            continue
        if entry.get("baseline") is not False:
            continue
        try:
            first_seen = _generated_at(entry.get("first_seen"))
        except (ValueError, OverflowError, OSError):
            continue
        if first_seen < cutoff:
            continue
        source = entry.get("source")
        name = _clean_model_text(entry.get("name"))
        if not name:
            continue
        if source == "codex_catalog":
            text = f'Codex model "{name}"'
        elif source == "agy_group":
            raw_models = entry.get("models")
            models = (
                [cleaned for m in raw_models if (cleaned := _clean_model_text(m))]
                if isinstance(raw_models, list)
                else []
            )
            models_part = f" (models: {', '.join(models)})" if models else ""
            text = f'Antigravity quota group "{name}"{models_part}'
        elif source == "usage_log":
            text = f'model "{name}" first seen in local usage logs'
        else:
            continue
        if entry.get("priced") is False:
            text += " (usage's price table does not know it yet)"
        found.append((key, first_seen, text))
    found.sort(key=lambda item: item[1], reverse=True)
    return found


def _model_reminders(session_id: str, now: float, state: dict[str, Any]) -> tuple[str, bool]:
    previous = state.get("models", {})
    records: dict[str, dict[str, Any]] = {}
    if isinstance(previous, dict):
        for key, value in previous.items():
            if (
                isinstance(key, str)
                and key
                and isinstance(value, dict)
                and isinstance(value.get("keys"), list)
                and all(isinstance(item, str) for item in value["keys"])
                and (seen_at := _number(value.get("at"))) is not None
                and seen_at >= now - 7 * 86400
            ):
                records[key] = {"keys": list(value["keys"]), "at": seen_at}
    changed = records != previous
    entry = records.get(session_id)
    seen_keys = list(entry["keys"]) if entry is not None else []
    seen_set = set(seen_keys)
    new_items = [item for item in _new_models(now) if item[0] not in seen_set]
    block = ""
    if new_items:
        shown = [text for _, _, text in new_items[:5]]
        if len(new_items) > 5:
            shown.append(f"and {len(new_items) - 5} more")
        block = (
            "[usage models] New in the last 7 days: "
            + "; ".join(shown)
            + ". Background only: bring it up when it affects the current task, "
            "such as choosing a model or agent, or when the user asks."
        )
        records[session_id] = {
            "keys": seen_keys + [key for key, _, _ in new_items],
            "at": now,
        }
        changed = True
    if records or "models" in state:
        state["models"] = records
    return block, changed


def _save(state: dict[str, Any]) -> None:
    temporary: Optional[str] = None
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=STATE_PATH.parent, suffix=".tmp", delete=False
        ) as handle:
            temporary = handle.name
            json.dump(state, handle)
        os.replace(temporary, STATE_PATH)
    finally:
        if temporary is not None and os.path.exists(temporary):
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


def _claude_pending(session_id: str, state: dict[str, Any]) -> bool:
    # Claude Code's quota is tied to this session only after its own reply or another session's
    # reply on the same account (see _windows), so an overview sent before that would leave out
    # the quota this session runs on.
    status = _read(CLAUDE_STATUS)
    if _can_use_status(session_id, status, state):
        return False
    owner = status.get("_rate_limits_session_id")
    return isinstance(owner, str) or (owner is None and _account_uuid() is not None)


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
    if session_id not in records and not _claude_pending(session_id, state):
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
    with _exclusive_lock():
        return _reminder(session_id, now)


def _same_window(seen: dict[str, float], observed_reset: float, observed_used: float) -> bool:
    if not seen:
        return False
    delta = observed_reset - seen["anchor_resets_at"]
    # A later estimate alone cannot reset a notice while usage remains at its level.
    return -600 < delta < 600 or (delta >= 600 and observed_used >= seen["level"])


def _reminder(session_id: str, now: float) -> str:
    state: dict[str, Any] = {
        key: value
        for key, value in _read(STATE_PATH).items()
        if key in _RESERVED_STATE_KEYS
        or (
            isinstance(value, dict)
            and _number(value.get("resets_at")) is not None
            and _number(value.get("level")) is not None
        )
    }
    quota_changed = False
    for key, seen in state.items():
        if key not in _RESERVED_STATE_KEYS and "anchor_resets_at" not in seen:
            seen["anchor_resets_at"] = seen["resets_at"]
            quota_changed = True
    messages = []
    limited = set()
    announced_agy = False
    account_line, accounts_changed, account_pending = _account_reminder(session_id, now, state)
    windows = _windows(session_id, now, state)
    old_limits = state["accounts"][session_id]["old_limits"] if account_pending else {}
    windows = [
        entry for entry in windows if entry[0] != "Claude Code" or entry[1] not in old_limits
    ]
    overview_block, overview_changed = _overview_reminder(session_id, now, state, windows)
    current = {(tool, window): (used, reset) for tool, window, used, reset, _suffix in windows}
    reset_lines = [account_line] if account_line else []
    for key, seen in list(state.items()):
        if key in _RESERVED_STATE_KEYS:
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
        if tool == "Claude Code" and window in old_limits:
            continue
        latest = current.get((tool, window))
        if latest is not None and _same_window(seen, latest[1], latest[0]):
            if seen["resets_at"] != latest[1]:
                seen["resets_at"] = latest[1]
                quota_changed = True
            continue
        if seen["resets_at"] > now and not (
            latest is not None and latest[1] - seen["anchor_resets_at"] >= 600
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
        key = json.dumps([session_id, tool, window])
        seen = state.get(key, {})
        same_window = _same_window(seen, reset, used)
        announced = seen.get("level", 0) if same_window else 0
        if same_window and seen["resets_at"] != reset:
            seen["resets_at"] = reset
            quota_changed = True
        if not level or level <= announced:
            continue
        label = "5-hour" if window == "five_hour" else "weekly"
        usage = _usage(used, reset, now)
        if tool.startswith("Antigravity ("):
            group = tool[len("Antigravity (") : -1]
            announced_agy = True
            messages.append(
                f'Antigravity CLI (agy) model group "{group}": {label} quota: {usage}. '
                "Only limits work sent to agy with those models."
            )
        else:
            scope = "work run in Claude Code" if tool == "Claude Code" else f"work sent to {tool}"
            messages.append(f"{tool} {label} quota: {usage}. Only limits {scope}.")
        messages[-1] += suffix
        state[key] = {
            "resets_at": reset,
            "anchor_resets_at": seen["anchor_resets_at"] if same_window else reset,
            "level": level,
        }
    service_messages, services_changed = _service_reminders(session_id, now, state)
    service_block = (
        "[usage service status] " + "\n".join(service_messages) if service_messages else ""
    )
    models_block, models_changed = _model_reminders(session_id, now, state)
    if (
        messages
        or quota_changed
        or services_changed
        or overview_changed
        or accounts_changed
        or models_changed
    ):
        _save(state)
    if not messages:
        quota_block = "[usage quota] " + "\n".join(reset_lines) if reset_lines else ""
        return "\n\n".join(
            block for block in (overview_block, quota_block, service_block, models_block) if block
        )
    # A spent agy model group reads as "Antigravity is used up" unless the groups that
    # still have quota are named next to it.
    open_groups: dict[str, float] = {}
    for tool, _window, used, _reset, _suffix in windows:
        if tool.startswith("Antigravity (") and tool not in limited:
            group = tool[len("Antigravity (") : -1]
            open_groups[group] = max(used, open_groups.get(group, 0.0))
    if open_groups and announced_agy:
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
    return "\n\n".join(
        block for block in (overview_block, quota_block, service_block, models_block) if block
    )


def _read_stdin_utf8() -> str:
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    return cast(bytes, buffer.read()).decode("utf-8", "replace")


def main() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            with suppress(AttributeError, OSError, ValueError):
                cast(Any, sys.stdout).reconfigure(encoding="utf-8", errors="replace")
        payload = json.loads(_read_stdin_utf8())
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
