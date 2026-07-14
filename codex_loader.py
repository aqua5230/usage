# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import time
from collections import OrderedDict
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from codex_disk_cache import (  # noqa: F401  (de)serializers re-exported for tests
    _deserialize_usage_entry as _deserialize_usage_entry,
)
from codex_disk_cache import (
    _serialize_usage_entry as _serialize_usage_entry,
)
from codex_disk_cache import (
    flush_caches,
    seed_caches,
)
from codex_events import (
    _as_dict,
    _as_int,
    _as_optional_float,
    _as_str,
    _event_value,
    _load_json_line,
    _session_model,
    _timestamp_from_log_ts,
    _token_usage_from_payload,
    _TokenUsage,
)
from codex_events import (
    _SessionFileInfo as _SessionFileInfo,
)
from codex_events import (
    _ThreadMetadata as _ThreadMetadata,
)
from codex_fork_replay import (
    _common_prefix_length,
    _fork_replay_lookup_key,
    _raw_token_usage_sequence,
    _ReplayCacheKey,
    _ReplayLookupKey,
    _token_usage_events_after_embedded_parent,
)
from history_loader import UsageEntry
from project_resolver import resolve_project_name
from time_utils import parse_optional_iso8601_utc

logger = logging.getLogger(__name__)

# Must comfortably exceed a real user's total *.jsonl session count. A cap at
# or below that count means every load_entries() call evicts and re-parses
# files that were just cached last refresh (LRU thrashing) — measured 512
# capped at 809 real sessions into a permanent 17+ second full-reparse every
# single call, even with per-file incremental caching working correctly in
# isolation. Also backs _file_info_cache and _fork_replay_cache below, which
# share the same real-world file count.
_JSONL_CACHE_MAXSIZE = 4096
_RECENT_JSONL_SCAN_LIMIT = 30


@dataclass(slots=True)
class _JsonlParseState:
    session_timestamp: str = ""
    project: str = "unknown"
    session_model: str = "unknown"
    previous_usage: _TokenUsage | None = None
    token_count_index: int = 0

    def copy(self) -> _JsonlParseState:
        return _JsonlParseState(
            session_timestamp=self.session_timestamp,
            project=self.project,
            session_model=self.session_model,
            previous_usage=self.previous_usage,
            token_count_index=self.token_count_index,
        )


@dataclass(slots=True)
class _JsonlCacheEntry:
    mtime: float
    size: int
    replay_cache_key: _ReplayCacheKey
    entries: list[UsageEntry]
    confirmed_offset: int = 0
    confirmed_prefix_digest: bytes = b""
    state: _JsonlParseState = field(default_factory=_JsonlParseState)


@dataclass(slots=True)
class _SqliteLogCache:
    watermark: tuple[int, int, int] | None = None
    entries: list[UsageEntry] = field(default_factory=list)


_jsonl_cache: OrderedDict[Path, _JsonlCacheEntry] = OrderedDict()
_fork_replay_cache: OrderedDict[
    Path,
    tuple[_ReplayLookupKey, int | None, _ReplayCacheKey],
] = OrderedDict()
_file_info_cache: OrderedDict[
    Path,
    tuple[float, int, _SessionFileInfo],
] = OrderedDict()
_sqlite_log_cache = _SqliteLogCache()

SESSIONS_DIR = Path(os.path.expanduser("~/.codex/sessions"))
ARCHIVED_SESSIONS_DIR = Path(os.path.expanduser("~/.codex/archived_sessions"))
STATE_DB = Path(os.path.expanduser("~/.codex/state_5.sqlite"))
LOGS_DB = Path(os.path.expanduser("~/.codex/logs_2.sqlite"))


def _readonly_sqlite_uri(path: Path) -> str:
    """Return a read-only SQLite URI that also accepts Windows drive paths."""
    return f"{path.resolve().as_uri()}?mode=ro"

# Disk cache for JSONL parsing results. Schema version must be bumped when the
# serialization format or parsing logic changes incompatibly.
_CODEX_JSONL_CACHE_SCHEMA = 3
JSONL_CACHE_PATH = Path(os.path.expanduser("~/.usage/codex_jsonl_cache.json"))

# Module-level flag to ensure seed loading happens exactly once.
_disk_cache_seeded = False
_DISK_CACHE_FLUSH_INTERVAL_S = 300.0
_disk_cache_dirty = False
_last_disk_cache_flush_at: float | None = None
_monotonic = time.monotonic


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


