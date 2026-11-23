# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from installer.setup_hook import current_hook_state
from loaders import claude_desktop
from loaders.claude_paths import claude_config_dirs, claude_json_path
from usage_common.i18n import _t
from usage_common.usage_lang import detect_lang

logger = logging.getLogger(__name__)

STATUS_FILE = os.path.expanduser("~/.claude/usage-status.json")
LEGACY_STATUS_FILE = os.path.expanduser("~/.claude/usag-status.json")
TT_STATUS_FILE = os.path.expanduser("~/.claude/tt-status.json")

# Stale files only affect hints; quota values still render.
STALE_SECONDS = 6 * 3600
HOOK_IDLE_SECONDS = 15 * 60
RECENT_ACTIVITY_SECONDS = 30 * 60
RECENT_ACTIVITY_CACHE_TTL_SECONDS = 75
HOOK_BROKEN_NOT_INSTALLED = "hook_broken_not_installed"
HOOK_BROKEN_RESTART = "hook_broken_restart"


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
    current_reset_at: float | None
    weekly_percent: int | None
    weekly_reset_at: float | None
    current_status: str
    polled_at: float
    is_stale: bool = False
    data_source: str = "hook"
    account_uuid: str | None = None


@dataclass(slots=True)
class PollOutcome:
    state: PollState
    snapshot: UsageSnapshot | None = None
    message: str | None = None
    _mtime: float | None = None
    _status_path: str | None = None


@dataclass(slots=True)
class _RecentActivityCache:
    checked_at: float
    result: bool


_recent_activity_cache: _RecentActivityCache | None = None


def _claude_json_file() -> str:
    return str(claude_json_path())


def _claude_projects_dirs() -> list[Path]:
    return [path / "projects" for path in claude_config_dirs()]


def _pct(value: Any) -> int | None:
    numeric = _as_finite_float(value)
    if numeric is None:
        return None
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
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def _iso_timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return None


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


def _read_claude_json_snapshot() -> UsageSnapshot | None:
    """Read Claude Code's own cached quota utilization as a fallback."""
    return _read_claude_json()[1]


