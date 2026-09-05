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
