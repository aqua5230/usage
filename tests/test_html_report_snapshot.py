from __future__ import annotations

from datetime import UTC, date, datetime, tzinfo
from pathlib import Path
from typing import Any

import pytest

import tips_loader
from ui import html_report

SNAPSHOT_DIR = Path(__file__).resolve().parent / "fixtures" / "html_report_snapshots"


class _FixedTipDate:
    @staticmethod
    def today() -> date:
        return date(2026, 5, 24)


class _FixedDateTime:
    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        fixed = datetime(2026, 5, 24, 10, 30, 45, tzinfo=UTC)
        return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _pin_nondeterministic_report_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tips_loader, "date", _FixedTipDate)
    monkeypatch.setattr(html_report, "datetime", _FixedDateTime)
    monkeypatch.setattr(html_report, "_version", lambda: "0.15.8")


def _full_report_data() -> dict[str, Any]:
    histogram = [0] * 24
    histogram[9] = 2
    histogram[14] = 7
    histogram[21] = 5
    return {
        "period_label": "2026-05-01 -> 2026-05-23",
        "summary": {
            "total_tokens": 2345678,
            "cost_usd": 45.6789,
            "sessions": 42,
            "messages": 314,
            "active_days": 18,
            "total_days": 23,
        },
        "by_agent": [
            {"name": "Claude", "pct": 62.5, "tokens": 1466049, "cost": 28.55},
            {"name": "Codex", "pct": 37.5, "tokens": 879629, "cost": 17.13},
        ],
        "subscriptions": [
            {"agent": "Claude", "plan": "Max", "since": "2026-01-15"},
            {"agent": "Codex", "plan": "Plus", "since": "2026-03-02"},
            {"agent": "Gemini", "plan": "Pro", "since": "2026-04-10"},
        ],
        "by_project": [
            {"project": "usage", "pct": 70.2, "tokens": 1646859, "cost": 32.07},
            {"project": "client<portal>", "pct": 20.1, "tokens": 471482, "cost": 9.18},
            {"project": "unknown", "pct": 9.7, "tokens": 227337, "cost": 4.43},
        ],
        "by_model": [
            {"model": "claude-sonnet-4", "pct": 52.4, "tokens": 1229345, "cost": 23.91},
            {"model": "gpt-5-codex", "pct": 36.6, "tokens": 858918, "cost": 16.70},
            {"model": "unknown", "pct": 11.0, "tokens": 258415, "cost": 5.07},
        ],
        "daily_trend": [
            {"date": "2026-05-04", "tokens": 120000, "cost": 2.34},
            {"date": "2026-05-05", "tokens": 180000, "cost": 3.45},
            {"date": "2026-05-12", "tokens": 260000, "cost": 5.12},
            {"date": "2026-05-13", "tokens": 300000, "cost": 6.01},
            {"date": "2026-05-20", "tokens": 140000, "cost": 2.87},
        ],
        "persona": {
            "hour_histogram": histogram,
            "recent_titles": ["Ship HTML report", "Ignore in current renderer"],
        },
        "top_sessions": [
            {
                "start_time": "2026-05-20 09:15",
                "project": "usage",
                "model": "claude-sonnet-4",
                "duration_min": 125.5,
                "tokens": 98765,
                "cost": 8.91,
            },
            {
                "start_time": "2026-05-21 21:05",
                "project": "client<portal>",
                "model": "gpt-5-codex",
                "duration_min": 35.0,
                "tokens": 45678,
                "cost": 4.56,
            },
        ],
    }


def _empty_report_data() -> dict[str, Any]:
    return {
        "period_label": "empty-window",
        "summary": {
            "total_tokens": 0,
            "cost_usd": 0.0,
            "sessions": 0,
            "messages": 0,
            "active_days": 0,
            "total_days": 7,
        },
        "by_agent": [],
        "subscriptions": [],
        "by_project": [],
        "by_model": [],
        "daily_trend": [],
        "persona": {"hour_histogram": []},
        "top_sessions": [],
    }


@pytest.mark.parametrize(
    ("name", "data", "language"),
    [
        ("full_zh_tw", _full_report_data(), "zh-TW"),
        ("full_en", _full_report_data(), "en"),
        ("empty_zh_tw", _empty_report_data(), "zh-TW"),
    ],
)
def test_generate_html_matches_golden_snapshot(
    name: str,
    data: dict[str, Any],
    language: str,
) -> None:
    expected = (SNAPSHOT_DIR / f"{name}.html").read_text(encoding="utf-8")

    assert html_report.generate_html(data, language=language) == expected
