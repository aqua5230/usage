# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

import json
import math
import os
import sqlite3
import sys
from collections import OrderedDict, defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import codex_loader as shared_codex_loader

from .types import AgentInfo, RateLimits, UsageEntry

CODEX_DIR = os.path.expanduser("~/.codex")
SESSIONS_DIR = os.path.join(CODEX_DIR, "sessions")
STATE_DB = os.path.join(CODEX_DIR, "state_5.sqlite")
_FILE_CACHE_MAXSIZE = 512
_file_cache: OrderedDict[Path, tuple[float, int, list[dict[str, Any]]]] = OrderedDict()


def _readonly_sqlite_uri(path: str | Path) -> str:
    return f"{Path(path).resolve().as_uri()}?mode=ro"


def detect() -> AgentInfo | None:
    if Path(SESSIONS_DIR).is_dir():
        return AgentInfo(
            id="codex",
            name="Codex",
            data_dir=SESSIONS_DIR,
            installed=True,
        )
    return None


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    cutoff = None
    if hours_back > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    models = _load_thread_models()
    sessions_path = Path(SESSIONS_DIR)
    delta_entries = shared_codex_loader._load_jsonl_entries(sessions_path, models, cutoff)
    by_session: dict[str, list[Any]] = defaultdict(list)
    for entry in delta_entries:
        by_session[entry.session_id].append(entry)

    entries = [_aggregate_session(session_entries) for session_entries in by_session.values()]
    entries.sort(key=lambda e: e.timestamp)
    return entries


def _aggregate_session(session_entries: list[Any]) -> UsageEntry:
    first = session_entries[0]
    primary = max(session_entries, key=lambda entry: entry.total_tokens)
    return UsageEntry(
        timestamp=first.timestamp,
        session_id=first.session_id,
        message_id=first.session_id,
        request_id="",
        model=primary.model,
        input_tokens=sum(entry.input_tokens for entry in session_entries),
        output_tokens=sum(entry.output_tokens for entry in session_entries),
        cache_creation_tokens=sum(entry.cache_creation_tokens for entry in session_entries),
        cache_read_tokens=sum(entry.cache_read_tokens for entry in session_entries),
        cost_usd=None,
        project=first.project,
        agent_id="codex",
        message_count=len(session_entries),
    )


def _load_thread_models() -> dict[str, str]:
    if not os.path.exists(STATE_DB):
        return {}
    try:
        with closing(sqlite3.connect(_readonly_sqlite_uri(STATE_DB), uri=True)) as conn:
            rows = conn.execute("SELECT id, model FROM threads WHERE model IS NOT NULL").fetchall()
        return {row[0]: row[1] for row in rows}
    except (sqlite3.Error, OSError) as exc:
        _debug_file_error("failed to load Codex thread models from", Path(STATE_DB), exc)
        return {}


def _extract_rate_limits(path: Path, models: dict[str, str]) -> RateLimits | None:
    session_id = ""
    session_model = "unknown"
    last_rl = None
    try:
        rows = _load_jsonl_rows(path)
    except (OSError, PermissionError, UnicodeDecodeError) as exc:
        _debug_file_error("failed to read Codex session log", path, exc)
        return None

    for data in rows:
        if data.get("type") == "session_meta":
            payload = data.get("payload", {})
            session_id = payload.get("id", "")
            session_model = _session_model(payload, session_model)
        if data.get("type") == "turn_context":
            session_model = _session_model(data.get("payload"), session_model)
        if data.get("type") != "event_msg":
            continue
        payload = data.get("payload", {})
        if payload.get("type") != "token_count":
            continue
        rl = payload.get("rate_limits")
        if rl:
            last_rl = (rl, data.get("timestamp", ""), session_id)

    if not last_rl:
        return None

    rl, ts, sid = last_rl
    primary = rl.get("primary") or {}
    secondary = rl.get("secondary") or {}

    five_pct = _as_optional_float(primary.get("used_percent"))
    five_reset = _as_optional_int(primary.get("resets_at"))
    seven_pct = _as_optional_float(secondary.get("used_percent"))
    seven_reset = _as_optional_int(secondary.get("resets_at"))

    now_ts = datetime.now(timezone.utc).timestamp()
    if five_reset is not None and five_reset < now_ts:
        five_pct = 0.0
        five_reset = None
    if seven_reset is not None and seven_reset < now_ts:
        seven_pct = 0.0
        seven_reset = None

    if five_pct is None and seven_pct is None:
        return None

    model_name = models.get(sid, "")

    return RateLimits(
        five_hour_pct=five_pct,
        five_hour_resets_at=five_reset,
        seven_day_pct=seven_pct,
        seven_day_resets_at=seven_reset,
        model=model_name or session_model,
        updated_at=ts,
    )


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    st = path.stat()
    cached = _file_cache.get(path)
    if cached is not None and cached[0] == st.st_mtime and cached[1] == st.st_size:
        _file_cache.move_to_end(path)
        return cached[2]

    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(data)

    if path not in _file_cache and len(_file_cache) >= _FILE_CACHE_MAXSIZE:
        _file_cache.popitem(last=False)
    _file_cache[path] = (st.st_mtime, st.st_size, rows)
    return rows


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


def _session_model(payload: Any, fallback: str) -> str:
    model = payload.get("model") if isinstance(payload, dict) else ""
    if not isinstance(model, str):
        model = ""
    return model or fallback


def _as_optional_int(value: Any) -> int | None:
    number = _as_optional_float(value)
    if number is None:
        return None
    return int(number)


def _debug_file_error(action: str, path: Path, exc: Exception) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        print(f"{action} {path}: {exc}", file=sys.stderr)
