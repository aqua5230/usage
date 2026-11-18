from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from analyzer.reporter import DailyTrendPoint
from tests.test_html_report_snapshot import _full_report_data
from tests.test_report_filter_js import NODE, NODE_HARNESS
from tests.test_report_headings import Texts
from ui import html_report
from ui.report_charts import weekly_scale
from ui.report_daily_chart import REPORT_DAILY_CHART_JS
from ui.report_filter import REPORT_FILTER_JS


@pytest.mark.parametrize(
    ("lang", "digest"),
    [
        ("zh-TW", "b406572680b56487b28bf0b6aefac594551baa71bc32c70e76e9c1f0104c3f29"),
        ("en", "36108cc75186e5fce188cf9ed81698e9e037d0cf11bb6ea7b7e1cc37585c5df9"),
        ("zh-CN", "2128298532b24b509e9d6b194ca9ebc9367ffdc7672375365b0790f075539daa"),
        ("ja", "8238e255a10722bec0bfb0e24b7f0764193ec6fbd6c3f3b9fa3fa7bc8cf05c11"),
        ("ko", "30237ebf08201316198dbc28f875811e495ea70bf2f19d91708a7dd12d8dd126"),
    ],
)
def test_known_rankings_keep_existing_markup(lang: str, digest: str) -> None:
    # Byte-for-byte baselines captured from the pre-change renderers, in all five languages.
    data = _full_report_data()
    data["by_project"][-1]["project"] = "third-private"
    rendered = html_report._render_project_section(data, lang) + html_report._render_tools_section(
        data, lang
    )
    assert hashlib.sha256(rendered.encode()).hexdigest() == digest


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
@pytest.mark.parametrize("lang", ["zh-TW", "en", "zh-CN", "ja", "ko"])
@pytest.mark.parametrize("unknown_name", ["unknown", ""])
@pytest.mark.parametrize("unknown_tokens", [5000, 1])
def test_unattributed_rankings_match_python_after_date_changes(
    tmp_path: Path, lang: str, unknown_name: str, unknown_tokens: int
) -> None:
    cube: dict[str, Any] = {
        "dates": ["2026-08-01", "2026-08-02", "2026-08-03"],
        "agents": [
            {"id": "unknown", "name": "unknown"},
            {"id": "codex", "name": "Codex"},
            {"id": "claude-code", "name": "Claude Code"},
        ],
        "models": [{"name": "test", "cost_known": True}, {"name": "unknown", "cost_known": False}],
        "projects": [unknown_name, *[f"private-{i}" for i in range(12)]],
        "rows": [[0, 0, 1, 0, unknown_tokens, 0, 0, 0, 5, 0, 1], [0, 1, 0, 1, 1, 0, 0, 0, 1, 1]]
        + [[1, 1 + i % 2, 0, i + 1, 200 - max(0, i - 1) * 10, 0, 0, 0, 1, 1] for i in range(12)],
    }
    config = json.loads(html_report._share_config_json(lang, interactive=True))
    script = (
        NODE_HARNESS.split("const cube = {", 1)[0]
        .replace("__REPORT_DAILY_CHART_JS__", json.dumps(REPORT_DAILY_CHART_JS))
        .replace("__REPORT_FILTER_JS__", json.dumps(REPORT_FILTER_JS))
    )
    script += "\nconst cube = " + json.dumps(cube) + ";\n"
    script += "const env = makeEnvironment(cube);\n"
    script += "Object.assign(shareConfig, " + json.dumps(config) + ");\nrun(env);\n"
    for start, end in [
        ("2026-08-01", "2026-08-03"),
        ("2026-08-01", "2026-08-01"),
        ("2026-08-02", "2026-08-02"),
        ("2026-08-03", "2026-08-03"),
        ("2026-08-01", "2026-08-03"),
    ]:
        matching = [r for r in cube["rows"] if start <= cube["dates"][r[0]] <= end]
        data: dict[str, Any] = {
            "date_from": start,
            "date_to": end,
            "cube": cube,
            "summary": {
                "total_tokens": sum(sum(r[4:8]) for r in matching),
                "total_cost": sum(r[8] for r in matching),
            },
            "by_project": [
                {"project": p, "tokens": sum(sum(r[4:8]) for r in matching if r[3] == i)}
                for i, p in enumerate(cube["projects"])
                if any(r[3] == i for r in matching)
            ],
            "by_agent": [
                {**a, "tokens": sum(sum(r[4:8]) for r in matching if r[1] == i)}
                for i, a in enumerate(cube["agents"])
            ],
        }

        def priced(rows: list[list[Any]]) -> bool:
            return any(cube["models"][r[2]]["cost_known"] for r in rows)

        for project in data["by_project"]:
            index = cube["projects"].index(project["project"])
            project["cost"] = sum(r[8] for r in matching if r[3] == index)
            project["cost_known"] = priced([r for r in matching if r[3] == index])
        data["by_agent_model"] = [
            {"agent_id": a["id"], "cost_known": priced([r for r in matching if r[1] == i])}
            for i, a in enumerate(cube["agents"])
        ]
        # Deliberately reverse ties: the cube dimension order must win in both renderers.
        data["by_project"] = sorted(reversed(data["by_project"]), key=lambda p: -p["tokens"])[:10]
        for i, agent in enumerate(data["by_agent"]):
            agent["cost"] = sum(r[8] for r in matching if r[1] == i)
            total = data["summary"]["total_tokens"]
            agent["pct"] = agent["tokens"] / total * 100 if total else 0
        data["by_agent"] = sorted(
            [a for a in data["by_agent"] if a["tokens"]], key=lambda a: -a["tokens"]
        )
        original = json.dumps(data, sort_keys=True)
        projects = html_report._render_project_section(data, lang)
        tools = html_report._render_tools_section(data, lang)
        assert json.dumps(data, sort_keys=True) == original
        expected = []
        for rendered, name_class in [(projects, "name"), (tools, "sub-agent")]:
            expected.append(
                [Texts(rendered, cls).values for cls in (name_class, "tokens", "cost", "pct")]
            )
        if start == "2026-08-01":
            names = Texts(projects, "name").values
            assert names[-1] == html_report._t(lang, "unattributed_projects")
            assert Texts(tools, "sub-agent").values[-1] == html_report._t(
                lang, "unattributed_tools"
            )
            # Legacy totals have no price data: show unknown cost, not $0.00 or $5.00.
            assert Texts(tools, "cost").values[-1] == "—"
            assert Texts(projects, "cost").values[-1] == "—"
            assert (
                "background:var(--chart-neutral)"
                in ChartTree(projects).nodes("hbar")[-1]["attrs"]["style"]
            )
            if end == "2026-08-01":
                # One attributed tool beside legacy totals must not claim all usage.
                assert Texts(tools, "prompt-title").values == [
                    html_report._t(
                        lang,
                        "title_tools_top",
                        tool="Codex",
                        pct=math.floor(100 / (unknown_tokens + 1) + 0.5),
                    )
                ]
            if end == "2026-08-03":
                assert names == [
                    *[f"private-{i}" for i in range(10)],
                    html_report._t(lang, "project_others"),
                    html_report._t(lang, "unattributed_projects"),
                ]
                assert (
                    "background:var(--chart-accent)"
                    in ChartTree(projects).nodes("hbar")[0]["attrs"]["style"]
                )
                assert (
                    "background:var(--chart-accent)"
                    in ChartTree(tools).nodes("hbar")[0]["attrs"]["style"]
                )
        script += (
            "window.usageReportFilter.applyBounds("
            + json.dumps({"from": start, "to": end})
            + ");\n"
        )
        script += (
            "assert.deepEqual([[env.projectList.children, 'name'], "
            "[env.tools.querySelectorAll('.tool-row'), 'sub-agent']].map(([rows,n]) => "
            "[n,'tokens','cost','pct'].map(c => rows.filter(r => r.querySelector('.pct'))"
            ".map(r => r.querySelector('.'+c).textContent))), " + json.dumps(expected) + ");\n"
        )
        metadata = [
            [
                next(iter(Texts(rendered, cls).values), "")
                for cls in ("prompt-title", "report-subtitle", "report-source")
            ]
            for rendered in (projects, tools)
        ]
        script += (
            "assert.deepEqual([env.projectSection, env.toolsSection].map(s => "
            "['prompt-title','report-subtitle','report-source'].map(c => "
            "s.querySelector('.'+c)?.textContent || '')), " + json.dumps(metadata) + ");\n"
        )
        if matching and start == "2026-08-01":
            script += """
assert.equal(env.projectList.children.at(-1).querySelector('.hbar').style.background,
  'var(--chart-neutral)');
assert.equal(env.tools.querySelectorAll('.tool-row').at(-1).querySelector('.hbar').style.background,
  'var(--chart-neutral)');
"""
            if end == "2026-08-03":
                script += """
assert.equal(env.tools.querySelector('.tool-row').querySelector('.hbar').style.background,
  'var(--chart-accent)');
assert.equal(env.projectList.children[0].querySelector('.hbar').style.background,
  'var(--chart-accent)');
"""
    path = tmp_path / "unattributed-rankings.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([NODE or "node", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


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


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
@pytest.mark.parametrize("lang", ["zh-TW", "en"])
def test_live_unknown_project_uses_unknown_label_while_ledger_unknown_stays_legacy(
    tmp_path: Path, lang: str
) -> None:
    import csv as csv_module
    import io

    cube: dict[str, Any] = {
        "dates": ["2026-08-01", "2026-11-16"],
        "agents": [
            {"id": "unknown", "name": "unknown"},
            {"id": "codex", "name": "Codex"},
        ],
        "models": [
            {"name": "unknown", "cost_known": False},
            {"name": "gpt-demo", "cost_known": True},
        ],
        "projects": ["unknown", "alpha"],
        "rows": [
            # Legacy ledger row (11 fields, index 10 == 1)
            [0, 0, 0, 0, 500, 0, 0, 0, 0.0, 0, 1],
            # Live Codex row with unknown cwd (10 fields)
            [1, 1, 1, 0, 100, 0, 0, 0, 0.01, 1],
            # Live Codex row with named project (10 fields)
            [1, 1, 1, 1, 200, 0, 0, 0, 0.02, 1],
        ],
    }
    data: dict[str, Any] = {
        "date_from": "2026-08-01",
        "date_to": "2026-11-16",
        "summary": {"total_tokens": 800, "total_cost": 0.03},
        "by_project": [
            {
                "project": "unknown",
                "tokens": 500,
                "cost": 0.0,
                "cost_known": False,
                "is_unattributed": True,
            },
            {"project": "alpha", "tokens": 200, "cost": 0.02, "cost_known": True},
            {"project": "unknown", "tokens": 100, "cost": 0.01, "cost_known": True},
        ],
        "by_agent": [
            {"id": "unknown", "name": "unknown", "tokens": 500, "cost": 0.0, "pct": 62.5},
            {"id": "codex", "name": "Codex", "tokens": 300, "cost": 0.03, "pct": 37.5},
        ],
        "by_model": [],
        "cube": cube,
    }
    rendered = html_report._render_project_section(data, lang)
    names = Texts(rendered, "name").values
    unknown_label = html_report._t(lang, "unknown")
    legacy_label = html_report._t(lang, "unattributed_projects")
    assert names == ["alpha", unknown_label, legacy_label]

    csv_rows = [
        row
        for row in csv_module.DictReader(io.StringIO(html_report._build_csv_data(data, lang)))
        if row["type"] == "project"
    ]
    assert [row["name"] for row in csv_rows] == ["alpha", unknown_label, legacy_label]

    config = json.loads(html_report._share_config_json(lang, interactive=True))
    prefix = NODE_HARNESS.split("const cube = {", 1)[0]
    script = prefix.replace("__REPORT_DAILY_CHART_JS__", json.dumps(REPORT_DAILY_CHART_JS)).replace(
        "__REPORT_FILTER_JS__", json.dumps(REPORT_FILTER_JS)
    )
    script += "\nconst cube = " + json.dumps(cube) + ";\n"
    script += "const env = makeEnvironment(cube);\n"
    script += "Object.assign(shareConfig, " + json.dumps(config) + ");\nrun(env);\n"
    script += "window.usageReportFilter.applyBounds({from: '2026-11-16', to: '2026-11-16'});\n"
    script += (
        "assert.deepEqual("
        "env.projectList.children.map((r) => r.querySelector('.name').textContent), "
        + json.dumps(["alpha", unknown_label])
        + ");\n"
    )
    script += "window.usageReportFilter.applyBounds({from: '2026-08-01', to: '2026-11-16'});\n"
    script += (
        "assert.deepEqual("
        "env.projectList.children.map((r) => r.querySelector('.name').textContent), "
        + json.dumps(["alpha", unknown_label, legacy_label])
        + ");\n"
    )
    path = tmp_path / "live-unknown.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([NODE or "node", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_recovered_live_unknown_stays_out_of_ledger_totals() -> None:
    from ui.report_charts import project_chart_rows

    named = [f"p{i:02d}" for i in range(1, 11)]
    data: dict[str, Any] = {
        "date_from": "2026-08-01",
        "date_to": "2026-11-16",
        "summary": {"total_tokens": 10050, "total_cost": 10.5},
        "by_project": [
            {"project": f"p{i:02d}", "tokens": 1010 - i * 10, "cost": 1.0, "cost_known": True}
            for i in range(1, 11)
        ],
        "cube": {
            "dates": ["2026-08-01", "2026-11-16"],
            "agents": [{"id": "unknown", "name": "unknown"}, {"id": "codex", "name": "Codex"}],
            "models": [{"name": "unknown", "cost_known": False}, {"name": "gpt", "cost_known": True}],
            "projects": ["unknown", *named],
            "rows": [
                *[[1, 1, 1, i, 1010 - i * 10, 0, 0, 0, 1.0, 1] for i in range(1, 11)],
                [0, 0, 0, 0, 300, 0, 0, 0, 0.0, 0, 1],  # ledger total-only row
                [1, 1, 1, 0, 200, 0, 0, 0, 0.5, 1],  # live Codex row with no project
            ],
        },
    }
    legacy = [row for row in project_chart_rows(data) if row.get("is_unattributed")]
    assert [row["tokens"] for row in legacy] == [300]
