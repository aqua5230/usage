# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import re
import sqlite3
import tempfile
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from history_loader import UsageEntry
from project_resolver import resolve_project_name

logger = logging.getLogger(__name__)

_JSONL_CACHE_MAXSIZE = 512
_RECENT_JSONL_SCAN_LIMIT = 30
_ReplayCacheKey = tuple[str, float, int, int] | None
_jsonl_cache: OrderedDict[
    Path,
    tuple[float, int, _ReplayCacheKey, list[UsageEntry]],
] = OrderedDict()
_ReplayLookupKey = tuple[float, int, tuple[tuple[str, float, int], ...]]
_fork_replay_cache: OrderedDict[
    Path,
    tuple[_ReplayLookupKey, int | None, _ReplayCacheKey],
] = OrderedDict()
_file_info_cache: OrderedDict[
    Path,
    tuple[float, int, _SessionFileInfo],
] = OrderedDict()

SESSIONS_DIR = Path(os.path.expanduser("~/.codex/sessions"))
STATE_DB = Path(os.path.expanduser("~/.codex/state_5.sqlite"))
LOGS_DB = Path(os.path.expanduser("~/.codex/logs_2.sqlite"))

# Disk cache for JSONL parsing results. Schema version must be bumped when the
# serialization format or parsing logic changes incompatibly.
_CODEX_JSONL_CACHE_SCHEMA = 1
JSONL_CACHE_PATH = Path(os.path.expanduser("~/.usage/codex_jsonl_cache.json"))

# Module-level flag to ensure seed loading happens exactly once.
_disk_cache_seeded = False


@dataclass(slots=True)
class CodexRateLimits:
    five_hour_pct: float | None
    five_hour_resets_at: float | None
    seven_day_pct: float | None
    seven_day_resets_at: float | None
    # window length (minutes) Codex reports for each slot; drives the row label
    # (≈300→Session, ≈10080→Weekly, ≈43200→Monthly). None when the source has no
    # window_minutes (header/error fallbacks) or the slot is absent (free plan).
    five_hour_window_minutes: float | None = None
    seven_day_window_minutes: float | None = None
    model: str | None = "unknown"
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class _ThreadMetadata:
    model: str = "unknown"
    cwd: str = ""


@dataclass(frozen=True, slots=True)
class _SessionFileInfo:
    session_id: str = ""
    forked_from_id: str = ""


def _serialize_usage_entry(entry: UsageEntry) -> dict[str, Any]:
    """Serialize UsageEntry to dict for JSON storage."""
    return {
        "timestamp": entry.timestamp.isoformat(),
        "session_id": entry.session_id,
        "message_id": entry.message_id,
        "request_id": entry.request_id,
        "model": entry.model,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "cache_creation_tokens": entry.cache_creation_tokens,
        "cache_read_tokens": entry.cache_read_tokens,
        "cost_usd": entry.cost_usd,
        "project": entry.project,
    }


def _deserialize_usage_entry(data: dict[str, Any]) -> UsageEntry:
    """Deserialize dict from JSON back to UsageEntry."""
    return UsageEntry(
        timestamp=datetime.fromisoformat(data["timestamp"]),
        session_id=data["session_id"],
        message_id=data["message_id"],
        request_id=data["request_id"],
        model=data["model"],
        input_tokens=data["input_tokens"],
        output_tokens=data["output_tokens"],
        cache_creation_tokens=data["cache_creation_tokens"],
        cache_read_tokens=data["cache_read_tokens"],
        cost_usd=data["cost_usd"],
        project=data["project"],
    )


