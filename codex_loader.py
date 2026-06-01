from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from history_loader import UsageEntry
from project_resolver import resolve_project_name

logger = logging.getLogger(__name__)

_JSONL_CACHE_MAXSIZE = 512
_RECENT_JSONL_SCAN_LIMIT = 30
_jsonl_cache: OrderedDict[Path, tuple[float, int, list[UsageEntry]]] = OrderedDict()

SESSIONS_DIR = Path(os.path.expanduser("~/.codex/sessions"))
STATE_DB = Path(os.path.expanduser("~/.codex/state_5.sqlite"))
LOGS_DB = Path(os.path.expanduser("~/.codex/logs_2.sqlite"))


@dataclass(slots=True)
class CodexRateLimits:
    five_hour_pct: float | None
    five_hour_resets_at: float | None
    seven_day_pct: float | None
    seven_day_resets_at: float | None
    model: str | None = "unknown"
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class _ThreadMetadata:
    model: str = "unknown"
    cwd: str = ""


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    entries_by_session: dict[str, list[UsageEntry]] = {}
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None
    cutoff_ts = cutoff.timestamp() if cutoff else None
    metadata = _load_thread_metadata()
    models = {session_id: data.model for session_id, data in metadata.items()}

    if SESSIONS_DIR.is_dir():
        for jsonl_path in SESSIONS_DIR.rglob("*.jsonl"):
            if cutoff_ts is not None:
                try:
                    if jsonl_path.stat().st_mtime < cutoff_ts:
                        continue
                except OSError as exc:
                    logger.warning("failed to stat session log %s: %s", jsonl_path, exc)
                    continue
            parsed = _parse_jsonl(jsonl_path, models, cutoff)
            if not parsed:
                continue
            existing = entries_by_session.get(parsed[0].session_id)
            if existing is None or _is_better_session_log(parsed, existing):
                entries_by_session[parsed[0].session_id] = parsed

    latest_jsonl_ts_by_session = {
        session_id: session_entries[-1].timestamp
        for session_id, session_entries in entries_by_session.items()
        if session_entries
    }

    entries = [
        entry
        for session_entries in entries_by_session.values()
        for entry in session_entries
    ]
    entries.extend(_load_sqlite_log_entries(metadata, cutoff, latest_jsonl_ts_by_session))
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _is_better_session_log(candidate: list[UsageEntry], existing: list[UsageEntry]) -> bool:
    candidate_latest = candidate[-1]
    existing_latest = existing[-1]
    if candidate_latest.timestamp != existing_latest.timestamp:
        return candidate_latest.timestamp > existing_latest.timestamp
    return _session_total_tokens(candidate) > _session_total_tokens(existing)


def _session_total_tokens(entries: list[UsageEntry]) -> int:
    return sum(entry.total_tokens for entry in entries)


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
    five_pct, five_reset = _pick_rate_limit_window(
        sqlite_limits.five_hour_pct,
        sqlite_limits.five_hour_resets_at,
        sqlite_ts,
        jsonl_limits.five_hour_pct,
        jsonl_limits.five_hour_resets_at,
        jsonl_ts,
    )
    seven_pct, seven_reset = _pick_rate_limit_window(
        sqlite_limits.seven_day_pct,
        sqlite_limits.seven_day_resets_at,
        sqlite_ts,
        jsonl_limits.seven_day_pct,
        jsonl_limits.seven_day_resets_at,
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
        model=newer.model,
        updated_at=newer.updated_at,
    )


def _pick_rate_limit_window(
    sqlite_pct: float | None,
    sqlite_reset: float | None,
    sqlite_ts: datetime,
    jsonl_pct: float | None,
    jsonl_reset: float | None,
    jsonl_ts: datetime,
) -> tuple[float | None, float | None]:
    if sqlite_pct is None:
        return jsonl_pct, jsonl_reset
    if jsonl_pct is None:
        return sqlite_pct, sqlite_reset
    if _active_window_limit_reached(sqlite_pct, sqlite_reset, jsonl_reset):
        return sqlite_pct, sqlite_reset
    if jsonl_ts > sqlite_ts:
        return jsonl_pct, jsonl_reset
    return sqlite_pct, sqlite_reset


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
        with sqlite3.connect(f"file:{LOGS_DB}?mode=ro", uri=True) as conn:
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
        with sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True) as conn:
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
        with sqlite3.connect(f"file:{LOGS_DB}?mode=ro", uri=True) as conn:
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
    output_tokens = _as_int(_event_value(body, "output_token_count")) + _as_int(
        _event_value(body, "reasoning_token_count")
    )
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
    paths = _recent_jsonl_files_from_date_dirs()
    if paths is None:
        paths = list(SESSIONS_DIR.rglob("*.jsonl"))
    return _sort_recent_jsonl_files(paths)


