from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import history_loader
import menubar
from adapters.types import AgentInfo
from analyzer import reporter

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


def test_generate_analysis_report_uses_analyzer_pipeline(
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
        return "~/.usage-reports/usage-report-test.html"

    monkeypatch.setattr("adapters.registry.detect_agents", lambda: agents)
    monkeypatch.setattr("analyzer.reporter.build_report_data", fake_build_report_data)
    monkeypatch.setattr("ui.html_report.save_and_open", fake_save_and_open)

    assert menubar._generate_analysis_report() == "~/.usage-reports/usage-report-test.html"
    assert calls == {"agents": agents, "period": "month", "data": report_data}


def test_report_codex_entries_use_shared_loader(monkeypatch: Any) -> None:
    source_entry = history_loader.UsageEntry(
        timestamp=datetime(2026, 5, 21, tzinfo=UTC),
        session_id="s1",
        message_id="m1",
        request_id="r1",
        model="gpt-test",
        input_tokens=1,
        output_tokens=2,
        cache_creation_tokens=3,
        cache_read_tokens=4,
        cost_usd=0.5,
        project="usage",
    )
    calls: dict[str, int] = {}

    def fake_load_entries(*, hours_back: int = 0) -> list[history_loader.UsageEntry]:
        calls["hours_back"] = hours_back
        return [source_entry]

    monkeypatch.setattr("analyzer.reporter.codex_loader.load_entries", fake_load_entries)

    entries = reporter._load_agent_entries(AgentInfo("codex", "Codex", "~/.codex", True), 24)

    assert calls == {"hours_back": 24}
    assert len(entries) == 1
    assert entries[0].agent_id == "codex"
    assert entries[0].total_tokens == source_entry.total_tokens
