# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import base64
import html
import json
import math
import os
import csv
import subprocess
import sys
import webbrowser
from datetime import date, datetime
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from io import StringIO
from pathlib import Path
from typing import Any, Mapping

from i18n import _t as _i18n_t
from usage_lang import detect_lang



# Rough USD→TWD rate for the zh-TW cost hint only. A display estimate (prefixed
# with ≈), not a live FX lookup — bump it if it drifts too far from reality.
_USD_TO_TWD = 32

def _t(lang: str, key: str, **kwargs: object) -> str:
    return _i18n_t(lang, f"report_{key}", **kwargs)

def _fmt_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _fmt_cost(value: float) -> str:
    return f"${value:,.4f}" if 0 < value < 1 else f"${value:,.2f}"


def _fmt_duration(minutes: float) -> str:
    if minutes >= 60:
        return f"{int(minutes // 60)}h {int(minutes % 60)}m"
    return f"{int(minutes)}m"


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def _version() -> str:
    try:
        return version("usage")
    except PackageNotFoundError:
        return "dev"


def _detect_lang(env: Mapping[str, str] | None = None) -> str:
    return detect_lang(env)



def _escape(value: object) -> str:
    return html.escape(str(value))


def _display_name(value: object, lang: str) -> str:
    text = str(value) if value else _t(lang, "unknown")
    return _t(lang, "unknown") if text == "unknown" else text


def _localized_text(value: object, lang: str) -> str:
    if not isinstance(value, dict):
        return ""
    for key in (lang, "en"):
        localized = value.get(key)
        if isinstance(localized, str) and localized:
            return localized
    for localized in value.values():
        if isinstance(localized, str) and localized:
            return localized
    return ""


def _section(title: str, body: str, class_name: str = "") -> str:
    classes = "section" if not class_name else f"section {class_name}"
    return f"""
    <section class="{classes}">
      <div class="prompt"><span>[usage]&gt;</span> {html.escape(title)}</div>
      <div class="rule" aria-hidden="true">────────────────────────────────────────────────────────</div>
      {body}
    </section>
    """


def _empty_line(label: str) -> str:
    return f'<div class="empty">→ {html.escape(label)}</div>'


def _rank_line(name: str, pct: float, tokens: int, cost: float, lang: str) -> str:
    return (
        '<div class="rank-line">'
        f'<span class="arrow">→</span><span class="name">{html.escape(name)}</span>'
        f'<span class="pct" data-label="{_escape(_t(lang, "share"))}">{pct:>5.1f}%</span>'
        f'<span class="tokens" data-label="{_escape(_t(lang, "tokens"))}">{_fmt_tokens(tokens)}</span>'
        f'<span class="cost" data-label="{_escape(_t(lang, "cost"))}">{_fmt_cost(cost)}</span>'
        "</div>"
    )


def _parse_daily_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _month_label(month: int, lang: str) -> str:
    return _t(lang, f"contribution_month_{month}")


def _estimate_books(tokens: int) -> int:
    return max(1, round(tokens / 80_000)) if tokens > 0 else 0


@lru_cache(maxsize=4)
def _sprite_data_uri(beast: str) -> str:
    asset_path = (
        Path(__file__).resolve().parent.parent
        / "assets"
        / "critters"
        / beast
        / "1.png"
    )
    encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _weekly_trend(daily: list[dict[str, Any]]) -> list[dict[str, int | float]]:
    weekly: dict[tuple[int, int], dict[str, int | float]] = {}
    for day in daily:
        parsed = _parse_daily_date(day["date"])
        iso_year, iso_week, _weekday = parsed.isocalendar()
        key = (iso_year, iso_week)
        bucket = weekly.setdefault(key, {"year": iso_year, "week": iso_week, "tokens": 0, "cost": 0.0})
        bucket["tokens"] = int(bucket["tokens"]) + int(day.get("tokens", 0))
        bucket["cost"] = float(bucket["cost"]) + float(day.get("cost", 0.0))
    return [weekly[key] for key in sorted(weekly)]


def _trend_summary(weekly: list[dict[str, int | float]], lang: str) -> str:
    if len(weekly) < 2:
        return f"→ {_t(lang, 'trend_compare_first')}"

    current = int(weekly[-1]["tokens"])
    previous = int(weekly[-2]["tokens"])
    if previous == 0:
        if current == 0:
            return f"→ {_t(lang, 'trend_compare_flat')}"
        return f"→ {_t(lang, 'trend_compare_new')}"

    pct = round((current - previous) / previous * 100)
    if abs(pct) <= 5:
        return f"→ {_t(lang, 'trend_compare_flat')}"
    if pct > 0:
        return f"→ {_t(lang, 'trend_compare_up', ratio=f'{current / previous:.1f}')}"
    return f"→ {_t(lang, 'trend_compare_down', pct=abs(pct))}"


_PALETTE = [
    "#58a6ff", "#3fb950", "#d29922", "#bc8cff",
    "#f778ba", "#56d4dd", "#7ee787", "#e3b341",
]


def _trend_delta(current: int, previous: int, lang: str) -> tuple[str, str]:
    if previous == 0:
        if current == 0:
            return "flat", "→ 0%"
        return "up", f"↗ {_t(lang, 'trend_marker_new')}"

    pct = round((current - previous) / previous * 100)
    if abs(pct) <= 5:
        return "flat", "→ 0%"
    if pct > 0:
        return "up", f"↗ +{pct}%"
    return "down", f"↘ {pct}%"


def _trend_ascii(daily: list[dict[str, Any]], lang: str) -> str:
    weekly = _weekly_trend(daily)
    max_tokens = max((int(week["tokens"]) for week in weekly), default=0)
    rows = []
    for idx, week in enumerate(weekly):
        tokens = int(week["tokens"])
        filled = max(1, round(tokens / max_tokens * 12)) if max_tokens and tokens else 0
        bar = "█" * filled
        delta_html = '<span class="delta flat"></span>'
        if idx > 0:
            delta_class, delta_label = _trend_delta(tokens, int(weekly[idx - 1]["tokens"]), lang)
            delta_html = f'<span class="delta {delta_class}">{_escape(delta_label)}</span>'
        rows.append(
            '<div class="trend-row">'
            f'<span class="week">W{int(week["week"])}</span>'
            f'<b>{bar}</b>'
            f'<em>{_fmt_tokens(tokens)}</em>'
            f"{delta_html}"
            "</div>"
        )
    if not rows:
        return _empty_line(_t(lang, "empty_daily"))

    trend_rows = "".join(rows)
    summary = f'<div class="trend-summary">{_escape(_trend_summary(weekly, lang))}</div>'
    return f'<div class="trend">{trend_rows}{summary}</div>'


def _hour_histogram_html(histogram: list[int]) -> str:
    values = [max(0, int(value)) for value in histogram[:24]]
    if len(values) < 24:
        values.extend([0] * (24 - len(values)))
    max_count = max(values, default=0)
    bars = []
    for hour, count in enumerate(values):
        height = max(6, round(count / max_count * 100)) if max_count and count else 0
        class_name = "persona-hour is-peak" if max_count and count == max_count else "persona-hour"
        bars.append(
            f'<div class="{class_name}"'
            f' title="{hour:02d}:00 {count}"'
            f' aria-label="{hour:02d}:00 {count}">'
            f'<span style="height:{height}%"></span>'
            f'<em>{hour:02d}</em>'
            "</div>"
        )
    return f'<div class="persona-hours">{"".join(bars)}</div>'


