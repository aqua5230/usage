# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loaders.agy_quota_probe import AgyQuotaGroup, AgyQuotaResult, AgyQuotaWindow
from menubar import agy as menubar_agy
from menubar.prefs import _save_agy_quota_group
from quota.burn_rate import BurnRateTracker
from usage_common import prefs


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


def _burn_rate_trackers() -> dict[str, BurnRateTracker]:
    return {
        "agy_session": BurnRateTracker(),
        "agy_weekly": BurnRateTracker(),
    }


def _quota_snapshot(
    fetched_at: datetime,
    *,
    session_used: float,
    weekly_used: float = 0.0,
    session_reset_minutes: int = 90,
    weekly_reset_minutes: int = 7 * 24 * 60,
) -> AgyQuotaResult:
    return AgyQuotaResult(
        groups=[
            _group(
                "GEMINI MODELS",
                session_remaining=100.0 - session_used,
                weekly_remaining=100.0 - weekly_used,
                session_reset_minutes=session_reset_minutes,
                weekly_reset_minutes=weekly_reset_minutes,
            )
        ],
        fetched_at=fetched_at.isoformat(),
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
    assert projection.group_switchable is True
    assert projection.session.title == "Session"
    assert projection.session.percent == 60.0
    assert projection.session.percent_text == "60% used"
    assert projection.weekly.percent == 10.0
    assert projection.weekly.percent_text == "10% used"
    assert projection.session.reset_text == "Resets in 1h 30m"


def test_project_quota_selects_claude_and_falls_back_to_gemini() -> None:
    quota = AgyQuotaResult(
        groups=[
            _group("GEMINI MODELS", session_remaining=40, weekly_remaining=90),
            _group("CLAUDE AND GPT MODELS", session_remaining=70, weekly_remaining=12.5),
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    selected = menubar_agy.project_quota(
        quota, "en", now=1_767_225_600.0, group_preference="claude_gpt"
    )
    assert selected is not None
    assert selected.group_name == "CLAUDE AND GPT MODELS"
    assert selected.session.percent == 30.0
    assert selected.weekly.percent == 87.5

    gemini_only = AgyQuotaResult(groups=quota.groups[:1], fetched_at=quota.fetched_at)
    fallback = menubar_agy.project_quota(
        gemini_only, "en", now=1_767_225_600.0, group_preference="claude_gpt"
    )
    assert fallback is not None
    assert fallback.group_name == "GEMINI MODELS"
    assert fallback.group_switchable is False


def test_fallback_projection_disables_group_switching() -> None:
    assert menubar_agy.fallback_projection("en").group_switchable is False


def test_switch_reprojects_cached_quota_and_resets_trackers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", tmp_path / "usage-preferences.json")
    quota = AgyQuotaResult(
        groups=[
            _group("GEMINI MODELS", session_remaining=40, weekly_remaining=90),
            _group("CLAUDE AND GPT MODELS", session_remaining=70, weekly_remaining=12.5),
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(menubar_agy, "_last_quota", quota)
    trackers = _burn_rate_trackers()
    old_session, old_weekly = trackers["agy_session"], trackers["agy_weekly"]
    old_session.record(100, 12)
    old_weekly.record(100, 34)
    assert _save_agy_quota_group("claude_gpt") is True

    projection = menubar_agy.reproject_cached_quota("en", trackers)

    assert projection is not None
    assert projection.group_name == "CLAUDE AND GPT MODELS"
    assert trackers["agy_session"] is not old_session
    assert trackers["agy_weekly"] is not old_weekly
    assert trackers["agy_session"].last_timestamp != 100
    assert trackers["agy_weekly"].last_timestamp != 100


def test_refresh_projects_saved_agy_group(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", tmp_path / "usage-preferences.json")
    quota = AgyQuotaResult(
        groups=[
            _group("GEMINI MODELS", session_remaining=40, weekly_remaining=90),
            _group("CLAUDE AND GPT MODELS", session_remaining=70, weekly_remaining=12.5),
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(menubar_agy, "find_agy", lambda: "agy")
    monkeypatch.setattr(menubar_agy, "load_quota", lambda: quota)
    assert _save_agy_quota_group("claude_gpt") is True

    result = menubar_agy.load_refresh_result("en")

    assert result.projection is not None
    assert result.projection.group_name == "CLAUDE AND GPT MODELS"


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
    assert projection.session.title == "Session"
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


def test_project_quota_marks_full_session_with_sliding_countdown_as_full() -> None:
    quota = AgyQuotaResult(
        groups=[
            AgyQuotaGroup(
                name="GEMINI MODELS",
                models=["model"],
                five_hour=AgyQuotaWindow(100.0, "4h 59m", 299),
                weekly=AgyQuotaWindow(50.0, "1d", 1440),
            )
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    projection = menubar_agy.project_quota(quota, "en", now=1_767_225_600.0)

    assert projection is not None
    assert projection.session.reset_text == "Quota full"
    assert projection.session.reset_text != "Resets in 4h 59m"


def test_project_quota_shows_session_paused_when_weekly_is_spent() -> None:
    quota = AgyQuotaResult(
        groups=[
            AgyQuotaGroup(
                name="CLAUDE AND GPT MODELS",
                models=["model"],
                five_hour=AgyQuotaWindow(100.0, None, None),
                weekly=AgyQuotaWindow(0.0, "57h", 3420),
            )
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    projection = menubar_agy.project_quota(quota, "en", now=1_767_225_600.0)

    assert projection is not None
    assert projection.session.percent_text == "Paused"
    assert projection.session.reset_text == "Weekly quota used up; waits for weekly reset"
    assert projection.weekly.percent == 100.0


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
    monkeypatch.setattr("menubar.agy.find_agy", lambda: None)
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
    monkeypatch.setattr("menubar.agy.find_agy", lambda: "/usr/local/bin/agy")
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


def test_project_quota_displays_zero_when_overdue() -> None:
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
    assert projection.session.reset_text == "Reset"
    assert projection.session.display_percent == 0.0
    assert projection.session.percent == 50.0
    assert not projection.session.warning


def test_project_quota_warns_when_session_will_empty_before_reset() -> None:
    trackers = _burn_rate_trackers()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    projection = None

    for index, used in enumerate((50.0, 58.0, 66.0, 74.0, 82.0, 90.0)):
        fetched_at = started_at + timedelta(minutes=5 * index)
        projection = menubar_agy.project_quota(
            _quota_snapshot(fetched_at, session_used=used),
            "en",
            now=fetched_at.timestamp(),
            burn_rate_trackers=trackers,
        )

    assert projection is not None
    assert projection.session.warning is True
    assert projection.session.reset_text == ("⚠ At this pace, empty in 6m · resets in 1h 30m")


def test_weekly_window_row_keeps_reset_text_when_whole_window_blocks_warning() -> None:
    row = menubar_agy._window_row(
        "Weekly",
        AgyQuotaWindow(
            remaining_percent=46.3,
            resets_in=None,
            resets_in_minutes=4380,
        ),
        "zh-TW",
        age_minutes=0,
        forecast_seconds=47_040,
        warning_max_seconds=24 * 3600,
        window_seconds=7 * 86400,
    )

    assert row.warning is False
    assert row.reset_text == "重置 3天 1小時"


def test_project_quota_deduplicates_identical_snapshot_timestamps() -> None:
    trackers = _burn_rate_trackers()
    fetched_at = datetime(2026, 1, 1, tzinfo=UTC)
    projection = None

    for _ in range(10):
        projection = menubar_agy.project_quota(
            _quota_snapshot(fetched_at, session_used=50.0),
            "en",
            now=fetched_at.timestamp(),
            burn_rate_trackers=trackers,
        )

    assert projection is not None
    assert trackers["agy_session"].last_timestamp == fetched_at.timestamp()
    assert projection.session.warning is False

    for index, used in enumerate((60.0, 70.0, 80.0), start=1):
        next_fetched_at = fetched_at + timedelta(minutes=5 * index)
        projection = menubar_agy.project_quota(
            _quota_snapshot(next_fetched_at, session_used=used),
            "en",
            now=next_fetched_at.timestamp(),
            burn_rate_trackers=trackers,
        )

    assert projection is not None
    assert projection.session.warning is False


def test_project_quota_does_not_forecast_stale_snapshot() -> None:
    trackers = _burn_rate_trackers()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    projection = None

    for index, used in enumerate((50.0, 58.0, 66.0, 74.0, 82.0, 90.0)):
        fetched_at = started_at + timedelta(minutes=5 * index)
        projection = menubar_agy.project_quota(
            _quota_snapshot(fetched_at, session_used=used),
            "en",
            now=fetched_at.timestamp(),
            burn_rate_trackers=trackers,
        )
    assert projection is not None
    assert projection.session.warning is True

    stale_fetched_at = started_at + timedelta(minutes=30)
    projection = menubar_agy.project_quota(
        _quota_snapshot(stale_fetched_at, session_used=95.0),
        "en",
        now=(stale_fetched_at + timedelta(seconds=menubar_agy.AGY_STALE_SECONDS + 1)).timestamp(),
        burn_rate_trackers=trackers,
    )

    assert projection is not None
    assert projection.stale is not None
    assert projection.session.warning is False


def test_project_quota_does_not_forecast_invalid_fetched_at() -> None:
    trackers = _burn_rate_trackers()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    projection = None

    for index, used in enumerate((50.0, 58.0, 66.0, 74.0, 82.0, 90.0)):
        fetched_at = started_at + timedelta(minutes=5 * index)
        projection = menubar_agy.project_quota(
            _quota_snapshot(fetched_at, session_used=used),
            "en",
            now=fetched_at.timestamp(),
            burn_rate_trackers=trackers,
        )
    assert projection is not None
    assert projection.session.warning is True

    valid_quota = _quota_snapshot(started_at, session_used=95.0)
    invalid_quota = AgyQuotaResult(
        groups=valid_quota.groups,
        fetched_at="not-a-timestamp",
    )
    projection = menubar_agy.project_quota(
        invalid_quota,
        "en",
        now=started_at.timestamp(),
        burn_rate_trackers=trackers,
    )

    assert projection is not None
    assert projection.session.warning is False


def test_project_quota_does_not_warn_below_percent_floor() -> None:
    trackers = _burn_rate_trackers()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    projection = None

    for index, used in enumerate((10.0, 14.0, 18.0, 22.0, 26.0, 30.0)):
        fetched_at = started_at + timedelta(minutes=5 * index)
        projection = menubar_agy.project_quota(
            _quota_snapshot(
                fetched_at,
                session_used=used,
                session_reset_minutes=180,
            ),
            "en",
            now=fetched_at.timestamp(),
            burn_rate_trackers=trackers,
        )

    assert projection is not None
    assert projection.session.percent == 30.0
    assert projection.session.warning is False


def test_project_quota_warns_for_weekly_window_after_thirty_minute_span() -> None:
    trackers = _burn_rate_trackers()
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    projection = None

    for index, used in enumerate((50.0, 57.0, 64.0, 71.0, 78.0, 85.0, 92.0)):
        fetched_at = started_at + timedelta(minutes=5 * index)
        projection = menubar_agy.project_quota(
            _quota_snapshot(fetched_at, session_used=0.0, weekly_used=used),
            "en",
            now=fetched_at.timestamp(),
            burn_rate_trackers=trackers,
        )

    assert projection is not None
    assert projection.weekly.warning is True


@pytest.mark.parametrize(
    "age_minutes, text, used",
    [(12.0, "Reset", 0.0), (11.5, "Reset imminent", 90.0), (11.0, "Resets in 1m", 90.0)],
)
def test_window_row_reset_boundary(age_minutes: float, text: str, used: float) -> None:
    window = AgyQuotaWindow(10.0, None, 12)
    row = menubar_agy._window_row("Session", window, "en", age_minutes, forecast_seconds=10.0)
    assert row.display_percent == used
    if age_minutes >= 11.5:
        assert row.reset_text == text
        assert not row.warning
    assert window.remaining_percent == 10.0


def test_fresh_cache_with_expired_login_is_stale() -> None:
    from loaders import agy_quota_probe
    from menubar import agy

    agy_quota_probe.AUTH_EXPIRED_PATH.touch()
    now = datetime.now(UTC)
    state = agy._stale_state(now.isoformat(), now.timestamp(), "zh-TW")
    assert state is not None
    assert state["ageText"] == "登入過期"
    assert "agy" in state["tooltip"]


@pytest.mark.parametrize("weekly", [True, False])
def test_unreported_window_is_unavailable_and_not_recorded(weekly: bool) -> None:
    now = datetime.now(UTC)
    window = AgyQuotaWindow(50, "1h 0m", 60)
    group = AgyQuotaGroup(
        "GEMINI MODELS", [], window if weekly else None, None if weekly else window
    )
    trackers = _burn_rate_trackers()
    projection = menubar_agy.project_quota(
        AgyQuotaResult([group], now.isoformat()),
        "en",
        now=now.timestamp(),
        burn_rate_trackers=trackers,
    )
    assert projection is not None
    row = projection.session if weekly else projection.weekly
    assert row.available is False
    assert row.percent is None
    assert row.percent_text == "--"
    assert row.reset_text == "Not reported by Google"
    assert trackers["agy_session" if weekly else "agy_weekly"].last_timestamp is None
    assert (projection.weekly if weekly else projection.session).percent_text == "50% used"


@pytest.mark.parametrize("preference", ["gemini", "claude_gpt", "argon"])
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("GEMINI MODELS", "gemini"),
        ("CLAUDE AND GPT MODELS", "claude_gpt"),
        ("Gemini 4 Argon", "argon"),
    ],
)
def test_matches_group_keeps_three_groups_separate(
    preference: str, name: str, expected: str
) -> None:
    assert menubar_agy._matches_group(name, preference) is (preference == expected)


@pytest.mark.parametrize("remaining", [0.0, 50.0, 100.0])
@pytest.mark.parametrize(
    ("language", "detail"),
    [
        ("zh-TW", "這組只有週額度"),
        ("en", "Weekly limit only"),
        ("zh-CN", "这组只有周额度"),
        ("ja", "週間上限のみ"),
        ("ko", "주간 한도만 있음"),
    ],
)
def test_project_quota_argon_has_weekly_only(remaining: float, language: str, detail: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    quota = AgyQuotaResult(
        groups=[
            _group("GEMINI MODELS", session_remaining=40, weekly_remaining=90),
            AgyQuotaGroup(
                "GEMINI 4 ARGON", ["Gemini 4 Argon"], AgyQuotaWindow(remaining, None, 1440), None
            ),
        ],
        fetched_at=now.isoformat(),
    )
    projection = menubar_agy.project_quota(
        quota, language, now=now.timestamp(), group_preference="argon"
    )
    assert projection is not None
    assert projection.group_name == "GEMINI 4 ARGON"
    assert projection.five_hour is None
    assert projection.session.percent is None
    assert projection.session.available is False
    assert projection.session.percent_text == "--"
    assert projection.session.reset_text == detail
    assert projection.weekly.percent == 100.0 - remaining
    assert projection.weekly_only is True


def test_project_quota_missing_argon_falls_back_to_gemini() -> None:
    quota = AgyQuotaResult(
        groups=[
            _group("CLAUDE AND GPT MODELS", session_remaining=70, weekly_remaining=0),
            _group("GEMINI MODELS", session_remaining=40, weekly_remaining=90),
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    projection = menubar_agy.project_quota(
        quota, "en", now=1_767_225_600.0, group_preference="argon"
    )
    assert projection is not None
    assert projection.group_name == "GEMINI MODELS"
    assert projection.weekly_only is False
    assert projection.session.percent_text == "60% used"


def test_missing_gemini_fallback_prefers_claude_over_argon() -> None:
    quota = AgyQuotaResult(
        groups=[
            _group("GEMINI 4 ARGON", session_remaining=0, weekly_remaining=0),
            _group("CLAUDE AND GPT MODELS", session_remaining=70, weekly_remaining=70),
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    projection = menubar_agy.project_quota(quota, "en", now=1_767_225_600.0)
    assert projection is not None
    assert projection.group_name == "CLAUDE AND GPT MODELS"
