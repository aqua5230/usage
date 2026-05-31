from __future__ import annotations

import subprocess
import sys
import webbrowser
from datetime import date
from pathlib import Path
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


def test_save_and_open_uses_macos_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> None:
        calls.append(command)
        assert check is False

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        webbrowser,
        "open",
        lambda url: pytest.fail(f"unexpected webbrowser.open({url})"),
    )

    display_path = html_report.save_and_open(_report_data())

    assert display_path.startswith("~/.usage-reports/usage-report-")
    assert calls
    assert calls[0][0] == "/usr/bin/open"
    assert calls[0][1].startswith(str(tmp_path / ".usage-reports"))


def test_generate_html_uses_explicit_language_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_LANG", "en")

    report = html_report.generate_html(_report_data(), language="zh-TW")

    assert '<html lang="zh-TW">' in report
    assert "壓縮對話節省 token" in report


def test_generate_html_includes_persona_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    data = _report_data()
    histogram = [0] * 24
    histogram[14] = 5
    data["persona"] = {
        "hour_histogram": histogram,
        "recent_titles": ["Fix <persona> report", "Keep English Title"],
    }

    report = html_report.generate_html(data)

    assert "使用習慣" in report
    assert "活躍時段" in report
    assert "你最常在 14:00 與 AI 協作" in report
    assert "14:00 5" in report
    assert '<div class="persona-hour is-peak" title="14:00 5"' in report
    assert "最近在忙什麼" not in report
    assert "Fix &lt;persona&gt; report" not in report
    assert "Keep English Title" not in report
    assert "persona-grid" not in report


def test_generate_html_handles_missing_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    data = _report_data()
    data["persona"] = None

    report = html_report.generate_html(data)

    assert "使用習慣" in report
    assert "這段期間還沒有足夠資料" in report
    assert '<div class="persona-hours">' not in report
    assert '<ul class="persona-titles">' not in report
