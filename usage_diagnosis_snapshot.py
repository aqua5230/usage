#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from analyzer import diagnoser, reporter
from time_utils import parse_optional_iso8601_utc

SNAPSHOT_PATH = Path(os.path.expanduser("~/.claude/usage-diagnosis.json"))
_LOOKBACK_DAYS = 7
_STALE_AFTER = timedelta(hours=24)
_lock = threading.Lock()
_refresh_in_flight = False


def maybe_schedule_refresh() -> None:
    if not _needs_refresh(_read_snapshot(), now=datetime.now(UTC)):
        return

    global _refresh_in_flight
    with _lock:
        if _refresh_in_flight:
            return
        _refresh_in_flight = True

    thread = threading.Thread(target=_refresh_in_background, daemon=True)
    thread.start()


def _refresh_in_background() -> None:
    global _refresh_in_flight
    try:
        refresh_snapshot()
    finally:
        with _lock:
            _refresh_in_flight = False


def refresh_snapshot(now: datetime | None = None) -> bool:
    current_time = now or datetime.now(UTC)
    existing = _read_snapshot()
    if not _needs_refresh(existing, now=current_time):
        return False

    date_to = current_time.date()
    date_from = date_to - timedelta(days=_LOOKBACK_DAYS - 1)
    tool_calls, sessions = diagnoser._load_records(date_from, date_to)
    diagnosis = diagnoser.analyze_loaded_records(
        date_from=date_from,
        date_to=date_to,
        total_cost_usd=0.0,
        tool_calls=tool_calls,
        entries=None,
        sessions=sessions,
    )
    total_corpus_tokens = sum(session.total_tokens for session in sessions)
    payload = reporter.serialize_diagnosis(
        diagnosis,
        total_corpus_tokens=total_corpus_tokens,
    )
    payload["generated_at"] = _format_timestamp(current_time)
    payload["findings_fingerprint"] = _findings_fingerprint(payload.get("findings"))
    _atomic_write_json(SNAPSHOT_PATH, payload)
    return True


def _needs_refresh(snapshot: dict[str, Any] | None, *, now: datetime) -> bool:
    if snapshot is None:
        return True
    generated_at = _parse_timestamp(snapshot.get("generated_at"))
    if generated_at is None:
        return True
    return now - generated_at >= _STALE_AFTER


def _findings_fingerprint(findings: object) -> str:
    if not isinstance(findings, list):
        return ""

    parts: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        kind = finding.get("kind")
        items = finding.get("items")
        if not isinstance(kind, str):
            continue
        item_hash = ""
        if isinstance(items, list) and items:
            first_item = items[0]
            encoded = json.dumps(
                first_item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            item_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]
        parts.append(f"{kind}:{item_hash}")
    parts.sort()
    return "|".join(parts)


def _read_snapshot() -> dict[str, Any] | None:
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _parse_timestamp(value: object) -> datetime | None:
    return parse_optional_iso8601_utc(value)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