def _seed_caches_from_disk() -> None:
    """Seed in-memory caches from disk exactly once. Silently fails on any error."""
    global _disk_cache_seeded

    if _disk_cache_seeded:
        return
    _disk_cache_seeded = True
    seed_caches(
        JSONL_CACHE_PATH,
        _CODEX_JSONL_CACHE_SCHEMA,
        _JSONL_CACHE_MAXSIZE,
        _jsonl_cache,
        _file_info_cache,
        _sqlite_log_cache,
    )


def _flush_caches_to_disk(*, force: bool = False) -> None:
    """Atomically write current in-memory caches to disk."""
    global _disk_cache_dirty, _last_disk_cache_flush_at

    if not _disk_cache_dirty:
        return
    now = _monotonic()
    if (
        not force
        and _last_disk_cache_flush_at is not None
        and now - _last_disk_cache_flush_at < _DISK_CACHE_FLUSH_INTERVAL_S
    ):
        return
    flush_caches(
        JSONL_CACHE_PATH,
        _CODEX_JSONL_CACHE_SCHEMA,
        _jsonl_cache,
        _file_info_cache,
        _sqlite_log_cache,
    )
    _last_disk_cache_flush_at = now
    _disk_cache_dirty = False


def flush_caches_on_terminate() -> None:
    """Best-effort persistence of cache changes still waiting for the throttle."""
    with contextlib.suppress(Exception):
        _flush_caches_to_disk(force=True)


def load_entries(
    hours_back: int = 0,
    *,
    jsonl_paths: Iterable[Path] | None = None,
) -> list[UsageEntry]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None
    metadata = _load_thread_metadata()
    models = {session_id: data.model for session_id, data in metadata.items()}
    entries = _load_jsonl_entries(SESSIONS_DIR, models, cutoff, jsonl_paths=jsonl_paths)

    latest_jsonl_ts_by_session = {
        entry.session_id: entry.timestamp
        for entry in entries
    }
    entries.extend(_load_sqlite_log_entries(metadata, cutoff, latest_jsonl_ts_by_session))
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _session_roots(primary_dir: Path) -> list[Path]:
    roots = [primary_dir]
    if ARCHIVED_SESSIONS_DIR.is_dir():
        roots.append(ARCHIVED_SESSIONS_DIR)
    return roots


def _session_root_for_path(path: Path) -> Path | None:
    for root in _session_roots(SESSIONS_DIR):
        if path.is_relative_to(root):
            return root
    return None


def _load_jsonl_entries(
    sessions_dir: Path,
    models: dict[str, str],
    cutoff: datetime | None,
    *,
    jsonl_paths: Iterable[Path] | None = None,
) -> list[UsageEntry]:
    global _disk_cache_dirty

    # Seed from disk on first call
    _seed_caches_from_disk()

    if jsonl_paths is None:
        roots = [root for root in _session_roots(sessions_dir) if root.is_dir()]
        if not roots:
            return []
        jsonl_path_list = [path for root in roots for path in root.rglob("*.jsonl")]
    else:
        jsonl_path_list = list(jsonl_paths)
        if not jsonl_path_list:
            return []

    # Snapshot each cached file's (mtime, size) to detect new or re-parsed files.
    # A re-parse overwrites an existing key in place, so cache size alone would
    # miss an updated (still-growing) session file — exactly the active files we
    # most want to persist. dict equality ignores LRU move_to_end reordering.
    jsonl_snapshot = {str(p): (e.mtime, e.size) for p, e in _jsonl_cache.items()}
    file_info_snapshot = {str(p): (v[0], v[1]) for p, v in _file_info_cache.items()}

    entries_by_session: dict[str, list[UsageEntry]] = {}
    cutoff_ts = cutoff.timestamp() if cutoff else None
    file_info = {path: _read_session_file_info(path) for path in jsonl_path_list}
    paths_by_session: dict[str, list[Path]] = {}
    for path, info in file_info.items():
        if info.session_id:
            paths_by_session.setdefault(info.session_id, []).append(path)

    for jsonl_path in jsonl_path_list:
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
        {str(p): (e.mtime, e.size) for p, e in _jsonl_cache.items()} != jsonl_snapshot
        or {str(p): (v[0], v[1]) for p, v in _file_info_cache.items()} != file_info_snapshot
    ):
        _disk_cache_dirty = True
        _flush_caches_to_disk()
    elif _disk_cache_dirty:
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
    if not any(root.is_dir() for root in _session_roots(SESSIONS_DIR)):
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
        with closing(sqlite3.connect(_readonly_sqlite_uri(LOGS_DB), uri=True)) as conn:
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
    (
        primary_pct,
        primary_reset,
        primary_window_minutes,
        secondary_pct,
        secondary_reset,
        secondary_window_minutes,
    ) = _assign_rate_limit_slots(
        primary_pct,
        primary_reset,
        primary_window_minutes,
        secondary_pct,
        secondary_reset,
        secondary_window_minutes,
    )
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