def _seed_caches_from_disk() -> None:
    """Seed in-memory caches from disk. Silently fails on any error."""
    global _disk_cache_seeded, _jsonl_cache, _file_info_cache

    if _disk_cache_seeded:
        return
    _disk_cache_seeded = True

    try:
        with JSONL_CACHE_PATH.open(encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return

    if not isinstance(cache, dict):
        return
    if cache.get("schema_version") != _CODEX_JSONL_CACHE_SCHEMA:
        return

    files = cache.get("files")
    if not isinstance(files, dict):
        return

    for path_str, file_data in files.items():
        if not isinstance(file_data, dict):
            continue
        try:
            path = Path(path_str)
            mtime = file_data["mtime"]
            size = file_data["size"]
            session_id = file_data["session_id"]
            forked_from_id = file_data["forked_from_id"]
            entries_data = file_data["entries"]

            # Seed file_info_cache
            if len(_file_info_cache) >= _JSONL_CACHE_MAXSIZE:
                _file_info_cache.popitem(last=False)
            _file_info_cache[path] = (
                mtime,
                size,
                _SessionFileInfo(session_id=session_id, forked_from_id=forked_from_id),
            )

            # Seed jsonl_cache only for non-fork files (entries not null)
            if entries_data is not None:
                if not isinstance(entries_data, list):
                    continue
                entries = [_deserialize_usage_entry(e) for e in entries_data]
                if len(_jsonl_cache) >= _JSONL_CACHE_MAXSIZE:
                    _jsonl_cache.popitem(last=False)
                # Non-fork files have replay_cache_key = None
                _jsonl_cache[path] = (mtime, size, None, entries)
        except (KeyError, TypeError, ValueError):
            # Skip malformed entry; continue with others
            continue


def _flush_caches_to_disk() -> None:
    """Atomically write current in-memory caches to disk."""
    tmp_path: str | None = None
    try:
        JSONL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=JSONL_CACHE_PATH.parent, suffix=".tmp")

        files: dict[str, Any] = {}
        # Write jsonl_cache entries
        for path, (mtime, size, replay_cache_key, entries) in _jsonl_cache.items():
            path_str = str(path)
            # For fork files (replay_cache_key is not None), entries = null
            if replay_cache_key is not None:
                entries_data = None
                # Still need session_id/forked_from_id from file_info_cache
                info = _file_info_cache.get(path)
                if info is None:
                    continue
                session_id = info[2].session_id
                forked_from_id = info[2].forked_from_id
            else:
                entries_data = [_serialize_usage_entry(e) for e in entries]
                if not entries:
                    # Empty entries list: get info from file_info_cache
                    info = _file_info_cache.get(path)
                    if info is None:
                        continue
                    session_id = info[2].session_id
                    forked_from_id = info[2].forked_from_id
                else:
                    session_id = entries[0].session_id
                    forked_from_id = ""  # Not stored in UsageEntry

            files[path_str] = {
                "mtime": mtime,
                "size": size,
                "session_id": session_id,
                "forked_from_id": forked_from_id,
                "entries": entries_data,
            }

        payload = {
            "schema_version": _CODEX_JSONL_CACHE_SCHEMA,
            "cached_at": datetime.now(UTC).timestamp(),
            "files": files,
        }

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, JSONL_CACHE_PATH)
        tmp_path = None
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("failed to write codex jsonl cache %s: %s", JSONL_CACHE_PATH, exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None
    metadata = _load_thread_metadata()
    models = {session_id: data.model for session_id, data in metadata.items()}
    entries = _load_jsonl_entries(SESSIONS_DIR, models, cutoff)

    latest_jsonl_ts_by_session = {
        entry.session_id: entry.timestamp
        for entry in entries
    }
    entries.extend(_load_sqlite_log_entries(metadata, cutoff, latest_jsonl_ts_by_session))
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _load_jsonl_entries(
    sessions_dir: Path,
    models: dict[str, str],
    cutoff: datetime | None,
) -> list[UsageEntry]:
    # Seed from disk on first call
    _seed_caches_from_disk()

    if not sessions_dir.is_dir():
        return []

    # Snapshot each cached file's (mtime, size) to detect new or re-parsed files.
    # A re-parse overwrites an existing key in place, so cache size alone would
    # miss an updated (still-growing) session file — exactly the active files we
    # most want to persist. dict equality ignores LRU move_to_end reordering.
    jsonl_snapshot = {str(p): (e[0], e[1]) for p, e in _jsonl_cache.items()}
    file_info_snapshot = {str(p): (v[0], v[1]) for p, v in _file_info_cache.items()}

    entries_by_session: dict[str, list[UsageEntry]] = {}
    cutoff_ts = cutoff.timestamp() if cutoff else None
    jsonl_paths = list(sessions_dir.rglob("*.jsonl"))
    file_info = {path: _read_session_file_info(path) for path in jsonl_paths}
    paths_by_session: dict[str, list[Path]] = {}
    for path, info in file_info.items():
        if info.session_id:
            paths_by_session.setdefault(info.session_id, []).append(path)

    for jsonl_path in jsonl_paths:
        if cutoff_ts is not None:
            try:
                if jsonl_path.stat().st_mtime < cutoff_ts:
                    continue
            except OSError as exc:
                logger.warning("failed to stat session log %s: %s", jsonl_path, exc)
                continue
        info = file_info[jsonl_path]
        replay_boundary, replay_cache_key = _fork_replay_boundary(
            jsonl_path,
            info,
            paths_by_session.get(info.forked_from_id, []),
        )
        parsed = _parse_jsonl(
            jsonl_path,
            models,
            cutoff,
            file_info=info,
            replay_boundary=replay_boundary,
            replay_cache_key=replay_cache_key,
        )
        if not parsed:
            continue
        existing = entries_by_session.get(parsed[0].session_id)
        if existing is None or _is_better_session_log(parsed, existing):
            entries_by_session[parsed[0].session_id] = parsed

    # Flush to disk if any file was newly parsed or re-parsed (content changed)
    if (
        {str(p): (e[0], e[1]) for p, e in _jsonl_cache.items()} != jsonl_snapshot
        or {str(p): (v[0], v[1]) for p, v in _file_info_cache.items()} != file_info_snapshot
    ):
        _flush_caches_to_disk()

    return [
        entry
        for session_entries in entries_by_session.values()
        for entry in session_entries
    ]


def _is_better_session_log(candidate: list[UsageEntry], existing: list[UsageEntry]) -> bool:
    candidate_latest = candidate[-1]
    existing_latest = existing[-1]
    if candidate_latest.timestamp != existing_latest.timestamp:
        return candidate_latest.timestamp > existing_latest.timestamp
    return _session_total_tokens(candidate) > _session_total_tokens(existing)


def _session_total_tokens(entries: list[UsageEntry]) -> int:
    return sum(entry.total_tokens for entry in entries)


def _read_session_file_info_uncached(path: Path) -> _SessionFileInfo:
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                data = _load_json_line(line)
                if data is None or data.get("type") != "session_meta":
                    continue
                payload = _as_dict(data.get("payload"))
                return _SessionFileInfo(
                    session_id=_as_str(payload.get("id")),
                    forked_from_id=_as_str(payload.get("forked_from_id")),
                )
    except (OSError, UnicodeDecodeError):
        return _SessionFileInfo()
    return _SessionFileInfo()


def _read_session_file_info(path: Path) -> _SessionFileInfo:
    try:
        st = path.stat()
    except OSError:
        return _SessionFileInfo()

    cached = _file_info_cache.get(path)
    if cached is not None and cached[0] == st.st_mtime and cached[1] == st.st_size:
        _file_info_cache.move_to_end(path)
        return cached[2]

    info = _read_session_file_info_uncached(path)

    if path not in _file_info_cache and len(_file_info_cache) >= _JSONL_CACHE_MAXSIZE:
        _file_info_cache.popitem(last=False)
    _file_info_cache[path] = (st.st_mtime, st.st_size, info)
    return info


def load_rate_limits() -> CodexRateLimits | None:
    sqlite_limits = _load_sqlite_rate_limits()
    jsonl_limits = _load_jsonl_rate_limits()
    if sqlite_limits is None:
        return jsonl_limits
    if jsonl_limits is None:
        return sqlite_limits
    merged = _merge_rate_limits(sqlite_limits, jsonl_limits)
    if merged is not None:
        return merged
    if _rate_limits_timestamp(jsonl_limits) > _rate_limits_timestamp(sqlite_limits):
        return jsonl_limits
    return sqlite_limits


def _load_jsonl_rate_limits() -> CodexRateLimits | None:
    if not SESSIONS_DIR.is_dir():
        return None
    models = _load_thread_models()
    # scan 30 recent sessions because short/interrupted Codex sessions write null rate_limits
    for path in _recent_jsonl_files():
        rate_limits = _extract_rate_limits(path, models)
        if rate_limits is not None:
            return rate_limits
    return None


def _rate_limits_timestamp(rate_limits: CodexRateLimits) -> datetime:
    parsed = _parse_timestamp(rate_limits.updated_at)
    return parsed if parsed is not None else datetime.min.replace(tzinfo=UTC)


def _merge_rate_limits(
    sqlite_limits: CodexRateLimits,
    jsonl_limits: CodexRateLimits,
) -> CodexRateLimits | None:
    sqlite_ts = _rate_limits_timestamp(sqlite_limits)
    jsonl_ts = _rate_limits_timestamp(jsonl_limits)
    five_pct, five_reset, five_window = _pick_rate_limit_window(
        sqlite_limits.five_hour_pct,
        sqlite_limits.five_hour_resets_at,
        sqlite_limits.five_hour_window_minutes,
        sqlite_ts,
        jsonl_limits.five_hour_pct,
        jsonl_limits.five_hour_resets_at,
        jsonl_limits.five_hour_window_minutes,
        jsonl_ts,
    )
    seven_pct, seven_reset, seven_window = _pick_rate_limit_window(
        sqlite_limits.seven_day_pct,
        sqlite_limits.seven_day_resets_at,
        sqlite_limits.seven_day_window_minutes,
        sqlite_ts,
        jsonl_limits.seven_day_pct,
        jsonl_limits.seven_day_resets_at,
        jsonl_limits.seven_day_window_minutes,
        jsonl_ts,
    )
    if five_pct is None and seven_pct is None:
        return None
    newer = jsonl_limits if jsonl_ts > sqlite_ts else sqlite_limits
    return CodexRateLimits(
        five_hour_pct=five_pct,
        five_hour_resets_at=five_reset,
        seven_day_pct=seven_pct,
        seven_day_resets_at=seven_reset,
        five_hour_window_minutes=five_window,
        seven_day_window_minutes=seven_window,
        model=newer.model,
        updated_at=newer.updated_at,
    )


def _pick_rate_limit_window(
    sqlite_pct: float | None,
    sqlite_reset: float | None,
    sqlite_window: float | None,
    sqlite_ts: datetime,
    jsonl_pct: float | None,
    jsonl_reset: float | None,
    jsonl_window: float | None,
    jsonl_ts: datetime,
) -> tuple[float | None, float | None, float | None]:
    if sqlite_pct is None:
        return jsonl_pct, jsonl_reset, jsonl_window
    if jsonl_pct is None:
        return sqlite_pct, sqlite_reset, sqlite_window
    if _active_window_limit_reached(sqlite_pct, sqlite_reset, jsonl_reset):
        return sqlite_pct, sqlite_reset, sqlite_window
    if jsonl_ts > sqlite_ts:
        return jsonl_pct, jsonl_reset, jsonl_window
    return sqlite_pct, sqlite_reset, sqlite_window


def _active_window_limit_reached(
    sqlite_pct: float,
    sqlite_reset: float | None,
    jsonl_reset: float | None,
) -> bool:
    if sqlite_pct < 100:
        return False
    if sqlite_reset is None:
        return True
    if sqlite_reset < datetime.now(UTC).timestamp():
        return False
    # A newer reset window means Codex has already moved past the 100% event.
    return jsonl_reset is None or jsonl_reset <= sqlite_reset + 60


def _load_sqlite_rate_limits() -> CodexRateLimits | None:
    if not LOGS_DB.exists():
        return None
    query = (
        "SELECT ts, feedback_log_body FROM logs "
        "WHERE target = 'codex_api::endpoint::responses_websocket' "
        "AND (feedback_log_body LIKE '%websocket event: {\"type\":\"codex.rate_limits\"%' "
        "OR feedback_log_body LIKE "
        "'%websocket event: {\"type\":\"error\"%usage_limit_reached%') "
        "ORDER BY ts DESC, ts_nanos DESC, id DESC LIMIT 50"
    )
    try:
        with closing(sqlite3.connect(f"file:{LOGS_DB}?mode=ro", uri=True)) as conn:
            rows = conn.execute(query).fetchall()
    except (OSError, sqlite3.Error):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("codex sqlite rate limits load failed", exc_info=True)
        return None

    for ts, body in rows:
        parsed = _parse_sqlite_rate_limits_row(ts, body)
        if parsed is not None:
            return parsed
    return None


def _parse_sqlite_rate_limits_row(ts: Any, body: Any) -> CodexRateLimits | None:
    if not isinstance(body, str):
        return None
    event = _websocket_event_payload(body)
    if not event:
        return None
    if event.get("type") == "codex.rate_limits":
        return _rate_limits_from_websocket_event(event, body, ts)
    if event.get("type") == "error":
        return _rate_limits_from_websocket_error(event, body, ts)
    return None


def _websocket_event_payload(body: str) -> dict[str, Any]:
    marker = "websocket event: "
    index = body.find(marker)
    if index < 0:
        return {}
    try:
        data = json.loads(body[index + len(marker):])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _rate_limits_from_websocket_event(
    event: dict[str, Any],
    body: str,
    ts: Any,
) -> CodexRateLimits | None:
    rate_limits = _as_dict(event.get("rate_limits"))
    primary = _as_dict(rate_limits.get("primary"))
    secondary = _as_dict(rate_limits.get("secondary"))
    return _build_rate_limits(
        primary_pct=_as_optional_float(primary.get("used_percent")),
        primary_reset=_as_optional_float(primary.get("reset_at")),
        secondary_pct=_as_optional_float(secondary.get("used_percent")),
        secondary_reset=_as_optional_float(secondary.get("reset_at")),
        primary_window_minutes=_as_optional_float(primary.get("window_minutes")),
        secondary_window_minutes=_as_optional_float(secondary.get("window_minutes")),
        model=_event_value(body, "model") or "unknown",
        updated_at=_timestamp_from_log_ts(ts),
    )


def _rate_limits_from_websocket_error(
    event: dict[str, Any],
    body: str,
    ts: Any,
) -> CodexRateLimits | None:
    headers = _as_dict(event.get("headers"))
    primary_reset = _as_optional_float(headers.get("X-Codex-Primary-Reset-At"))
    secondary_reset = _as_optional_float(headers.get("X-Codex-Secondary-Reset-At"))
    now_ts = datetime.now(UTC).timestamp()
    if primary_reset is None:
        primary_reset_after = _as_optional_float(headers.get("X-Codex-Primary-Reset-After-Seconds"))
        primary_reset = now_ts + primary_reset_after if primary_reset_after is not None else None
    if secondary_reset is None:
        secondary_reset_after = _as_optional_float(
            headers.get("X-Codex-Secondary-Reset-After-Seconds")
        )
        secondary_reset = (
            now_ts + secondary_reset_after if secondary_reset_after is not None else None
        )
    return _build_rate_limits(
        primary_pct=_as_optional_float(headers.get("X-Codex-Primary-Used-Percent")),
        primary_reset=primary_reset,
        secondary_pct=_as_optional_float(headers.get("X-Codex-Secondary-Used-Percent")),
        secondary_reset=secondary_reset,
        model=_event_value(body, "model") or "unknown",
        updated_at=_timestamp_from_log_ts(ts),
    )


def _build_rate_limits(
    *,
    primary_pct: float | None,
    primary_reset: float | None,
    secondary_pct: float | None,
    secondary_reset: float | None,
    model: str,
    updated_at: datetime | None,
    primary_window_minutes: float | None = None,
    secondary_window_minutes: float | None = None,
) -> CodexRateLimits | None:
    now_ts = datetime.now(UTC).timestamp()
    if primary_reset is not None and primary_reset < now_ts:
        primary_pct = None
        primary_reset = None
    if secondary_reset is not None and secondary_reset < now_ts:
        secondary_pct = None
        secondary_reset = None
    if primary_pct is None and secondary_pct is None:
        return None
    return CodexRateLimits(
        five_hour_pct=primary_pct,
        five_hour_resets_at=primary_reset,
        seven_day_pct=secondary_pct,
        seven_day_resets_at=secondary_reset,
        five_hour_window_minutes=primary_window_minutes,
        seven_day_window_minutes=secondary_window_minutes,
        model=model,
        updated_at=updated_at.isoformat() if updated_at is not None else "",
    )


def _load_thread_models() -> dict[str, str]:
    return {
        thread_id: metadata.model
        for thread_id, metadata in _load_thread_metadata().items()
    }


def _load_thread_metadata() -> dict[str, _ThreadMetadata]:
    if not STATE_DB.exists():
        return {}
    try:
        with closing(sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)) as conn:
            rows = conn.execute(
                "SELECT id, model, cwd FROM threads",
            ).fetchall()
    except (OSError, sqlite3.Error):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("codex thread metadata load failed", exc_info=True)
        return {}
    return {
        thread_id: _ThreadMetadata(
            model=model if isinstance(model, str) and model else "unknown",
            cwd=cwd if isinstance(cwd, str) else "",
        )
        for thread_id, model, cwd in rows
        if isinstance(thread_id, str) and thread_id
    }


