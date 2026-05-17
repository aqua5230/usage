from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))


@dataclass(slots=True)
class UsageEntry:
    timestamp: datetime
    session_id: str
    message_id: str
    request_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float | None
    project: str

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    entries: list[UsageEntry] = []
    seen: set[str] = set()
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None

    if not CLAUDE_PROJECTS_DIR.is_dir():
        return []

    cutoff_ts = cutoff.timestamp() if cutoff else None
    for jsonl_path in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        if cutoff_ts is not None:
            try:
                if jsonl_path.stat().st_mtime < cutoff_ts:
                    continue
            except OSError as exc:
                logger.warning("failed to stat Claude project log %s: %s", jsonl_path, exc)
                continue
        project = _project_from_path(jsonl_path)
        _load_file(jsonl_path, project, cutoff, seen, entries)

    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _load_file(
    path: Path,
    project: str,
    cutoff: datetime | None,
    seen: set[str],
    entries: list[UsageEntry],
) -> None:
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                entry = _parse_line(line, project)
                if entry is None:
                    continue
                if cutoff is not None and entry.timestamp < cutoff:
                    continue

                dedup_key = f"{entry.message_id}:{entry.request_id}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                entries.append(entry)
    except OSError as exc:
        logger.warning("failed to read Claude project log %s: %s", path, exc)
        return


def _parse_line(line: str, project: str) -> UsageEntry | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict) or data.get("type") != "assistant":
        return None

    message = data.get("message")
    if not isinstance(message, dict):
        return None

    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    timestamp = _parse_timestamp(data.get("timestamp"))
    if timestamp is None:
        return None

    input_tokens = _as_int(usage.get("input_tokens"))
    output_tokens = _as_int(usage.get("output_tokens"))
    cache_creation_tokens = _as_int(usage.get("cache_creation_input_tokens"))
    cache_read_tokens = _as_int(usage.get("cache_read_input_tokens"))
    if input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens == 0:
        return None

    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd:
        project = _project_from_cwd(cwd)

    return UsageEntry(
        timestamp=timestamp,
        session_id=_as_str(data.get("sessionId")),
        message_id=_as_str(message.get("id")),
        request_id=_as_str(data.get("requestId")),
        model=_as_str(message.get("model")) or "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        cost_usd=_as_optional_float(data.get("costUSD")),
        project=project,
    )


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


def _project_from_path(jsonl_path: Path) -> str:
    try:
        project_dir = jsonl_path.relative_to(CLAUDE_PROJECTS_DIR).parts[0]
    except (IndexError, ValueError):
        return "unknown"
    decoded = project_dir.replace("-", os.sep).strip(os.sep)
    return Path(decoded).name or "unknown"


def _project_from_cwd(cwd: str) -> str:
    return Path(os.path.expanduser(cwd)).name or "unknown"


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_optional_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
