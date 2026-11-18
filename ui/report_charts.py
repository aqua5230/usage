# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import Any


def is_unattributed(value: object) -> bool:
    return value in (None, "", "unknown")


def _row_in_range(cube: Mapping[str, Any], row: Sequence[Any], data: Mapping[str, Any]) -> bool:
    dates = cube.get("dates", [])
    index = int(row[0])
    if not 0 <= index < len(dates):
        return False
    day = dates[index]
    date_from = data.get("date_from", day)
    date_to = data.get("date_to", day)
    return bool(date_from <= day <= date_to)


def _row_is_ledger_unattributed(cube: Mapping[str, Any], row: Sequence[Any]) -> bool:
    projects = cube.get("projects", [])
    index = int(row[3])
    name = projects[index] if 0 <= index < len(projects) else None
    return len(row) > 10 and row[10] == 1 and is_unattributed(name)


def is_unattributed_project(
    project: Mapping[str, Any],
    data: Mapping[str, Any] | None = None,
) -> bool:
    """Identify total-only legacy project buckets without mislabeling live unknown projects."""
    if "is_unattributed" in project:
        return bool(project["is_unattributed"])
    name = project.get("project")
    if not is_unattributed(name):
        return False
    cube = data.get("cube") if isinstance(data, Mapping) else None
    if not isinstance(cube, Mapping) or not cube.get("rows") or data is None:
        return True
    projects = cube.get("projects", [])
    matched_ledger = False
    matched_live = False
    for row in cube.get("rows", []):
        if not _row_in_range(cube, row, data):
            continue
        index = int(row[3])
        if 0 <= index < len(projects) and projects[index] == name:
            if len(row) > 10 and row[10] == 1:
                matched_ledger = True
            else:
                matched_live = True
    if matched_ledger and matched_live:
        return not any(
            other is not project
            and other.get("project") == name
            and other.get("is_unattributed") is True
            for other in data.get("by_project", [])
        )
    if matched_ledger:
        return True
    return not matched_live


def project_chart_rows(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep legacy totals outside the ten project ranks, without changing report data."""
    projects = list(data.get("by_project", []))
    cube = data.get("cube")
    cube = cube if isinstance(cube, Mapping) else {}
    has_unattributed_in_projects = any(
        is_unattributed_project(p, data) and not p.get("is_other") for p in projects
    )
    has_unattributed_in_cube = any(
        _row_is_ledger_unattributed(cube, row) for row in cube.get("rows", [])
    )
    if not has_unattributed_in_projects and not has_unattributed_in_cube:
        return projects

    # The analyzer supplies only ten rows. Recover omitted rows from the embedded
    # cube so legacy totals neither consume a rank nor disappear into Other projects.
    present = {(p["project"], is_unattributed_project(p, data)) for p in projects}
    missing: dict[tuple[str, bool], dict[str, Any]] = {}
    for row in cube.get("rows", []):
        if not _row_in_range(cube, row, data):
            continue
        name = cube["projects"][int(row[3])]
        row_unattributed = _row_is_ledger_unattributed(cube, row)
        key = (name, row_unattributed)
        if key in present:
            continue
        default_item: dict[str, Any] = {
            "project": name,
            "tokens": 0,
            "cost": 0.0,
            "cost_known": False,
        }
        # Recovered rows know whether they are ledger totals; never leave it to inference.
        default_item["is_unattributed"] = row_unattributed
        item = missing.setdefault(key, default_item)
        item["tokens"] += sum(int(value) for value in row[4:8])
        item["cost"] += float(row[8])
        item["cost_known"] |= bool(cube["models"][int(row[2])].get("cost_known"))
    projects.extend(p for p in missing.values() if p["tokens"] > 0 or p["cost"] > 0)
    unknown = [p for p in projects if is_unattributed_project(p, data) and not p.get("is_other")]
    project_order = {name: index for index, name in enumerate(cube.get("projects", []))}
    ranked = sorted(
        [p for p in projects if not is_unattributed_project(p, data) and not p.get("is_other")],
        key=lambda p: (-p["tokens"], project_order.get(p["project"], len(project_order))),
    )[:10]
    ranked.extend(p for p in projects if p.get("is_other"))
    if unknown:
        ranked.append(
            {
                "project": "unknown",
                "tokens": sum(p["tokens"] for p in unknown),
                "cost": sum(p.get("cost", 0.0) for p in unknown),
                "cost_known": any(p.get("cost_known", True) for p in unknown),
                "is_unattributed": True,
            }
        )
    return ranked


def render_trend_bar(tokens: int, max_tokens: int) -> str:
    width = 0.0
    if tokens > 0 and max_tokens > 0:
        width = max(2.0, min(100.0, tokens / max_tokens * 100))
    return f'<div class="trend-bar" aria-hidden="true"><div style="width:{width:.2f}%"></div></div>'


def render_share_bar(pct: float, color: str | None = None) -> str:
    width = max(2.0, min(100.0, pct)) if pct > 0 else 0.0
    color_style = f";background:{html.escape(color, quote=True)}" if color else ""
    return (
        '<span class="share-bar" aria-hidden="true">'
        f'<span style="width:{width:.2f}%{color_style}"></span>'
        "</span>"
    )


def render_axis() -> str:
    return (
        '<div class="haxis" aria-hidden="true">'
        + "".join(f'<span style="left:{pct}%">{pct}%</span>' for pct in (0, 25, 50, 75, 100))
        + "</div>"
    )


def render_lane(pct: float, label: str, detail: str = "", color: str | None = None) -> str:
    width = max(0.0, min(100.0, pct))
    background = f";background:{html.escape(color, quote=True)}" if color else ""
    return (
        f'<div class="hlane" style="--value:{width:.1f}%">'
        f'<div class="hbar" aria-hidden="true" style="width:{width:.1f}%{background}"></div>'
        f'<span class="htail"><span class="pct">{html.escape(label)}</span>{detail}</span></div>'
    )


def weekly_scale(max_tokens: int) -> tuple[int, int]:
    """Four intervals with integer 1/2/5 steps, including an all-zero range."""
    import math

    raw = max(1, max_tokens) / 4
    unit = 10 ** math.floor(math.log10(raw))
    step = next(factor * unit for factor in (1, 2, 5, 10) if factor * unit >= raw)
    step = max(1, int(step))
    return step, step * 4


def format_axis_tokens(value: int) -> str:
    for unit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= unit:
            return f"{value / unit:.10f}".rstrip("0").rstrip(".") + suffix
    return str(value)
