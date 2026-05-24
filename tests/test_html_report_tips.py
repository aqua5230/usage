from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import tips_loader
from ui import html_report


class _FixedDate:
    """Pin date.today() so tip rotation is deterministic in tests.

    tips_loader picks `commands[date.today().toordinal() % len(commands)]`;
    2026-05-24 lands on index 0 (/compact), which the tip-content assertions
    below depend on.
    """

    @staticmethod
    def today() -> date:
        return date(2026, 5, 24)


@pytest.fixture(autouse=True)
def _pin_tip_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tips_loader, "date", _FixedDate)


def _report_data() -> dict[str, Any]:
    return {
        "period_label": "2026-05-01 -> 2026-05-23",
        "summary": {
            "total_tokens": 123456,
            "cost_usd": 12.34,
            "sessions": 8,
            "messages": 64,
            "active_days": 10,
            "total_days": 23,
        },
        "by_project": [
            {"project": "usage", "pct": 100.0, "tokens": 123456, "cost": 12.34},
        ],
        "by_model": [
            {"model": "claude-sonnet-4", "pct": 100.0, "tokens": 123456, "cost": 12.34},
        ],
        "daily_trend": [
            {"date": "2026-05-20", "tokens": 10000, "cost": 1.23},
            {"date": "2026-05-21", "tokens": 12000, "cost": 1.45},
            {"date": "2026-05-22", "tokens": 15000, "cost": 1.67},
        ],
        "top_sessions": [
            {
                "start_time": "2026-05-22 10:00",
                "project": "usage",
                "model": "claude-sonnet-4",
                "duration_min": 90.0,
                "tokens": 45678,
                "cost": 4.56,
            }
        ],
    }


def test_generate_html_includes_compact_tip_in_zh_tw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")

    report = html_report.generate_html(_report_data())

    assert "/compact" in report
    assert "💡 本期 Claude 進階指令" in report


def test_generate_html_includes_all_tip_headings_in_zh_tw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")

    report = html_report.generate_html(_report_data())

    for heading in ("這個指令做什麼？", "什麼時候用？", "怎麼用？", "保留 / 丟掉", "實際情境"):
        assert heading in report


def test_generate_html_switches_tip_content_by_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    zh_report = html_report.generate_html(_report_data())

    monkeypatch.setenv("USAGE_LANG", "en")
    en_report = html_report.generate_html(_report_data())

    assert "壓縮對話節省 token" in zh_report
    assert "Compress the chat to save tokens" in en_report
    assert "把你目前跟 Claude 的對話『壓縮』成一份摘要。" in zh_report
    assert "This turns your current conversation with Claude into a shorter summary." in en_report
