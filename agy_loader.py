# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Read Antigravity CLI generation usage from its local SQLite conversations."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

AGY_SESSIONS_DIR = Path(os.path.expanduser("~/.gemini/antigravity-cli/conversations"))


@dataclass(frozen=True, slots=True)
class AgyUsageEntry:
    """One deduplicated Antigravity CLI generation."""

    timestamp: datetime
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    thinking_tokens: int
    dedup_key: str
    session_id: str


@dataclass(frozen=True, slots=True)
class AgyLoadResult:
    """Loaded entries plus rows omitted because they lacked a deduplication key."""

    entries: list[AgyUsageEntry]
    skipped_missing_dedup_key: int


def load_entries(hours_back: int = 0) -> list[AgyUsageEntry]:
    """Load deduplicated entries from the last ``hours_back`` hours.

    A zero value means all available history. Files being written by Antigravity
    are skipped rather than interrupting the caller's refresh cycle.
    """
    return load_entries_with_stats(hours_back).entries


def load_entries_with_stats(hours_back: int = 0) -> AgyLoadResult:
    """Load entries and report how many usage rows lacked a deduplication key."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None
    if not AGY_SESSIONS_DIR.is_dir():
        return AgyLoadResult(entries=[], skipped_missing_dedup_key=0)

    entries: list[AgyUsageEntry] = []
    seen_dedup_keys: set[str] = set()
    skipped_missing_dedup_key = 0
    for path in AGY_SESSIONS_DIR.glob("*.db"):
        file_entries, skipped = _load_database(path, cutoff, seen_dedup_keys)
        entries.extend(file_entries)
        skipped_missing_dedup_key += skipped

    entries.sort(key=lambda entry: entry.timestamp)
    return AgyLoadResult(
        entries=entries,
        skipped_missing_dedup_key=skipped_missing_dedup_key,
    )


def recent_input_output_tokens(hours_back: int) -> int:
    """Return recent input plus output tokens, excluding cache-read and thinking."""
    return sum(
        entry.input_tokens + entry.output_tokens for entry in load_entries(hours_back)
    )


def _load_database(
    path: Path,
    cutoff: datetime | None,
    seen_dedup_keys: set[str],
) -> tuple[list[AgyUsageEntry], int]:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            session_timestamp = _session_timestamp(connection, path)
            rows = connection.execute("SELECT data FROM gen_metadata ORDER BY idx")
            entries: list[AgyUsageEntry] = []
            skipped_missing_dedup_key = 0
            for (blob,) in rows:
                if not isinstance(blob, bytes):
                    continue
                entry, missing_dedup_key = _parse_generation(
                    blob,
                    path.stem,
                    session_timestamp,
                    seen_dedup_keys,
                )
                skipped_missing_dedup_key += missing_dedup_key
                if entry is not None and (cutoff is None or entry.timestamp >= cutoff):
                    entries.append(entry)
            return entries, skipped_missing_dedup_key
    except sqlite3.Error as exc:
        logger.debug("skipping Antigravity database %s: %s", path, exc)
        return [], 0


def _session_timestamp(connection: sqlite3.Connection, path: Path) -> datetime:
    try:
        row = connection.execute(
            "SELECT data FROM trajectory_metadata_blob LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row is not None and isinstance(row[0], bytes):
        timestamp = _timestamp(_message_field(row[0], 2))
        if timestamp is not None:
            return timestamp
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return datetime.fromtimestamp(0, UTC)


def _parse_generation(
    blob: bytes,
    session_id: str,
    session_timestamp: datetime,
    seen_dedup_keys: set[str],
) -> tuple[AgyUsageEntry | None, int]:
    chat_model = _message_field(blob, 1)
    if chat_model is None:
        return None, 0
    usage = _message_field(chat_model, 4)
    if usage is None:
        return None, 0

    system_tokens = _varint_field(usage, 1) or 0
    new_input_tokens = _varint_field(usage, 2) or 0
    cache_read_tokens = _varint_field(usage, 5) or 0
    output_tokens = _varint_field(usage, 9) or 0
    thinking_tokens = _varint_field(usage, 10) or 0
    token_counts = (
        system_tokens,
        new_input_tokens,
        cache_read_tokens,
        output_tokens,
        thinking_tokens,
    )
    if not any(token_counts):
        return None, 0

    dedup_key = _string_field(usage, 11)
    if dedup_key is None or not dedup_key.strip():
        return None, 1
    if dedup_key in seen_dedup_keys:
        return None, 0
    seen_dedup_keys.add(dedup_key)

    timestamp = _timestamp(_message_field(_message_field(chat_model, 9) or b"", 4))
    model = _string_field(chat_model, 19) or "unknown"
    return (
        AgyUsageEntry(
            timestamp=timestamp or session_timestamp,
            model=model,
            input_tokens=system_tokens + new_input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            thinking_tokens=thinking_tokens,
            dedup_key=dedup_key,
            session_id=session_id,
        ),
        0,
    )


def _timestamp(blob: bytes | None) -> datetime | None:
    if blob is None:
        return None
    seconds = _varint_field(blob, 1)
    nanos = _varint_field(blob, 2) or 0
    if seconds is None or not 0 <= nanos <= 999_999_999:
        return None
    try:
        return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _message_field(blob: bytes, target_field: int) -> bytes | None:
    for field, wire_type, value in _fields(blob):
        if field == target_field and wire_type == 2 and isinstance(value, bytes):
            return value
    return None


def _varint_field(blob: bytes, target_field: int) -> int | None:
    for field, wire_type, value in _fields(blob):
        if field == target_field and wire_type == 0 and isinstance(value, int):
            return value
    return None


def _string_field(blob: bytes, target_field: int) -> str | None:
    value = _message_field(blob, target_field)
    if value is None:
        return None
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _fields(blob: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    position = 0
    while position < len(blob):
        tag_and_position = _read_varint(blob, position)
        if tag_and_position is None:
            return
        tag, position = tag_and_position
        field = tag >> 3
        wire_type = tag & 7
        if field == 0:
            return
        if wire_type == 0:
            value_and_position = _read_varint(blob, position)
            if value_and_position is None:
                return
            value, position = value_and_position
            yield field, wire_type, value
        elif wire_type == 1:
            position += 8
            if position > len(blob):
                return
        elif wire_type == 2:
            length_and_position = _read_varint(blob, position)
            if length_and_position is None:
                return
            length, position = length_and_position
            end = position + length
            if end > len(blob):
                return
            yield field, wire_type, blob[position:end]
            position = end
        elif wire_type == 5:
            position += 4
            if position > len(blob):
                return
        else:
            return


def _read_varint(blob: bytes, position: int) -> tuple[int, int] | None:
    value = 0
    for shift in range(0, 70, 7):
        if position >= len(blob):
            return None
        byte = blob[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, position
    return None