def _persona_body(persona: object, lang: str) -> str:
    if not isinstance(persona, dict):
        return _empty_line(_t(lang, "persona_empty"))

    raw_histogram = persona.get("hour_histogram", [])
    histogram = raw_histogram if isinstance(raw_histogram, list) else []
    values = [max(0, int(value)) if isinstance(value, int) else 0 for value in histogram[:24]]
    if len(values) < 24:
        values.extend([0] * (24 - len(values)))
    if not any(values):
        return _empty_line(_t(lang, "persona_empty"))

    peak_hours = sorted(
        ((count, hour) for hour, count in enumerate(values) if count > 0),
        key=lambda item: (-item[0], item[1]),
    )[:2]
    h1 = f"{peak_hours[0][1]:02d}:00"
    h2 = (
        _t(lang, "persona_caption_second", h2=f"{peak_hours[1][1]:02d}:00")
        if len(peak_hours) > 1
        else ""
    )
    caption = _t(lang, "persona_caption", h1=h1, h2=h2)
    return (
        '<div class="persona-card">'
        f'<h3>{_escape(_t(lang, "persona_active_hours"))}</h3>'
        f'<p class="persona-caption">{_escape(caption)}</p>'
        f'{_hour_histogram_html(values)}'
        '</div>'
    )


def _donut_svg(items: list[tuple[str, int]], lang: str) -> str:
    data = [(name, tok) for name, tok in items if tok > 0]
    if not data:
        return ""
    total = sum(tok for _, tok in data)
    shown = data[:6]
    rest = sum(tok for _, tok in data[6:])
    if rest > 0:
        shown = [*shown, (_t(lang, "chart_other"), rest)]

    cx = cy = 80.0
    radius = 60.0
    circ = 2 * math.pi * radius
    segs: list[str] = []
    legend: list[str] = []
    offset = 0.0
    for idx, (name, tok) in enumerate(shown):
        frac = tok / total
        seg_len = circ * frac
        color = _PALETTE[idx % len(_PALETTE)]
        segs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{color}" '
            f'stroke-width="22" stroke-dasharray="{seg_len:.2f} {circ - seg_len:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += seg_len
        legend.append(
            f'<li><span class="dot" style="background:{color}"></span>'
            f'<span class="lg-name">{html.escape(name)}</span>'
            f'<span class="lg-pct">{frac * 100:.1f}%</span></li>'
        )
    center = (
        f'<text x="{cx}" y="{cy - 3}" class="donut-total" text-anchor="middle">{_fmt_tokens(total)}</text>'
        f'<text x="{cx}" y="{cy + 15}" class="donut-sub" text-anchor="middle">tokens</text>'
    )
    return (
        '<div class="donut-wrap">'
        f'<svg class="donut" viewBox="0 0 160 160" role="img" '
        f'aria-label="{_escape(_t(lang, "project_section"))}">{"".join(segs)}{center}</svg>'
        f'<ul class="donut-legend">{"".join(legend)}</ul>'
        '</div>'
    )


def _tools_body(subs: list[dict[str, Any]], agents: list[dict[str, Any]], lang: str) -> str:
    """One card per tool, joining subscription plan with usage by tool name."""
    by_name = {str(sub.get("agent", "")): sub for sub in subs}
    seen: set[str] = set()
    rows: list[str] = []

    def _plan_html(sub: dict[str, Any] | None) -> str:
        if not sub:
            return ""
        plan = sub.get("plan")
        since = sub.get("since")
        since_html = (
            f'<span class="sub-since" data-mask>{_escape(_t(lang, "sub_since"))} {_escape(since)}</span>'
            if since
            else ""
        )
        plan_html = f'<span class="sub-plan">{_escape(str(plan))}</span>' if plan else ""
        return plan_html + since_html

    def _row(name: str, plan_html: str, stats_html: str) -> str:
        return (
            '<div class="tool-row">'
            f'<div class="tool-head"><span class="sub-agent">{_escape(name)}</span>{plan_html}</div>'
            f"{stats_html}"
            "</div>"
        )

    for agent in agents:
        name = _display_name(agent["name"], lang)
        seen.add(str(agent["name"]))
        stats_html = (
            f'<span class="pct" data-label="{_escape(_t(lang, "share"))}">{float(agent["pct"]):.1f}%</span>'
            f'<span class="tokens" data-label="{_escape(_t(lang, "tokens"))}">{_fmt_tokens(int(agent["tokens"]))}</span>'
            f'<span class="cost" data-label="{_escape(_t(lang, "cost"))}">{_fmt_cost(float(agent["cost"]))}</span>'
        )
        rows.append(_row(name, _plan_html(by_name.get(str(agent["name"]))), stats_html))

    # Subscriptions for tools that have no usage in this period still get a card.
    for sub_name, sub in by_name.items():
        if sub_name in seen or not sub_name:
            continue
        rows.append(_row(sub_name, _plan_html(sub), "<span></span><span></span><span></span>"))

    if not rows:
        return _empty_line(_t(lang, "sub_empty"))
    head = (
        '<div class="tools-head">'
        "<span></span>"
        f'<span>{_escape(_t(lang, "share"))}</span>'
        f'<span>{_escape(_t(lang, "tokens"))}</span>'
        f'<span>{_escape(_t(lang, "cost"))}</span>'
        "</div>"
    )
    return f'<div class="tools">{head}{"".join(rows)}</div>'


def _narrative(data: dict[str, Any], lang: str) -> str:
    summary = data["summary"]
    daily = data.get("daily_trend", [])
    peak = max(daily, key=lambda day: int(day["tokens"]), default={"date": data.get("date_to", "---- -- --"), "tokens": 0})
    top_model = data.get("by_model", [{}])[0].get("model", _t(lang, "unknown")) if data.get("by_model") else _t(lang, "unknown")
    return _t(
        lang,
        "narrative",
        tokens=_fmt_tokens(int(summary["total_tokens"])),
        projects=len(data.get("by_project", [])),
        peak_date=str(peak["date"]),
        peak_tokens=_fmt_tokens(int(peak["tokens"])),
        top_model=_display_name(top_model, lang),
    )


def _cost_value(cost_usd: float, lang: str) -> tuple[str, str]:
    main = _fmt_cost(cost_usd)
    sub = f"≈ NT${cost_usd * _USD_TO_TWD:,.0f}" if lang == "zh-TW" else ""
    return main, sub


def _render_cards_section(cards: list[tuple[str, str, str]]) -> str:
    return f"""<section class="cards">{''.join(f'<div class="card"><span>{html.escape(label)}</span><b>{html.escape(value)}</b>' + (f'<i>{html.escape(sub)}</i>' if sub else '') + '</div>' for label, value, sub in cards)}</section>"""


def _summary_cards(summary: Mapping[str, Any], lang: str) -> list[tuple[str, str, str]]:
    total_tokens = int(summary["total_tokens"])
    cost_main, cost_sub = _cost_value(float(summary["cost_usd"]), lang)
    return [
        (_t(lang, "kpi_tokens"), f"{total_tokens:,}", f"≈ {_fmt_tokens(total_tokens)}"),
        (_t(lang, "kpi_cost"), cost_main, cost_sub),
        (_t(lang, "kpi_sessions"), f'{int(summary["sessions"]):,}', ""),
        (_t(lang, "kpi_messages"), f'{int(summary["messages"]):,}', ""),
        (_t(lang, "kpi_active"), f'{int(summary["active_days"])}/{int(summary["total_days"])}', ""),
    ]


