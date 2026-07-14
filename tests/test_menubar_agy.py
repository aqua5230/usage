# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import menubar_agy
from agy_quota_probe import AgyQuotaGroup, AgyQuotaResult, AgyQuotaWindow


def _group(
    name: str,
    *,
    session_remaining: float,
    weekly_remaining: float,
    session_reset_minutes: int | None = 90,
    weekly_reset_minutes: int | None = 1440,
) -> AgyQuotaGroup:
    return AgyQuotaGroup(
        name=name,
        models=["model"],
        five_hour=AgyQuotaWindow(
            remaining_percent=session_remaining,
            resets_in=None,
            resets_in_minutes=session_reset_minutes,
        ),
        weekly=AgyQuotaWindow(
            remaining_percent=weekly_remaining,
            resets_in=None,
            resets_in_minutes=weekly_reset_minutes,
        ),
    )


def test_project_quota_selects_gemini_group_and_converts_percent() -> None:
    quota = AgyQuotaResult(
        groups=[
            _group("GEMINI MODELS", session_remaining=40, weekly_remaining=90),
            _group("CLAUDE AND GPT MODELS", session_remaining=70, weekly_remaining=12.5),
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    projection = menubar_agy.project_quota(quota, "en", now=1_767_225_600.0)

    assert projection is not None
    assert projection.group_name == "GEMINI MODELS"
    assert projection.session.title == "Session · Gemini"
    assert projection.session.percent == 60.0
    assert projection.session.percent_text == "60% used"
    assert projection.weekly.percent == 10.0
    assert projection.weekly.percent_text == "10% used"
    assert projection.session.reset_text == "Resets in 1h 30m"


def test_project_quota_falls_back_to_most_constrained_group_without_gemini() -> None:
    quota = AgyQuotaResult(
        groups=[
            _group("CLAUDE AND GPT MODELS", session_remaining=70, weekly_remaining=12.5),
            _group("OTHER MODELS", session_remaining=40, weekly_remaining=90),
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    projection = menubar_agy.project_quota(quota, "en", now=1_767_225_600.0)

    assert projection is not None
    assert projection.group_name == "CLAUDE AND GPT MODELS"
    assert projection.session.title == "Session · Claude/GPT"
    assert projection.session.percent == 30.0
    assert projection.weekly.percent == 87.5


def test_project_quota_marks_full_quota_without_a_countdown() -> None:
    quota = AgyQuotaResult(
        groups=[
            _group(
                "GEMINI MODELS",
                session_remaining=100,
                weekly_remaining=100,
                session_reset_minutes=None,
                weekly_reset_minutes=None,
            )
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    projection = menubar_agy.project_quota(quota, "en", now=1_767_225_600.0)

    assert projection is not None
    assert projection.session.percent == 0.0
    assert projection.weekly.percent == 0.0
    assert projection.session.reset_text == "Quota full"
    assert projection.weekly.reset_text == "Quota full"


def test_project_quota_marks_cached_result_stale_after_twenty_minutes() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    quota = AgyQuotaResult(
        groups=[_group("GEMINI MODELS", session_remaining=80, weekly_remaining=80)],
        fetched_at=(now - timedelta(minutes=21)).isoformat(),
    )

    projection = menubar_agy.project_quota(quota, "en", now=now.timestamp())

    assert projection is not None
    assert projection.stale is not None
    assert projection.stale["ageText"] == "about 21 minutes ago"


def test_load_refresh_result_hides_card_when_agy_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("menubar_agy.find_agy", lambda: None)
    monkeypatch.setattr(
        menubar_agy,
        "load_quota",
        lambda: pytest.fail("load_quota must not run without agy"),
    )

    result = menubar_agy.load_refresh_result("en")

    assert result.hide_agy is True
    assert result.projection is None


def test_load_refresh_result_projects_mocked_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    quota = AgyQuotaResult(
        groups=[_group("GEMINI MODELS", session_remaining=75, weekly_remaining=50)],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr("menubar_agy.find_agy", lambda: "/usr/local/bin/agy")
    monkeypatch.setattr(menubar_agy, "load_quota", lambda: quota)

    result = menubar_agy.load_refresh_result("en")

    assert result.hide_agy is False
    assert result.projection is not None
    assert result.projection.group_name == "GEMINI MODELS"


def test_project_quota_counts_down_by_cache_age() -> None:
    now_dt = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    fetched = now_dt - timedelta(minutes=3)
    quota = AgyQuotaResult(
        groups=[
            _group(
                "GEMINI MODELS",
                session_remaining=50,
                weekly_remaining=100,
                session_reset_minutes=12,
                weekly_reset_minutes=None,
            )
        ],
        fetched_at=fetched.isoformat(),
    )

    projection = menubar_agy.project_quota(quota, "en", now=now_dt.timestamp())

    assert projection is not None
    assert projection.session.reset_text == "Resets in 9m"


def test_project_quota_countdown_clamps_to_one_minute_when_overdue() -> None:
    now_dt = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    fetched = now_dt - timedelta(minutes=18)
    quota = AgyQuotaResult(
        groups=[
            _group(
                "GEMINI MODELS",
                session_remaining=50,
                weekly_remaining=100,
                session_reset_minutes=12,
                weekly_reset_minutes=None,
            )
        ],
        fetched_at=fetched.isoformat(),
    )

    projection = menubar_agy.project_quota(quota, "en", now=now_dt.timestamp())

    assert projection is not None
    assert projection.session.reset_text == "Resets in 1m"