# This relies on Codex writing sessions under their creation date. A long session
# from an older day that is still appended can differ from a full rglob if newer
# date dirs already contain the scan limit; full elimination would require the
# expensive all-tree scan this path avoids.
def _recent_jsonl_files_from_date_dirs() -> list[Path] | None:
    paths: list[Path] = []
    years = _sorted_date_dirs(SESSIONS_DIR, 4)
    if years is None:
        return None
    for year in years:
        months = _sorted_date_dirs(Path(year.path), 2)
        if months is None:
            return None
        for month in months:
            days = _sorted_date_dirs(Path(month.path), 2)
            if days is None:
                return None
            for day in days:
                day_paths = _jsonl_files_in_day_dir(Path(day.path))
                if day_paths is None:
                    return None
                paths.extend(day_paths)
                if len(paths) >= _RECENT_JSONL_SCAN_LIMIT:
                    return paths
    return paths


def _sorted_date_dirs(parent: Path, name_length: int) -> list[os.DirEntry[str]] | None:
    dirs: list[os.DirEntry[str]] = []
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if not entry.is_dir():
                        return None
                except OSError:
                    return None
                if len(entry.name) != name_length or not entry.name.isdigit():
                    return None
                dirs.append(entry)
    except OSError:
        return None
    dirs.sort(key=lambda entry: entry.name, reverse=True)
    return dirs


def _jsonl_files_in_day_dir(day_dir: Path) -> list[Path] | None:
    paths: list[Path] = []
    try:
        with os.scandir(day_dir) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        return None
                    if entry.is_file() and entry.name.endswith(".jsonl"):
                        paths.append(Path(entry.path))
                except OSError:
                    return None
    except OSError:
        return None
    return paths


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
    last_rate_limits: tuple[dict[str, Any], str] | None = None
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                data = _load_json_line(line)
                if data is None:
                    continue
                if data.get("type") == "session_meta":
                    session_id = _as_str(_as_dict(data.get("payload")).get("id"))
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
    seven_pct = _as_optional_float(secondary.get("used_percent"))
    seven_reset = _as_optional_float(secondary.get("resets_at"))
    now_ts = datetime.now(UTC).timestamp()
    if five_reset is not None and five_reset < now_ts:
        five_pct = None
        five_reset = None
    if seven_reset is not None and seven_reset < now_ts:
        seven_pct = None
        seven_reset = None
    if five_pct is None and seven_pct is None:
        return None
    return CodexRateLimits(
        five_hour_pct=five_pct,
        five_hour_resets_at=five_reset,
        seven_day_pct=seven_pct,
        seven_day_resets_at=seven_reset,
        model=models.get(session_id, "unknown"),
        updated_at=updated_at,
    )


def _parse_jsonl(path: Path, models: dict[str, str], cutoff: datetime | None) -> list[UsageEntry]:
    try:
        st = path.stat()
    except OSError as exc:
        logger.warning("failed to parse codex session %s: %s", path, exc)
        return []

    cache_entry = _jsonl_cache.get(path)
    if cache_entry is not None and cache_entry[0] == st.st_mtime and cache_entry[1] == st.st_size:
        _jsonl_cache.move_to_end(path)
        cached_entries = cache_entry[2]
        for entry in cached_entries:
            entry.model = models.get(entry.session_id, "unknown")
        if cutoff is None:
            return cached_entries
        return [entry for entry in cached_entries if entry.timestamp >= cutoff]

    session_id = ""
    session_timestamp = ""
    project = "unknown"
    entries: list[UsageEntry] = []
    previous_usage: _TokenUsage | None = None
    token_count_index = 0
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                data = _load_json_line(line)
                if data is None:
                    continue
                if data.get("type") == "session_meta":
                    payload = _as_dict(data.get("payload"))
                    session_id = _as_str(payload.get("id"))
                    session_timestamp = _as_str(payload.get("timestamp"))
                    project = _project_from_cwd(_as_str(payload.get("cwd")))
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
                        model=models.get(session_id, "unknown"),
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
        _jsonl_cache[path] = (st.st_mtime, st.st_size, [])
        return []
    if not entries and session_timestamp:
        if path not in _jsonl_cache and len(_jsonl_cache) >= _JSONL_CACHE_MAXSIZE:
            _jsonl_cache.popitem(last=False)
        _jsonl_cache[path] = (st.st_mtime, st.st_size, [])
        return []
    if path not in _jsonl_cache and len(_jsonl_cache) >= _JSONL_CACHE_MAXSIZE:
        _jsonl_cache.popitem(last=False)
    _jsonl_cache[path] = (st.st_mtime, st.st_size, entries)
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
    output_tokens = _as_int(usage.get("output_tokens")) + _as_int(
        usage.get("reasoning_output_tokens"),
    )
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
