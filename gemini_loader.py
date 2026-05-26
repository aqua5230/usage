from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from history_loader import UsageEntry

logger = logging.getLogger(__name__)

# Cache parsed files by (mtime, size) to avoid re-parsing on every refresh
_jsonl_cache: dict[Path, tuple[float, int, list[UsageEntry]]] = {}

BRAIN_DIR = Path(os.path.expanduser("~/.gemini/antigravity-cli/brain"))

# Gemini 1.5 Pro Pricing
INPUT_COST_PER_M = 1.25
OUTPUT_COST_PER_M = 5.00


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk_count = 0
    non_cjk_count = 0
    for char in text:
        # Detect CJK (Chinese, Japanese, Korean) ranges
        if (
            "\u4e00" <= char <= "\u9fff"
            or "\u3040" <= char <= "\u30ff"
            or "\u1100" <= char <= "\u11ff"
            or "\u3130" <= char <= "\u318f"
            or "\uac00" <= char <= "\ud7af"
            or "\uff00" <= char <= "\uffee"
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
    accumulated_context = ""
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

                # If it's user input, we accumulate it into the context
                if source == "USER_EXPLICIT" and step_type == "USER_INPUT":
                    accumulated_context += f"\nUser: {content}"
                    continue

                # If it's a planner response (model completion call)
                if source == "MODEL" and step_type == "PLANNER_RESPONSE":
                    thinking = data.get("thinking", "")
                    # Model response text consists of thinking block + actual tool calls
                    # or response content
                    output_text = f"Thinking:\n{thinking}\nResponse:\n{content}"

                    input_tokens = estimate_tokens(accumulated_context)
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

                    # Accumulate only the content (and not the thinking block)
                    # for next turns' input context
                    accumulated_context += f"\nAssistant: {content}"
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
