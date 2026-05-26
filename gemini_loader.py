from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from history_loader import UsageEntry

logger = logging.getLogger(__name__)

# Cache parsed files by (mtime, size) to avoid re-parsing on every refresh
_jsonl_cache: dict[Path, tuple[float, int, list[UsageEntry]]] = {}

BRAIN_DIR = Path(os.path.expanduser("~/.gemini/antigravity-cli/brain"))
LOG_DIR = Path(os.path.expanduser("~/.gemini/antigravity-cli/log"))

# Gemini 1.5 Pro Pricing (reference only; Antigravity quota is "Work Done" based)
INPUT_COST_PER_M = 1.25
OUTPUT_COST_PER_M = 5.00

# Empirical API-call limit per 5h window; actual Antigravity quota is proprietary
# "Work Done" units and not publicly documented. Used only when log data is absent.
FIVE_HOUR_CALL_LIMIT = 360
SEVEN_DAY_CALL_LIMIT = 3600

# Regex: match RESOURCE_EXHAUSTED log lines that contain a "Resets in …" duration
_EXHAUSTED_PAT = re.compile(
    r"^[EW](\d{4})\s+(\d{2}:\d{2}:\d{2})\.\d+.*?RESOURCE_EXHAUSTED.*?Resets in ([\dhms ]+?)\.",
    re.MULTILINE,
)


@dataclass
class GeminiRateLimits:
    five_hour_exhausted: bool          # True when quota confirmed exhausted right now
    five_hour_resets_at: float | None  # unix timestamp of next 5h reset (if known)
    seven_day_exhausted: bool
    seven_day_resets_at: float | None
    window_start_ts: float | None      # unix timestamp when current window began


def _parse_resets_in(s: str) -> timedelta | None:
    """Parse '1h15m1s', '40m36s', '7s' etc. into a timedelta."""
    hm = re.search(r"(\d+)h", s)
    mm = re.search(r"(\d+)m", s)
    sm = re.search(r"(\d+)s", s)
    h = int(hm.group(1)) if hm else 0
    m = int(mm.group(1)) if mm else 0
    sec = int(sm.group(1)) if sm else 0
    if h == 0 and m == 0 and sec == 0:
        return None
    return timedelta(hours=h, minutes=m, seconds=sec)


def load_rate_limits() -> GeminiRateLimits | None:
    """
    Parse Antigravity CLI log files for RESOURCE_EXHAUSTED quota events.

    Returns the latest known quota state so the UI can show 100% when the
    quota is confirmed exhausted, and anchor the window start to the last
    reset so the estimate doesn't bleed across window boundaries.
    """
    if not LOG_DIR.is_dir():
        return None

    log_files = sorted(LOG_DIR.glob("cli-*.log"), reverse=True)[:5]
    if not log_files:
        return None

    best_error_dt: datetime | None = None
    best_reset_dt: datetime | None = None

    for log_file in log_files:
        # Filename: cli-20260526_141243.log  →  year = 2026
        try:
            file_year = int(log_file.name[4:8])
        except (ValueError, IndexError):
            continue
        try:
            text = log_file.read_text(errors="replace")
        except OSError:
            continue

        for mat in _EXHAUSTED_PAT.finditer(text):
            mmdd, time_str, resets_str = mat.groups()
            duration = _parse_resets_in(resets_str)
            if duration is None:
                continue
            try:
                error_dt = datetime.strptime(
                    f"{file_year}{mmdd} {time_str}", "%Y%m%d %H:%M:%S"
                ).replace(tzinfo=UTC)
            except ValueError:
                continue
            if best_error_dt is None or error_dt > best_error_dt:
                best_error_dt = error_dt
                best_reset_dt = error_dt + duration

    if best_error_dt is None or best_reset_dt is None:
        return None

    now = datetime.now(UTC)
    resets_duration = best_reset_dt - best_error_dt

    # Distinguish 5h sprint (resets < 6 h) from 7d weekly cap (resets > 12 h)
    if resets_duration > timedelta(hours=12):
        # Weekly cap exhausted
        if best_reset_dt > now:
            return GeminiRateLimits(
                five_hour_exhausted=False,
                five_hour_resets_at=None,
                seven_day_exhausted=True,
                seven_day_resets_at=best_reset_dt.timestamp(),
                window_start_ts=(best_reset_dt - timedelta(days=7)).timestamp(),
            )
        else:
            return GeminiRateLimits(
                five_hour_exhausted=False,
                five_hour_resets_at=None,
                seven_day_exhausted=False,
                seven_day_resets_at=best_reset_dt.timestamp(),
                window_start_ts=best_reset_dt.timestamp(),
            )

    # 5h sprint
    if best_reset_dt > now:
        # Currently exhausted
        return GeminiRateLimits(
            five_hour_exhausted=True,
            five_hour_resets_at=best_reset_dt.timestamp(),
            seven_day_exhausted=False,
            seven_day_resets_at=None,
            window_start_ts=(best_reset_dt - timedelta(hours=5)).timestamp(),
        )
    else:
        # Quota reset; new window started at reset time
        return GeminiRateLimits(
            five_hour_exhausted=False,
            five_hour_resets_at=best_reset_dt.timestamp(),
            seven_day_exhausted=False,
            seven_day_resets_at=None,
            window_start_ts=best_reset_dt.timestamp(),
        )


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk_count = 0
    non_cjk_count = 0
    for char in text:
        # Detect CJK (Chinese, Japanese, Korean) ranges
        if (
            "一" <= char <= "鿿"
            or "぀" <= char <= "ヿ"
            or "ᄀ" <= char <= "ᇿ"
            or "㄰" <= char <= "㆏"
            or "가" <= char <= "힯"
            or "＀" <= char <= "￮"
        ):
            cjk_count += 1
        else:
            non_cjk_count += 1
    # Heuristic: CJK characters are roughly 1.2 tokens each;
    # English/other characters are 0.25 (1/4) tokens each
    tokens = int(cjk_count * 1.2 + non_cjk_count * 0.25)
    return max(1, tokens)


