# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import base64
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any

import pytest

from ui import html_report

SNAPSHOT_DIR = Path(__file__).resolve().parent / "fixtures" / "html_report_snapshots"


class _FixedDateTime:
    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        fixed = datetime(2026, 5, 24, 10, 30, 45, tzinfo=UTC)
        return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _pin_nondeterministic_report_values(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setattr(html_report, "datetime", _FixedDateTime)
    monkeypatch.setattr(html_report, "_version", lambda: "0.15.8")
    # generate_html renders the local timezone abbreviation via %Z, which varies
    # by machine (CST locally, UTC on CI). Pin it so the golden is portable.
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        yield
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()


def _full_report_data() -> dict[str, Any]:
    histogram = [0] * 24
    histogram[9] = 2
    histogram[14] = 7
    histogram[21] = 5
    contribution_weeks = [
        [
            {"date": "2026-04-26", "tokens": 0, "level": 0},
            {"date": "2026-04-27", "tokens": 0, "level": 0},
            {"date": "2026-04-28", "tokens": 12000, "level": 1},
            {"date": "2026-04-29", "tokens": 0, "level": 0},
            {"date": "2026-04-30", "tokens": 25000, "level": 2},
            {"date": "2026-05-01", "tokens": 40000, "level": 2},
            {"date": "2026-05-02", "tokens": 0, "level": 0},
        ],
        [
            {"date": "2026-05-03", "tokens": 60000, "level": 3},
            {"date": "2026-05-04", "tokens": 120000, "level": 3},
            {"date": "2026-05-05", "tokens": 180000, "level": 3},
            {"date": "2026-05-06", "tokens": 0, "level": 0},
            {"date": "2026-05-07", "tokens": 90000, "level": 3},
            {"date": "2026-05-08", "tokens": 0, "level": 0},
            {"date": "2026-05-09", "tokens": 0, "level": 0},
        ],
        [
            {"date": "2026-05-10", "tokens": 70000, "level": 3},
            {"date": "2026-05-11", "tokens": 110000, "level": 3},
            {"date": "2026-05-12", "tokens": 260000, "level": 4},
            {"date": "2026-05-13", "tokens": 300000, "level": 4},
            {"date": "2026-05-14", "tokens": 150000, "level": 3},
            {"date": "2026-05-15", "tokens": 0, "level": 0},
            {"date": "2026-05-16", "tokens": 0, "level": 0},
        ],
        [
            {"date": "2026-05-17", "tokens": 50000, "level": 2},
            {"date": "2026-05-18", "tokens": 0, "level": 0},
            {"date": "2026-05-19", "tokens": 0, "level": 0},
            {"date": "2026-05-20", "tokens": 140000, "level": 3},
            {"date": "2026-05-21", "tokens": 80000, "level": 3},
            {"date": "2026-05-22", "tokens": 95000, "level": 3},
            {"date": "2026-05-23", "tokens": 100000, "level": 3},
        ],
    ]
    return {
        "period_label": "2026-05-01 -> 2026-05-23",
        "summary": {
            "total_tokens": 2345678,
            "cost_usd": 45.6789,
            "sessions": 252,
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
        "comparison": {
            "period": "month",
            "has_prev": True,
            "prev_tokens": 1500000,
            "prev_cost": 30.0,
            "prev_projects": ["client<portal>", "unknown"],
            "prev_model_share": {"claude-sonnet-4": 45.0, "gpt-5-codex": 42.0},
        },
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
        "ai_updates": [
            {
                "id": "claude_code",
                "name": "Claude Code",
                "versions": [
                    {
                        "version": "2.1.183",
                        "period": "2026-06-17 ~ 2026-06-19",
                        "items": [
                            {
                                "title": {
                                    "zh-TW": "改設定不再怕手滑",
                                    "en": "Settings are easier to keep",
                                },
                                "body": {
                                    "zh-TW": "Esc 會存檔後關閉。",
                                    "en": "Esc now saves and closes.",
                                },
                                "original": "Changed /config toggle behavior.",
                            },
                            {
                                "title": {
                                    "zh-TW": "更安全：自動執行時攔下危險指令",
                                    "en": "Safer auto mode: blocks destructive commands",
                                },
                                "body": {
                                    "zh-TW": "自動模式會先擋掉危險指令。",
                                    "en": "Auto mode now blocks destructive commands first.",
                                },
                                "original": "Improved auto mode safety.",
                            },
                        ],
                    },
                    {
                        "version": "2.1.182",
                        "period": "2026-06-10 ~ 2026-06-16",
                        "items": [
                            {
                                "title": {
                                    "zh-TW": "舊版設定面板更穩",
                                    "en": "The older settings panel is steadier",
                                },
                                "body": {
                                    "zh-TW": "切換主題時不再跳動。",
                                    "en": "Theme switching no longer flickers.",
                                },
                                "original": "Stabilized the settings panel.",
                            }
                        ],
                    },
                ],
            },
            {
                "id": "codex",
                "name": "Codex",
                "versions": [
                    {
                        "version": "0.141.0",
                        "period": "2026-06-18",
                        "items": [
                            {
                                "title": {"en": "Remote work keeps the remote machine's shell."},
                                "body": {"en": "Native directories and shells are preserved."},
                                "original": (
                                    "Cross-platform remote execution now preserves "
                                    "executor-native working directories and shells, "
                                    "including filesystem permission paths across "
                                    "app-server and exec-server boundaries."
                                ),
                            }
                        ],
                    },
                    {
                        "version": "0.140.9",
                        "period": "2026-06-12",
                        "items": [
                            {
                                "title": {"en": "Remote sessions reconnect more reliably."},
                                "body": {"en": "Recovery is smoother after transient disconnects."},
                                "original": "Improved reconnect handling.",
                            }
                        ],
                    },
                ],
            },
            {
                "id": "agy",
                "name": "Antigravity",
                "versions": [
                    {
                        "version": "1.0.10",
                        "period": "2026-06-13 ~ 2026-06-19",
                        "items": [
                            {
                                "title": {"en": "Built-in guides are one ask away."},
                                "body": {
                                    "en": "The antigravity_guide skill opens docs in context."
                                },
                                "original": (
                                    "Added antigravity_guide builtin skill to provide "
                                    "instant, in-context reference guides for the "
                                    "Antigravity 2.0, CLI, IDE, and SDK."
                                ),
                            }
                        ],
                    },
                    {
                        "version": "1.0.9",
                        "period": "2026-06-06 ~ 2026-06-12",
                        "items": [
                            {
                                "title": {"en": "Task drawer opens faster."},
                                "body": {"en": "Background task details render with less lag."},
                                "original": "Optimized task drawer rendering.",
                            }
                        ],
                    },
                ],
            },
        ],
        "contribution": {
            "weeks": contribution_weeks,
            "start": "2026-04-26",
            "end": "2026-05-23",
            "max_tokens": 300000,
            "total_tokens": 1842000,
            "active_days": 15,
            "current_streak": 4,
            "longest_streak": 5,
            "busiest_day": {"date": "2026-05-13", "tokens": 300000},
        },
        "wrapped": {
            "year_label": "2026",
            "total_tokens": 2345678,
            "total_cost": 45.6789,
            "active_days": 118,
            "total_sessions": 252,
            "top_model": "claude-sonnet-4",
            "top_project": "usage",
            "busiest_day": {"date": "2026-05-13", "tokens": 300000},
            "longest_streak": 11,
            "claude_tokens": 1466049,
            "codex_tokens": 879629,
            "beast": "phoenix",
        },
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
        "comparison": {"period": "week", "has_prev": False},
        "persona": {"hour_histogram": []},
        "top_sessions": [],
        "contribution": {
            "weeks": [],
            "start": "2026-05-18",
            "end": "2026-05-24",
            "max_tokens": 0,
            "total_tokens": 0,
            "active_days": 0,
            "current_streak": 0,
            "longest_streak": 0,
            "busiest_day": None,
        },
        "wrapped": {
            "year_label": "2026",
            "total_tokens": 0,
            "total_cost": 0.0,
            "active_days": 0,
            "total_sessions": 0,
            "top_model": None,
            "top_project": None,
            "busiest_day": None,
            "longest_streak": 0,
            "claude_tokens": 0,
            "codex_tokens": 0,
            "beast": None,
        },
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


def test_sprite_data_uri_reads_py2app_resourcepath_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phoenix_png = b"bundle phoenix"
    dragon_png = b"bundle dragon"
    (tmp_path / "critters" / "phoenix").mkdir(parents=True)
    (tmp_path / "critters" / "dragon").mkdir(parents=True)
    (tmp_path / "critters" / "phoenix" / "wrapped.png").write_bytes(phoenix_png)
    (tmp_path / "critters" / "dragon" / "wrapped.png").write_bytes(dragon_png)
    monkeypatch.setenv("RESOURCEPATH", str(tmp_path))

    html_report._sprite_data_uri.cache_clear()
    try:
        data_uri = html_report._sprite_data_uri("phoenix")
    finally:
        html_report._sprite_data_uri.cache_clear()

    prefix = "data:image/png;base64,"
    assert data_uri.startswith(prefix)
    assert base64.b64decode(data_uri.removeprefix(prefix)) == phoenix_png


def test_build_csv_data_contains_projects_and_models() -> None:
    csv_text = html_report._build_csv_data(_full_report_data(), "en")

    assert "type,name,share_pct,tokens,cost_usd\r\n" in csv_text
    assert "project,usage,70.2,1646859,32.07\r\n" in csv_text
    assert "project,client<portal>,20.1,471482,9.18\r\n" in csv_text
    assert "model,claude-sonnet-4,52.4,1229345,23.91\r\n" in csv_text


def test_build_csv_data_masks_project_names() -> None:
    csv_text = html_report._build_csv_data(_full_report_data(), "en", mask_projects=True)

    assert "project,Project 1,70.2,1646859,32.07\r\n" in csv_text
    assert "project,Project 2,20.1,471482,9.18\r\n" in csv_text
    assert "model,claude-sonnet-4,52.4,1229345,23.91\r\n" in csv_text
    assert "project,usage,70.2,1646859,32.07\r\n" not in csv_text


def test_render_ai_updates_section_falls_back_to_english_and_escapes() -> None:
    html = html_report._render_ai_updates_section(
        {
            "ai_updates": [
                {
                    "id": "codex",
                    "name": "Codex<script>",
                    "versions": [
                        {
                            "version": "0.141.0",
                            "period": "2026-06-18",
                            "items": [
                                {
                                    "title": {"en": "Remote <upgrade>"},
                                    "body": {"en": "Remote <upgrade> shipped."},
                                    "original": "Use `codex --remote` <beta>.",
                                }
                            ],
                        },
                        {
                            "version": "0.140.9",
                            "period": "2026-06-12",
                            "items": [
                                {
                                    "title": {"en": "Fallback <mode>"},
                                    "body": {"en": "Fallback <mode> recovered."},
                                    "original": "Older entry.",
                                }
                            ],
                        },
                    ],
                }
            ]
        },
        "ja",
    )

    assert "AIツール更新速報" in html
    assert "Updated to 0.141.0" not in html
    assert "更新：" in html
    assert "Original" not in html
    assert "原文" in html
    assert "Remote &lt;upgrade&gt;" in html
    assert "Remote &lt;upgrade&gt; shipped." in html
    assert "Use `codex --remote` &lt;beta&gt;." in html
    assert "<details" in html
    assert '<ol class="ai-update-items">' in html
    assert '<li class="ai-update-item">' in html
    assert "更新履歴を見る" in html
    assert "0.140.9" in html


def test_fmt_cost_returns_dash_for_none() -> None:
    """_fmt_cost returns '—' for None (unpriced models)."""
    assert html_report._fmt_cost(None) == "—"
    assert html_report._fmt_cost(0.0) == "$0.00"
    assert html_report._fmt_cost(0.001) == "$0.0010"
    assert html_report._fmt_cost(1.5) == "$1.50"


def test_csv_cost_returns_dash_for_none() -> None:
    """_csv_cost returns '—' for None (unpriced models in CSV)."""
    assert html_report._csv_cost(None) == "—"
    assert html_report._csv_cost(0.0) == "0.00"
    assert html_report._csv_cost(0.001) == "0.0010"
    assert html_report._csv_cost(1.5) == "1.50"


def test_render_model_section_shows_dash_for_unpriced_models() -> None:
    """_render_model_section shows '—' for models with cost_known=False."""
    data = {
        "by_model": [
            {
                "model": "claude-opus-4-8",
                "tokens": 100000,
                "cost": 1.5,
                "cost_known": True,
                "pct": 60.0,
            },
            {
                "model": "glm-5.2",
                "tokens": 50000,
                "cost": 0.0,
                "cost_known": False,
                "pct": 40.0,
            },
        ]
    }
    html = html_report._render_model_section(data, "en")

    assert "claude-opus-4-8" in html
    assert "$1.50" in html
    assert "glm-5.2" in html
    assert "—" in html
    assert "$0.00" not in html


def test_build_csv_data_shows_dash_for_unpriced_models() -> None:
    """_build_csv_data shows '—' for models with cost_known=False."""
    data = {
        "by_model": [
            {
                "model": "claude-opus-4-8",
                "tokens": 100000,
                "cost": 1.5,
                "cost_known": True,
                "pct": 60.0,
            },
            {
                "model": "glm-5.2",
                "tokens": 50000,
                "cost": 0.0,
                "cost_known": False,
                "pct": 40.0,
            },
        ]
    }
    csv_text = html_report._build_csv_data(data, "en")

    assert "model,claude-opus-4-8,60.0,100000,1.50\r\n" in csv_text
    assert "model,glm-5.2,40.0,50000,—\r\n" in csv_text