def _render_header(data: dict[str, Any], lang: str, title: str, generated_at: str) -> str:
    return f"""<header>
    <div>
      <div class="eyebrow"><span>$ usage report</span> --period {html.escape(str(data["period_label"]))}<span class="cursor">_</span></div>
      <h1>{html.escape(title)}</h1>
      <p class="narrative">{html.escape(_narrative(data, lang))}</p>
    </div>
    <div class="header-actions">
      <div class="meta">{html.escape(_t(lang, "generated"))} {html.escape(generated_at)}<br>usage {_escape(_t(lang, "version"))} {_escape(_version())}</div>
      <button class="share-trigger" type="button" data-share-open><span aria-hidden="true">↗</span>{html.escape(_t(lang, "share_button_label"))}</button>
    </div>
  </header>"""


def _render_share_dialog(lang: str) -> str:
    return f"""<dialog class="share-dialog" data-share-dialog>
    <div class="share-modal">
      <button class="share-close" type="button" data-share-close aria-label="{html.escape(_t(lang, "share_close"))}">×</button>
      <h2>{html.escape(_t(lang, "share_modal_title"))}</h2>
      <section class="share-section">
        <h3>{html.escape(_t(lang, "share_file_title"))}</h3>
        <label class="share-file-mask"><input type="checkbox" data-share-file-mask checked> {html.escape(_t(lang, "share_file_mask_toggle"))}</label>
        <div class="share-file-actions">
          <button class="share-action" type="button" data-share-file="download"><span class="share-icon" aria-hidden="true">📥</span>{html.escape(_t(lang, "share_download_html"))}</button>
          <button class="share-action" type="button" data-share-file="csv"><span class="share-icon" aria-hidden="true">📊</span>{html.escape(_t(lang, "share_download_csv"))}</button>
        </div>
        <p class="share-file-hint">{html.escape(_t(lang, "share_file_hint"))}</p>
      </section>
      <div class="share-toast" data-share-toast role="status" aria-live="polite"></div>
    </div>
  </dialog>"""


def _render_project_section(data: dict[str, Any], lang: str) -> str:
    project_rows = [
        _rank_line(
            _display_name(project["project"], lang),
            float(project["pct"]),
            int(project["tokens"]),
            float(project["cost"]),
            lang,
        )
        for project in data.get("by_project", [])
    ]
    project_rows_html = "".join(project_rows)
    project_donut = _donut_svg(
        [(_display_name(project["project"], lang), int(project["tokens"])) for project in data.get("by_project", [])],
        lang,
    )
    project_body = (
        project_donut
        + f'<div class="rank-head"><span></span><span>{_escape(_t(lang, "project"))}</span><span>{_escape(_t(lang, "share"))}</span><span>{_escape(_t(lang, "tokens"))}</span><span>{_escape(_t(lang, "cost"))}</span></div>'
        + f'<div class="rank-list">{project_rows_html}</div>'
        if project_rows
        else _empty_line(_t(lang, "empty_projects"))
    )
    return _section(_t(lang, "project_section"), project_body, "project-section")


def _render_model_section(data: dict[str, Any], lang: str) -> str:
    model_rows = [
        _rank_line(
            _display_name(model["model"], lang),
            float(model["pct"]),
            int(model["tokens"]),
            float(model["cost"]),
            lang,
        )
        for model in data.get("by_model", [])
    ]
    model_rows_html = "".join(model_rows)
    model_body = (
        f'<div class="rank-head"><span></span><span>{_escape(_t(lang, "model"))}</span><span>{_escape(_t(lang, "share"))}</span><span>{_escape(_t(lang, "tokens"))}</span><span>{_escape(_t(lang, "cost"))}</span></div>'
        f'<div class="rank-list">{model_rows_html}</div>'
        if model_rows
        else _empty_line(_t(lang, "empty_models"))
    )
    return _section(_t(lang, "model_section"), model_body)


def _render_tools_section(data: dict[str, Any], lang: str) -> str:
    tools_body = _tools_body(data.get("subscriptions", []), data.get("by_agent", []), lang)
    return _section(_t(lang, "tools_section"), tools_body, "tools-section")


def _render_insight_note(component: dict[str, Any], lang: str) -> str:
    return (
        '<div class="insight-note">'
        f'{_t(lang, component["key"], **_insight_kwargs(component))}'
        '</div>'
    )


def _render_insight_action(component: dict[str, Any], lang: str) -> str:
    return (
        '<div class="insight-action">'
        f'{_t(lang, component["key"], **_insight_kwargs(component))}'
        '</div>'
    )


def _insight_kwargs(component: dict[str, Any]) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    for key, value in component.items():
        if key in {"key", "type", "direction", "delta_pct"}:
            continue
        if key == "tokens" or key == "mean_tokens":
            kwargs[key] = _fmt_tokens(int(value))
        elif key == "cost_usd":
            kwargs[key] = _fmt_cost(float(value))
        elif key in {"project", "model", "date"}:
            kwargs[key] = _escape(value)
        else:
            kwargs[key] = value
    return kwargs


def _render_insight_surface(data: dict[str, Any], lang: str) -> str:
    from analyzer.insights import build_insights

    components = build_insights(data)
    quiet = f'<div class="insight-note">{_t(lang, "insights_quiet")}</div>'
    if not components:
        return _section(_t(lang, "insights_section"), quiet, "insights-section")

    renderers = {
        "change_headline": _render_insight_note,
        "spike": _render_insight_note,
        "shift": _render_insight_note,
        "pace_note": _render_insight_note,
        "action": _render_insight_action,
    }
    body = "".join(
        renderer(component, lang)
        for component in components
        if (renderer := renderers.get(str(component.get("type")))) is not None
    )
    if not body:
        body = quiet
    return _section(_t(lang, "insights_section"), body, "insights-section")


def _render_trend_section(data: dict[str, Any], lang: str) -> str:
    return _section(_t(lang, "trend_section"), _trend_ascii(data.get("daily_trend", []), lang))


