# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, tzinfo
from io import StringIO
from types import SimpleNamespace
from typing import Self

import pytest
from rich.console import Console
from rich.text import Text

from adapters.types import DailyStats, MonthlyStats, P90Limits, SessionStats, WeeklyStats
from ui import tables
from usage_common.i18n import t


@pytest.mark.parametrize(
    ("theme", "colorfgbg", "expected"),
    [
        ("light", "0;0", True),
        ("dark", "0;15", False),
        ("", "15;10", True),
        ("", "invalid", False),
        ("", "", False),
    ],
)
def test_is_light_theme_reads_theme_and_colorfgbg(
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    colorfgbg: str,
    expected: bool,
) -> None:
    if theme:
        monkeypatch.setenv("TT_THEME", theme)
    else:
        monkeypatch.delenv("TT_THEME", raising=False)
    if colorfgbg:
        monkeypatch.setenv("COLORFGBG", colorfgbg)
    else:
        monkeypatch.delenv("COLORFGBG", raising=False)

    assert tables._is_light_theme() is expected


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-opus-4-7", "Opus 4.7"),
        ("claude-sonnet-5", "Sonnet 5"),
        ("provider/model-name-that-is-long", "model-name-that-"),
        ("plain-model-name-that-is-long", "plain-model-name"),
    ],
)
def test_model_short_uses_known_names_and_truncates(model: str, expected: str) -> None:
    assert tables._model_short(model) == expected


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (999, "999"),
        (1_000, "1.0K"),
        (1_500_000, "1.5M"),
        (1_234_567_890, "1.23B"),
    ],
)
def test_fmt_tokens_scales_large_values(tokens: int, expected: str) -> None:
    assert tables._fmt_tokens(tokens) == expected


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        (None, "--"),
        (0.0, "$0"),
        (0.1234, "$0.123"),
        (1.234, "$1.23"),
        (100.4, "$100"),
    ],
)
def test_fmt_cost_uses_expected_precision(cost: float | None, expected: str) -> None:
    assert tables._fmt_cost(cost) == expected


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (59.9, "59min"),
        (125.5, "2h05m"),
    ],
)
def test_fmt_duration_formats_minutes_and_hours(minutes: float, expected: str) -> None:
    assert tables._fmt_duration(minutes) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("usage", 5),
        ("用量usage", 9),
    ],
)
def test_display_width_counts_non_ascii_as_double_width(text: str, expected: int) -> None:
    assert tables._display_width(text) == expected


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (0.5, "bold"),
        (0.51, f"bold {tables._S.warn}"),
        (0.81, f"bold {tables._S.bad}"),
    ],
)
def test_token_heat_style_uses_warning_and_bad_thresholds(
    ratio: float,
    expected: str,
) -> None:
    assert tables._token_heat_style(ratio) == expected


@pytest.mark.parametrize(
    ("pct", "expected"),
    [
        (50.0, tables._S.bar_low),
        (50.1, tables._S.bar_mid),
        (80.1, tables._S.bar_high),
    ],
)
def test_pct_style_uses_bar_thresholds(pct: float, expected: str) -> None:
    assert tables._pct_style(pct) == expected


@pytest.mark.parametrize(
    ("agent_ids", "expected"),
    [
        (["claude-code", "codex"], True),
        (["claude-code", "", None], False),
    ],
)
def test_is_multi_agent_counts_distinct_non_empty_agent_ids(
    agent_ids: list[str | None],
    expected: bool,
) -> None:
    stats = [SimpleNamespace(agent_id=agent_id) for agent_id in agent_ids]

    assert tables._is_multi_agent(stats) is expected


def test_group_by_agent_returns_lists_keyed_by_agent_id() -> None:
    claude_first = SimpleNamespace(agent_id="claude-code")
    codex = SimpleNamespace(agent_id="codex")
    claude_second = SimpleNamespace(agent_id="claude-code")

    grouped = tables._group_by_agent([claude_first, codex, claude_second])

    assert grouped == defaultdict(
        list,
        {
            "claude-code": [claude_first, claude_second],
            "codex": [codex],
        },
    )


@pytest.mark.parametrize("kind", ["daily", "weekly", "sessions"])
def test_zero_usage_tables_render(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    output = StringIO()
    monkeypatch.setattr(tables, "console", Console(file=output, width=140))
    if kind == "daily":
        tables.render_daily([DailyStats("2026-11-04")])
    elif kind == "weekly":
        tables.render_weekly([WeeklyStats("2026-W45")])
    else:
        tables.render_sessions([_session(datetime(2026, 11, 4, tzinfo=UTC))])
    assert "0" in output.getvalue()


def _session(start: datetime) -> SessionStats:
    return SessionStats(
        session_id="test",
        project="test",
        model="test",
        start_time=start,
        end_time=start,
        duration_minutes=0,
    )


@pytest.fixture
def taipei_timezone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if not hasattr(time, "tzset"):
        pytest.skip("requires time.tzset")
    try:
        with monkeypatch.context() as zone_patch:
            zone_patch.setenv("TZ", "Asia/Taipei")
            time.tzset()
            yield
    finally:
        time.tzset()


def test_rate_bar_shows_local_reset_time(taipei_timezone: None) -> None:
    lines = Text()
    reset = datetime(2026, 11, 4, 2, tzinfo=UTC)
    tables._render_rate_bar(lines, "5h", 20, int(reset.timestamp()), 20)
    assert "10:00" in lines.plain


@pytest.mark.parametrize("recent", [False, True])
def test_session_tables_show_local_time(
    monkeypatch: pytest.MonkeyPatch, taipei_timezone: None, recent: bool
) -> None:
    output = StringIO()
    monkeypatch.setattr(tables, "console", Console(file=output, width=140))
    session = _session(datetime(2026, 11, 4, 2, tzinfo=UTC))
    session.total_tokens = 10
    render = tables._render_recent_sessions if recent else tables.render_sessions
    render([session])
    assert "11-04 10:00" in output.getvalue()


@pytest.mark.parametrize("section", ["week", "month", "daily"])
def test_daily_averages_use_local_calendar(
    monkeypatch: pytest.MonkeyPatch, taipei_timezone: None, section: str
) -> None:
    # Taipei Monday, June 1 00:30; UTC is still Sunday, May 31.
    fixed = datetime(2026, 5, 31, 16, 30, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp(fixed.timestamp(), tz)

    monkeypatch.setattr(tables, "datetime", Clock)
    output = StringIO()
    monkeypatch.setattr(tables, "console", Console(file=output, width=140))
    week = WeeklyStats("2026-W23", total_tokens=7000, cost_usd=7)
    expected = t("daily_avg", cost="$7.00")
    if section == "week":
        lines = Text()
        tables._render_week_section(lines, week)
        rendered = lines.plain
    elif section == "month":
        tables._render_month_overview(MonthlyStats("2026-06", cost_usd=7))
        rendered = output.getvalue()
        expected = t("daily_avg_colon") + "$7.00"
    else:
        tables._render_daily_panel(DailyStats("2026-06-01"), None, P90Limits(), week)
        rendered = output.getvalue()
    assert expected in rendered
    if section != "month":
        assert t("rate_per_day", rate="7.0K") in rendered
