# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""HTML for the recent Claude dispatch ledger."""

from __future__ import annotations

import html
from typing import Any, Mapping, cast

from analyzer.dispatch_ledger import LedgerData, ledger_blocks
from usage_common.i18n import _t


def _label(lang: str, key: str, **kwargs: object) -> str:
    return _t(lang, f"report_{key}", **kwargs)


def format_pct(value: float | None, lang: str) -> str:
    if value is None:
        return "—"
    if 0 < value < 0.1:
        return "<0.1%"
    # Round first so 0.95 reads "1%", not "1.0%".
    number = f"{value:.1f}" if round(value, 1) < 1 else f"{value:.0f}"
    return _label(lang, "quota_approx", value=number)


# Antigravity's quota groups arrive as shouty names that wrap the cell onto four lines.
_AGY_GROUP_SHORT = {
    "GEMINI MODELS": "Gemini",
    "CLAUDE AND GPT MODELS": "Claude/GPT",
    "GEMINI 4 ARGON": "Argon",
}


def _rank_line(name: str, value: float, lang: str) -> str:
    return (
        '<div class="rank-line">'
        f'<span class="name"><span class="arrow">&rarr;</span> {name}</span>'
        f'<span class="pct">{html.escape(format_pct(value, lang))}</span></div>'
    )


def render_ledger(data: Mapping[str, Any], lang: str) -> str:
    ledger = data.get("dispatch_ledger")
    if not isinstance(ledger, Mapping):
        return ""
    typed = cast(LedgerData, ledger)
    blocks = ledger_blocks(typed.get("rows", []), typed.get("used_pct", {}))
    if not blocks:
        return ""
    body = []
    for block in blocks:
        quota = block["quota"]
        group = quota.removeprefix("antigravity:")
        name = "Codex" if quota == "codex" else _AGY_GROUP_SHORT.get(group, group)
        used = block["used_pct"]
        header = html.escape(name)
        if used is not None:
            header += " · " + html.escape(_label(lang, "ledger_used", pct=f"{used:.0f}"))
        lines = []
        if block["all_reset"]:
            lines.append(f"<p>{html.escape(_label(lang, 'ledger_all_reset'))}</p>")
        else:
            for row, share in block["conversations"]:
                # Escape the translated template before inserting masked project markup.
                meta = html.escape(
                    _label(
                        lang, "ledger_row_meta", project="{project}", count=row["dispatch_count"]
                    )
                ).replace("{project}", f"<span data-mask>{html.escape(row['project'])}</span>")
                title = f"<span data-mask>{html.escape(row['title'])}</span>"
                lines.append(
                    _rank_line(f'{title} <span class="ledger-meta">· {meta}</span>', share, lang)
                )
            if block["more_count"]:
                lines.append(
                    _rank_line(
                        html.escape(_label(lang, "ledger_more", count=block["more_count"])),
                        block["more_pct"],
                        lang,
                    )
                )
            if block["other_pct"] is not None:
                lines.append(
                    _rank_line(
                        html.escape(_label(lang, "ledger_other")),
                        block["other_pct"],
                        lang,
                    )
                )
        body.append(
            f'<h3 class="ledger-quota">{header}</h3>'
            f'<div class="rank-list ledger-list">{"".join(lines)}</div>'
        )
    return (
        '<section class="section dispatch-ledger-section">'
        f'<div class="prompt"><span>[usage]&gt;</span> {html.escape(_label(lang, "ledger_section"))}</div>'
        '<div class="rule" aria-hidden="true">────────────────────────────────────────────────────────</div>'
        f"<p>{html.escape(_label(lang, 'ledger_lead'))}</p>" + "".join(body) + "</section>"
    )