def _render_contribution_section(data: dict[str, Any], lang: str) -> str:
    contribution = data.get("contribution")
    if not isinstance(contribution, dict) or int(contribution.get("active_days", 0)) <= 0:
        return ""

    raw_weeks = contribution.get("weeks", [])
    weeks = [
        week for week in raw_weeks
        if isinstance(week, list) and len(week) == 7
    ]
    if not weeks:
        return ""

    month_labels: list[str] = []
    seen_month: int | None = None
    last_label_col = -3
    for col, week in enumerate(weeks):
        parsed = _parse_daily_date(week[0].get("date", ""))
        label = ""
        if parsed.month != seen_month and col - last_label_col >= 3:
            label = _month_label(parsed.month, lang)
            last_label_col = col
        seen_month = parsed.month
        month_labels.append(label)

    grid_cells: list[str] = []
    for week in weeks:
        for cell in week:
            cell_date = str(cell.get("date", ""))
            tokens = int(cell.get("tokens", 0))
            level = max(0, min(4, int(cell.get("level", 0))))
            title = _t(lang, "contribution_cell_title", date=cell_date, tokens=_fmt_int(tokens))
            grid_cells.append(
                f'<span class="contribution-cell level-{level}" title="{_escape(title)}" '
                f'aria-label="{_escape(title)}"></span>'
            )

    busiest_day = contribution.get("busiest_day")
    busiest_value = "—"
    if isinstance(busiest_day, dict):
        busiest_value = (
            f'{_escape(busiest_day.get("date", ""))} · '
            f'{_escape(_fmt_tokens(int(busiest_day.get("tokens", 0))))}'
        )

    days_unit = _escape(_t(lang, "contribution_days_unit"))
    current_streak = (
        f'{_escape(_fmt_int(int(contribution.get("current_streak", 0))))} {days_unit}'
    )
    longest_streak = (
        f'{_escape(_fmt_int(int(contribution.get("longest_streak", 0))))} {days_unit}'
    )
    stats = [
        (_t(lang, "contribution_current_streak"), current_streak),
        (_t(lang, "contribution_longest_streak"), longest_streak),
        (_t(lang, "contribution_busiest_day"), busiest_value),
    ]
    stats_html = "".join(
        '<div class="contribution-stat">'
        f'<span>{_escape(label)}</span><b>{value}</b>'
        "</div>"
        for label, value in stats
    )
    month_html = "".join(
        f'<span>{_escape(label)}</span>' for label in month_labels
    )
    legend_cells = "".join(
        f'<span class="contribution-cell level-{level}" aria-hidden="true"></span>'
        for level in range(5)
    )
    body = (
        '<div class="contribution-wrap">'
        f'<div class="contribution-heatmap" style="--weeks:{len(weeks)}">'
        f'<div class="contribution-months">{month_html}</div>'
        '<div class="contribution-board">'
        '<div class="contribution-days">'
        '<span></span>'
        f'<span>{_escape(_t(lang, "contribution_mon"))}</span>'
        '<span></span>'
        f'<span>{_escape(_t(lang, "contribution_wed"))}</span>'
        '<span></span>'
        f'<span>{_escape(_t(lang, "contribution_fri"))}</span>'
        '<span></span>'
        '</div>'
        f'<div class="contribution-grid">{ "".join(grid_cells) }</div>'
        '</div>'
        '<div class="contribution-legend">'
        f'<span>{_escape(_t(lang, "contribution_less"))}</span>'
        f'{legend_cells}'
        f'<span>{_escape(_t(lang, "contribution_more"))}</span>'
        '</div>'
        '</div>'
        f'<div class="contribution-stats">{stats_html}</div>'
        '</div>'
    )
    return _section(_t(lang, "contribution_section"), body, "contribution-section")


def _render_wrapped_section(data: dict[str, Any], lang: str) -> str:
    wrapped = data.get("wrapped")
    if not isinstance(wrapped, dict):
        return ""

    beast = wrapped.get("beast")
    if beast not in {"phoenix", "dragon"}:
        return ""

    beast_name = _t(lang, f"wrapped_beast_{beast}_title")
    beast_caption = _t(lang, f"wrapped_beast_{beast}_caption")
    books = _estimate_books(int(wrapped.get("total_tokens", 0)))
    top_project = _display_name(wrapped.get("top_project"), lang)
    top_model = _display_name(wrapped.get("top_model"), lang)
    body = (
        '<div class="wrapped-card">'
        '<div class="wrapped-copy">'
        f'<div class="wrapped-kicker">{_escape(_t(lang, "wrapped_year_badge", year=wrapped.get("year_label", "")))}</div>'
        f'<h3>{_escape(beast_name)}</h3>'
        f'<p class="wrapped-beast-line">{_escape(beast_caption)}</p>'
        f'<div class="wrapped-total">{_escape(_fmt_int(int(wrapped.get("total_tokens", 0))))}</div>'
        f'<p class="wrapped-total-label">{_escape(_t(lang, "wrapped_total_tokens"))}</p>'
        f'<p class="wrapped-analogy">{_escape(_t(lang, "wrapped_books_equivalent", books=_fmt_int(books)))}</p>'
        '</div>'
        '<div class="wrapped-art">'
        f'<img src="{_escape(_sprite_data_uri(str(beast)))}" alt="{_escape(beast_name)}">'
        '</div>'
        '<div class="wrapped-metrics">'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_total_cost"))}</span><b>{_escape(_fmt_cost(float(wrapped.get("total_cost", 0.0))))}</b></div>'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_active_days"))}</span><b>{_escape(_fmt_int(int(wrapped.get("active_days", 0))))}</b></div>'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_longest_streak"))}</span><b>{_escape(_fmt_int(int(wrapped.get("longest_streak", 0))))} {_escape(_t(lang, "contribution_days_unit"))}</b></div>'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_top_model"))}</span><b>{_escape(top_model)}</b></div>'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_top_project"))}</span><b data-mask>{_escape(top_project)}</b></div>'
        '</div>'
        '</div>'
    )
    return _section(_t(lang, "wrapped_section"), body, "wrapped-section")


def _render_persona_section(data: dict[str, Any], lang: str) -> str:
    persona_body = _persona_body(data.get("persona"), lang)
    return _section(_t(lang, "persona_section"), persona_body, "persona-section")


def _render_session_section(data: dict[str, Any], lang: str) -> str:
    session_rows = []
    for idx, session in enumerate(data.get("top_sessions", []), 1):
        session_rows.append(f"""
        <tr>
          <td>#{idx}</td>
          <td>{_escape(session["start_time"])}</td>
          <td class="name">{_escape(_display_name(session["project"], lang))}</td>
          <td>{_escape(_display_name(session["model"], lang))}</td>
          <td>{_fmt_duration(float(session["duration_min"]))}</td>
          <td>{_fmt_tokens(int(session["tokens"]))}</td>
          <td>{_fmt_cost(float(session["cost"]))}</td>
        </tr>""")
    session_body = (
        f"""
        <div class="table-wrap">
          <table>
            <thead><tr><th>{_escape(_t(lang, "rank"))}</th><th>{_escape(_t(lang, "start_time"))}</th><th>{_escape(_t(lang, "project"))}</th><th>{_escape(_t(lang, "model"))}</th><th>{_escape(_t(lang, "duration"))}</th><th>{_escape(_t(lang, "tokens"))}</th><th>{_escape(_t(lang, "cost"))}</th></tr></thead>
            <tbody>{''.join(session_rows)}</tbody>
          </table>
        </div>
        """
        if session_rows
        else _empty_line(_t(lang, "empty_sessions"))
    )
    return _section(_t(lang, "session_section"), session_body, "session-section")