def _load_sqlite_log_entries(
    metadata: dict[str, _ThreadMetadata],
    cutoff: datetime | None,
    latest_jsonl_ts_by_session: dict[str, datetime],
) -> list[UsageEntry]:
    if not LOGS_DB.exists():
        return []
    cutoff_ts = cutoff.timestamp() if cutoff else None
    query = (
        "SELECT id, ts, ts_nanos, feedback_log_body FROM logs "
        "WHERE target = 'codex_otel.trace_safe' "
        "AND feedback_log_body LIKE '%event.kind=response.completed%' "
        "AND feedback_log_body LIKE '%input_token_count=%'"
    )
    params: tuple[float, ...] = ()
    if cutoff_ts is not None:
        query += " AND ts >= ?"
        params = (cutoff_ts,)
    query += " ORDER BY ts ASC, ts_nanos ASC, id ASC"
    try:
        with closing(sqlite3.connect(f"file:{LOGS_DB}?mode=ro", uri=True)) as conn:
            rows = conn.execute(query, params).fetchall()
    except (OSError, sqlite3.Error):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("codex sqlite logs load failed", exc_info=True)
        return []

    entries: list[UsageEntry] = []
    for row_id, ts, ts_nanos, body in rows:
        entry = _parse_sqlite_log_row(row_id, ts, ts_nanos, body, metadata)
        if entry is None:
            continue
        if cutoff is not None and entry.timestamp < cutoff:
            continue
        latest_jsonl_ts = latest_jsonl_ts_by_session.get(entry.session_id)
        if latest_jsonl_ts is not None and entry.timestamp <= latest_jsonl_ts:
            continue
        entries.append(entry)
    return entries


