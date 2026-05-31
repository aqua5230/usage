import json
import math
import os
import sqlite3
import sys
from collections import OrderedDict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .types import AgentInfo, RateLimits, UsageEntry

CODEX_DIR = os.path.expanduser("~/.codex")
SESSIONS_DIR = os.path.join(CODEX_DIR, "sessions")
STATE_DB = os.path.join(CODEX_DIR, "state_5.sqlite")
_FILE_CACHE_MAXSIZE = 512
_file_cache: OrderedDict[Path, tuple[float, int, list[dict[str, Any]]]] = OrderedDict()


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
    entries: list[UsageEntry] = []
    seen: set[str] = set()
    cutoff = None
    if hours_back > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    models = _load_thread_models()

    sessions_path = Path(SESSIONS_DIR)
    if not sessions_path.is_dir():
        return entries

    for jsonl_path in sessions_path.rglob("*.jsonl"):
        _parse_jsonl(jsonl_path, models, entries, seen, cutoff)

    entries.sort(key=lambda e: e.timestamp)
    return entries


def _load_thread_models() -> dict[str, str]:
    if not os.path.exists(STATE_DB):
        return {}
    try:
        with closing(sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)) as conn:
            rows = conn.execute("SELECT id, model FROM threads WHERE model IS NOT NULL").fetchall()
        return {row[0]: row[1] for row in rows}
    except (sqlite3.Error, OSError) as exc:
        _debug_file_error("failed to load Codex thread models from", Path(STATE_DB), exc)
        return {}


def load_rate_limits() -> RateLimits | None:
    sessions_path = Path(SESSIONS_DIR)
    if not sessions_path.is_dir():
        return None

    jsonl_files = sorted(sessions_path.rglob("*.jsonl"), key=_safe_mtime, reverse=True)
    models = _load_thread_models()

    for path in jsonl_files[:5]:
        rl = _extract_rate_limits(path, models)
        if rl:
            return rl
    return None


def _extract_rate_limits(path: Path, models: dict[str, str]) -> RateLimits | None:
    session_id = ""
    last_rl = None
    try:
        rows = _load_jsonl_rows(path)
    except (OSError, PermissionError, UnicodeDecodeError) as exc:
        _debug_file_error("failed to read Codex session log", path, exc)
        return None

    for data in rows:
        if data.get("type") == "session_meta":
            session_id = data.get("payload", {}).get("id", "")
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
        five_pct = None
        five_reset = None
    if seven_reset is not None and seven_reset < now_ts:
        seven_pct = None
        seven_reset = None

    if five_pct is None and seven_pct is None:
        return None

    model_name = models.get(sid, "")

    return RateLimits(
        five_hour_pct=five_pct,
        five_hour_resets_at=five_reset,
        seven_day_pct=seven_pct,
        seven_day_resets_at=seven_reset,
        model=model_name,
        updated_at=ts,
    )


def _project_from_cwd(cwd: str) -> str:
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        rel = cwd[len(home):].strip(os.sep)
    else:
        rel = cwd.strip(os.sep)
    parts = rel.split(os.sep)
    return parts[-1] if parts and parts[-1] else rel or "unknown"


def _parse_jsonl(
    path: Path,
    models: dict[str, str],
    entries: list[UsageEntry],
    seen: set[str],
    cutoff: datetime | None,
) -> None:
    session_id = ""
    session_ts = ""
    project = "unknown"
    model = "unknown"
    last_usage = None
    msg_count = 0

    try:
        rows = _load_jsonl_rows(path)
    except (OSError, PermissionError, UnicodeDecodeError) as exc:
        _debug_file_error("failed to read Codex session log", path, exc)
        return

    for data in rows:
        row_type = data.get("type")

        if row_type == "session_meta":
            payload = data.get("payload", {})
            session_id = payload.get("id", "")
            session_ts = payload.get("timestamp", "")
            cwd = payload.get("cwd", "")
            if cwd:
                project = _project_from_cwd(cwd)
            model = models.get(session_id, "unknown")
            continue

        if row_type != "event_msg":
            continue

        payload = data.get("payload", {})
        if payload.get("type") == "token_count":
            info = payload.get("info")
            if info and info.get("total_token_usage"):
                last_usage = info["total_token_usage"]
                msg_count += 1

    if not last_usage or not session_id:
        return

    cached = _as_int(last_usage.get("cached_input_tokens"))
    input_tokens = _as_int(last_usage.get("input_tokens")) - cached
    output_tokens = _as_int(last_usage.get("output_tokens")) + _as_int(
        last_usage.get("reasoning_output_tokens")
    )

    if input_tokens == 0 and output_tokens == 0:
        return

    try:
        ts = datetime.fromisoformat(session_ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return

    if cutoff and ts < cutoff:
        return

    if session_id in seen:
        return
    seen.add(session_id)

    entries.append(UsageEntry(
        timestamp=ts,
        session_id=session_id,
        message_id=session_id,
        request_id="",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=0,
        cache_read_tokens=cached,
        cost_usd=None,
        project=project,
        agent_id="codex",
        message_count=msg_count,
    ))


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


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return float("-inf")


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


def _as_int(value: Any) -> int:
    number = _as_optional_float(value)
    if number is None:
        return 0
    return int(number)


def _as_optional_int(value: Any) -> int | None:
    number = _as_optional_float(value)
    if number is None:
        return None
    return int(number)


def _debug_file_error(action: str, path: Path, exc: Exception) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        print(f"{action} {path}: {exc}", file=sys.stderr)