def _render_ai_updates_section(data: dict[str, Any], lang: str) -> str:
    raw_updates = data.get("ai_updates")
    if not isinstance(raw_updates, list) or not raw_updates:
        return ""

    cards: list[str] = []
    for tool in raw_updates:
        if not isinstance(tool, dict):
            continue
        raw_items = tool.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            continue

        items: list[str] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            title = _localized_text(item.get("title"), lang)
            body = _localized_text(item.get("body"), lang)
            original = item.get("original")
            if not title or not body or not isinstance(original, str):
                continue
            items.append(
                '<li class="ai-update-item">'
                f'<p class="ai-update-item-title">{_escape(title)}</p>'
                f'<p class="ai-update-item-body">{_escape(body)}</p>'
                '<details class="ai-update-original">'
                f'<summary>{_escape(_t(lang, "ai_updates_original"))}</summary>'
                f'<div>{_escape(original)}</div>'
                "</details>"
                "</li>"
            )

        if not items:
            continue
        cards.append(
            '<article class="ai-update-card">'
            f'<div class="ai-update-head"><h3>{_escape(tool.get("name", ""))}</h3>'
            f'<span class="ai-update-version">{_escape(_t(lang, "ai_updates_updated_to"))} {_escape(tool.get("version", ""))}</span></div>'
            f'<p class="ai-update-period">{_escape(tool.get("period", ""))}</p>'
            f'<ol class="ai-update-items">{"".join(items)}</ol>'
            "</article>"
        )
    if not cards:
        return ""
    return _section(
        _t(lang, "ai_updates_section"),
        f'<div class="ai-updates-grid">{"".join(cards)}</div>',
        "ai-updates-section",
    )


def _share_config_json(lang: str) -> str:
    share_config = {
        "copied": _t(lang, "share_copied"),
        "pathCopied": _t(lang, "share_path_copied"),
    }
    return json.dumps(share_config, ensure_ascii=False).replace("</", "<\\/")


def _csv_cost(value: float) -> str:
    return f"{value:.4f}" if 0 < value < 1 else f"{value:.2f}"


def _build_csv_data(data: dict[str, Any], lang: str, *, mask_projects: bool = False) -> str:
    out = StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["type", "name", "share_pct", "tokens", "cost_usd"])
    for idx, item in enumerate(data.get("by_project", []), start=1):
        writer.writerow(
            [
                "project",
                f"Project {idx}" if mask_projects else _display_name(item.get("project"), lang),
                f"{float(item.get('pct', 0.0)):.1f}",
                str(int(item.get("tokens", 0))),
                _csv_cost(float(item.get("cost", 0.0))),
            ]
        )
    for item in data.get("by_model", []):
        writer.writerow(
            [
                "model",
                _display_name(item.get("model"), lang),
                f"{float(item.get('pct', 0.0)):.1f}",
                str(int(item.get("tokens", 0))),
                _csv_cost(float(item.get("cost", 0.0))),
            ]
        )
    return out.getvalue()


def _render_sponsor_section(lang: str) -> str:
    return f"""<p class="sponsor">
    <a href="https://ko-fi.com/lollapalooza" target="_blank" rel="noopener" aria-label="Buy me a coffee on Ko-fi"><img src="https://img.shields.io/badge/Ko--fi-FF5E5B?logo=ko-fi&amp;logoColor=white" alt="Ko-fi"></a>
    <span class="tagline">{html.escape(_t(lang, "sponsor"))}</span>
    <a href="https://ko-fi.com/lollapalooza" target="_blank" rel="noopener" aria-label="Buy me a coffee on Ko-fi"><img src="https://img.shields.io/badge/Ko--fi-FF5E5B?logo=ko-fi&amp;logoColor=white" alt="Ko-fi"></a>
  </p>
  <p class="sponsor-link"><a href="https://github.com/aqua5230/usage" target="_blank" rel="noopener">github.com/aqua5230/usage</a></p>"""


