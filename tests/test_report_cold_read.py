from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest

from analyzer import reporter
from analyzer.reporter import DailyTrendPoint
from ui import html_report
from ui.report_daily_chart import nice_ticks
from ui.report_ledger import format_pct


@pytest.fixture(autouse=True)
def utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "UTC")
    if hasattr(time, "tzset"):
        time.tzset()
    yield
    if original is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", original)
    if hasattr(time, "tzset"):
        time.tzset()


def daily(start: date, days: int) -> list[DailyTrendPoint]:
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "tokens": 100, "cost": 0.0}
        for i in range(days)
    ]


def test_summary_names_last_complete_week() -> None:
    weeks = html_report._weekly_trend(daily(date(2026, 8, 3), 17))
    result = html_report._trend_summary(weeks, "zh-TW", date(2026, 8, 19))
    assert "上個完整週（W33）" in result
    assert "本週" not in result


@pytest.mark.parametrize(
    "start,days,partial",
    [
        (date(2026, 8, 1), 9, True),
        (date(2026, 8, 3), 14, False),
        (date(2026, 8, 1), 1, True),
    ],
)
def test_partial_week_does_not_drive_next_delta(start: date, days: int, partial: bool) -> None:
    result = html_report._trend_ascii(daily(start, days), "en", start + timedelta(days=days - 1))
    assert ("only" in result) is partial
    if days > 7:
        second = result.split('class="trend-row"')[2].split('class="trend-summary"')[0]
        assert ('class="delta flat"></span>' in second) is partial
        if partial:
            assert "Fewer than two complete weeks" in result


@pytest.mark.parametrize(
    "value,expected",
    [(0.001, "<0.1%"), (0.099, "<0.1%"), (0.1, "about 0.1%"), (0, "about 0.0%"), (None, "—")],
)
def test_quota_small_values(value: float | None, expected: str) -> None:
    assert format_pct(value, "en") == expected


@pytest.mark.parametrize(
    "claude,codex,beast,dominant",
    [
        (199, 100, "phoenix", False),
        (200, 100, "phoenix", True),
        (100, 199, "dragon", False),
        (100, 200, "dragon", True),
        (1, 0, "phoenix", True),
        (0, 1, "dragon", True),
        (0, 0, "phoenix", False),
    ],
)
def test_wrapped_dominance(claude: int, codex: int, beast: str, dominant: bool) -> None:
    result = html_report._render_wrapped_section(
        {
            "wrapped": {
                "beast": beast,
                "claude_tokens": claude,
                "codex_tokens": codex,
            }
        },
        "zh-TW",
    )
    assert ("遙遙領先" in result) is dominant


@pytest.mark.parametrize(
    "peak,ceiling",
    [
        (1_040_000_000, 1_200_000_000),
        (900_000_000, 1_000_000_000),
        (0, 0),
        (1_000_000_000, 1_200_000_000),
        (999, 1000),
    ],
)
def test_axis_ceiling(peak: int, ceiling: int) -> None:
    assert nice_ticks(peak)[-1] == ceiling


def test_composition_missing_and_no_missing() -> None:
    for total, visible in [(150, True), (100, False)]:
        result = html_report._render_composition_section(
            {
                "summary": {
                    "total_tokens": total,
                    "input_tokens": 100,
                }
            },
            "en",
        )
        assert ("data-composition-missing hidden" not in result) is visible
        if visible:
            assert "Another 50 tokens" in result


def test_year_cost_scope_and_grid() -> None:
    day = {
        "total_tokens": 1,
        "cost": 0.0,
        "sessions": 0,
        "model_tokens": {},
        "project_tokens": {},
        "agent_tokens": {},
    }
    ledger: Any = {
        "schema_version": 1,
        "days": {"2026-08-01": day, "2026-08-02": {**day, "cost": 2.0}},
    }
    output = reporter._build_year_output_from_ledger(
        ledger, grid_start=date(2026, 8, 1), grid_end=date(2026, 8, 7), today=date(2026, 8, 7)
    )
    assert output["wrapped"]["cost_recorded_from"] == "2026-08-02"
    assert output["wrapped"]["total_cost"] == 2.0
    assert "1-week contribution heatmap" in html_report._render_contribution_section(output, "en")


def test_history_scope_requires_earlier_nonzero_totals() -> None:
    data: Any = {
        "cube": {"dates": ["2026-08-01", "2026-10-16"]},
        "contribution": {"weeks": [[{"date": "2026-04-21", "tokens": 1}]]},
    }
    assert "Per-tool records start on 2026-08-01" in html_report._date_filter(data, "en")
    data["contribution"]["weeks"][0][0]["tokens"] = 0
    assert "data-history-note" not in html_report._date_filter(data, "en")


def test_dispatch_ledger_follows_fixed_group_note() -> None:
    from tests.test_html_report_snapshot import _full_report_data

    data: Any = _full_report_data()
    data["dispatch_ledger"] = {
        "rows": [
            {
                "date": "2026-10-16",
                "project": "sample",
                "title": "dispatch",
                "dispatch_count": 1,
                "claude_pct": 0.01,
                "codex_pct": 0.01,
                "agy_groups": {},
                "codex_reset": False,
            }
        ]
    }
    result = html_report.generate_html(data, language="en")
    assert result.index('class="fixed-group-note"') < result.index("dispatch-ledger-section")
    assert "&lt;0.1%" in result


@pytest.mark.parametrize("lang", ["zh-TW", "en", "zh-CN", "ja", "ko"])
def test_cold_read_labels_and_active_day_definition(lang: str) -> None:
    from tests.test_html_report_snapshot import _full_report_data

    data: Any = _full_report_data()
    result = html_report.generate_html(data, language=lang)
    for key in (
        "session_section",
        "share",
        "pricing_section",
        "pricing_priced",
        "wrapped_books_hint",
    ):
        assert html_report._t(lang, key) in result
    hint = html_report._t(lang, "kpi_active_hint")
    assert f"<i>{hint}</i>" in result
    assert f'"kpiActiveHint": "{hint}"' in result
    assert "shareConfig.kpiActiveHint" in result
    data.pop("cube")
    assert html_report._summary_cards(data, lang)[2][2] == hint


@pytest.mark.parametrize("codex,agy", [(0, 0), (3, 0), (0, 4), (3, 4)])
def test_ledger_without_quota_shares_omits_unowned_counts(codex: int, agy: int) -> None:
    from ui.report_ledger import render_ledger

    assert (
        render_ledger(
            {"dispatch_ledger": {"rows": [], "unowned_codex": codex, "unowned_agy": agy}},
            "zh-TW",
        )
        == ""
    )
