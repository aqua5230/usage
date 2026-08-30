# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence


def render_daily_sparkline(
    daily: Sequence[Mapping[str, str | int | float]], aria_label: str
) -> str:
    if len(daily) < 2:
        return ""

    values = [max(0, int(day.get("tokens", 0))) for day in daily]
    max_tokens = max(values, default=0)
    if max_tokens == 0:
        return ""

    left = 3.0
    right = 597.0
    top = 6.0
    baseline = 114.0
    step = (right - left) / (len(values) - 1)
    points = [
        (left + index * step, baseline - value / max_tokens * (baseline - top))
        for index, value in enumerate(values)
    ]
    point_list = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    area_points = f"{left:.2f},{baseline:.2f} {point_list} {right:.2f},{baseline:.2f}"
    peak_index = min(
        (index for index, value in enumerate(values) if value == max_tokens),
        key=lambda index: str(daily[index].get("date", "")),
    )
    peak_x, peak_y = points[peak_index]
    first_date = html.escape(str(daily[0].get("date", "")))
    last_date = html.escape(str(daily[-1].get("date", "")))
    label = html.escape(aria_label, quote=True)
    return (
        '<div class="daily-sparkline">'
        f'<svg viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label="{label}">'
        f'<polygon class="daily-sparkline-area" points="{area_points}"/>'
        f'<polyline class="daily-sparkline-line" points="{point_list}"/>'
        f'<circle class="daily-sparkline-peak" cx="{peak_x:.2f}" cy="{peak_y:.2f}" r="3"/>'
        "</svg>"
        '<div class="daily-sparkline-dates">'
        f"<span>{first_date}</span><span>{last_date}</span>"
        "</div>"
        "</div>"
    )


def render_trend_bar(tokens: int, max_tokens: int) -> str:
    width = 0.0
    if tokens > 0 and max_tokens > 0:
        width = max(2.0, min(100.0, tokens / max_tokens * 100))
    return (
        '<div class="trend-bar" aria-hidden="true">'
        f'<div style="width:{width:.2f}%"></div>'
        "</div>"
    )


def render_share_bar(pct: float, color: str | None = None) -> str:
    width = max(2.0, min(100.0, pct)) if pct > 0 else 0.0
    color_style = f";background:{html.escape(color, quote=True)}" if color else ""
    return (
        '<span class="share-bar" aria-hidden="true">'
        f'<span style="width:{width:.2f}%{color_style}"></span>'
        "</span>"
    )
