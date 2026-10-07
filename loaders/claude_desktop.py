# SPDX-License-Identifier: AGPL-3.0-only

"""Read Claude Desktop's local plan history without credentials or network access."""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loaders.chromium_cache import load_cached_json

HISTORY_NAME = "plan-usage-history.json"
STALE_SECONDS = 30 * 60
MAX_AGE_SECONDS = 2 * 3600
MAX_FILE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DesktopQuota:
    current_percent: int | None
    weekly_percent: int | None
    polled_at: float
    current_reset_at: float | None = None
    weekly_reset_at: float | None = None


def desktop_history_paths() -> tuple[Path, ...]:
    home = Path.home()
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        paths = [roaming / "Claude" / HISTORY_NAME]
        try:
            packages = sorted((local / "Packages").glob("Claude_*"))
        except OSError:
            packages = []
        paths.extend(
            package / "LocalCache" / "Roaming" / "Claude" / HISTORY_NAME for package in packages
        )
        return tuple(paths)
    if sys.platform == "darwin":
        return (home / "Library" / "Application Support" / "Claude" / HISTORY_NAME,)
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
    return (config / "Claude" / HISTORY_NAME,)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _percent(value: object) -> int | None:
    number = _number(value)
    return round(number) if number is not None and 0 <= number <= 100 else None


def _read_history(path: Path, now: float) -> DesktopQuota | None:
    try:
        with path.open("rb") as file:
            raw = file.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return None
        data = json.loads(raw)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None
    if (
        not isinstance(data, dict)
        or type(data.get("version")) is not int
        or data["version"] not in {1, 2}
    ):
        return None
    samples = data.get("samples")
    if not isinstance(samples, list):
        return None
    # Choose the latest observation first, including its organization. Never
    # fill a missing window using an older sample from another account/org.
    latest: dict[str, object] | None = None
    latest_time = 0.0
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("org"), str):
            continue
        timestamp = _number(sample.get("t"))
        if timestamp is not None and timestamp >= latest_time and sample["org"]:
            latest, latest_time = sample, timestamp
    polled_at = latest_time / 1000
    if latest is None or not -60 <= now - polled_at <= MAX_AGE_SECONDS:
        return None
    utilization = latest.get("u")
    if not isinstance(utilization, dict):
        return None
    current = _percent(utilization.get("fh"))
    weekly = _percent(utilization.get("sd"))
    if current is None and weekly is None:
        return None
    quota = DesktopQuota(current, weekly, polled_at)
    try:
        url = f"https://claude.ai/api/organizations/{latest['org']}/usage".encode()
    except UnicodeEncodeError:
        return None
    response = load_cached_json(path.parent / "Cache" / "Cache_Data", url, polled_at - 60, now)
    if response is None:
        return quota
    # Desktop history is throttled to one sample every few minutes. The HTTP
    # cache can already contain a newer complete observation from the same org.
    five, seven = response.data.get("five_hour"), response.data.get("seven_day")
    cached_current = _percent(five.get("utilization")) if isinstance(five, dict) else None
    cached_weekly = _percent(seven.get("utilization")) if isinstance(seven, dict) else None
    if response.fetched_at >= polled_at and (
        cached_current is not None or cached_weekly is not None
    ):
        current, weekly, polled_at = cached_current, cached_weekly, response.fetched_at
    current_reset = _reset_time(five, polled_at, now + 5 * 3600 + 60, current)
    weekly_reset = _reset_time(seven, polled_at, now + 7 * 86400 + 60, weekly)
    # Expiry is part of the loaded quota, not a presentation-only adjustment.
    # Keep the timestamp for countdowns while every consumer sees zero usage.
    if current is not None and current_reset is not None and current_reset <= now:
        current = 0
    if weekly is not None and weekly_reset is not None and weekly_reset <= now:
        weekly = 0
    return DesktopQuota(current, weekly, polled_at, current_reset, weekly_reset)


def _reset_time(
    window: object, observed_at: float, latest: float, percent: int | None = None
) -> float | None:
    if not isinstance(window, dict) or not isinstance(value := window.get("resets_at"), str):
        return None
    cached_percent = _percent(window.get("utilization"))
    if cached_percent is None or (percent is not None and cached_percent != percent):
        return None
    try:
        date = datetime.fromisoformat(value)
        if date.tzinfo is None:
            return None
        timestamp = date.timestamp()
    except (ValueError, OverflowError, OSError):
        return None
    return timestamp if observed_at < timestamp <= latest else None


def load_desktop_quota(now: float) -> DesktopQuota | None:
    observations = (
        quota for path in desktop_history_paths() if (quota := _read_history(path, now)) is not None
    )
    return max(observations, key=lambda quota: quota.polled_at, default=None)
