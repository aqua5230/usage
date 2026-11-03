from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from analyzer.reporter import DailyTrendPoint
from tests.test_html_report_snapshot import _full_report_data
from tests.test_report_filter_js import NODE, NODE_HARNESS
from ui import html_report
from ui.report_charts import format_axis_tokens
from ui.report_daily_chart import REPORT_DAILY_CHART_JS
from ui.report_filter import REPORT_FILTER_JS
from ui.report_scripts import REPORT_JS_TEMPLATE
from ui.report_styles import REPORT_CSS


class Texts(HTMLParser):
    """Read the actual emitted text, including nested legend spans."""

    def __init__(self, source: str, target: str) -> None:
        super().__init__()
        self.target = target
        self.depth = 0
        self.values: list[str] = []
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth:
            self.depth += 1
        elif self.target in (dict(attrs).get("class") or "").split():
            self.depth = 1
            self.values.append("")

    def handle_endtag(self, tag: str) -> None:
        if self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.values[-1] += data


def heading(kind: str, **data: Any) -> str:
    return html_report._report_heading(data, "zh-TW", kind)[0]


@pytest.mark.parametrize(
    ("agents", "expected"),
    [
        (
            [{"name": "Codex", "tokens": 129}, {"name": "Claude Code", "tokens": 71}],
            "Codex 用得最多，佔 65%",
        ),
        (
            [{"name": "Codex", "tokens": 200}, {"name": "Claude Code", "tokens": 0}],
            "全部用量來自 Codex",
        ),
        ([{"name": "Codex", "tokens": 0}], html_report._t("zh-TW", "tools_section")),
    ],
)
def test_tools_title_branches_and_half_up(agents: list[dict[str, Any]], expected: str) -> None:
    assert heading("tools", summary={"total_tokens": 200}, by_agent=agents) == expected


@pytest.mark.parametrize("count", [0, 2, 3])
def test_project_title_threshold_and_other_denominator(count: int) -> None:
    projects = [{"project": f"private-{i}", "tokens": 43} for i in range(count)]
    projects.append({"project": "Other projects", "tokens": 71, "is_other": True})
    actual = heading("projects", summary={"total_tokens": 200}, by_project=projects)
    expected = (
        "前 3 個專案佔了 65% 的用量" if count == 3 else html_report._t("zh-TW", "project_section")
    )
    assert actual == expected


@pytest.mark.parametrize("days", [0, 7, 14])
def test_trend_title_complete_week_threshold(days: int) -> None:
    start = date(2026, 8, 3)
    daily = [
        {"date": (start + timedelta(days=i)).isoformat(), "tokens": 1 if i < 7 else 2, "cost": 0}
        for i in range(days)
    ]
    actual = heading("trend", daily_trend=daily, date_from="2026-08-03", date_to="2026-08-16")
    assert actual == (
        "08/10 那週用量最高" if days == 14 else html_report._t("zh-TW", "trend_section")
    )


def test_trend_partial_week_cannot_win_title() -> None:
    daily = [
        {
            "date": (date(2026, 8, 1) + timedelta(days=i)).isoformat(),
            "tokens": 999 if i < 2 or i >= 16 else 1,
            "cost": 0,
        }
        for i in range(19)
    ]
    assert (
        heading("trend", daily_trend=daily, date_from="2026-08-01", date_to="2026-08-19")
        == "08/03 那週用量最高"
    )


@pytest.mark.parametrize(
    "summary", [{}, {"total_tokens": 200}, {"input_tokens": 129, "cache_read_tokens": 71}]
)
def test_composition_title_branches(summary: dict[str, int]) -> None:
    expected = (
        "65% 的 token 是" + html_report._t("zh-TW", "composition_input")
        if summary.get("input_tokens")
        else html_report._t("zh-TW", "composition_section")
    )
    assert heading("composition", summary=summary) == expected


@pytest.mark.parametrize("sessions", [[], [{"tokens": 4_000_000_000}]])
def test_session_title_branches(sessions: list[dict[str, int]]) -> None:
    assert heading("sessions", top_sessions=sessions) == (
        "最大的一段會話用了 4.00B tokens"
        if sessions
        else html_report._t("zh-TW", "session_section")
    )


@pytest.mark.parametrize("days", [6, 7])
def test_streak_title_threshold(days: int) -> None:
    data = _full_report_data()
    data["contribution"]["current_streak"] = days
    title = Texts(html_report._render_contribution_section(data, "zh-TW"), "prompt").values[0]
    assert title == "[usage]> " + (
        f"已經連續 {days} 天每天都有用"
        if days >= 7
        else html_report._t(
            "zh-TW", "contribution_section", weeks=len(data["contribution"]["weeks"])
        )
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(4_000_000_000, "4B"), (500_000_000, "500M"), (750_000_000, "750M"), (1_500_000_000, "1.5B")],
)
def test_axis_format(value: int, expected: str) -> None:
    assert format_axis_tokens(value) == expected


