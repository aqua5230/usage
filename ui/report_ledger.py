# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""HTML for the recent Claude dispatch ledger."""

from __future__ import annotations

import html
from typing import Any, Mapping

from usage_common.i18n import _t


def _label(lang: str, key: str, **kwargs: object) -> str:
    return _t(lang, f"report_{key}", **kwargs)


def format_pct(value: float | None, lang: str) -> str:
    if value is None:
        return "—"
    if 0 < value < 0.1:
        return "<0.1%"
    number = f"{value:.1f}" if value < 1 else f"{value:.0f}"
    return _label(lang, "quota_approx", value=number)


def _month_day(value: str) -> str:
    """The ledger covers the last 7 days, so the year only pushes the date onto two lines."""
    return value[5:] if len(value) == 10 and value[4] == "-" else value


def render_ledger(data: Mapping[str, Any], lang: str) -> str:
    ledger = data.get("dispatch_ledger")
    if not isinstance(ledger, Mapping):
        return ""
    rows = ledger.get("rows")
    if not isinstance(rows, list) or not rows:
        return ""
    headers = (
        "ledger_date",
        "project",
        "ledger_title",
        "ledger_count",
        "ledger_claude",
        "ledger_codex",
        "ledger_agy",
    )
    head = "".join(f"<th>{html.escape(_label(lang, key))}</th>" for key in headers)
    body = "".join(
        "<tr>"
        + f'<td class="ledger-date">{html.escape(_month_day(str(row["date"])))}</td>'
        + f"<td data-mask>{html.escape(str(row['project']))}</td>"
        + f'<td class="name" data-mask>{html.escape(str(row["title"]))}</td>'
        + f"<td>{int(row['dispatch_count'])}</td>"
        + "".join(
            f"<td>{html.escape(format_pct(row[key], lang))}</td>"
            for key in ("claude_pct", "codex_pct", "agy_pct")
        )
        + "</tr>"
        for row in rows
    )
    unowned = []
    for key, label in (("unowned_codex", "ledger_codex"), ("unowned_agy", "ledger_agy")):
        count = int(ledger.get(key, 0))
        if count:
            unowned.append(
                _label(
                    lang,
                    "ledger_unowned_part",
                    count=count,
                    agent={"ledger_codex": "Codex", "ledger_agy": "Antigravity"}[label],
                )
            )
    items = _label(lang, "ledger_unowned_sep").join(unowned)
    note = (
        f"<small>{html.escape(_label(lang, 'ledger_unowned', items=items))}</small>"
        if unowned
        else ""
    )
    return (
        '<section class="section dispatch-ledger-section">'
        f'<div class="prompt"><span>[usage]&gt;</span> {html.escape(_label(lang, "ledger_section"))}</div>'
        '<div class="rule" aria-hidden="true">────────────────────────────────────────────────────────</div>'
        f"<div>{note}</div>"
        f"<div><small>{html.escape(_label(lang, 'ledger_pct_note'))}</small></div>"
        f'<div class="table-wrap"><table class="ledger-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
        "</section>"
    )
