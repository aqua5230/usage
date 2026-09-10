# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Read per-request Grok CLI usage from local Grok CLI logs.

The Grok CLI appends events to ``~/.grok/logs/unified.jsonl``. This module only
reads that file, per-session ``updates.jsonl`` files, and ``~/.grok/config.toml``;
it never starts the CLI or contacts a network API.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tomllib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from loaders.history_loader import UsageEntry
from loaders.jsonl_limits import read_bounded_jsonl_line
from project_resolver import resolve_project_name
from usage_common.time_utils import parse_optional_iso8601_utc

logger = logging.getLogger(__name__)

GROK_HOME = Path(os.path.expanduser("~/.grok"))
GROK_LOG_PATH = GROK_HOME / "logs" / "unified.jsonl"
GROK_CONFIG_PATH = GROK_HOME / "config.toml"
GROK_SESSIONS_DIR = GROK_HOME / "sessions"

_MSG_INFERENCE = "shell.turn.inference_done"
_MSG_MODEL = "model changed"
_MSG_CREATED = "session created"
_EventKind = Literal["inference", "model", "created"]
_KIND_INFERENCE: _EventKind = "inference"
_KIND_MODEL: _EventKind = "model"
_KIND_CREATED: _EventKind = "created"

# Wider than grok_quota_probe's 4 MiB / 10k-line tail: this loader collects a
# window of requests, not a single billing snapshot. The log is append-only and
# currently has no rotation, so the cap is mandatory.
_MAX_READ_BYTES = 8 * 1024 * 1024
_MAX_READ_LINES = 50_000
_UNKNOWN_MODEL = "unknown"
_COST_USD_PER_TICK = 1e-10
_UPDATE_METHODS = frozenset({"session/update", "_x.ai/session/update"})


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    """Return per-request Grok CLI usage, oldest timestamp first."""
    if not GROK_LOG_PATH.is_file():
        return []

    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None
    try:
        events = list(_parse_events())
    except OSError:
        return []

    events.sort(key=lambda event: (event[0], event[1]))
    last_model: dict[str, tuple[datetime, str]] = {}
    last_cwd: dict[str, tuple[datetime, str]] = {}
    default_model: str | None = None
    entries: list[UsageEntry] = []

    for timestamp, _order, kind, sid, payload in events:
        if kind == _KIND_MODEL:
            last_model[sid] = (timestamp, payload["model"])
            continue
        if kind == _KIND_CREATED:
            last_cwd[sid] = (timestamp, payload["cwd"])
            continue

        if cutoff is not None and timestamp < cutoff:
            continue

        previous_model = last_model.get(sid)
        if previous_model is not None and previous_model[0] < timestamp:
            model = _normalize_model(previous_model[1])
        else:
            if default_model is None:
                default_model = _default_model()
            model = _normalize_model(default_model)

        previous_cwd = last_cwd.get(sid)
        cwd = (
            previous_cwd[1]
            if previous_cwd is not None and previous_cwd[0] < timestamp
            else ""
        )
        entry_id = f"{sid}:{payload['loop_index']}"
        entries.append(
            UsageEntry(
                timestamp=timestamp,
                session_id=sid,
                message_id=entry_id,
                request_id=entry_id,
                model=model,
                input_tokens=payload["input_tokens"],
                output_tokens=payload["output_tokens"],
                cache_creation_tokens=0,
                cache_read_tokens=payload["cache_read_tokens"],
                cost_usd=None,
                project=resolve_project_name(cwd) if cwd else "",
            )
        )

    _apply_session_costs(entries)
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _parse_events() -> Iterator[tuple[datetime, int, _EventKind, str, dict[str, Any]]]:
    for order, line in enumerate(_iter_recent_lines(GROK_LOG_PATH)):
        parsed = _event_from_line(line, order)
        if parsed is not None:
            yield parsed


def _iter_recent_lines(path: Path) -> Iterator[bytes]:
    """Yield recent JSONL lines oldest-first without buffering the entire file."""
    with path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        size = log_file.tell()
        start = max(0, size - _MAX_READ_BYTES)
        log_file.seek(start)
        if start > 0:
            read_bounded_jsonl_line(log_file)

        scanned_lines = 0
        while scanned_lines < _MAX_READ_LINES:
            raw_bytes, too_long = read_bounded_jsonl_line(log_file)
            if too_long:
                scanned_lines += 1
                logger.warning("skipping oversized JSONL line in Grok log %s", path)
                continue
            if not raw_bytes:
                break
            scanned_lines += 1
            stripped = raw_bytes.strip()
            if stripped:
                yield stripped