def test_axis_and_legend_emitted_text() -> None:
    daily: list[DailyTrendPoint] = [{"date": "2026-08-03", "tokens": 3_680_000_000, "cost": 0}]
    chart = html_report._trend_ascii(daily, "en", date(2026, 8, 9))
    assert Texts(chart, "weekly-grid").values == ["0", "1B", "2B", "3B", "4B"]
    assert Texts(chart, "weekly-heading").values == ["Weekly usage"]
    rendered = html_report._render_composition_section(
        {"summary": {"total_tokens": 200, "input_tokens": 129, "cache_read_tokens": 71}}, "zh-TW"
    )
    assert Texts(rendered, "composition-item").values == [
        "輸入 64.5%（129）",
        "快取讀取 35.5%（71）",
    ]
    assert "--label:200px" in REPORT_CSS
    assert "min-height:36px;padding:9px 0" in REPORT_CSS
    assert "@media(max-width:560px)" in REPORT_CSS
    assert ".hchart .sub-since{display:inline-block;white-space:nowrap}" in REPORT_CSS


def sample_cube() -> dict[str, Any]:
    return {
        "dates": [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(23)],
        "agents": [{"id": "codex", "name": "Codex"}, {"id": "claude-code", "name": "Claude Code"}],
        "models": [{"name": "test", "cost_known": True}],
        "projects": ["secret-alpha", "secret-beta", "secret-gamma"],
        "rows": [
            [i, agent, 0, (i + agent) % 3, 129 if agent == 0 else 0, 0, 0, 71 if agent else 0, 1, 1]
            for i in range(19)
            for agent in range(2)
        ]
        + [[19, 0, 0, 0, 129, 0, 0, 71, 1, 1]],
    }


