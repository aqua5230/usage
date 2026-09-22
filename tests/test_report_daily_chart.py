from __future__ import annotations

from ui.report_daily_chart import (
    daily_usage,
    pricing_usage,
    render_daily_chart,
    render_pricing_body,
)


def _cube(rows: list[list[object]], dates: list[str] | None = None) -> dict[str, object]:
    return {
        "dates": dates if dates is not None else ["2026-05-01"],
        "agents": [{"id": "claude-code", "name": "Claude Code"}],
        "models": [
            {"name": "priced", "cost_known": True},
            {"name": "unknown", "cost_known": False},
        ],
        "rows": rows,
    }


def _t(key: str) -> str:
    return key


def _tokens(value: int) -> str:
    return str(value)


def _display_name(value: str) -> str:
    return "未知" if value == "unknown" else value


def test_daily_usage_handles_empty_and_single_day() -> None:
    assert daily_usage(_cube([], [])) == (
        [],
        [
            {
                "id": "claude-code",
                "name": "Claude Code",
                "color": "#5abfa0",
                "tokens": [],
                "cost": [],
            }
        ],
    )
    dates, agents = daily_usage(_cube([[0, 0, 0, 0, 1, 2, 3, 4, 1.25, 1]]))
    assert dates == ["2026-05-01"]
    assert agents[0]["tokens"] == [10]
    assert agents[0]["cost"] == [1.25]


def test_daily_chart_empty_and_all_zero_are_empty_states() -> None:
    assert 'class="empty"' in render_daily_chart(_cube([], []), _t, _tokens, str)
    zero = _cube([[0, 0, 0, 0, 0, 0, 0, 0, 0, 1]])
    assert 'class="empty"' in render_daily_chart(zero, _t, _tokens, str)


def test_daily_chart_compacts_over_120_days_and_single_tool() -> None:
    dates = (
        [f"2026-01-{day:02d}" for day in range(1, 32)]
        + [f"2026-02-{day:02d}" for day in range(1, 32)]
        + [f"2026-03-{day:02d}" for day in range(1, 32)]
        + [f"2026-04-{day:02d}" for day in range(1, 31)]
    )
    cube = _cube([[index, 0, 0, 0, 1, 0, 0, 0, 0, 1] for index in range(len(dates))], dates)
    html = render_daily_chart(cube, _t, _tokens, str)
    assert html.count('class="daily-segment"') == len(dates)
    assert 'width="5.72"' in html
    assert html.count("daily-legend-item") == 1


def test_daily_chart_centers_55_percent_bars_for_31_or_fewer_days() -> None:
    dates = [f"2026-05-{day:02d}" for day in range(1, 6)]
    cube = _cube([[index, 0, 0, 0, 1, 0, 0, 0, 0, 1] for index in range(5)], dates)

    html = render_daily_chart(cube, _t, _tokens, str)

    assert 'preserveAspectRatio="none"' in html
    assert html.count('vector-effect="non-scaling-stroke"') == 3
    assert "<text " not in html
    assert 'width="77.44"' in html
    assert 'x="79.68"' in html
    assert 'class="daily-chart-label daily-y-label"' in html


def test_pricing_usage_and_body_cover_priced_and_unpriced() -> None:
    priced = _cube([[0, 0, 0, 0, 2, 0, 0, 0, 1, 1]])
    assert pricing_usage(priced) == (2, 0, [])
    assert "pricing_all_priced" in render_pricing_body(2, 0, [], _t, _tokens, _display_name, "、")
    mixed = _cube(
        [
            [0, 0, 0, 0, 2, 0, 0, 0, 1, 1],
            [0, 0, 1, 0, 3, 0, 0, 0, 0, 1],
        ]
    )
    assert pricing_usage(mixed) == (2, 3, ["unknown"])
    body = render_pricing_body(2, 3, ["unknown"], _t, _tokens, _display_name, "、")
    assert "40.0%" in body and "60.0%" in body and "未知" in body
    assert 'class="pricing-bar-labels"' not in body
    assert '<span class="pricing-models">未知</span>' in body