def _render_styles() -> str:
    empty = ""
    return f"""{empty}:root{{--bg:#050505;--panel:#0d0f12;--soft:#15181d;--text:#f2f4f8;--muted:#8b949e;--faint:#343941;--token:#58a6ff;--cost:#3fb950;--warn:#d29922;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;line-height:1.55}}
.wrap{{max-width:960px;margin:0 auto;padding:42px 22px 34px}}
header{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;align-items:start;margin-bottom:26px}}
h1{{margin:0 0 10px;font-size:clamp(1.8rem, 4.2vw, 3rem);line-height:1.02;font-weight:800;letter-spacing:-0.02em;white-space:nowrap}}
.eyebrow,.meta,.empty,footer{{color:var(--muted)}}
.eyebrow span,.prompt span,.cursor{{color:var(--token)}}
.cursor{{display:inline-block;animation:blink 1s steps(2,start) infinite}}
.narrative{{max-width:760px;margin:18px 0 0;color:#d5dbe4;font-size:1.02rem}}
.meta{{font-size:.82rem;text-align:right;white-space:nowrap}}
.header-actions{{display:flex;flex-direction:column;align-items:flex-end;gap:10px}}
.share-trigger{{display:inline-flex;align-items:center;gap:7px;background:#161b22;border:1px solid #30363d;color:#f0f6fc;padding:4px 11px;border-radius:4px;cursor:pointer;font:inherit;font-size:.8rem;line-height:1.3;text-decoration:none;transition:border-color .15s,color .15s,transform .15s}}
.share-trigger:hover{{border-color:#58a6ff;color:#58a6ff;transform:translateY(-1px)}}
.share-trigger:focus-visible,.share-close:focus-visible,.share-action:focus-visible{{outline:2px solid #58a6ff;outline-offset:2px}}
.cards{{display:grid;grid-template-columns:1.7fr 1.15fr .95fr .95fr .95fr;gap:10px;margin:22px 0 12px}}
.card{{background:var(--panel);padding:16px 14px;border-radius:6px;min-height:108px;display:flex;flex-direction:column}}
.card span{{display:block;color:var(--muted);font-size:.75rem;text-transform:uppercase;margin-bottom:10px}}
.card b{{display:block;font-size:clamp(1rem,1.5vw,1.3rem);color:var(--text);white-space:nowrap;overflow-wrap:normal;line-height:1.2;font-weight:700;letter-spacing:-.01em;font-variant-numeric:tabular-nums}}
.card i{{display:block;font-style:normal;color:var(--muted);font-size:.72rem;margin-top:auto;padding-top:6px;overflow-wrap:anywhere;letter-spacing:0}}
.card:first-child b{{color:var(--token)}}.card:nth-child(2) b{{color:var(--cost)}}
.section{{background:var(--panel);border-radius:8px;margin-top:16px;padding:18px 16px}}
.prompt{{font-size:.95rem;color:#f0f6fc;margin-bottom:4px}}
.rule{{color:var(--faint);white-space:nowrap;overflow:hidden;margin-bottom:14px}}
.rank-head,.rank-line{{display:grid;grid-template-columns:24px minmax(0,1fr) 72px 92px 88px;gap:12px;align-items:center}}
.rank-head{{color:var(--muted);font-size:.74rem;text-transform:uppercase;margin-bottom:8px}}
.rank-head>span:nth-child(n+3){{text-align:right}}
.rank-line{{padding:7px 0;color:#dce2ea}}
.arrow{{color:var(--warn)}}.name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.pct{{color:var(--token)}}.cost{{color:var(--cost)}}.tokens,.cost,.pct{{text-align:right;white-space:nowrap}}
.trend{{display:grid;gap:6px}}
.trend-row{{display:grid;grid-template-columns:58px minmax(0,1fr) 72px 82px;gap:12px;align-items:center}}
.trend-row .week{{color:var(--muted)}}.trend-row b{{color:var(--token);font-weight:400;white-space:nowrap;overflow:hidden}}.trend-row em{{font-style:normal;text-align:right;color:#dce2ea}}.delta{{color:var(--muted);white-space:nowrap}}.delta.up{{color:var(--cost)}}.delta.down{{color:var(--warn)}}.delta.flat{{color:var(--muted)}}.trend-summary{{color:#dce2ea;margin-top:8px}}
.persona-card{{border:1px solid #30363d;border-radius:7px;background:#090b0e;padding:14px;min-width:0}}
.persona-card h3{{margin:0 0 12px;color:#f0f6fc;font-size:.9rem;font-weight:700;letter-spacing:0}}
.persona-caption{{margin:0 0 14px;color:#dce2ea;font-size:.86rem;line-height:1.5}}
.persona-hours{{display:grid;grid-template-columns:repeat(24,minmax(8px,1fr));gap:4px;align-items:end;height:176px;padding-top:8px}}
.persona-hour{{display:grid;grid-template-rows:1fr auto;gap:7px;align-items:end;min-width:0;height:100%}}
.persona-hour span{{display:block;width:100%;min-height:1px;border-radius:3px 3px 1px 1px;background:linear-gradient(180deg,var(--token),#285f9f)}}
.persona-hour.is-peak span{{background:linear-gradient(180deg,#56d364,var(--token));box-shadow:0 0 12px rgba(86,211,100,.28)}}
.persona-hour em{{font-style:normal;color:var(--muted);font-size:.58rem;text-align:center;overflow:hidden}}
.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:760px}}th,td{{padding:8px 10px;text-align:left;font-size:.86rem}}th{{color:var(--muted);font-weight:500;text-transform:uppercase}}td{{color:#dce2ea}}td:first-child{{color:var(--warn)}}
.share-dialog{{width:min(760px,calc(100vw - 28px));max-height:min(92vh,860px);border:1px solid #30363d;border-radius:8px;background:#0d0f12;color:var(--text);padding:0;box-shadow:0 24px 70px rgba(0,0,0,.58);overflow:auto}}
.share-dialog::backdrop{{background:rgba(0,0,0,.72)}}
.share-modal{{position:relative;padding:20px;display:grid;gap:16px;align-content:start}}
.share-modal h2{{margin:0 40px 0 0;font-size:1.1rem;line-height:1.35;letter-spacing:0}}
.share-close{{position:absolute;top:14px;right:14px;width:30px;height:30px;display:grid;place-items:center;border:1px solid #30363d;border-radius:4px;background:#161b22;color:#f0f6fc;cursor:pointer;font:inherit;font-size:1.1rem;line-height:1}}
.share-close:hover{{border-color:#58a6ff;color:#58a6ff}}
.share-section{{border:1px solid #30363d;border-radius:8px;background:#090b0e;padding:14px;display:grid;gap:12px}}
.share-section h3{{margin:0;color:#f0f6fc;font-size:.98rem;line-height:1.35;letter-spacing:0}}
.share-file-mask{{display:inline-flex;align-items:center;gap:9px;color:#dce2ea;font-size:.86rem;cursor:pointer;user-select:none}}
.share-file-mask input{{width:16px;height:16px;accent-color:#58a6ff}}
.share-action{{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:36px;border:1px solid #30363d;border-radius:4px;background:#161b22;color:#f0f6fc;cursor:pointer;font:inherit;font-size:.78rem;line-height:1.2;white-space:nowrap;transition:border-color .15s,color .15s,transform .15s}}
.share-action:hover{{border-color:#58a6ff;color:#58a6ff;transform:translateY(-1px)}}
.share-icon{{color:#58a6ff;font-weight:800}}
.share-file-actions{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
.share-file-hint{{margin:0;color:var(--muted);font-size:.8rem;line-height:1.5}}
.share-toast{{min-height:20px;color:#56d364;font-size:.82rem;opacity:0;transition:opacity .15s}}
.share-toast.show{{opacity:1}}
.sponsor{{display:flex;justify-content:center;align-items:center;gap:18px;flex-wrap:wrap;padding:24px 16px 32px;color:var(--muted);font-size:.88rem}}
.sponsor a{{opacity:.85;transition:opacity .2s,transform .2s;text-decoration:none;display:inline-flex}}
.sponsor a:hover{{opacity:1;transform:scale(1.06)}}
.sponsor img{{vertical-align:middle;display:block}}
.tagline{{font-size:1rem;color:#d5dbe4;letter-spacing:.01em;animation:sponsorWobble 2.6s ease-in-out infinite;display:inline-block;transform-origin:center center}}
.sponsor-link{{text-align:center;padding:0 16px 24px;font-size:.8rem}}
.sponsor-link a{{color:var(--muted);text-decoration:none;opacity:.7;transition:opacity .2s}}
.sponsor-link a:hover{{opacity:1;color:var(--token)}}
@keyframes blink{{0%,45%{{opacity:1}}46%,100%{{opacity:0}}}}
@keyframes sponsorWobble{{0%,100%{{transform:translate(0,0) rotate(0)}}25%{{transform:translate(-1px,-2px) rotate(-.8deg)}}50%{{transform:translate(0,-2.5px) rotate(0)}}75%{{transform:translate(1px,-2px) rotate(.8deg)}}}}
.trend{{display:grid;gap:6px}}
.trend-row{{display:grid;grid-template-columns:58px minmax(0,1fr) 72px 82px;gap:12px;align-items:center}}
.trend-row .week{{color:var(--muted)}}.trend-row b{{color:var(--token);font-weight:400;white-space:nowrap;overflow:hidden}}.trend-row em{{font-style:normal;text-align:right;color:#dce2ea}}.delta{{color:var(--muted);white-space:nowrap}}.delta.up{{color:var(--cost)}}.delta.down{{color:var(--warn)}}.delta.flat{{color:var(--muted)}}.trend-summary{{color:#dce2ea;margin-top:8px}}
.donut-wrap{{display:flex;align-items:center;gap:24px;flex-wrap:wrap;margin-bottom:18px}}
.donut{{width:150px;height:150px;flex:0 0 auto}}
.donut-total{{fill:var(--text);font-size:20px;font-weight:700}}
.donut-sub{{fill:var(--muted);font-size:11px;text-transform:uppercase}}
.donut-legend{{list-style:none;margin:0;padding:0;display:grid;gap:8px;flex:1 1 200px;min-width:200px}}
.donut-legend li{{display:grid;grid-template-columns:12px minmax(0,1fr) auto;gap:10px;align-items:center;font-size:.86rem;color:#dce2ea}}
.donut-legend .dot{{width:10px;height:10px;border-radius:2px}}
.donut-legend .lg-name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.donut-legend .lg-pct{{color:var(--muted);text-align:right}}
.tools{{display:grid;gap:10px}}
.tools-head,.tool-row{{display:grid;grid-template-columns:minmax(0,1fr) 72px 100px 100px;gap:18px;align-items:center}}
.tools-head{{padding:0 17px;color:var(--muted);font-size:.74rem;text-transform:uppercase;margin-bottom:-2px}}
.tools-head>span:nth-child(n+2){{text-align:right}}
.tool-row{{padding:14px 16px;border:1px solid #30363d;border-radius:7px;background:#090b0e}}
.tool-head{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-width:0}}
.sub-agent{{font-weight:700;color:#f0f6fc}}
.sub-plan{{color:var(--token);background:rgba(56,139,253,0.12);padding:3px 11px;border-radius:999px;font-size:.86rem}}
.sub-since{{color:var(--muted);font-size:.84rem}}
.tool-row .pct,.tool-row .tokens,.tool-row .cost{{white-space:nowrap;text-align:right}}
.tool-row .pct{{color:var(--token)}}.tool-row .tokens{{color:#dce2ea}}.tool-row .cost{{color:var(--cost)}}
.ai-updates-grid{{display:grid;gap:12px}}
.ai-update-card{{padding:14px 16px;border:1px solid #30363d;border-radius:7px;background:#090b0e}}
.ai-update-head{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}}
.ai-update-head h3{{margin:0;color:#f0f6fc;font-size:1rem;line-height:1.35}}
.ai-update-version{{color:var(--token);font-size:.84rem;white-space:nowrap}}
.ai-update-period{{margin:8px 0 0;color:var(--muted);font-size:.82rem}}
.ai-update-items{{list-style:none;display:grid;gap:14px;margin:14px 0 0;padding:0;counter-reset:ai-updates}}
.ai-update-item{{position:relative;counter-increment:ai-updates;padding:14px 14px 12px 46px;border:1px solid #20252c;border-radius:8px;background:linear-gradient(180deg,#10141a,#0c1015);box-shadow:inset 0 1px 0 rgba(255,255,255,.03)}}
.ai-update-item:nth-child(even){{background:linear-gradient(180deg,#111821,#0d1218);border-color:#27303a}}
.ai-update-item::before{{content:counter(ai-updates, decimal-leading-zero);position:absolute;top:14px;left:14px;color:var(--token);font-size:.72rem;font-weight:700;letter-spacing:.08em;line-height:1}}
.ai-update-item-title{{margin:0;color:#f0f6fc;font-size:.92rem;font-weight:700;line-height:1.5}}
.ai-update-item-body{{margin:6px 0 0;color:#dce2ea;font-size:.9rem;line-height:1.65}}
.ai-update-original{{margin-top:8px;border:1px solid #262c34;border-radius:6px;background:#0d1014}}
.ai-update-original summary{{cursor:pointer;list-style:none;padding:8px 10px;color:var(--token);font-size:.82rem;user-select:none}}
.ai-update-original summary::-webkit-details-marker{{display:none}}
.ai-update-original[open] summary{{border-bottom:1px solid #262c34}}
.ai-update-original div{{padding:10px;color:var(--muted);font-size:.82rem;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}}
.wrapped-section{{background:linear-gradient(135deg,#11161c,#090c10 58%,#161015)}}
.wrapped-card{{display:grid;grid-template-columns:minmax(0,1.25fr) 180px minmax(280px,.95fr);gap:18px;align-items:center;padding:4px}}
.wrapped-kicker{{display:inline-flex;align-items:center;gap:8px;padding:5px 10px;border:1px solid rgba(88,166,255,.28);border-radius:999px;background:rgba(88,166,255,.08);color:#9bc5ff;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase}}
.wrapped-copy h3{{margin:14px 0 8px;font-size:clamp(1.7rem,3.6vw,2.5rem);line-height:.98;letter-spacing:-.03em}}
.wrapped-beast-line{{margin:0;color:#f7d38e;font-size:.95rem;line-height:1.5}}
.wrapped-total{{margin-top:18px;font-size:clamp(1.7rem,4.2vw,2.8rem);line-height:1;font-weight:800;letter-spacing:-.04em;color:#f0f6fc;white-space:nowrap}}
.wrapped-total-label{{margin:8px 0 0;color:#9fb3c8;font-size:.9rem;text-transform:uppercase;letter-spacing:.08em}}
.wrapped-analogy{{margin:10px 0 0;color:#dce2ea;font-size:.96rem;line-height:1.55}}
.wrapped-art{{display:grid;place-items:center}}
.wrapped-art img{{width:min(180px,100%);height:auto;image-rendering:auto;filter:drop-shadow(0 14px 28px rgba(0,0,0,.42)) drop-shadow(0 0 22px rgba(247,120,186,.22))}}
.wrapped-metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}
.wrapped-metric{{padding:13px 14px;border:1px solid #2a313a;border-radius:10px;background:rgba(9,12,16,.82);min-width:0}}
.wrapped-metric span{{display:block;color:#8b949e;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}}
.wrapped-metric b{{display:block;color:#f0f6fc;font-size:1rem;line-height:1.35;overflow-wrap:anywhere}}
.contribution-wrap{{display:grid;gap:14px;align-items:start}}
.contribution-heatmap{{min-width:0}}
.contribution-months{{display:grid;grid-template-columns:repeat(var(--weeks),minmax(0,1fr));gap:3px;padding-left:30px;margin-bottom:6px;color:#8b949e;font-size:.7rem;letter-spacing:.01em}}
.contribution-months span{{min-height:1em;white-space:nowrap;overflow:visible}}
.contribution-board{{display:grid;grid-template-columns:24px minmax(0,1fr);gap:6px;align-items:stretch}}
.contribution-days{{display:grid;grid-template-rows:repeat(7,1fr);gap:3px;color:#8b949e;font-size:.6rem;line-height:1;padding-top:0}}
.contribution-grid{{display:grid;grid-template-columns:repeat(var(--weeks),minmax(0,1fr));grid-template-rows:repeat(7,auto);grid-auto-flow:column;gap:3px}}
.contribution-cell{{display:block;width:100%;aspect-ratio:1;border-radius:2px;background:#161b22;border:1px solid rgba(255,255,255,.04)}}
.contribution-cell.level-1{{background:#0e4429}}
.contribution-cell.level-2{{background:#006d32}}
.contribution-cell.level-3{{background:#26a641}}
.contribution-cell.level-4{{background:#39d353}}
.contribution-legend{{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-top:10px;color:#8b949e;font-size:.72rem}}
.contribution-legend .contribution-cell{{width:12px;min-width:12px;height:12px;aspect-ratio:auto}}
.contribution-stats{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}
.contribution-stat{{padding:13px 14px;border:1px solid #2a313a;border-radius:8px;background:#090b0e}}
.contribution-stat span{{display:block;color:#8b949e;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:7px}}
.contribution-stat b{{display:block;color:#f0f6fc;font-size:1rem;line-height:1.35;overflow-wrap:anywhere}}
@media (max-width:780px){{.wrap{{padding:28px 14px}}header{{display:block}}.meta{{text-align:left;margin-top:16px}}.header-actions{{align-items:flex-start;margin-top:16px}}.cards{{grid-template-columns:repeat(2,1fr)}}.rank-head{{display:none}}.rank-list{{display:grid;gap:10px}}.rank-line{{display:grid;grid-template-columns:1fr;gap:8px;padding:12px;border:1px solid #30363d;border-radius:6px;background:#090b0e}}.rank-line .arrow{{display:none}}.rank-line .name{{white-space:normal;font-weight:700;color:#f0f6fc}}.rank-line .pct,.rank-line .tokens,.rank-line .cost{{display:flex;justify-content:space-between;gap:14px;text-align:left}}.rank-line .pct::before,.rank-line .tokens::before,.rank-line .cost::before{{content:attr(data-label);color:var(--muted)}}.tools-head{{display:none}}.tool-row{{grid-template-columns:1fr;gap:8px}}.tool-row .pct,.tool-row .tokens,.tool-row .cost{{display:flex;justify-content:space-between;gap:14px;text-align:left}}.tool-row .pct:empty,.tool-row .tokens:empty,.tool-row .cost:empty{{display:none}}.tool-row .pct::before,.tool-row .tokens::before,.tool-row .cost::before{{content:attr(data-label);color:var(--muted)}}}}
@media (max-width:780px){{.wrapped-card{{grid-template-columns:1fr;gap:16px}}.wrapped-art{{order:-1}}.wrapped-art img{{width:140px}}.wrapped-metrics{{grid-template-columns:1fr 1fr}}.contribution-months{{padding-left:30px}}}}
@media (max-width:480px){{.wrap{{padding:22px 12px 28px}}h1{{white-space:normal}}.cards{{grid-template-columns:repeat(2,1fr);gap:8px}}.card{{min-height:96px;padding:13px 11px}}.share-dialog{{width:100vw;max-width:none;height:100dvh;max-height:none;margin:0;border:0;border-radius:0}}.share-modal{{min-height:100dvh;padding:16px 12px 18px}}.share-section{{padding:12px}}.share-action{{min-height:42px;font-size:.72rem;gap:4px;white-space:normal}}.share-file-actions{{grid-template-columns:1fr}}.section{{padding:16px 12px}}.wrapped-metrics{{grid-template-columns:1fr}}.contribution-stats{{grid-template-columns:1fr}}.contribution-months{{font-size:.66rem;padding-left:26px}}.contribution-board{{grid-template-columns:22px minmax(0,1fr)}}.contribution-days{{font-size:.58rem}}}}"""