def _parse_sqlite_log_row(
    row_id: Any,
    ts: Any,
    ts_nanos: Any,
    body: Any,
    metadata: dict[str, _ThreadMetadata],
) -> UsageEntry | None:
    if not isinstance(body, str):
        return None
    if 'event.name="codex.sse_event"' not in body or "event.kind=response.completed" not in body:
        return None
    session_id = _event_value(body, "conversation.id")
    if not session_id:
        return None
    timestamp = _parse_timestamp(_event_value(body, "event.timestamp"))
    if timestamp is None:
        timestamp = _timestamp_from_log_ts(ts)
    if timestamp is None:
        return None
    cached = _as_int(_event_value(body, "cached_token_count"))
    input_tokens = max(0, _as_int(_event_value(body, "input_token_count")) - cached)
    output_tokens = _as_int(_event_value(body, "output_token_count"))
    if input_tokens + output_tokens + cached == 0:
        return None
    thread = metadata.get(session_id, _ThreadMetadata())
    model = _event_value(body, "model") or thread.model
    project = _project_from_cwd(thread.cwd) if thread.cwd else "unknown"
    return UsageEntry(
        timestamp=timestamp,
        session_id=session_id,
        message_id=f"{session_id}:sqlite:{row_id}:{ts_nanos}",
        request_id="",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=0,
        cache_read_tokens=cached,
        cost_usd=None,
        project=project,
    )