def range_data(cube: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    rows = [r for r in cube["rows"] if start <= cube["dates"][r[0]] <= end]

    def tokens(row: list[int]) -> int:
        return sum(row[4:8])

    return {
        "date_from": start,
        "date_to": end,
        "summary": {
            "total_tokens": sum(tokens(r) for r in rows),
            **{
                key: sum(r[i] for r in rows)
                for i, key in enumerate(
                    ["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens"],
                    4,
                )
            },
        },
        "by_agent": [
            {**a, "tokens": sum(tokens(r) for r in rows if r[1] == i)}
            for i, a in enumerate(cube["agents"])
        ],
        "by_project": [
            {"project": p, "tokens": sum(tokens(r) for r in rows if r[3] == i)}
            for i, p in enumerate(cube["projects"])
            if any(r[3] == i for r in rows)
        ],
        "daily_trend": [
            {
                "date": day,
                "tokens": sum(tokens(r) for r in rows if cube["dates"][r[0]] == day),
                "cost": 0,
            }
            for day in cube["dates"]
            if start <= day <= end
        ],
        "top_sessions": [{"tokens": 200}] if start <= cube["dates"][19] <= end else [],
    }


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
@pytest.mark.parametrize("lang", ["zh-TW", "en", "zh-CN", "ja", "ko"])
def test_date_rebuild_headings_match_python_and_masked_export(tmp_path: Path, lang: str) -> None:
    cube = sample_cube()
    config = json.loads(html_report._share_config_json(lang, interactive=True))
    script = (
        NODE_HARNESS.split("const cube = {", 1)[0]
        .replace("__REPORT_DAILY_CHART_JS__", json.dumps(REPORT_DAILY_CHART_JS))
        .replace("__REPORT_FILTER_JS__", json.dumps(REPORT_FILTER_JS))
    )
    script += "\nconst cube = " + json.dumps(cube) + ";\n"
    script += (
        "const env = makeEnvironment(cube, {}, false, "
        "[{date_idx:19,tokens:200,cost:1,project_idx:0,model_idx:0,duration_min:1}]);\n"
    )
    script += "Object.assign(shareConfig, " + json.dumps(config) + ");\nrun(env);\n"
    cases = [
        ("2026-08-01", "2026-08-23"),
        ("2026-08-20", "2026-08-20"),
        ("2026-08-21", "2026-08-23"),
        ("2026-08-03", "2026-08-09"),
    ]
    for start, end in cases:
        data = range_data(cube, start, end)
        expected = []
        for kind in ["tools", "projects", "trend", "composition", "sessions"]:
            rendered = html_report._data_section(data, lang, kind, "", "")
            expected.append(
                [
                    next(iter(Texts(rendered, cls).values), "")
                    for cls in ("prompt-title", "report-subtitle", "report-source")
                ]
            )
        script += (
            "window.usageReportFilter.applyBounds("
            + json.dumps({"from": start, "to": end})
            + ");\n"
        )
        script += """
var sections = [env.toolsSection, env.projectSection, env.trendSection,
  env.compositionSection, env.sessionSection];
"""
        script += (
            "assert.deepEqual(sections.map((section) => "
            "['prompt-title','report-subtitle','report-source'].map((cls) => "
            "section.querySelector('.'+cls)?.textContent || '')), " + json.dumps(expected) + ");\n"
        )
        script += (
            "assert.equal(env.toolsSection.querySelector('.report-pricing').textContent, "
            + json.dumps(config["source_pricing"])
            + ");\n"
        )
        script += (
            "assert.equal(env.compositionSection.querySelectorAll('.composition-item')"
            ".some((row) => /% |（ | ）/.test(row.textContent)), false);\n"
        )
    # Run the actual export masking function and inspect its callback's metadata.
    export_start = REPORT_JS_TEMPLATE.index("async function withShareableReport(")
    export_end = REPORT_JS_TEMPLATE.index("\nasync function downloadHtml", export_start)
    script += """
function closeShareModal() {}
function stopSnakeAndRestore() {}
const reportRoot = {querySelectorAll: () => []};
const originalQuery = document.querySelector;
document.querySelector = (selector) => selector.startsWith('#') ? null : originalQuery(selector);
const originalQueryAll = document.querySelectorAll;
document.querySelectorAll = (selector) => {
  const nodes = originalQueryAll(selector);
  nodes.forEach((node) => {node.closest = () => null;});
  return nodes;
};
"""
    script += REPORT_JS_TEMPLATE[export_start:export_end]
    script += """
(async () => {
  await withShareableReport(true, async () => {
    const metadata = sections.map((section) =>
      ['prompt-title','report-subtitle','report-source'].map((cls) =>
        section.querySelector('.'+cls)?.textContent || '')).flat().join(' ');
    cube.projects.forEach((project) => assert.equal(metadata.includes(project), false));
  });
})().catch((error) => {console.error(error); process.exitCode = 1;});
"""
    path = tmp_path / "heading-parity.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [NODE or "node", str(path)], capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr


def test_all_zero_complete_weeks_have_no_peak_marker() -> None:
    daily: list[DailyTrendPoint] = [
        {
            "date": (date(2026, 8, 3) + timedelta(days=i)).isoformat(),
            "tokens": 0 if i < 14 else 5,
            "cost": 0,
        }
        for i in range(17)
    ]
    chart = html_report._trend_ascii(daily, "zh-TW", date(2026, 8, 19))
    assert "weekly-column peak" not in chart
    assert "<strong>" not in chart


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_zero_usage_weeks_and_projects_keep_neutral_titles(tmp_path: Path) -> None:
    cube = sample_cube()
    cube["rows"] = [
        [*row[:4], 0, 0, 0, 0, *row[8:]] if row[0] < 16 else row for row in cube["rows"]
    ]
    data = range_data(cube, "2026-08-03", "2026-08-16")
    expected = [
        next(
            iter(
                Texts(html_report._data_section(data, "zh-TW", kind, "", ""), "prompt-title").values
            ),
            "",
        )
        for kind in ("projects", "trend")
    ]
    assert expected == [
        html_report._t("zh-TW", "project_section"),
        html_report._t("zh-TW", "trend_section"),
    ]
    config = json.loads(html_report._share_config_json("zh-TW", interactive=True))
    script = (
        NODE_HARNESS.split("const cube = {", 1)[0]
        .replace("__REPORT_DAILY_CHART_JS__", json.dumps(REPORT_DAILY_CHART_JS))
        .replace("__REPORT_FILTER_JS__", json.dumps(REPORT_FILTER_JS))
    )
    script += "\nconst cube = " + json.dumps(cube) + ";\n"
    script += "const env = makeEnvironment(cube, {}, false, []);\n"
    script += "Object.assign(shareConfig, " + json.dumps(config) + ");\nrun(env);\n"
    script += 'window.usageReportFilter.applyBounds({"from": "2026-08-03", "to": "2026-08-16"});\n'
    script += (
        "assert.deepEqual([env.projectSection, env.trendSection].map((section) => "
        "section.querySelector('.prompt-title')?.textContent || ''), "
        + json.dumps(expected)
        + ");\n"
    )
    path = tmp_path / "zero-usage.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [NODE or "node", str(path)], capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr
