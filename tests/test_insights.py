from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from analyzer.insights import build_insights


def _daily(tokens: list[int]) -> list[dict[str, Any]]:
    return [
        {"date": f"2026-05-{index:02d}", "tokens": value, "cost": value / 100}
        for index, value in enumerate(tokens, 1)
    ]


def _daily_from(start: date, tokens: list[int]) -> list[dict[str, Any]]:
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "tokens": value,
            "cost": value / 100,
        }
        for index, value in enumerate(tokens)
    ]


def _payload() -> dict[str, Any]:
    return {
        "date_from": "2026-05-01",
        "date_to": "2026-05-21",
        "summary": {
            "total_tokens": 1800,
            "cost_usd": 9.25,
            "sessions": 39,
            "messages": 120,
            "active_days": 3,
            "total_days": 21,
        },
        "by_project": [
            {"project": "new-work", "tokens": 450, "cost": 2.0, "sessions": 8, "pct": 25.0},
            {"project": "usage", "tokens": 1350, "cost": 7.25, "sessions": 31, "pct": 75.0},
        ],
        "by_model": [
            {"model": "gpt-5-codex", "tokens": 1260, "cost": 6.5, "pct": 70.0},
            {"model": "gpt-5-mini", "tokens": 540, "cost": 2.75, "pct": 30.0},
        ],
        "daily_trend": _daily(
            [
                100,
                100,
                100,
                100,
                100,
                100,
                100,
                200,
                200,
                200,
                200,
                200,
                200,
                200,
                3000,
                100,
                100,
                100,
                100,
                100,
                100,
            ]
        ),
        "comparison": {
            "period": "week",
            "has_prev": True,
            "prev_tokens": 1000,
            "prev_cost": 5.0,
            "prev_projects": ["usage"],
            "prev_model_share": {"gpt-5-codex": 40.0, "gpt-5-mini": 60.0},
        },
    }


def test_build_insights_golden_output_is_deterministic() -> None:
    assert build_insights(_payload()) == [
        {
            "type": "change_headline",
            "key": "insights_change_up",
            "tokens": 1800,
            "cost_usd": 9.25,
            "pct": 80,
            "direction": "up",
            "delta_pct": 80,
        },
        {
            "type": "spike",
            "key": "insights_spike_v2",
            "date": "2026-05-15",
            "tokens": 3000,
            "mean_multiplier": 11.05,
        },
        {
            "type": "shift",
            "key": "insights_shift_new_project",
            "project": "new-work",
            "pct": 25.0,
        },
        {
            "type": "pace_note",
            "key": "insights_pace_dense",
            "active_days": 3,
            "sessions": 39,
            "per_day": 13,
        },
        {"type": "action", "key": "insights_action_watch_quota"},
    ]


def test_change_headline_skips_without_previous_period() -> None:
    payload = _payload()
    payload["comparison"] = {"period": "today", "has_prev": False}

    assert not any(
        component["type"] == "change_headline" for component in build_insights(payload)
    )


def test_change_headline_skips_when_previous_tokens_are_zero() -> None:
    payload = _payload()
    payload["comparison"]["prev_tokens"] = 0

    assert not any(
        component["type"] == "change_headline" for component in build_insights(payload)
    )


def test_spike_skips_without_clear_spike() -> None:
    payload = _payload()
    payload["daily_trend"] = _daily([100, 110, 105, 100])

    assert not any(component["type"] == "spike" for component in build_insights(payload))


def test_shift_skips_without_signal() -> None:
    payload = _payload()
    payload["by_project"] = [
        {"project": "usage", "tokens": 1800, "cost": 9.25, "sessions": 39, "pct": 100.0}
    ]
    payload["by_model"] = [
        {"model": "gpt-5-codex", "tokens": 900, "cost": 4.0, "pct": 50.0}
    ]
    payload["comparison"]["prev_model_share"] = {"gpt-5-codex": 45.0}
    payload["daily_trend"] = _daily_from(date(2026, 5, 4), [100] * 14)

    assert not any(component["type"] == "shift" for component in build_insights(payload))


def test_pace_note_skips_when_sessions_are_sparse() -> None:
    payload = _payload()
    payload["summary"]["sessions"] = 20
    payload["summary"]["active_days"] = 2

    assert not any(component["type"] == "pace_note" for component in build_insights(payload))


def test_action_skips_without_quota_or_spike_signal() -> None:
    payload = _payload()
    payload["summary"]["total_tokens"] = 1040
    payload["comparison"]["prev_tokens"] = 1000
    payload["daily_trend"] = _daily([100, 110, 105, 100])

    assert not any(component["type"] == "action" for component in build_insights(payload))


def test_change_headline_emits_up_down_and_flat() -> None:
    cases = [
        (1100, "insights_change_up", 10),
        (900, "insights_change_down", 10),
        (1040, "insights_change_flat", 4),
    ]
    for tokens, key, pct in cases:
        payload = _payload()
        payload["summary"]["total_tokens"] = tokens

        change = build_insights(payload)[0]

        assert change["type"] == "change_headline"
        assert change["key"] == key
        assert change["pct"] == pct


def test_shift_new_project_takes_priority_over_model_and_trend() -> None:
    shift = next(
        component for component in build_insights(_payload()) if component["type"] == "shift"
    )

    assert shift["key"] == "insights_shift_new_project"


def test_shift_model_takes_priority_over_trend() -> None:
    payload = _payload()
    payload["by_project"] = [
        {"project": "usage", "tokens": 1800, "cost": 9.25, "sessions": 39, "pct": 100.0}
    ]

    shift = next(
        component for component in build_insights(payload) if component["type"] == "shift"
    )

    assert shift == {
        "type": "shift",
        "key": "insights_shift_model_up",
        "model": "gpt-5-codex",
        "prev_pct": 40.0,
        "pct": 70.0,
    }


def test_shift_trend_up_and_down() -> None:
    payload = _payload()
    payload["by_project"] = [
        {"project": "usage", "tokens": 1800, "cost": 9.25, "sessions": 39, "pct": 100.0}
    ]
    payload["by_model"] = [
        {"model": "gpt-5-codex", "tokens": 900, "cost": 4.0, "pct": 50.0}
    ]
    payload["comparison"]["prev_model_share"] = {"gpt-5-codex": 45.0}
    payload["daily_trend"] = _daily_from(
        date(2026, 5, 4),
        [100] * 7 + [200] * 7 + [300] * 7,
    )

    shift = next(
        component for component in build_insights(payload) if component["type"] == "shift"
    )
    assert shift == {"type": "shift", "key": "insights_shift_trend_up"}

    payload["daily_trend"] = _daily_from(date(2026, 5, 4), [200] * 7 + [100] * 7)
    shift = next(
        component for component in build_insights(payload) if component["type"] == "shift"
    )
    assert shift == {"type": "shift", "key": "insights_shift_trend_down"}


def test_action_smooth_spike_is_used_when_quota_watch_does_not_apply() -> None:
    payload = _payload()
    payload["summary"]["total_tokens"] = 1100

    action = next(
        component for component in build_insights(payload) if component["type"] == "action"
    )

    assert action == {
        "type": "action",
        "key": "insights_action_smooth_spike",
        "date": "2026-05-15",
    }