_EVENT_VALUE_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _event_value(body: str, key: str) -> str:
    pattern = _EVENT_VALUE_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(rf'(?:^|[\s{{]){re.escape(key)}=(?:"([^"]*)"|([^\s}}]+))')
        _EVENT_VALUE_RE_CACHE[key] = pattern
    match = pattern.search(body)
    if match is None:
        return ""
    return match.group(1) if match.group(1) is not None else match.group(2)


def _timestamp_from_log_ts(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp):
        return None
    return datetime.fromtimestamp(timestamp, UTC)


def _recent_jsonl_files() -> list[Path]:
    try:
        paths = [path for path in SESSIONS_DIR.rglob("*.jsonl") if _is_visible_jsonl(path)]
    except OSError:
        return []
    return _sort_recent_jsonl_files(paths)


def _is_visible_jsonl(path: Path) -> bool:
    try:
        relative = path.relative_to(SESSIONS_DIR)
    except ValueError:
        return False
    return all(not part.startswith(".") for part in relative.parts)


def _sort_recent_jsonl_files(paths: list[Path]) -> list[Path]:
    paths_with_mtime: list[tuple[float, Path]] = []
    for path in paths:
        try:
            paths_with_mtime.append((path.stat().st_mtime, path))
        except OSError as exc:
            logger.warning("failed to stat codex session %s: %s", path, exc)
    paths_with_mtime.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in paths_with_mtime[:_RECENT_JSONL_SCAN_LIMIT]]


