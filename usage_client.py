from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from i18n import _t
from usage_lang import detect_lang

logger = logging.getLogger(__name__)

STATUS_FILE = os.path.expanduser("~/.claude/usage-status.json")
LEGACY_STATUS_FILE = os.path.expanduser("~/.claude/usag-status.json")
TT_STATUS_FILE = os.path.expanduser("~/.claude/tt-status.json")

# Stale files only affect hints; quota values still render.
STALE_SECONDS = 6 * 3600


class PollState(StrEnum):
    LOADING = "loading"
    SUCCESS = "success"
    TOKEN_ERROR = "token_error"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMITED = "rate_limited"
    FATAL = "fatal"


@dataclass(slots=True)
class UsageSnapshot:
    current_percent: int | None
    current_reset_at: float
    weekly_percent: int | None
    weekly_reset_at: float
    current_status: str
    polled_at: float
    is_stale: bool = False
    data_source: str = "hook"


@dataclass(slots=True)
class PollOutcome:
    state: PollState
    snapshot: UsageSnapshot | None = None
    message: str | None = None
    _mtime: float | None = None
    _status_path: str | None = None


def _pct(value: Any) -> int:
    numeric = _as_finite_float(value)
    if numeric is None:
        return 0
    return max(0, min(100, round(numeric)))


def _reset_at(value: Any, default: float) -> float:
    numeric = _as_finite_float(value)
    if numeric is None:
        return default
    return numeric


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _read_status_file() -> tuple[dict[str, Any], str, float] | None:
    """Read the first available status JSON, preferring usage-owned files."""
    for path in (STATUS_FILE, LEGACY_STATUS_FILE, TT_STATUS_FILE):
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("failed to read status file %s", path, exc_info=True)
            continue
        if isinstance(data, dict):
            return data, path, mtime
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("status file %s is not a JSON object", path)
    return None


def _status_file_stat() -> tuple[str, float] | None:
    for path in (STATUS_FILE, LEGACY_STATUS_FILE, TT_STATUS_FILE):
        try:
            return path, os.stat(path).st_mtime
        except OSError:
            continue
    return None


def _source_from_path(source_path: str) -> str:
    if source_path == TT_STATUS_FILE:
        return "tt-fallback"
    return "hook"


def _has_complete_rate_limits(data: dict[str, Any]) -> bool:
    rl = data.get("rate_limits")
    if not isinstance(rl, dict):
        return False
    five = rl.get("five_hour")
    seven = rl.get("seven_day")
    if not isinstance(five, dict) or not isinstance(seven, dict):
        return False
    return five.get("used_percentage") is not None and seven.get("used_percentage") is not None


def _build_snapshot(data: dict[str, Any], *, data_source: str = "hook") -> UsageSnapshot | None:
    rl = _as_dict(data.get("rate_limits"))
    five = _as_dict(rl.get("five_hour"))
    seven = _as_dict(rl.get("seven_day"))

    five_pct_raw = five.get("used_percentage")
    seven_pct_raw = seven.get("used_percentage")
    if five_pct_raw is None and seven_pct_raw is None:
        return None

    now = time.time()
    five_reset = _reset_at(five.get("resets_at"), now)
    seven_reset = _reset_at(seven.get("resets_at"), now)

    # Reset expired percentages to match Claude Code rate-limit semantics.
    five_pct = (
        0
        if five_reset and five_reset < now
        else _pct(five_pct_raw)
        if five_pct_raw is not None
        else None
    )
    seven_pct = (
        0
        if seven_reset and seven_reset < now
        else _pct(seven_pct_raw)
        if seven_pct_raw is not None
        else None
    )

    polled_at = _as_finite_float(data.get("_received_at_ts")) or now

    status = ""
    if isinstance(rl.get("status"), str):
        status = rl["status"]

    return UsageSnapshot(
        current_percent=five_pct,
        current_reset_at=five_reset,
        weekly_percent=seven_pct,
        weekly_reset_at=seven_reset,
        current_status=status,
        polled_at=polled_at,
        is_stale=(now - polled_at) > STALE_SECONDS,
        data_source=data_source,
    )


class ClaudeUsageClient:
    """Read quota state from the local JSON written by the Claude Code statusLine hook."""

    def __init__(self, *, interval_seconds: int = 60, mock: bool = False) -> None:
        self.interval_seconds = interval_seconds
        self.mock = mock
        self._last_outcome: PollOutcome | None = None
        self._cached_data: dict[str, Any] | None = None
        self._cached_path: str | None = None
        self._cached_mtime: float | None = None

    async def aclose(self) -> None:
        return None

    async def fetch_once(self) -> PollOutcome:
        if self.mock:
            return self._mock_outcome()

        if (
            (stat_result := _status_file_stat()) is not None
            and self._cached_data is not None
            and self._cached_path == stat_result[0]
            and self._cached_mtime == stat_result[1]
        ):
            data = self._cached_data
            source_path, mtime = stat_result
        else:
            result = _read_status_file()
            if result is None:
                self._last_outcome = None
                self._cached_data = None
                self._cached_path = None
                self._cached_mtime = None
                return PollOutcome(
                    state=PollState.TOKEN_ERROR,
                    message=_t(detect_lang(), "usage_status_missing"),
                )

            data, source_path, mtime = result
            self._cached_data = data
            self._cached_path = source_path
            self._cached_mtime = mtime

        if not _has_complete_rate_limits(data):
            outcome = PollOutcome(
                state=PollState.LOADING,
                message="awaiting_rate_limits",
                _mtime=mtime,
                _status_path=source_path,
            )
            self._last_outcome = outcome
            return outcome

        snapshot = _build_snapshot(data, data_source=_source_from_path(source_path))
        if snapshot is None:
            outcome = PollOutcome(
                state=PollState.LOADING,
                message=_t(detect_lang(), "usage_status_no_quota"),
                _mtime=mtime,
                _status_path=source_path,
            )
            self._last_outcome = outcome
            return outcome

        now = time.time()
        message = None
        if snapshot.is_stale:
            source_tag = "tt-status" if snapshot.data_source == "tt-fallback" else "usage"
            mins = int((now - snapshot.polled_at) / 60)
            message = f"⚠ {source_tag} stale {mins}m"

        outcome = PollOutcome(
            state=PollState.SUCCESS,
            snapshot=snapshot,
            message=message,
            _mtime=mtime,
            _status_path=source_path,
        )
        self._last_outcome = outcome
        return outcome

    def _mock_outcome(self) -> PollOutcome:
        now = time.time()
        return PollOutcome(
            state=PollState.SUCCESS,
            snapshot=UsageSnapshot(
                current_percent=50,
                current_reset_at=now + 82 * 60,
                weekly_percent=11,
                weekly_reset_at=now + ((6 * 24) + 8) * 3600,
                current_status="ok",
                polled_at=now,
                is_stale=False,
                data_source="hook",
            ),
            message=None,
        )