def _render_scripts(share_config_json: str, csv_data_json: str, masked_csv_data_json: str) -> str:
    return f"""const shareConfig = {share_config_json};
const csvData = {csv_data_json};
const maskedCsvData = {masked_csv_data_json};
const shareDialog = document.querySelector('[data-share-dialog]');
const shareFileMask = document.querySelector('[data-share-file-mask]');
const shareToast = document.querySelector('[data-share-toast]');
let shareToastTimer = null;

function showShareToast(message) {{
  window.clearTimeout(shareToastTimer);
  shareToast.textContent = message;
  shareToast.classList.add('show');
  shareToastTimer = window.setTimeout(() => {{
    shareToast.classList.remove('show');
  }}, 2500);
}}

async function copyText(text) {{
  try {{
    await navigator.clipboard.writeText(text);
    return true;
  }} catch (_) {{
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let success = false;
    try {{ success = document.execCommand('copy'); }} catch (_e) {{}}
    document.body.removeChild(ta);
    return success;
  }}
}}

function downloadBlob(blob, filename) {{
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}}

function closeShareModal() {{
  if (!shareDialog) return;
  if (shareDialog.open && typeof shareDialog.close === 'function') {{
    shareDialog.close();
  }} else {{
    shareDialog.removeAttribute('open');
  }}
}}

function downloadHtml(maskProjects) {{
  closeShareModal();
  const restores = [];
  const detached = [];
  if (maskProjects) {{
    document.querySelectorAll('.project-section .name').forEach((el, i) => {{
      restores.push({{el, original: el.textContent}});
      el.textContent = `Project ${{i + 1}}`;
    }});
    document.querySelectorAll('.session-section .name').forEach((el, i) => {{
      restores.push({{el, original: el.textContent}});
      el.textContent = `Project ${{i + 1}}`;
    }});
    document.querySelectorAll('[data-mask]').forEach((el) => {{
      restores.push({{el, original: el.textContent}});
      el.textContent = '—';
    }});
  }}
  document.querySelectorAll('[data-share-dialog], [data-share-open]').forEach((el) => {{
    detached.push({{el, parent: el.parentNode, next: el.nextSibling}});
    el.remove();
  }});
  const html = '<!doctype html>\\n' + document.documentElement.outerHTML;
  detached.forEach((item) => {{
    item.parent.insertBefore(item.el, item.next);
  }});
  restores.forEach((item) => {{
    item.el.textContent = item.original;
  }});
  const blob = new Blob([html], {{type: 'text/html'}});
  downloadBlob(blob, `usage-report-${{new Date().toISOString().slice(0, 10)}}.html`);
}}

function downloadCsv(maskProjects) {{
  closeShareModal();
  const csvText = maskProjects ? maskedCsvData : csvData;
  const blob = new Blob([csvText], {{type: 'text/csv;charset=utf-8'}});
  downloadBlob(blob, `usage-report-${{new Date().toISOString().slice(0, 10)}}.csv`);
}}

document.querySelector('[data-share-open]')?.addEventListener('click', () => {{
  shareFileMask.checked = true;
  if (typeof shareDialog.showModal === 'function') {{
    shareDialog.showModal();
  }} else {{
    shareDialog.setAttribute('open', '');
  }}
  shareFileMask.focus();
}});

document.querySelector('[data-share-close]')?.addEventListener('click', () => {{
  closeShareModal();
}});

shareDialog?.addEventListener('click', (e) => {{
  if (e.target === shareDialog) closeShareModal();
}});

document.addEventListener('click', (e) => {{
  const btn = e.target.closest('[data-share-file]');
  if (!btn) return;
  const action = btn.dataset.shareFile;
  if (action === 'download') {{
    downloadHtml(Boolean(shareFileMask?.checked));
    return;
  }}
  if (action === 'csv') {{
    downloadCsv(Boolean(shareFileMask?.checked));
  }}
}});
"""