def _extract_rate_limits(path: Path, models: dict[str, str]) -> CodexRateLimits | None:
    session_id = ""
    session_model = "unknown"
    last_rate_limits: tuple[dict[str, Any], str] | None = None
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                data = _load_json_line(line)
                if data is None:
                    continue
                if data.get("type") == "session_meta":
                    session_id = _as_str(_as_dict(data.get("payload")).get("id"))
                    session_model = _session_model(data.get("payload"), session_model)
                    continue
                if data.get("type") == "turn_context":
                    session_model = _session_model(data.get("payload"), session_model)
                    continue
                if data.get("type") != "event_msg":
                    continue
                payload = _as_dict(data.get("payload"))
                if payload.get("type") != "token_count":
                    continue
                rate_limits = _as_dict(payload.get("rate_limits"))
                if rate_limits:
                    last_rate_limits = (rate_limits, _as_str(data.get("timestamp")))
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("failed to read codex session %s: %s", path, exc)
        return None
    if last_rate_limits is None:
        return None
    rate_limits, updated_at = last_rate_limits
    primary = _as_dict(rate_limits.get("primary"))
    secondary = _as_dict(rate_limits.get("secondary"))
    five_pct = _as_optional_float(primary.get("used_percent"))
    five_reset = _as_optional_float(primary.get("resets_at"))
    five_window = _as_optional_float(primary.get("window_minutes"))
    seven_pct = _as_optional_float(secondary.get("used_percent"))
    seven_reset = _as_optional_float(secondary.get("resets_at"))
    seven_window = _as_optional_float(secondary.get("window_minutes"))
    now_ts = datetime.now(UTC).timestamp()
    if five_reset is not None and five_reset < now_ts:
        five_pct = 0.0
        five_reset = None
    if seven_reset is not None and seven_reset < now_ts:
        seven_pct = 0.0
        seven_reset = None
    if five_pct is None and seven_pct is None:
        return None
    return CodexRateLimits(
        five_hour_pct=five_pct,
        five_hour_resets_at=five_reset,
        seven_day_pct=seven_pct,
        seven_day_resets_at=seven_reset,
        five_hour_window_minutes=five_window,
        seven_day_window_minutes=seven_window,
        model=models.get(session_id, session_model),
        updated_at=updated_at,
    )