def _account_uuid(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _hook_account_mismatch(data: dict[str, Any], current_account: str | None) -> bool:
    hook_account = _account_uuid(data.get("_rate_limits_account_uuid"))
    return bool(hook_account and current_account and hook_account != current_account)


def _read_claude_json() -> tuple[str | None, UsageSnapshot | None]:
    """Read the signed-in account even when Claude Code has no usable quota cache."""
    try:
        with open(_claude_json_file(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None

    cached = _as_dict(data.get("cachedUsageUtilization"))
    # Claude Code tags the cache with the account that fetched it and drops it
    # after an account switch. An untagged cache predates the tag and stays usable.
    cached_account = cached.get("accountUuid")
    signed_in_account = _as_dict(data.get("oauthAccount")).get("accountUuid")
    current_account = _account_uuid(signed_in_account)
    if cached_account is not None and cached_account != signed_in_account:
        return current_account, None
    fetched_at_ms = _as_finite_float(cached.get("fetchedAtMs"))
    if fetched_at_ms is None:
        return current_account, None
    utilization = _as_dict(cached.get("utilization"))
    five = _as_dict(utilization.get("five_hour"))
    seven = _as_dict(utilization.get("seven_day"))
    five_raw = five.get("utilization")
    seven_raw = seven.get("utilization")

    five_pct = _pct(five_raw) if five_raw is not None else None
    seven_pct = _pct(seven_raw) if seven_raw is not None else None
    if five_pct is None and seven_pct is None:
        return current_account, None

    now = time.time()
    five_reset = _iso_timestamp(five.get("resets_at")) if five else None
    seven_reset = _iso_timestamp(seven.get("resets_at")) if seven else None
    if five and five_reset is None:
        return current_account, None
    if seven and seven_reset is None:
        return current_account, None
    five_reset = five_reset if five_reset is not None else now
    seven_reset = seven_reset if seven_reset is not None else now
    if five_pct is not None and five_reset < now:
        five_pct = 0
    if seven_pct is not None and seven_reset < now:
        seven_pct = 0

    polled_at = fetched_at_ms / 1000
    return current_account, UsageSnapshot(
        current_percent=five_pct,
        current_reset_at=five_reset,
        weekly_percent=seven_pct,
        weekly_reset_at=seven_reset,
        current_status="",
        polled_at=polled_at,
        is_stale=(now - polled_at) > STALE_SECONDS,
        data_source="claude-json",
        account_uuid=_account_uuid(cached_account) or current_account,
    )


def _time_adjusted(snapshot: UsageSnapshot) -> UsageSnapshot:
    """Re-derive expiry-sensitive fields of a cached snapshot at the current time."""
    now = time.time()
    five_pct = snapshot.current_percent
    if (
        five_pct is not None
        and snapshot.current_reset_at is not None
        and snapshot.current_reset_at < now
    ):
        five_pct = 0
    seven_pct = snapshot.weekly_percent
    if (
        seven_pct is not None
        and snapshot.weekly_reset_at is not None
        and snapshot.weekly_reset_at < now
    ):
        seven_pct = 0
    return UsageSnapshot(
        current_percent=five_pct,
        current_reset_at=snapshot.current_reset_at,
        weekly_percent=seven_pct,
        weekly_reset_at=snapshot.weekly_reset_at,
        current_status=snapshot.current_status,
        polled_at=snapshot.polled_at,
        is_stale=(now - snapshot.polled_at) > STALE_SECONDS,
        data_source=snapshot.data_source,
        account_uuid=snapshot.account_uuid,
    )


def _has_recent_claude_project_activity(now: float) -> bool:
    global _recent_activity_cache

    if (
        _recent_activity_cache is not None
        and now - _recent_activity_cache.checked_at < RECENT_ACTIVITY_CACHE_TTL_SECONDS
    ):
        return _recent_activity_cache.result

    result = False
    try:
        for projects_dir in _claude_projects_dirs():
            for path in projects_dir.rglob("*.jsonl"):
                try:
                    if now - path.stat().st_mtime <= RECENT_ACTIVITY_SECONDS:
                        result = True
                        break
                except OSError:
                    continue
            if result:
                break
    except OSError:
        result = False
    _recent_activity_cache = _RecentActivityCache(checked_at=now, result=result)
    return result


def _hook_broken_message(now: float, polled_at: float) -> str | None:
    if now - polled_at <= RECENT_ACTIVITY_SECONDS:
        return None
    if not _has_recent_claude_project_activity(now):
        return None
    hook_state = current_hook_state()
    if hook_state in {"us-direct", "us-forwarder"}:
        return HOOK_BROKEN_RESTART
    return HOOK_BROKEN_NOT_INSTALLED


def _has_rate_limits(data: dict[str, Any]) -> bool:
    """True when every window the hook sent is valid and at least one was sent.

    Plans without a 5-hour limit never send five_hour, so requiring both windows
    would leave them on the cache or the loading state forever. A window that is
    present but unreadable still falls back to the cache.
    """
    rl = data.get("rate_limits")
    if not isinstance(rl, dict):
        return False
    windows = [w for w in (rl.get("five_hour"), rl.get("seven_day")) if w is not None]
    return bool(windows) and all(
        isinstance(w, dict) and _as_finite_float(w.get("used_percentage")) is not None
        for w in windows
    )


def _hook_observed_at(data: dict[str, Any], now: float) -> float | None:
    def valid_timestamp(value: Any) -> float | None:
        if not isinstance(value, (int, float)):
            return None
        timestamp = _as_finite_float(value)
        return timestamp if timestamp is not None and 0 < timestamp <= now + 60 else None

    observed = data.get("_rate_limits_observed_at")
    if isinstance(observed, dict):
        observations = (observed.get("five_hour"), observed.get("seven_day"))
        timestamp = max(
            (ts for value in observations if (ts := valid_timestamp(value)) is not None),
            default=None,
        )
    else:
        timestamp = valid_timestamp(observed)
    return timestamp if timestamp is not None else valid_timestamp(data.get("_received_at_ts"))


def _should_prefer_claude_json(
    data: dict[str, Any], hook: UsageSnapshot, cached: UsageSnapshot | None, now: float
) -> bool:
    if cached is None or cached.data_source != "claude-json":
        return False
    fetched_at = cached.polled_at
    if not math.isfinite(fetched_at) or fetched_at > now + 60:
        return False

    rate_limits = _as_dict(data.get("rate_limits"))
    windows = (
        ("five_hour", hook.current_percent, cached.current_percent, cached.current_reset_at),
        ("seven_day", hook.weekly_percent, cached.weekly_percent, cached.weekly_reset_at),
    )
    crossed_reset = False
    for window, hook_pct, cached_pct, cached_reset in windows:
        if hook_pct is None:
            continue
        if cached_pct is None:
            return False
        hook_reset = _as_finite_float(_as_dict(rate_limits.get(window)).get("resets_at"))
        if hook_reset is None or cached_reset is None:
            continue
        if cached_reset < hook_reset - 60:
            return False
        if hook_reset <= now < cached_reset and fetched_at >= hook_reset:
            crossed_reset = True

    observed_at = _hook_observed_at(data, now)
    return crossed_reset or (
        observed_at is not None
        and now - observed_at > HOOK_IDLE_SECONDS
        and fetched_at > observed_at + 60
    )


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

    polled_at = _hook_observed_at(data, now) or now

    status = ""
    if isinstance(rl.get("status"), str):
        status = rl["status"]

    return UsageSnapshot(
        current_percent=five_pct,
        # Keep an unknown hook reset unknown so the keeper cannot remember a
        # parse-time default as a real boundary. Display expiry logic above
        # still uses the default to preserve the reported percentage.
        current_reset_at=_as_finite_float(five.get("resets_at")),
        weekly_percent=seven_pct,
        weekly_reset_at=seven_reset,
        current_status=status,
        polled_at=polled_at,
        is_stale=(now - polled_at) > STALE_SECONDS,
        data_source=data_source,
        account_uuid=_account_uuid(data.get("_rate_limits_account_uuid")),
    )


def read_quota_fallback(
    cache_reader: Callable[[], UsageSnapshot | None] | None = None,
) -> UsageSnapshot | None:
    """Use the same Claude Code cache -> Desktop priority in the app and CLI.

    Call when the hook is missing or incomplete. A caller can supply a snapshot
    reader to reuse an existing parse or the GUI's modification-time cache.
    """
    cached = (cache_reader or _read_claude_json_snapshot)()
    if cached is not None:
        return cached
    now = time.time()
    desktop = claude_desktop.load_desktop_quota(now)
    if desktop is None:
        return None
    return UsageSnapshot(
        current_percent=desktop.current_percent,
        current_reset_at=desktop.current_reset_at,
        weekly_percent=desktop.weekly_percent,
        weekly_reset_at=desktop.weekly_reset_at,
        current_status="",
        polled_at=desktop.polled_at,
        is_stale=now - desktop.polled_at > claude_desktop.STALE_SECONDS,
        data_source="claude-desktop",
    )


class ClaudeUsageClient:
    """Read Claude Code quota files, falling back to Claude Desktop's local history."""

    def __init__(self, *, interval_seconds: int = 60, mock: bool = False) -> None:
        self.interval_seconds = interval_seconds
        self.mock = mock
        self._last_outcome: PollOutcome | None = None
        self._cached_data: dict[str, Any] | None = None
        self._cached_path: str | None = None
        self._cached_mtime: float | None = None
        self._claude_json_cached_path: str | None = None
        self._claude_json_cached_mtime: float | None = None
        self._claude_json_cached: tuple[str | None, UsageSnapshot | None] = (None, None)
        self._claude_json_cache_valid = False

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
                fallback_snapshot = read_quota_fallback(lambda: self._read_claude_json_cached()[1])
                if fallback_snapshot is not None:
                    return self._success_outcome(fallback_snapshot)
                message_key = "usage_status_missing"
                if current_hook_state() in {
                    "us-direct",
                    "us-forwarder",
                } and _has_recent_claude_project_activity(time.time()):
                    message_key = "usage_status_missing_active"
                return PollOutcome(
                    state=PollState.TOKEN_ERROR,
                    message=_t(detect_lang(), message_key),
                )

            data, source_path, mtime = result
            self._cached_data = data
            self._cached_path = source_path
            self._cached_mtime = mtime

        current_account, cached_snapshot = self._read_claude_json_cached()
        account_mismatch = _hook_account_mismatch(data, current_account)
        if account_mismatch or not _has_rate_limits(data):
            fallback_snapshot = (
                cached_snapshot
                if account_mismatch
                else read_quota_fallback(lambda: cached_snapshot)
            )
            if fallback_snapshot is not None:
                return self._success_outcome(fallback_snapshot)
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

        # An untagged hook is treated as the signed-in account (rule above), so it
        # shares that account's notification history instead of starting a new one.
        if snapshot.account_uuid is None:
            snapshot.account_uuid = current_account
        if cached_snapshot is not None and _should_prefer_claude_json(
            data, snapshot, cached_snapshot, time.time()
        ):
            return self._success_outcome(cached_snapshot)
        return self._success_outcome(snapshot, mtime=mtime, source_path=source_path)

    def _read_claude_json_cached(self) -> tuple[str | None, UsageSnapshot | None]:
        claude_json_file = _claude_json_file()
        try:
            mtime = os.stat(claude_json_file).st_mtime
        except OSError:
            self._claude_json_cache_valid = False
            self._claude_json_cached_path = None
            self._claude_json_cached_mtime = None
            self._claude_json_cached = (None, None)
            return self._claude_json_cached
        if (
            self._claude_json_cache_valid
            and self._claude_json_cached_path == claude_json_file
            and self._claude_json_cached_mtime == mtime
        ):
            # The file may sit unchanged across a quota reset, so the expiry-derived
            # fields must be recomputed on every hit — only the parse is cached.
            current_account, snapshot = self._claude_json_cached
            return current_account, _time_adjusted(snapshot) if snapshot is not None else None
        self._claude_json_cached = _read_claude_json()
        self._claude_json_cache_valid = True
        self._claude_json_cached_path = claude_json_file
        self._claude_json_cached_mtime = mtime
        return self._claude_json_cached

    def _success_outcome(
        self,
        snapshot: UsageSnapshot,
        *,
        mtime: float | None = None,
        source_path: str | None = None,
    ) -> PollOutcome:
        now = time.time()
        message: str | None
        if snapshot.data_source == "claude-desktop":
            minutes = max(0, int((now - snapshot.polled_at) / 60))
            key = "claude_desktop_stale" if snapshot.is_stale else "claude_desktop_updated"
            message = _t(detect_lang(), key, minutes=minutes)
        elif snapshot.data_source == "claude-json":
            message = None
            if current_hook_state() not in {"us-direct", "us-forwarder"}:
                message = _hook_broken_message(now, snapshot.polled_at)
            if message is None:
                minutes = max(0, int((now - snapshot.polled_at) / 60))
                key = "claude_json_stale" if snapshot.is_stale else "claude_json_updated"
                message = _t(detect_lang(), key, minutes=minutes)
        else:
            message = _hook_broken_message(now, snapshot.polled_at)
            if snapshot.is_stale:
                source_tag = "tt-status" if snapshot.data_source == "tt-fallback" else "usage"
                mins = int((now - snapshot.polled_at) / 60)
                message = message or f"⚠ {source_tag} stale {mins}m"

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
