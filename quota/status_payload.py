# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.


from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from adapters.rate_limits import load_rate_limits as load_claude_rate_limits
from adapters.types import RateLimits
from loaders import agy_quota_probe, codex_loader, grok_quota_probe
from usage_common.time_utils import parse_optional_iso8601_utc


def _load_codex_rate_limits() -> RateLimits | None:
    rate_limits = codex_loader.load_rate_limits()
    if rate_limits is None:
        return None
    return RateLimits(
        five_hour_pct=rate_limits.five_hour_pct,
        five_hour_resets_at=(
            int(rate_limits.five_hour_resets_at)
            if rate_limits.five_hour_resets_at is not None
            else None
        ),
        seven_day_pct=rate_limits.seven_day_pct,
        seven_day_resets_at=(
            int(rate_limits.seven_day_resets_at)
            if rate_limits.seven_day_resets_at is not None
            else None
        ),
        model=rate_limits.model or "",
        updated_at=rate_limits.updated_at,
    )


RATE_LIMIT_LOADERS = {"claude-code": load_claude_rate_limits, "codex": _load_codex_rate_limits}


def _status_window(used_percent: float | None, resets_at: int | None, now: int) -> dict[str, Any]:
    return {
        "used_percent": used_percent,
        "resets_at": resets_at,
        "resets_in_seconds": None if resets_at is None else max(0, resets_at - now),
    }


def _age_seconds(updated_at: str | None, now: int) -> int | None:
    parsed = parse_optional_iso8601_utc(updated_at)
    return None if parsed is None else max(0, now - int(parsed.timestamp()))


def _status_agent(
    rate_limits: RateLimits | None, now: int, reason: str = "no_data"
) -> dict[str, Any]:
    if rate_limits is None:
        return {
            "available": False,
            "reason": reason,
            "five_hour": _status_window(None, None, now),
            "seven_day": _status_window(None, None, now),
            "model": None,
            "updated_at": None,
            "age_seconds": None,
        }
    return {
        "available": True,
        "five_hour": _status_window(
            rate_limits.five_hour_pct, rate_limits.five_hour_resets_at, now
        ),
        "seven_day": _status_window(
            rate_limits.seven_day_pct, rate_limits.seven_day_resets_at, now
        ),
        "model": rate_limits.model,
        "updated_at": rate_limits.updated_at,
        "age_seconds": _age_seconds(rate_limits.updated_at, now),
    }


def _status_antigravity(now: int) -> dict[str, Any]:
    if agy_quota_probe.auth_expired():
        return _status_agent(None, now, "not_signed_in")
    try:
        quota = agy_quota_probe._read_cache()
    except (OSError, UnicodeError, ValueError):
        return _status_agent(None, now, "error")
    if quota is None:
        reason = "no_data" if agy_quota_probe._TOKEN_PATH.exists() else "not_signed_in"
        return _status_agent(None, now, reason)
    fetched_at = parse_optional_iso8601_utc(quota.fetched_at)
    if fetched_at is None:
        return _status_agent(None, now)

    fetched_timestamp = fetched_at.timestamp()

    def window_status(window: agy_quota_probe.AgyQuotaWindow) -> dict[str, Any]:
        return {
            "used_percent": round(100 - window.remaining_percent, 1),
            "resets_in_seconds": (
                None
                if window.resets_in_minutes is None
                else int(max(0, fetched_timestamp + window.resets_in_minutes * 60 - now))
            ),
        }

    return {
        "available": True,
        "groups": [
            {
                "name": group.name,
                "five_hour": window_status(group.five_hour),
                "seven_day": window_status(group.weekly),
            }
            for group in quota.groups
        ],
        "updated_at": quota.fetched_at,
        "age_seconds": _age_seconds(quota.fetched_at, now),
    }


def _status_grok(now: int) -> dict[str, Any]:
    try:
        quota = grok_quota_probe.load_quota()
        period_end = None if quota is None else parse_optional_iso8601_utc(quota.period_end)
        resets_at = None if period_end is None else int(period_end.timestamp())
    except (OSError, ValueError, OverflowError):
        return _status_agent(None, now, "error")
    if quota is None or resets_at is None:
        return _status_agent(None, now)
    return {
        "available": True,
        "period": _status_window(quota.used_percent, resets_at, now),
        "tier": quota.subscription_tier,
        "updated_at": quota.fetched_at,
        "age_seconds": _age_seconds(quota.fetched_at, now),
    }


def _status_payload(*, include_extra_agents: bool = True) -> dict[str, Any]:
    generated_at = datetime.now(UTC).replace(microsecond=0)
    now = int(generated_at.timestamp())
    agents: dict[str, dict[str, Any]] = {}
    for agent_id in ("claude-code", "codex"):
        try:
            rate_limits = RATE_LIMIT_LOADERS[agent_id]()
        except Exception:
            agents[agent_id] = _status_agent(None, now, "error")
        else:
            agents[agent_id] = _status_agent(rate_limits, now)
    if include_extra_agents:
        agents["antigravity"] = _status_antigravity(now)
        agents["grok"] = _status_grok(now)
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "agents": agents,
    }