def _event_from_line(
    line: bytes, order: int
) -> tuple[datetime, int, _EventKind, str, dict[str, Any]] | None:
    try:
        payload: object = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None

    msg = payload.get("msg")
    sid = payload.get("sid")
    timestamp = parse_optional_iso8601_utc(payload.get("ts"))
    context = payload.get("ctx")
    if (
        not isinstance(msg, str)
        or not isinstance(sid, str)
        or not sid
        or timestamp is None
        or not isinstance(context, dict)
    ):
        return None

    if msg == _MSG_MODEL:
        model = context.get("model")
        if not isinstance(model, str) or not model:
            return None
        return timestamp, order, _KIND_MODEL, sid, {"model": model}

    if msg == _MSG_CREATED:
        cwd = context.get("cwd")
        if not isinstance(cwd, str):
            return None
        return timestamp, order, _KIND_CREATED, sid, {"cwd": cwd}

    if msg != _MSG_INFERENCE:
        return None
    if not all(
        key in context
        for key in ("prompt_tokens", "cached_prompt_tokens", "completion_tokens")
    ):
        return None
    loop_index = context.get("loop_index")
    if isinstance(loop_index, bool) or not isinstance(loop_index, int):
        return None
    prompt_tokens = _as_int(context.get("prompt_tokens"))
    cached_prompt_tokens = _as_int(context.get("cached_prompt_tokens"))
    return (
        timestamp,
        order,
        _KIND_INFERENCE,
        sid,
        {
            "loop_index": loop_index,
            "input_tokens": max(0, prompt_tokens - cached_prompt_tokens),
            "output_tokens": _as_int(context.get("completion_tokens")),
            "cache_read_tokens": cached_prompt_tokens,
        },
    )


def _default_model() -> str:
    try:
        with GROK_CONFIG_PATH.open("rb") as file:
            parsed: object = tomllib.load(file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return _UNKNOWN_MODEL
    if not isinstance(parsed, dict):
        return _UNKNOWN_MODEL
    models = parsed.get("models")
    if not isinstance(models, dict):
        return _UNKNOWN_MODEL
    default = models.get("default")
    if isinstance(default, str) and default:
        return default
    return _UNKNOWN_MODEL


def _normalize_model(model: str) -> str:
    """Align Grok's internal build labels with its public model names."""
    return model.removesuffix("-build")


def _apply_session_costs(entries: list[UsageEntry]) -> None:
    """Attach Grok-recorded session costs to their unified-log entries."""
    entries_by_session: dict[str, list[UsageEntry]] = {}
    earliest_entry: dict[str, datetime] = {}
    for entry in entries:
        entries_by_session.setdefault(entry.session_id, []).append(entry)
        earliest = earliest_entry.get(entry.session_id)
        if earliest is None or entry.timestamp < earliest:
            earliest_entry[entry.session_id] = entry.timestamp

    ticks_by_session: dict[str, int] = {}
    seen_cost_by_session: set[str] = set()
    for path in _iter_update_paths(set(entries_by_session)):
        sid = path.parent.name
        earliest = earliest_entry[sid]
        try:
            lines = _iter_recent_lines(path)
            for line in lines:
                update = _cost_update_from_line(line)
                if update is None:
                    continue
                timestamp, ticks = update
                # unified.jsonl is a shorter rolling window. Do not charge an
                # entry for earlier turns that are no longer present there.
                if timestamp < earliest:
                    continue
                seen_cost_by_session.add(sid)
                ticks_by_session[sid] = ticks_by_session.get(sid, 0) + ticks
        except OSError:
            continue

    for sid, session_entries in entries_by_session.items():
        if sid not in seen_cost_by_session:
            continue
        _allocate_session_cost(session_entries, ticks_by_session.get(sid, 0))


def _iter_update_paths(session_ids: set[str]) -> Iterator[Path]:
    """Yield bounded-session update logs that match unified-log session IDs."""
    try:
        for path in GROK_SESSIONS_DIR.glob("*/*/updates.jsonl"):
            if path.parent.name in session_ids:
                yield path
    except OSError:
        return


def _cost_update_from_line(line: bytes) -> tuple[datetime, int] | None:
    try:
        payload: object = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(payload, dict) or payload.get("method") not in _UPDATE_METHODS:
        return None

    timestamp = _parse_update_timestamp(payload.get("timestamp"))
    params = payload.get("params")
    if timestamp is None or not isinstance(params, dict):
        return None
    update = params.get("update")
    if not isinstance(update, dict):
        return None
    usage = update.get("usage")
    if not isinstance(usage, dict):
        return None
    ticks = _as_nonnegative_int(usage.get("costUsdTicks"))
    if ticks is None:
        return None
    return timestamp, ticks


def _parse_update_timestamp(value: object) -> datetime | None:
    timestamp = parse_optional_iso8601_utc(value)
    if timestamp is not None:
        return timestamp
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value):
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _allocate_session_cost(entries: list[UsageEntry], ticks: int) -> None:
    """Allocate a session's exact recorded cost by unified-log token share."""
    total_tokens = sum(entry.total_tokens for entry in entries)
    if total_tokens > 0:
        # updates.jsonl reports exact costs per turn, while unified.jsonl is the
        # source of display entries and need not align turn-for-turn. Therefore
        # per-entry values are token-weighted estimates; their session total is
        # the exact Grok-recorded amount.
        for entry in entries:
            entry.cost_usd = ticks * (entry.total_tokens / total_tokens) * _COST_USD_PER_TICK
        return

    # A zero-token session has no token ratio. Keep its exact total by assigning
    # it to the first entry instead of silently dropping a recorded charge.
    entries[0].cost_usd = ticks * _COST_USD_PER_TICK
    for entry in entries[1:]:
        entry.cost_usd = 0.0


def _as_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and math.isfinite(value) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number):
        return 0
    return max(0, int(number))
