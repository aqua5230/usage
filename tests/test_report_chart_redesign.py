from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from analyzer.reporter import DailyTrendPoint
from tests.test_report_filter_js import NODE, NODE_HARNESS
from ui import html_report
from ui.report_charts import weekly_scale
from ui.report_daily_chart import REPORT_DAILY_CHART_JS
from ui.report_filter import REPORT_FILTER_JS


class ChartTree(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.root: dict[str, Any] = {"tag": "root", "class": "", "children": [], "attrs": {}}
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        node: dict[str, Any] = {
            "tag": tag,
            "class": attributes.get("class", ""),
            "children": [],
            "attrs": attributes,
        }
        self.stack[-1]["children"].append(node)
        if tag not in {"br", "hr", "img", "input", "meta", "link"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        assert self.stack[-1]["tag"] == tag
        self.stack.pop()

    def nodes(self, class_name: str) -> list[dict[str, Any]]:
        def walk(node: dict[str, Any]) -> list[dict[str, Any]]:
            result = [node] if class_name in node["class"].split() else []
            return result + [item for child in node["children"] for item in walk(child)]

        return walk(self.root)


def shape(node: dict[str, Any]) -> list[Any]:
    return [node["tag"], node["class"], [shape(child) for child in node["children"]]]


def chart_daily() -> list[DailyTrendPoint]:
    # Partial first week; peak W32; lower last complete week; ongoing final week.
    start = date(2026, 8, 1)
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "tokens": 200 if 2 <= i < 9 else 100,
            "cost": 1.0,
        }
        for i in range(19)
    ]


def test_weekly_highlight_and_latest_complete_labels() -> None:
    chart = ChartTree(html_report._trend_ascii(chart_daily(), "en", date(2026, 8, 19)))
    columns = chart.nodes("weekly-column")
    assert [node["class"] for node in columns] == [
        "trend-row weekly-column partial",
        "trend-row weekly-column peak",
        "trend-row weekly-column",
        "trend-row weekly-column partial",
    ]
    assert [any(child["tag"] == "strong" for child in node["children"]) for node in columns] == [
        False,
        True,
        True,
        False,
    ]
    assert columns[1]["attrs"]["style"] == "height:70.00%"
    assert len(chart.nodes("weekly-grid")) == 5


def test_weekly_incomplete_weeks_do_not_win_highlight() -> None:
    daily = chart_daily()
    daily[0]["tokens"] = 999_999
    chart = ChartTree(html_report._trend_ascii(daily, "zh-TW", date(2026, 8, 19)))
    columns = chart.nodes("weekly-column")
    assert "partial" in columns[0]["class"]
    assert "partial" in columns[-1]["class"]
    assert len(chart.nodes("peak")) == 1
    assert "W32" in chart.nodes("peak")[0]["attrs"]["title"]
    assert "不完整週" in html_report._trend_ascii(daily, "zh-TW", date(2026, 8, 19))


def test_weekly_tooltips_keep_ranges_tokens_cost_and_status() -> None:
    chart = ChartTree(html_report._trend_ascii(chart_daily(), "en", date(2026, 8, 19)))
    titles = [node["attrs"]["title"] for node in chart.nodes("weekly-column")]
    assert titles[0] == "W31 (08/01–08/02) · only 2 days · 2026-08-01 – 2026-08-02 · 200 · $2.00"
    assert titles[2] == "W33 (08/10–08/16) · 2026-08-10 – 2026-08-16 · 700 · $7.00 · ↘ -50%"
    assert titles[-1] == "W34 (08/17–08/19) · 2026-08-17 – 2026-08-19 · 300 · $3.00 · in progress"


