# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Periodically preserve real usage without scanning on the app thread."""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from adapters.registry import detect_agents
from analyzer import diagnosis_snapshot, reporter, usage_snapshot
from usage_common.time_utils import parse_optional_iso8601_utc

STATE_PATH = Path.home() / ".usage" / "history_persist_state.json"
_INTERVAL = timedelta(hours=6)
_LOOKBACK_DAYS = 45
_lock = threading.Lock()
_refresh_in_flight = False
_timer: threading.Timer | None = None
logger = logging.getLogger(__name__)


def _remaining(now: datetime) -> float:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        last = (
            parse_optional_iso8601_utc(state.get("last_success"))
            if isinstance(state, dict)
            else None
        )
    except (OSError, ValueError):
        last = None
    return max(0.0, (_INTERVAL - (now - last)).total_seconds()) if last else 0.0


def _schedule_next_locked(delay: float) -> None:
    global _timer
    if _timer is None:
        _timer = threading.Timer(delay, _on_timer)
        _timer.daemon = True
        try:
            _timer.start()
        except Exception:
            _timer = None
            raise


def _on_timer() -> None:
    global _timer
    with _lock:
        _timer = None
    maybe_schedule_refresh()


def maybe_schedule_refresh() -> None:
    global _refresh_in_flight, _timer
    try:
        with _lock:
            if _refresh_in_flight:
                return
            remaining = _remaining(datetime.now(UTC))
            if remaining > 0:
                _schedule_next_locked(remaining)
                return
            if _timer is not None:
                _timer.cancel()
                _timer = None
            _refresh_in_flight = True
        threading.Thread(target=_refresh_in_background, daemon=True).start()
    except Exception:
        with _lock:
            _refresh_in_flight = False
        logger.warning("Failed to schedule usage history persistence", exc_info=True)


def _refresh_in_background() -> None:
    global _refresh_in_flight
    try:
        refresh_history()
    except Exception:
        logger.warning("Failed to persist usage history", exc_info=True)
    finally:
        with _lock:
            _refresh_in_flight = False
            try:
                _schedule_next_locked(_INTERVAL.total_seconds())
            except Exception:
                logger.warning("Failed to reschedule usage history persistence", exc_info=True)


def refresh_history(now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    if _remaining(current) > 0:
        return False
    today = current.astimezone().date()
    entries = reporter.load_history_entries(
        detect_agents(), today - timedelta(days=_LOOKBACK_DAYS - 1), today
    )
    snapshot = usage_snapshot.record_entries(entries)
    ledger = reporter.persist_year_entries(entries, today)
    # Existing writers swallow I/O errors. Read back before marking success.
    for path, expected in (
        (usage_snapshot.SNAPSHOT_PATH, snapshot),
        (reporter.YEAR_LEDGER_PATH, ledger),
    ):
        if json.loads(path.read_text(encoding="utf-8")) != expected:
            raise OSError(f"Usage history write verification failed: {path}")
    diagnosis_snapshot._atomic_write_json(STATE_PATH, {"last_success": current.isoformat()})
    return True