def generate_html(data: dict[str, Any], language: str | None = None) -> str:
    lang = language or _detect_lang()
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    cards = _summary_cards(data["summary"], lang)
    share_config_json = _share_config_json(lang)
    csv_data_json = json.dumps(_build_csv_data(data, lang), ensure_ascii=False).replace("</", "<\\/")
    masked_csv_data_json = json.dumps(_build_csv_data(data, lang, mask_projects=True), ensure_ascii=False).replace("</", "<\\/")
    title = _t(lang, "title")
    insight_surface = _render_insight_surface(data, lang)
    return f"""<!doctype html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
{_render_styles()}
</style>
</head>
<body>
<main class="wrap">
  {_render_header(data, lang, title, generated_at)}
  {_render_share_dialog(lang)}
  {_render_cards_section(cards)}
  {_render_wrapped_section(data, lang)}
{insight_surface}  {_render_tools_section(data, lang)}
  {_render_project_section(data, lang)}
  {_render_model_section(data, lang)}
  {_render_trend_section(data, lang)}
  {_render_contribution_section(data, lang)}
  {_render_persona_section(data, lang)}
  {_render_session_section(data, lang)}
  {_render_ai_updates_section(data, lang)}
  {_render_sponsor_section(lang)}
</main>
<script>
{_render_scripts(share_config_json, csv_data_json, masked_csv_data_json)}
</script>
</body>
</html>
"""


def save_and_open(
    data: dict[str, Any],
    out_path: str | None = None,
    language: str | None = None,
) -> str:
    if out_path:
        path = Path(os.path.expanduser(out_path))
        display_path = str(path.expanduser())
    else:
        reports_dir = Path.home() / ".usage-reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"usage-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
        display_path = f"~/.usage-reports/{path.name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_html(data, language=language), encoding="utf-8")
    if out_path is None:
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/open", str(path.resolve())], check=False)
        else:
            webbrowser.open(path.resolve().as_uri())
    return display_path