@pytest.mark.parametrize("maximum", [0, 1, 999, 1_200_000, 3_680_000_000])
def test_weekly_axis_has_four_readable_integer_intervals(maximum: int) -> None:
    step, ceiling = weekly_scale(maximum)
    assert isinstance(step, int)
    assert ceiling == step * 4 >= maximum
    assert str(step).rstrip("0") in {"1", "2", "5"}


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_js_rebuild_matches_python_chart_class_structure(tmp_path: Path) -> None:
    daily = chart_daily()
    cube = {
        "dates": [day["date"] for day in daily],
        "agents": [{"id": "codex", "name": "Codex"}],
        "models": [{"name": "gpt-test", "cost_known": True}],
        "projects": ["private-project"],
        "rows": [[i, 0, 0, 0, day["tokens"], 0, 0, 0, 1, 1] for i, day in enumerate(daily)],
    }
    tokens = sum(day["tokens"] for day in daily)
    tools = ChartTree(
        html_report._tools_body(
            [],
            [
                {
                    "id": "codex",
                    "name": "Codex",
                    "tokens": tokens,
                    "cost": 19,
                    "pct": 100,
                    "input_tokens": tokens,
                    "output_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "sessions": 19,
                    "messages": 19,
                }
            ],
            [
                {
                    "agent_id": "codex",
                    "models": [{"model": "gpt-test", "tokens": tokens, "cost": 19, "pct": 100}],
                }
            ],
            "en",
        )
    )
    weekly = ChartTree(html_report._trend_ascii(daily, "en", date(2026, 8, 19)))
    composition = ChartTree(
        html_report._render_composition_section(
            {
                "summary": {"total_tokens": tokens, "input_tokens": tokens},
                "by_agent": [{"name": "Codex", "input_tokens": tokens}],
            },
            "en",
        )
    )
    projects = ChartTree(
        html_report._render_project_section(
            {
                "summary": {"total_tokens": tokens, "total_cost": 19},
                "by_project": [{"project": "private-project", "tokens": tokens, "cost": 19}],
            },
            "en",
        )
    )
    expected = [
        shape(tools.nodes("tool-row")[0]),
        shape(tools.nodes("model-child")[0]),
        shape(weekly.nodes("trend")[0]),
        shape(composition.nodes("composition-stack")[0]),
        shape(composition.nodes("composition-item")[0]),
        shape(composition.nodes("rank-line")[0]),
        shape(projects.nodes("rank-line")[0]),
    ]
    prefix = NODE_HARNESS.split("const cube = {", 1)[0]
    script = prefix.replace("__REPORT_DAILY_CHART_JS__", json.dumps(REPORT_DAILY_CHART_JS)).replace(
        "__REPORT_FILTER_JS__", json.dumps(REPORT_FILTER_JS)
    )
    script += "\nconst cube = " + json.dumps(cube) + ";\n"
    script += """
const env = run(makeEnvironment(cube));
window.usageReportFilter.applyBounds({from: cube.dates[0], to: cube.dates.at(-1)});
function shape(node) {
  return [node.tagName, node.className, node.children.map(shape)];
}
const actual = [shape(env.tools.querySelector('.tool-row')),
  shape(env.tools.querySelector('.model-child')),
  shape(env.trendSection.querySelector('.trend')),
  shape(env.compositionSection.querySelector('.composition-stack')),
  shape(env.compositionSection.querySelector('.composition-item')),
  shape(env.compositionSection.querySelectorAll('.rank-list')[1].children[0]),
  shape(env.projectList.children[0])];
"""
    script += "assert.deepEqual(actual, " + json.dumps(expected) + ");\n"
    script += """
assert.equal(env.tools.querySelector('.hbar').style.background, 'var(--chart-accent)');
assert.equal(env.trendSection.querySelector('.peak').querySelector('strong').textContent, '1.4K');
const columns = env.trendSection.querySelectorAll('.weekly-column');
assert.equal(columns.filter((node) => node.classList.contains('partial')).length, 2);
assert.equal(columns.at(-1).getAttribute('title').endsWith('in progress'), true);
const grid = env.trendSection.querySelectorAll('.weekly-grid');
assert.deepEqual(grid.map((node) => node.textContent), ['0', '500', '1K', '1.5K', '2K']);
cube.rows = [[2, 0, 0, 0, 3680000000, 0, 0, 0, 1, 1]];
const billionEnv = run(makeEnvironment(cube));
window.usageReportFilter.applyBounds({from: cube.dates[0], to: cube.dates.at(-1)});
assert.deepEqual(billionEnv.trendSection.querySelectorAll('.weekly-grid')
  .map((node) => node.textContent), ['0', '1B', '2B', '3B', '4B']);
"""
    path = tmp_path / "chart-parity.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([NODE or "node", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