def _fork_replay_boundary(
    path: Path,
    info: _SessionFileInfo,
    parent_paths: list[Path],
) -> tuple[int | None, _ReplayCacheKey]:
    if not info.forked_from_id:
        return 0, None

    # Fork logs rewrite replay timestamps, but preserve the parent's cumulative token sequence.
    lookup_key = _fork_replay_lookup_key(path, parent_paths)
    if lookup_key is None:
        return None, None
    cached = _fork_replay_cache.get(path)
    if cached is not None and cached[0] == lookup_key:
        _fork_replay_cache.move_to_end(path)
        return cached[1], cached[2]

    child_events = _token_usage_events_after_embedded_parent(path, info.forked_from_id)
    if child_events is None:
        result: tuple[int | None, _ReplayCacheKey] = (0, None)
        _cache_fork_replay_boundary(path, lookup_key, result)
        return result
    if not lookup_key[2]:
        result = (None, None)
        _cache_fork_replay_boundary(path, lookup_key, result)
        return result

    child_usage = [usage for _, usage in child_events]
    best_match = 0
    best_key: _ReplayCacheKey = None
    for parent_path in parent_paths:
        match_count = _common_prefix_length(
            child_usage,
            _raw_token_usage_sequence(parent_path),
        )
        if match_count <= best_match:
            continue
        try:
            parent_stat = parent_path.stat()
        except OSError:
            continue
        best_match = match_count
        best_key = (
            str(parent_path),
            parent_stat.st_mtime,
            parent_stat.st_size,
            match_count,
        )

    if child_events and best_match == 0:
        result = (None, None)
        _cache_fork_replay_boundary(path, lookup_key, result)
        return result
    boundary = child_events[best_match - 1][0] if best_match else 0
    result = (boundary, best_key)
    _cache_fork_replay_boundary(path, lookup_key, result)
    return result


def _fork_replay_lookup_key(
    path: Path,
    parent_paths: list[Path],
) -> _ReplayLookupKey | None:
    try:
        child_stat = path.stat()
    except OSError:
        return None
    parent_stats: list[tuple[str, float, int]] = []
    for parent_path in parent_paths:
        try:
            parent_stat = parent_path.stat()
        except OSError:
            continue
        parent_stats.append((str(parent_path), parent_stat.st_mtime, parent_stat.st_size))
    return child_stat.st_mtime, child_stat.st_size, tuple(sorted(parent_stats))


def _cache_fork_replay_boundary(
    path: Path,
    lookup_key: _ReplayLookupKey,
    result: tuple[int | None, _ReplayCacheKey],
) -> None:
    if path not in _fork_replay_cache and len(_fork_replay_cache) >= _JSONL_CACHE_MAXSIZE:
        _fork_replay_cache.popitem(last=False)
    _fork_replay_cache[path] = (lookup_key, result[0], result[1])


def _token_usage_events_after_embedded_parent(
    path: Path,
    parent_session_id: str,
) -> list[tuple[int, _TokenUsage]] | None:
    embedded_parent = False
    root_seen = False
    events: list[tuple[int, _TokenUsage]] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                data = _load_json_line(line)
                if data is None:
                    continue
                if data.get("type") == "session_meta":
                    session_id = _as_str(_as_dict(data.get("payload")).get("id"))
                    if not root_seen:
                        root_seen = True
                    elif session_id == parent_session_id:
                        embedded_parent = True
                    continue
                usage = _token_usage_from_event(data)
                if embedded_parent and usage is not None:
                    events.append((line_number, usage))
    except (OSError, UnicodeDecodeError):
        return None
    return events if embedded_parent else None


def _raw_token_usage_sequence(path: Path) -> list[_TokenUsage]:
    usage_events: list[_TokenUsage] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                data = _load_json_line(line)
                if data is None:
                    continue
                usage = _token_usage_from_event(data)
                if usage is not None:
                    usage_events.append(usage)
    except (OSError, UnicodeDecodeError):
        return []
    return usage_events


def _token_usage_from_event(data: dict[str, Any]) -> _TokenUsage | None:
    if data.get("type") != "event_msg":
        return None
    payload = _as_dict(data.get("payload"))
    if payload.get("type") != "token_count":
        return None
    usage = _as_dict(_as_dict(payload.get("info")).get("total_token_usage"))
    return _token_usage_from_payload(usage) if usage else None


def _common_prefix_length(left: list[_TokenUsage], right: list[_TokenUsage]) -> int:
    matched = 0
    for left_usage, right_usage in zip(left, right, strict=False):
        if left_usage != right_usage:
            break
        matched += 1
    return matched