def calculate_gemini_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * INPUT_COST_PER_M / 1_000_000.0) + (
        output_tokens * OUTPUT_COST_PER_M / 1_000_000.0
    )


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    if not BRAIN_DIR.is_dir():
        return []

    entries: list[UsageEntry] = []
    cutoff = (
        datetime.now(UTC) - timedelta(hours=hours_back)
        if hours_back > 0
        else None
    )
    cutoff_ts = cutoff.timestamp() if cutoff else None

    # Each folder in brain/ represents a conversation ID
    for conv_dir in BRAIN_DIR.iterdir():
        if not conv_dir.is_dir() or conv_dir.name.startswith("."):
            continue

        transcript_path = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript_path.exists():
            continue

        if cutoff_ts is not None:
            try:
                if transcript_path.stat().st_mtime < cutoff_ts:
                    continue
            except OSError as exc:
                logger.warning("failed to stat transcript log %s: %s", transcript_path, exc)
                continue

        parsed_entries = _parse_transcript(transcript_path, conv_dir.name, cutoff)
        entries.extend(parsed_entries)

    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _parse_transcript(path: Path, conv_id: str, cutoff: datetime | None) -> list[UsageEntry]:
    try:
        st = path.stat()
    except OSError as exc:
        logger.warning("failed to stat transcript %s: %s", path, exc)
        return []

    cache_entry = _jsonl_cache.get(path)
    if cache_entry is not None and cache_entry[0] == st.st_mtime and cache_entry[1] == st.st_size:
        return [e for e in cache_entry[2] if cutoff is None or e.timestamp >= cutoff]

    parsed: list[UsageEntry] = []
    # Track only the new content since the last model response — prevents
    # runaway accumulation in very long conversations. The transcript truncates
    # tool-output content anyway, so full-history re-charging per turn produces
    # wildly inflated estimates.
    turn_context = ""
    last_timestamp = None

    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(data, dict):
                    continue

                source = data.get("source")
                step_type = data.get("type")
                content = data.get("content", "")
                created_at = data.get("created_at") or data.get("timestamp")

                ts = _parse_timestamp(created_at)
                if ts:
                    last_timestamp = ts

                # 1. User input → new content for this turn
                if source == "USER_EXPLICIT" and step_type == "USER_INPUT":
                    turn_context += f"\nUser: {content}"
                    continue

                # 2. Tool output (source is MODEL but not PLANNER_RESPONSE)
                if source == "MODEL" and step_type != "PLANNER_RESPONSE":
                    turn_context += f"\nTool Output ({step_type}): {content}"
                    continue

                # 3. Assistant response (model completion call)
                if source == "MODEL" and step_type == "PLANNER_RESPONSE":
                    thinking = data.get("thinking", "")
                    tool_calls = data.get("tool_calls", [])
                    tc_str = json.dumps(tool_calls) if tool_calls else ""

                    input_tokens = estimate_tokens(turn_context)

                    output_text = f"Thinking:\n{thinking}\nResponse:\n{content}"
                    if tc_str:
                        output_text += f"\nTool Calls:\n{tc_str}"

                    output_tokens = estimate_tokens(output_text)
                    cost = calculate_gemini_cost(input_tokens, output_tokens)
                    timestamp = ts or last_timestamp or datetime.now(UTC)

                    entry = UsageEntry(
                        timestamp=timestamp,
                        session_id=conv_id,
                        message_id=f"{conv_id}:{data.get('step_index', 0)}",
                        request_id="",
                        model="gemini-1.5-pro",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_creation_tokens=0,
                        cache_read_tokens=0,
                        cost_usd=cost,
                        project="Antigravity (Gemini)",
                    )
                    parsed.append(entry)

                    # Reset for next turn
                    turn_context = ""
    except Exception as exc:
        logger.warning("failed to parse transcript %s: %s", path, exc)
        return []

    _jsonl_cache[path] = (st.st_mtime, st.st_size, parsed)
    return [e for e in parsed if cutoff is None or e.timestamp >= cutoff]


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
