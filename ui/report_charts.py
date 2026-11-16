# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any


def is_unattributed(value: object) -> bool:
    return value in (None, "", "unknown")


def project_chart_rows(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep legacy totals outside the ten project ranks, without changing report data."""
    projects = list(data.get("by_project", []))
    cube = data.get("cube")
    cube = cube if isinstance(cube, Mapping) else {}
    if not any(is_unattributed(p["project"]) for p in projects) and not any(
        is_unattributed(p) for p in cube.get("projects", [])
    ):
        return projects

    # The analyzer supplies only ten rows. Recover omitted rows from the embedded
    # cube so unknown neither consumes a rank nor disappears into Other projects.
    present = {p["project"] for p in projects}
    missing: dict[str, dict[str, Any]] = {}
    for row in cube.get("rows", []):
        day = cube["dates"][int(row[0])]
        if not data.get("date_from", day) <= day <= data.get("date_to", day):
            continue
        name = cube["projects"][int(row[3])]
        if name in present:
            continue
        item = missing.setdefault(
            name, {"project": name, "tokens": 0, "cost": 0.0, "cost_known": False}
        )
        item["tokens"] += sum(int(value) for value in row[4:8])
        item["cost"] += float(row[8])
        item["cost_known"] |= bool(cube["models"][int(row[2])].get("cost_known"))
    projects.extend(p for p in missing.values() if p["tokens"] > 0 or p["cost"] > 0)
    unknown = [p for p in projects if is_unattributed(p["project"]) and not p.get("is_other")]
    project_order = {name: index for index, name in enumerate(cube.get("projects", []))}
    ranked = sorted(
        [p for p in projects if not is_unattributed(p["project"]) and not p.get("is_other")],
        key=lambda p: (-p["tokens"], project_order.get(p["project"], len(project_order))),
    )[:10]
    ranked.extend(p for p in projects if p.get("is_other"))
    if unknown:
        ranked.append(
            {
                "project": "unknown",
                "tokens": sum(p["tokens"] for p in unknown),
                "cost": sum(p["cost"] for p in unknown),
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