def _parse_jsonl(
    path: Path,
    models: dict[str, str],
    cutoff: datetime | None,
    *,
    file_info: _SessionFileInfo | None = None,
    replay_boundary: int | None = 0,
    replay_cache_key: _ReplayCacheKey = None,
) -> list[UsageEntry]:
    try:
        st = path.stat()
    except OSError as exc:
        logger.warning("failed to parse codex session %s: %s", path, exc)
        return []

    cache_entry = _jsonl_cache.get(path)
    if (
        cache_entry is not None
        and cache_entry[0] == st.st_mtime
        and cache_entry[1] == st.st_size
        and cache_entry[2] == replay_cache_key
    ):
        _jsonl_cache.move_to_end(path)
        cached_entries = cache_entry[3]
        for entry in cached_entries:
            if entry.session_id in models:
                entry.model = models[entry.session_id]
        if cutoff is None:
            return cached_entries
        return [entry for entry in cached_entries if entry.timestamp >= cutoff]

    info = file_info or _read_session_file_info(path)
    if replay_boundary is None:
        return []

    session_id = info.session_id
    session_timestamp = ""
    project = "unknown"
    session_model = "unknown"
    entries: list[UsageEntry] = []
    previous_usage: _TokenUsage | None = None
    token_count_index = 0
    try:
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                data = _load_json_line(line)
                if data is None:
                    continue
                if data.get("type") == "session_meta":
                    payload = _as_dict(data.get("payload"))
                    if not session_timestamp:
                        session_timestamp = _as_str(payload.get("timestamp"))
                        project = _project_from_cwd(_as_str(payload.get("cwd")))
                        session_model = _session_model(payload, session_model)
                    continue
                if line_number <= replay_boundary:
                    continue
                if data.get("type") == "turn_context":
                    session_model = _session_model(data.get("payload"), session_model)
                    continue
                if data.get("type") != "event_msg":
                    continue
                payload = _as_dict(data.get("payload"))
                if payload.get("type") != "token_count":
                    continue
                usage = _as_dict(_as_dict(payload.get("info")).get("total_token_usage"))
                timestamp = _parse_timestamp(_as_str(data.get("timestamp")))
                if not usage or not session_id or timestamp is None:
                    continue
                current_usage = _token_usage_from_payload(usage)
                delta = current_usage.delta(previous_usage)
                previous_usage = current_usage
                if delta.total_tokens == 0:
                    continue
                token_count_index += 1
                entries.append(
                    UsageEntry(
                        timestamp=timestamp,
                        session_id=session_id,
                        message_id=f"{session_id}:{token_count_index}",
                        request_id="",
                        model=models.get(session_id, session_model),
                        input_tokens=delta.input_tokens,
                        output_tokens=delta.output_tokens,
                        cache_creation_tokens=0,
                        cache_read_tokens=delta.cache_read_tokens,
                        cost_usd=None,
                        project=project,
                    )
                )
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("failed to parse codex session %s: %s", path, exc)
        if path not in _jsonl_cache and len(_jsonl_cache) >= _JSONL_CACHE_MAXSIZE:
            _jsonl_cache.popitem(last=False)
        _jsonl_cache[path] = (st.st_mtime, st.st_size, replay_cache_key, [])
        return []
    if not entries and session_timestamp:
        if path not in _jsonl_cache and len(_jsonl_cache) >= _JSONL_CACHE_MAXSIZE:
            _jsonl_cache.popitem(last=False)
        _jsonl_cache[path] = (st.st_mtime, st.st_size, replay_cache_key, [])
        return []
    if path not in _jsonl_cache and len(_jsonl_cache) >= _JSONL_CACHE_MAXSIZE:
        _jsonl_cache.popitem(last=False)
    _jsonl_cache[path] = (st.st_mtime, st.st_size, replay_cache_key, entries)
    if cutoff is not None:
        return [entry for entry in entries if entry.timestamp >= cutoff]
    return entries


@dataclass(frozen=True, slots=True)
class _TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens

    def delta(self, previous: _TokenUsage | None) -> _TokenUsage:
        if previous is None:
            return self
        return _TokenUsage(
            input_tokens=max(0, self.input_tokens - previous.input_tokens),
            output_tokens=max(0, self.output_tokens - previous.output_tokens),
            cache_read_tokens=max(0, self.cache_read_tokens - previous.cache_read_tokens),
        )


def _token_usage_from_payload(usage: dict[str, Any]) -> _TokenUsage:
    cached = _as_int(usage.get("cached_input_tokens"))
    input_tokens = max(0, _as_int(usage.get("input_tokens")) - cached)
    output_tokens = _as_int(usage.get("output_tokens"))
    return _TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cached,
    )


def _load_json_line(line: str) -> dict[str, Any] | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _project_from_cwd(cwd: str) -> str:
    return resolve_project_name(cwd)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _session_model(payload: Any, fallback: str) -> str:
    model = _as_str(_as_dict(payload).get("model"))
    return model or fallback


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


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number
