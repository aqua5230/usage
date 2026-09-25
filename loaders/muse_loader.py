# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Read Muse Code per-call usage from local session journals."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loaders.history_loader import UsageEntry
from project_resolver import resolve_project_name

logger = logging.getLogger(__name__)
MUSE_SESSIONS_DIR = Path(os.path.expanduser("~/.local/share/muse/sessions"))


def session_paths() -> tuple[Path, ...]:
    try:
        return tuple(MUSE_SESSIONS_DIR.glob("*/*/*/*/session.jsonl"))
    except OSError:
        return ()


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    """Return each completed run and independent automated review once."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None
    entries: list[UsageEntry] = []
    seen: set[str] = set()
    for path in session_paths():
        try:
            entries.extend(_read_session(path, cutoff, seen))
        except OSError:
            logger.warning("failed to read Muse session %s", path, exc_info=True)
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _read_session(path: Path, cutoff: datetime | None, seen: set[str]) -> list[UsageEntry]:
    session_id = path.parent.name
    workspace = ""
    route_cwd = ""
    entries: list[UsageEntry] = []
    with path.open("rb") as journal:
        for line in journal:
            # Most lines include large prompts. Decode only records relevant to usage
            # or project attribution; wrapped children are decoded below if present.
            if not any(
                marker in line
                for marker in (
                    b"model_completed",
                    b"automated_review_completed",
                    b"runtime.session.metadata",
                    b"runtime.session.route_facts",
                )
            ):
                continue
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                continue
            if not isinstance(record, dict):
                continue
            records = [record]
            children = record.get("children")
            if isinstance(children, list):
                for child in children:
                    if not isinstance(child, dict) or not isinstance(child.get("record_json"), str):
                        continue
                    try:
                        nested = json.loads(child["record_json"])
                    except (json.JSONDecodeError, RecursionError):
                        continue
                    if isinstance(nested, dict):
                        records.append(nested)
            for item in records:
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                record_data = payload.get("record")
                if isinstance(record_data, dict):
                    if item.get("payload_type") == "runtime.session.metadata":
                        value = record_data.get("workspace_root")
                        if isinstance(value, str) and value:
                            workspace = value
                    elif item.get("payload_type") == "runtime.session.route_facts":
                        value = record_data.get("cwd")
                        if isinstance(value, str) and value:
                            route_cwd = value
                entry = _usage_entry(item, payload, session_id)
                if entry is None or entry.message_id in seen:
                    continue
                seen.add(entry.message_id)
                if cutoff is None or entry.timestamp >= cutoff:
                    entries.append(entry)
    project_path = workspace or route_cwd
    project = resolve_project_name(project_path) if project_path else ""
    for entry in entries:
        entry.project = project
    return entries


def _usage_entry(
    item: dict[str, Any], payload: dict[str, Any], session_id: str
) -> UsageEntry | None:
    if item.get("payload_type") != "runtime.session":
        return None
    event = payload.get("event")
    if not isinstance(event, dict):
        return None
    kind = event.get("kind")
    is_run = payload.get("kind") == "run" and kind == "model_completed"
    is_review = payload.get("kind") == "approval" and kind == "automated_review_completed"
    if not (is_run or is_review):
        return None
    record_id = item.get("id")
    micros = item.get("recorded_at")
    usage = event.get("usage")
    model = event.get("model")
    if is_review and isinstance(model, dict):
        model = model.get("model_id")
    if (
        not isinstance(record_id, str)
        or not record_id
        or isinstance(micros, bool)
        or not isinstance(micros, int)
        or not isinstance(usage, dict)
        or not isinstance(model, str)
        or not model
    ):
        return None
    try:
        seconds, microseconds = divmod(micros, 1_000_000)
        timestamp = datetime.fromtimestamp(seconds, UTC).replace(microsecond=microseconds)
    except (OverflowError, OSError, ValueError):
        return None
    input_tokens = _token_count(usage.get("input_tokens"))
    output_tokens = _token_count(usage.get("output_tokens"))
    cache_read = _token_count(
        usage.get(
            "cache_read_tokens", usage.get("cached_input_tokens", usage.get("cached_tokens", 0))
        )
    )
    cache_write = _token_count(usage.get("cache_write_tokens", 0))
    if input_tokens is None or output_tokens is None or cache_read is None or cache_write is None:
        return None
    if cache_read + cache_write > input_tokens:
        return None
    return UsageEntry(
        timestamp=timestamp,
        session_id=session_id,
        message_id=record_id,
        request_id=record_id,
        model=model,
        input_tokens=input_tokens - cache_read - cache_write,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_write,
        cache_read_tokens=cache_read,
        cost_usd=None,
        project="",
    )


def _token_count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
