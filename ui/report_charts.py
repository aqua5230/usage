# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import html


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
