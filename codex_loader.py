from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from history_loader import UsageEntry
from project_resolver import resolve_project_name

logger = logging.getLogger(__name__)

_jsonl_cache: dict[Path, tuple[float, int, list[UsageEntry]]] = {}

SESSIONS_DIR = Path(os.path.expanduser("~/.codex/sessions"))
STATE_DB = Path(os.path.expanduser("~/.codex/state_5.sqlite"))


@dataclass(slots=True)
class CodexRateLimits:
    five_hour_pct: float | None
    five_hour_resets_at: float | None
    seven_day_pct: float | None
    seven_day_resets_at: float | None
    model: str | None = "unknown"
    updated_at: str = ""


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    if not SESSIONS_DIR.is_dir():
        return []

    entries_by_session: dict[str, list[UsageEntry]] = {}
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None
    cutoff_ts = cutoff.timestamp() if cutoff else None
    models = _load_thread_models()

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

    entries = [
        entry
        for session_entries in entries_by_session.values()
        for entry in session_entries
    ]
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
    if not SESSIONS_DIR.is_dir():
        return None
    models = _load_thread_models()
    for path in _recent_jsonl_files():
        rate_limits = _extract_rate_limits(path, models)
        if rate_limits is not None:
            return rate_limits
    return None


def _load_thread_models() -> dict[str, str]:
    if not STATE_DB.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT id, model FROM threads WHERE model IS NOT NULL",
            ).fetchall()
    except (OSError, sqlite3.Error):
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("codex thread models load failed", exc_info=True)
        return {}
    return {
        thread_id: model
        for thread_id, model in rows
        if isinstance(thread_id, str) and isinstance(model, str) and model
    }


def _recent_jsonl_files() -> list[Path]:
    paths_with_mtime: list[tuple[float, Path]] = []
    for path in SESSIONS_DIR.rglob("*.jsonl"):
        try:
            paths_with_mtime.append((path.stat().st_mtime, path))
        except OSError as exc:
            logger.warning("failed to stat codex session %s: %s", path, exc)
    paths_with_mtime.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in paths_with_mtime[:5]]


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
    except OSError as exc:
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
        five_pct = 0.0
    if seven_reset is not None and seven_reset < now_ts:
        seven_pct = 0.0
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
    except OSError as exc:
        logger.warning("failed to parse codex session %s: %s", path, exc)
        _jsonl_cache[path] = (st.st_mtime, st.st_size, [])
        return []
    if not entries and session_timestamp:
        _jsonl_cache[path] = (st.st_mtime, st.st_size, [])
        return []
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
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, int(value))


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