def _assign_rate_limit_slots(
    primary_pct: float | None,
    primary_reset: float | None,
    primary_window_minutes: float | None,
    secondary_pct: float | None,
    secondary_reset: float | None,
    secondary_window_minutes: float | None,
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]:
    primary_is_session = (
        primary_window_minutes is not None and primary_window_minutes <= 600.0
    )
    secondary_is_session = (
        secondary_window_minutes is not None and secondary_window_minutes <= 600.0
    )
    classify_by_window = (
        primary_window_minutes is not None
        and secondary_window_minutes is not None
        and primary_is_session != secondary_is_session
    ) or (
        primary_window_minutes is not None
        and secondary_pct is None
        and secondary_window_minutes is None
    ) or (
        secondary_window_minutes is not None
        and primary_pct is None
        and primary_window_minutes is None
    )
    if classify_by_window and not primary_is_session:
        primary_pct, secondary_pct = secondary_pct, primary_pct
        primary_reset, secondary_reset = secondary_reset, primary_reset
        primary_window_minutes, secondary_window_minutes = (
            secondary_window_minutes,
            primary_window_minutes,
        )
    return (
        primary_pct,
        primary_reset,
        primary_window_minutes,
        secondary_pct,
        secondary_reset,
        secondary_window_minutes,
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
        with closing(sqlite3.connect(_readonly_sqlite_uri(STATE_DB), uri=True)) as conn:
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
    global _disk_cache_dirty

    if not LOGS_DB.exists():
        return []
    query = (
        "SELECT id, ts, ts_nanos, feedback_log_body FROM logs "
        "WHERE target = 'codex_otel.trace_safe' "
        "AND feedback_log_body LIKE '%event.kind=response.completed%' "
        "AND feedback_log_body LIKE '%input_token_count=%'"
    )
    params: tuple[int, ...] = ()
    if _sqlite_log_cache.watermark is not None:
        query += " AND (ts, ts_nanos, id) > (?, ?, ?)"
        params = _sqlite_log_cache.watermark
    query += " ORDER BY ts ASC, ts_nanos ASC, id ASC"
    try:
        with closing(sqlite3.connect(_readonly_sqlite_uri(LOGS_DB), uri=True)) as conn:
            conn.execute("BEGIN")
            rows = conn.execute(query, params).fetchall()
            newest_rows = conn.execute(
                "SELECT ts, ts_nanos, id FROM logs "
                "ORDER BY ts DESC, ts_nanos DESC, id DESC LIMIT 1"
            ).fetchall()
            newest = newest_rows[0] if newest_rows else None
    except (OSError, sqlite3.Error):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("codex sqlite logs load failed", exc_info=True)
        return []

    candidates = list(_sqlite_log_cache.entries)
    for row_id, ts, ts_nanos, body in rows:
        entry = _parse_sqlite_log_row(row_id, ts, ts_nanos, body, metadata)
        if entry is not None:
            candidates.append(entry)

    watermark = _sqlite_log_watermark(newest)
    if _sqlite_log_cache.watermark is not None and (
        watermark is None or watermark < _sqlite_log_cache.watermark
    ):
        watermark = _sqlite_log_cache.watermark
    if watermark != _sqlite_log_cache.watermark or len(candidates) != len(
        _sqlite_log_cache.entries
    ):
        _sqlite_log_cache.watermark = watermark
        _sqlite_log_cache.entries = candidates
        _disk_cache_dirty = True
        _flush_caches_to_disk()

    entries: list[UsageEntry] = []
    for entry in candidates:
        if cutoff is not None and entry.timestamp < cutoff:
            continue
        latest_jsonl_ts = latest_jsonl_ts_by_session.get(entry.session_id)
        if latest_jsonl_ts is not None and entry.timestamp <= latest_jsonl_ts:
            continue
        entries.append(entry)
    return entries


def _sqlite_log_watermark(row: Any) -> tuple[int, int, int] | None:
    if not isinstance(row, (list, tuple)) or len(row) != 3:
        return None
    try:
        return int(row[0]), int(row[1]), int(row[2])
    except (TypeError, ValueError):
        return None


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


def _recent_jsonl_files() -> list[Path]:
    try:
        paths = [
            path
            for root in _session_roots(SESSIONS_DIR)
            for path in root.rglob("*.jsonl")
            if _is_visible_jsonl(path)
        ]
    except OSError:
        return []
    return _sort_recent_jsonl_files(paths)


def _is_visible_jsonl(path: Path) -> bool:
    root = _session_root_for_path(path)
    if root is None:
        return False
    relative = path.relative_to(root)
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
    five_pct, five_reset, five_window, seven_pct, seven_reset, seven_window = (
        _assign_rate_limit_slots(
            five_pct,
            five_reset,
            five_window,
            seven_pct,
            seven_reset,
            seven_window,
        )
    )
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


def _cache_fork_replay_boundary(
    path: Path,
    lookup_key: _ReplayLookupKey,
    result: tuple[int | None, _ReplayCacheKey],
) -> None:
    if path not in _fork_replay_cache and len(_fork_replay_cache) >= _JSONL_CACHE_MAXSIZE:
        _fork_replay_cache.popitem(last=False)
    _fork_replay_cache[path] = (lookup_key, result[0], result[1])


def _cache_jsonl_entry(path: Path, entry: _JsonlCacheEntry) -> None:
    if path not in _jsonl_cache and len(_jsonl_cache) >= _JSONL_CACHE_MAXSIZE:
        _jsonl_cache.popitem(last=False)
    _jsonl_cache[path] = entry


def _confirmed_prefix_hasher(path: Path, cached: _JsonlCacheEntry) -> Any | None:
    if cached.confirmed_offset == 0:
        return hashlib.blake2b(digest_size=16)
    digest = hashlib.blake2b(digest_size=16)
    remaining = cached.confirmed_offset
    try:
        with path.open("rb") as file:
            while remaining > 0:
                chunk = file.read(min(remaining, 65536))
                if not chunk:
                    return None
                digest.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return None
    if digest.digest() != cached.confirmed_prefix_digest:
        return None
    return digest


def _parse_linear_jsonl_bytes(
    file: Any,
    *,
    session_id: str,
    models: dict[str, str],
    entries: list[UsageEntry],
    state: _JsonlParseState,
    digest: Any,
    confirmed_offset: int,
) -> int:
    while True:
        line_start = int(file.tell())
        line = file.readline()
        if not line:
            return confirmed_offset
        data = _load_json_line(line.decode("utf-8", errors="replace"))
        if not line.endswith(b"\n") and data is None:
            return line_start
        digest.update(line)
        confirmed_offset = int(file.tell())
        if data is None:
            continue
        if data.get("type") == "session_meta":
            payload = _as_dict(data.get("payload"))
            if not state.session_timestamp:
                state.session_timestamp = _as_str(payload.get("timestamp"))
                state.project = _project_from_cwd(_as_str(payload.get("cwd")))
                state.session_model = _session_model(payload, state.session_model)
            continue
        if data.get("type") == "turn_context":
            state.session_model = _session_model(data.get("payload"), state.session_model)
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
        delta = current_usage.delta(state.previous_usage)
        state.previous_usage = current_usage
        if delta.total_tokens == 0:
            continue
        state.token_count_index += 1
        entries.append(
            UsageEntry(
                timestamp=timestamp,
                session_id=session_id,
                message_id=f"{session_id}:{state.token_count_index}",
                request_id="",
                model=models.get(session_id, state.session_model),
                input_tokens=delta.input_tokens,
                output_tokens=delta.output_tokens,
                cache_creation_tokens=0,
                cache_read_tokens=delta.cache_read_tokens,
                cost_usd=None,
                project=state.project,
            )
        )


def _refresh_linear_jsonl_cache(
    path: Path,
    st: os.stat_result,
    session_id: str,
    models: dict[str, str],
    cached: _JsonlCacheEntry | None,
) -> _JsonlCacheEntry | None:
    prefix_hasher = (
        _confirmed_prefix_hasher(path, cached)
        if cached is not None and st.st_size >= cached.confirmed_offset and st.st_size > cached.size
        else None
    )
    if prefix_hasher is not None:
        assert cached is not None
        incremental_entries = list(cached.entries)
        state = cached.state.copy()
        try:
            with path.open("rb") as file:
                file.seek(cached.confirmed_offset)
                confirmed_offset = _parse_linear_jsonl_bytes(
                    file,
                    session_id=session_id,
                    models=models,
                    entries=incremental_entries,
                    state=state,
                    digest=prefix_hasher,
                    confirmed_offset=cached.confirmed_offset,
                )
        except OSError as exc:
            logger.warning("failed to parse codex session %s: %s", path, exc)
            return None
        return _JsonlCacheEntry(
            mtime=st.st_mtime,
            size=st.st_size,
            replay_cache_key=None,
            entries=incremental_entries,
            confirmed_offset=confirmed_offset,
            confirmed_prefix_digest=prefix_hasher.digest(),
            state=state,
        )

    entries: list[UsageEntry] = []
    state = _JsonlParseState()
    digest = hashlib.blake2b(digest_size=16)
    try:
        with path.open("rb") as file:
            confirmed_offset = _parse_linear_jsonl_bytes(
                file,
                session_id=session_id,
                models=models,
                entries=entries,
                state=state,
                digest=digest,
                confirmed_offset=0,
            )
    except OSError as exc:
        logger.warning("failed to parse codex session %s: %s", path, exc)
        return None
    return _JsonlCacheEntry(
        mtime=st.st_mtime,
        size=st.st_size,
        replay_cache_key=None,
        entries=entries,
        confirmed_offset=confirmed_offset,
        confirmed_prefix_digest=digest.digest(),
        state=state,
    )


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
        and cache_entry.mtime == st.st_mtime
        and cache_entry.size == st.st_size
        and cache_entry.replay_cache_key == replay_cache_key
    ):
        _jsonl_cache.move_to_end(path)
        cached_entries = cache_entry.entries
        for entry in cached_entries:
            if entry.session_id in models:
                entry.model = models[entry.session_id]
        if cutoff is None:
            return cached_entries
        return [entry for entry in cached_entries if entry.timestamp >= cutoff]

    info = file_info or _read_session_file_info(path)
    if replay_boundary is None:
        return []

    if not info.forked_from_id and replay_boundary == 0 and replay_cache_key is None:
        refreshed = _refresh_linear_jsonl_cache(path, st, info.session_id, models, cache_entry)
        if refreshed is None:
            _cache_jsonl_entry(
                path,
                _JsonlCacheEntry(
                    mtime=st.st_mtime,
                    size=st.st_size,
                    replay_cache_key=None,
                    entries=[],
                ),
            )
            return []
        _cache_jsonl_entry(path, refreshed)
        refreshed_entries = refreshed.entries
        # Carried-forward entries from a prior incremental parse were built
        # before `models` (thread->model, resolved from sqlite) may have caught
        # up — reapply it here too, not just to entries parsed in this call, or
        # a stale/unknown model (and thus wrong per-model cost) sticks forever.
        for entry in refreshed_entries:
            if entry.session_id in models:
                entry.model = models[entry.session_id]
        if cutoff is not None:
            return [entry for entry in refreshed_entries if entry.timestamp >= cutoff]
        return refreshed_entries

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
        _cache_jsonl_entry(
            path,
            _JsonlCacheEntry(
                mtime=st.st_mtime,
                size=st.st_size,
                replay_cache_key=replay_cache_key,
                entries=[],
            ),
        )
        return []
    if not entries and session_timestamp:
        _cache_jsonl_entry(
            path,
            _JsonlCacheEntry(
                mtime=st.st_mtime,
                size=st.st_size,
                replay_cache_key=replay_cache_key,
                entries=[],
            ),
        )
        return []
    _cache_jsonl_entry(
        path,
        _JsonlCacheEntry(
            mtime=st.st_mtime,
            size=st.st_size,
            replay_cache_key=replay_cache_key,
            entries=entries,
        ),
    )
    if cutoff is not None:
        return [entry for entry in entries if entry.timestamp >= cutoff]
    return entries


def _parse_timestamp(value: Any) -> datetime | None:
    return parse_optional_iso8601_utc(value)


def _project_from_cwd(cwd: str) -> str:
    return resolve_project_name(cwd)
