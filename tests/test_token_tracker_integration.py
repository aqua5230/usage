from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import menubar
from adapters.types import AgentInfo

ROOT = Path(__file__).resolve().parents[1]


def test_all_languages_have_analyze_label() -> None:
    bundle = json.loads((ROOT / "i18n.json").read_text(encoding="utf-8"))

    assert bundle["zh-TW"]["analyze_usage"] == "分析"
    assert bundle["zh-CN"]["analyze_usage"] == "分析"
    assert bundle["en"]["analyze_usage"] == "Analyze"
    assert bundle["ja"]["analyze_usage"] == "分析"
    assert bundle["ko"]["analyze_usage"] == "분석"


def test_all_languages_have_cli_statusline_labels() -> None:
    bundle = json.loads((ROOT / "i18n.json").read_text(encoding="utf-8"))

    for table in bundle.values():
        assert table["cli"] == "CLI"
        assert table["cli_disabled"] == "CLI"
        assert table["cli_enabled"] == "CLI ✓"
        removed_statusline_message_keys = {
            "statusline_" + suffix for suffix in ("installed", "uninstalled")
        }
        assert removed_statusline_message_keys.isdisjoint(table)
        assert not any(key.startswith("cli_five_hour") for key in table)


def test_html_panels_expose_analyze_action() -> None:
    panels_dir = ROOT / "assets" / "panels"

    for path in panels_dir.glob("*.html"):
        html = path.read_text(encoding="utf-8")
        assert 'data-action="analyze"' in html, path.name
        assert 'data-i18n="analyze_usage"' in html, path.name
        assert 'data-action="toggle-statusline"' in html, path.name


def test_generate_analysis_report_uses_token_tracker_pipeline(
    monkeypatch: Any,
) -> None:
    agents = [AgentInfo("codex", "Codex", "~/.codex", True)]
    report_data: dict[str, object] = {"summary": {"total_tokens": 123}}
    calls: dict[str, object] = {}

    def fake_build_report_data(received_agents: list[AgentInfo], period: str) -> dict[str, object]:
        calls["agents"] = received_agents
        calls["period"] = period
        return report_data

    def fake_save_and_open(received_data: dict[str, object]) -> str:
        calls["data"] = received_data
        return "~/.tt-reports/tt-report-test.html"

    monkeypatch.setattr("adapters.registry.detect_agents", lambda: agents)
    monkeypatch.setattr("analyzer.reporter.build_report_data", fake_build_report_data)
    monkeypatch.setattr("ui.html_report.save_and_open", fake_save_and_open)

    assert menubar._generate_analysis_report() == "~/.tt-reports/tt-report-test.html"
    assert calls == {"agents": agents, "period": "month", "data": report_data}
