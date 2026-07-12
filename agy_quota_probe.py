# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Fetch Antigravity quota straight from the official Cloud Code quota API.

Reads the local OAuth token that the Antigravity CLI stores after sign-in,
refreshes it through Google's token endpoint when stale, then POSTs the
internal ``retrieveUserQuotaSummary`` endpoint for the quota summary. No CLI is
spawned, no screen text is parsed.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import urllib.parse
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

CACHE_PATH = Path(os.path.expanduser("~/.usage/agy_quota_cache.json"))
# OAuth token written by the Antigravity CLI at sign-in. Read-only: we never
# write back here (that is the CLI's home and would risk corrupting its login).
_TOKEN_PATH = Path(os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token"))

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_QUOTA_URL = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
# Antigravity's installed-app public client constants (same values quotio ships).
_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
_CLIENT_SECRET = "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"
_USER_AGENT = "antigravity/1.11.3 Darwin/arm64"

# In-memory cache of a refreshed access token so each probe does not re-refresh.
# Holds {"access_token": str, "expires_monotonic": float}.
_token_cache: dict[str, object] = {}


@dataclass(frozen=True, slots=True)
class AgyQuotaWindow:
    """Remaining quota and its reported reset countdown."""

    remaining_percent: float
    resets_in: str | None
    resets_in_minutes: int | None


@dataclass(frozen=True, slots=True)
class AgyQuotaGroup:
    """Quota windows shared by a named group of Antigravity models."""

    name: str
    models: list[str]
    weekly: AgyQuotaWindow
    five_hour: AgyQuotaWindow


@dataclass(frozen=True, slots=True)
class AgyQuotaResult:
    """All model groups returned by one quota probe."""

    groups: list[AgyQuotaGroup]
    fetched_at: str


def probe_quota(timeout_seconds: float = 15) -> AgyQuotaResult | None:
    """Fetch the quota summary via the Cloud Code API, returning no result on failure."""
    if timeout_seconds <= 0:
        return None
    access_token = _resolve_access_token(timeout_seconds)
    if access_token is None:
        return None
    raw = _post_json(_QUOTA_URL, access_token, {}, timeout_seconds)
    if raw is None:
        return None
    groups_raw = _extract_groups(raw)
    if not groups_raw:
        return None
    return _build_result(groups_raw)


def find_agy() -> str | None:
    """Find the Antigravity CLI in PATH or common user installation paths."""
    path = shutil.which("agy")
    if path is not None:
        return path
    for candidate in ("~/.local/bin/agy", "/opt/homebrew/bin/agy", "/usr/local/bin/agy"):
        expanded = os.path.expanduser(candidate)
        if os.access(expanded, os.X_OK):
            return expanded
    return None


def load_quota(max_age_minutes: float = 5) -> AgyQuotaResult | None:
    """Return fresh cached quota, otherwise probe and preserve stale fallback."""
    cached = _read_cache()
    if cached is not None and _is_fresh(cached, max_age_minutes):
        return cached

    probed = probe_quota()
    if probed is None:
        return cached
    _write_cache(probed)
    return probed


def _resolve_access_token(timeout: float) -> str | None:
    """Return a usable access token, refreshing when stale.

    Prefer a refreshed token still held in memory, then the on-disk token if its
    expiry is comfortably in the future, otherwise refresh via the token
    endpoint. Falls back to the on-disk access token (possibly expired) only if a
    refresh is impossible, so a 401 surfaces naturally.
    """
    cached_token = _token_cache.get("access_token")
    cached_expiry = _token_cache.get("expires_monotonic")
    if (
        isinstance(cached_token, str)
        and isinstance(cached_expiry, (int, float))
        and time.monotonic() < float(cached_expiry) - 60
    ):
        return cached_token

    token_data = _read_token_file()
    if not isinstance(token_data, dict):
        return None
    token = token_data.get("token")
    if not isinstance(token, dict):
        return None
    access_token = token.get("access_token")
    expiry = token.get("expiry")
    if (
        isinstance(access_token, str)
        and isinstance(expiry, str)
        and _seconds_until(expiry) > 60
    ):
        return access_token

    refresh_token = token.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return access_token if isinstance(access_token, str) else None
    refreshed = _refresh_token(refresh_token, timeout)
    if refreshed is None:
        return access_token if isinstance(access_token, str) else None
    new_token, expires_in = refreshed
    _token_cache["access_token"] = new_token
    _token_cache["expires_monotonic"] = time.monotonic() + float(expires_in)
    return new_token


def _read_token_file() -> object:
    """Read and parse the Antigravity OAuth token file (never writes back)."""
    try:
        with _TOKEN_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _refresh_token(refresh_token: str, timeout: float) -> tuple[str, int] | None:
    """Exchange a refresh token for a fresh access token via the token endpoint."""
    body = urllib.parse.urlencode(
        {
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    request = Request(
        _TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (URLError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    access_token = payload.get("access_token")
    expires_in = payload.get("expires_in")
    if not isinstance(access_token, str) or isinstance(expires_in, bool):
        return None
    if not isinstance(expires_in, (int, float)):
        return None
    return access_token, int(expires_in)


def _post_json(url: str, access_token: str, body: dict[str, object], timeout: float) -> object:
    """POST a JSON body with the bearer token; return parsed JSON or None on failure."""
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (URLError, OSError, ValueError):
        return None


def _extract_groups(raw: object) -> list[dict[str, object]] | None:
    """Pull the groups array from any of its three known nesting locations."""
    if not isinstance(raw, dict):
        return None
    direct = raw.get("groups")
    if isinstance(direct, list):
        return [group for group in direct if isinstance(group, dict)]
    for wrapper_key in ("response", "summary"):
        wrapper = raw.get(wrapper_key)
        if isinstance(wrapper, dict):
            inner = wrapper.get("groups")
            if isinstance(inner, list):
                return [group for group in inner if isinstance(group, dict)]
    return None


def _build_result(groups_raw: list[dict[str, object]]) -> AgyQuotaResult | None:
    """Classify buckets into the Gemini / Claude-GPT groups UI expects."""
    windows: dict[str, dict[str, AgyQuotaWindow]] = {}
    for group in groups_raw:
        group_id = _group_id(group)
        if group_id is None:
            continue
        buckets = group.get("buckets")
        if not isinstance(buckets, list):
            continue
        slot = windows.setdefault(group_id, {})
        for bucket in buckets:
            if not isinstance(bucket, dict) or _bucket_disabled(bucket):
                continue
            period = _bucket_period(bucket)
            if period is None or period in slot:
                continue
            window = _bucket_to_window(bucket)
            if window is None:
                continue
            slot[period] = window
    result_groups = _assemble_groups(windows)
    if not result_groups:
        return None
    return AgyQuotaResult(groups=result_groups, fetched_at=datetime.now(UTC).isoformat())


def _assemble_groups(
    windows: dict[str, dict[str, AgyQuotaWindow]],
) -> list[AgyQuotaGroup]:
    """Lay out the two UI groups in fixed order, filling missing windows as full."""
    full = AgyQuotaWindow(100.0, None, None)
    layout = (
        ("gemini", "GEMINI MODELS", ["Gemini Flash", "Gemini Pro"]),
        ("claude-gpt", "CLAUDE AND GPT MODELS", ["Claude Opus", "Claude Sonnet", "GPT-OSS"]),
    )
    groups: list[AgyQuotaGroup] = []
    for group_id, name, models in layout:
        slot = windows.get(group_id)
        if slot is None:
            continue
        groups.append(
            AgyQuotaGroup(
                name=name,
                models=list(models),
                weekly=slot.get("weekly", full),
                five_hour=slot.get("session", full),
            )
        )
    return groups


def _group_id(group: dict[str, object]) -> str | None:
    name = _coerce_str(group.get("displayName")) or _coerce_str(group.get("name"))
    if name is None:
        return None
    lower = name.lower()
    if "gemini" in lower:
        return "gemini"
    if "claude" in lower or "gpt" in lower:
        return "claude-gpt"
    return None


def _bucket_period(bucket: dict[str, object]) -> str | None:
    label = " ".join(
        [
            _coerce_str(bucket.get("bucketId")) or "",
            _coerce_str(bucket.get("id")) or "",
            _coerce_str(bucket.get("displayName")) or "",
            _coerce_str(bucket.get("name")) or "",
            _coerce_str(bucket.get("window")) or "",
        ]
    ).lower()
    if "week" in label or "7d" in label or "seven" in label:
        return "weekly"
    if "session" in label or "5" in label or "hour" in label:
        return "session"
    return None


def _bucket_disabled(bucket: dict[str, object]) -> bool:
    value = bucket.get("disabled")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    text = _coerce_str(value)
    return text is not None and text.lower() in {"true", "1"}


def _bucket_to_window(bucket: dict[str, object]) -> AgyQuotaWindow | None:
    fraction = _remaining_fraction(bucket)
    if fraction is None:
        return None
    remaining = max(0.0, min(1.0, fraction)) * 100.0
    reset_time = _bucket_reset_time(bucket)
    if remaining >= 100.0 and reset_time is None:
        return AgyQuotaWindow(100.0, None, None)
    if reset_time is None:
        return AgyQuotaWindow(remaining, None, None)
    minutes = _minutes_until(reset_time)
    if minutes is None:
        return AgyQuotaWindow(remaining, None, None)
    minutes = max(0, minutes)
    return AgyQuotaWindow(remaining, _format_resets_in(minutes), minutes)


def _remaining_fraction(bucket: dict[str, object]) -> float | None:
    """Read remainingFraction across its three shapes (flat, nested, or case-tagged)."""
    for key in ("remainingFraction", "remaining_fraction"):
        value = _coerce_float(bucket.get(key))
        if value is not None:
            return value
    remaining = bucket.get("remaining")
    if not isinstance(remaining, dict):
        return None
    for key in ("remainingFraction", "remaining_fraction"):
        value = _coerce_float(remaining.get(key))
        if value is not None:
            return value
    if _coerce_str(remaining.get("case")) == "remainingFraction":
        return _coerce_float(remaining.get("value"))
    return None


def _bucket_reset_time(bucket: dict[str, object]) -> str | None:
    for key in ("resetTime", "reset_time", "resetAt", "reset_at"):
        value = _coerce_str(bucket.get(key))
        if value:
            return value
    return None


def _seconds_until(expiry: str) -> float:
    parsed = _parse_timestamp(expiry)
    if parsed is None:
        return -1.0
    return (parsed - datetime.now(UTC)).total_seconds()


def _minutes_until(reset_time: str) -> int | None:
    parsed = _parse_timestamp(reset_time)
    if parsed is None:
        return None
    delta_seconds = (parsed - datetime.now(UTC)).total_seconds()
    return int(delta_seconds // 60)


def _format_resets_in(minutes: int) -> str:
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60}m"
    return f"{minutes}m"


def _coerce_str(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _is_fresh(result: AgyQuotaResult, max_age_minutes: float) -> bool:
    if max_age_minutes < 0:
        return False
    fetched_at = _parse_timestamp(result.fetched_at)
    if fetched_at is None:
        return False
    return datetime.now(UTC) - fetched_at <= timedelta(minutes=max_age_minutes)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp.astimezone(UTC)


def _read_cache() -> AgyQuotaResult | None:
    try:
        with CACHE_PATH.open(encoding="utf-8") as cache_file:
            payload: object = json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None
    return _result_from_payload(payload)


def _write_cache(result: AgyQuotaResult) -> None:
    temporary_path: str | None = None
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(dir=CACHE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as cache_file:
            json.dump(_result_to_payload(result), cache_file, ensure_ascii=False)
        os.replace(temporary_path, CACHE_PATH)
        temporary_path = None
    except OSError:
        return
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                os.unlink(temporary_path)


def _result_to_payload(result: AgyQuotaResult) -> dict[str, object]:
    return {
        "fetched_at": result.fetched_at,
        "groups": [
            {
                "name": group.name,
                "models": group.models,
                "weekly": _window_to_payload(group.weekly),
                "five_hour": _window_to_payload(group.five_hour),
            }
            for group in result.groups
        ],
    }


def _window_to_payload(window: AgyQuotaWindow) -> dict[str, float | int | str | None]:
    return {
        "remaining_percent": window.remaining_percent,
        "resets_in": window.resets_in,
        "resets_in_minutes": window.resets_in_minutes,
    }


def _result_from_payload(payload: object) -> AgyQuotaResult | None:
    if not isinstance(payload, dict):
        return None
    fetched_at = payload.get("fetched_at")
    raw_groups = payload.get("groups")
    if not isinstance(fetched_at, str) or _parse_timestamp(fetched_at) is None:
        return None
    if not isinstance(raw_groups, list) or not raw_groups:
        return None
    groups: list[AgyQuotaGroup] = []
    for raw_group in raw_groups:
        group = _group_from_payload(raw_group)
        if group is None:
            return None
        groups.append(group)
    return AgyQuotaResult(groups=groups, fetched_at=fetched_at)


def _group_from_payload(payload: object) -> AgyQuotaGroup | None:
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    models = payload.get("models")
    weekly = _window_from_payload(payload.get("weekly"))
    five_hour = _window_from_payload(payload.get("five_hour"))
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(models, list)
        or not all(isinstance(model, str) and model for model in models)
        or weekly is None
        or five_hour is None
    ):
        return None
    return AgyQuotaGroup(name=name, models=models, weekly=weekly, five_hour=five_hour)


def _window_from_payload(payload: object) -> AgyQuotaWindow | None:
    if not isinstance(payload, dict):
        return None
    remaining_percent = payload.get("remaining_percent")
    resets_in = payload.get("resets_in")
    resets_in_minutes = payload.get("resets_in_minutes")
    if (
        not isinstance(remaining_percent, (int, float))
        or isinstance(remaining_percent, bool)
        or not 0 <= float(remaining_percent) <= 100
        or (resets_in is not None and not isinstance(resets_in, str))
        or (resets_in_minutes is not None and not isinstance(resets_in_minutes, int))
    ):
        return None
    if (resets_in is None) != (resets_in_minutes is None):
        return None
    return AgyQuotaWindow(
        remaining_percent=float(remaining_percent),
        resets_in=resets_in,
        resets_in_minutes=resets_in_minutes,
    )
