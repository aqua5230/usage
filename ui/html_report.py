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
from typing import Any, Mapping, cast

from analyzer.reporter import (
    AgentReportRow,
    DailyTrendPoint,
    ReportData,
    SummaryReportData,
)

from i18n import _t as _i18n_t, packaged_resource_path
from usage_lang import detect_lang
from ui.report_scripts import HTML_TO_IMAGE_UMD, REPORT_JS_TEMPLATE
from ui.report_styles import REPORT_CSS



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


def _fmt_cost(value: float | None) -> str:
    if value is None:
        return "—"
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


def _rank_line(name: str, pct: float, tokens: int, cost: float | None, lang: str) -> str:
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
    asset_path = packaged_resource_path(
        f"critters/{beast}/1.png",
        Path(__file__).resolve().parent.parent
        / "assets"
        / "critters"
        / beast
        / "1.png",
    )
    encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _weekly_trend(daily: list[DailyTrendPoint]) -> list[dict[str, int | float]]:
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


def _trend_ascii(daily: list[DailyTrendPoint], lang: str) -> str:
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


def _persona_body(persona: Mapping[str, object] | None, lang: str) -> str:
    if persona is None:
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


def _tools_body(
    subs: list[dict[str, str | None]],
    agents: list[AgentReportRow],
    lang: str,
) -> str:
    """One card per tool, joining subscription plan with usage by tool name."""
    by_name = {str(sub.get("agent", "")): sub for sub in subs}
    seen: set[str] = set()
    rows: list[str] = []

    def _plan_html(sub: dict[str, str | None] | None) -> str:
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


def _narrative(data: ReportData, lang: str) -> str:
    summary = data["summary"]
    daily = data.get("daily_trend", [])
    peak_date = data.get("date_to", "---- -- --")
    peak_tokens = 0
    if daily:
        peak = max(daily, key=lambda day: int(day["tokens"]))
        peak_date = peak["date"]
        peak_tokens = peak["tokens"]
    top_model = data.get("by_model", [{}])[0].get("model", _t(lang, "unknown")) if data.get("by_model") else _t(lang, "unknown")
    return _t(
        lang,
        "narrative",
        tokens=_fmt_tokens(int(summary["total_tokens"])),
        projects=len(data.get("by_project", [])),
        peak_date=str(peak_date),
        peak_tokens=_fmt_tokens(int(peak_tokens)),
        top_model=_display_name(top_model, lang),
    )


def _cost_value(cost_usd: float, lang: str) -> tuple[str, str]:
    main = _fmt_cost(cost_usd)
    sub = f"≈ NT${cost_usd * _USD_TO_TWD:,.0f}" if lang == "zh-TW" else ""
    return main, sub


def _render_cards_section(cards: list[tuple[str, str, str]]) -> str:
    return f"""<section class="cards">{''.join(f'<div class="card"><span>{html.escape(label)}</span><b>{html.escape(value)}</b>' + (f'<i>{html.escape(sub)}</i>' if sub else '') + '</div>' for label, value, sub in cards)}</section>"""


def _summary_cards(summary: SummaryReportData, lang: str) -> list[tuple[str, str, str]]:
    total_tokens = int(summary["total_tokens"])
    messages = int(summary["messages"])
    cost_main, cost_sub = _cost_value(float(summary["cost_usd"]), lang)
    tokens_per_msg = total_tokens // messages if messages else 0
    return [
        (_t(lang, "kpi_tokens"), f"{total_tokens:,}", f"≈ {_fmt_tokens(total_tokens)}"),
        (_t(lang, "kpi_cost"), cost_main, cost_sub),
        (_t(lang, "kpi_sessions"), f'{int(summary["sessions"]):,}', ""),
        (_t(lang, "kpi_messages"), f'{messages:,}', ""),
        (_t(lang, "kpi_active"), f'{int(summary["active_days"])}/{int(summary["total_days"])}', ""),
        (_t(lang, "kpi_productivity"), f"{tokens_per_msg:,}", _t(lang, "kpi_productivity_unit")),
    ]


def _render_header(data: ReportData, lang: str, title: str, generated_at: str) -> str:
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
          <button class="share-action" type="button" data-share-file="png"><span class="share-icon" aria-hidden="true">🖼️</span>{html.escape(_t(lang, "share_download_png"))}</button>
        </div>
        <p class="share-file-hint">{html.escape(_t(lang, "share_file_hint"))}</p>
      </section>
      <div class="share-toast" data-share-toast role="status" aria-live="polite"></div>
    </div>
  </dialog>"""


def _render_project_section(data: Mapping[str, Any], lang: str) -> str:
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


def _render_model_section(data: Mapping[str, Any], lang: str) -> str:
    model_rows = [
        _rank_line(
            _display_name(model["model"], lang),
            float(model["pct"]),
            int(model["tokens"]),
            None if not model.get("cost_known", True) else float(model["cost"]),
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


def _render_tools_section(data: Mapping[str, Any], lang: str) -> str:
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


def _render_insight_surface(data: Mapping[str, Any], lang: str) -> str:
    from analyzer.insights import build_insights

    components = build_insights(dict(data))
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


def _render_trend_section(data: Mapping[str, Any], lang: str) -> str:
    return _section(_t(lang, "trend_section"), _trend_ascii(data.get("daily_trend", []), lang))


def _render_contribution_section(data: Mapping[str, Any], lang: str) -> str:
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


def _render_wrapped_section(data: Mapping[str, Any], lang: str) -> str:
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


def _render_persona_section(data: Mapping[str, Any], lang: str) -> str:
    persona_body = _persona_body(data.get("persona"), lang)
    return _section(_t(lang, "persona_section"), persona_body, "persona-section")


def _render_session_section(data: Mapping[str, Any], lang: str) -> str:
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


def _render_ai_updates_section(data: Mapping[str, Any], lang: str) -> str:
    raw_updates = data.get("ai_updates")
    if not isinstance(raw_updates, list) or not raw_updates:
        return ""

    cards: list[str] = []
    for tool in raw_updates:
        if not isinstance(tool, dict):
            continue
        raw_versions = tool.get("versions")
        if not isinstance(raw_versions, list) or not raw_versions:
            continue
        latest = raw_versions[0]
        if not isinstance(latest, dict):
            continue
        raw_items = latest.get("items")
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

        history = ""
        if len(raw_versions) > 1:
            history_versions: list[str] = []
            for raw_version in raw_versions[1:]:
                if not isinstance(raw_version, dict):
                    continue
                version = raw_version.get("version")
                period = raw_version.get("period")
                version_items = raw_version.get("items")
                if (
                    not isinstance(version, str)
                    or not isinstance(period, str)
                    or not isinstance(version_items, list)
                    or not version_items
                ):
                    continue

                history_items: list[str] = []
                for item in version_items:
                    if not isinstance(item, dict):
                        continue
                    title = _localized_text(item.get("title"), lang)
                    body = _localized_text(item.get("body"), lang)
                    if not title or not body:
                        continue
                    history_items.append(
                        '<li class="ai-update-history-item">'
                        f'<p class="ai-update-item-title">{_escape(title)}</p>'
                        f'<p class="ai-update-item-body">{_escape(body)}</p>'
                        "</li>"
                    )

                if not history_items:
                    continue
                history_versions.append(
                    '<section class="ai-update-history-period">'
                    f'<p class="ai-update-period">{_escape(version)} · {_escape(period)}</p>'
                    f'<ol class="ai-update-history-items">{"".join(history_items)}</ol>'
                    "</section>"
                )

            if history_versions:
                history = (
                    '<details class="ai-update-history">'
                    f'<summary>{_escape(_t(lang, "ai_updates_history"))}</summary>'
                    f'<div>{"".join(history_versions)}</div>'
                    "</details>"
                )

        cards.append(
            '<article class="ai-update-card">'
            f'<div class="ai-update-head"><h3>{_escape(tool.get("name", ""))}</h3>'
            f'<span class="ai-update-version">{_escape(_t(lang, "ai_updates_updated_to"))} {_escape(latest.get("version", ""))}</span></div>'
            f'<p class="ai-update-period">{_escape(latest.get("period", ""))}</p>'
            f'<ol class="ai-update-items">{"".join(items)}</ol>'
            f"{history}"
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


def _csv_cost(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.4f}" if 0 < value < 1 else f"{value:.2f}"


def _build_csv_data(data: Mapping[str, Any], lang: str, *, mask_projects: bool = False) -> str:
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
    for model_item in data.get("by_model", []):
        cost_val = None if not model_item.get("cost_known", True) else float(model_item.get("cost", 0.0))
        writer.writerow(
            [
                "model",
                _display_name(model_item.get("model"), lang),
                f"{float(model_item.get('pct', 0.0)):.1f}",
                str(int(model_item.get("tokens", 0))),
                _csv_cost(cost_val),
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
    return REPORT_CSS


def _render_scripts(share_config_json: str, csv_data_json: str, masked_csv_data_json: str) -> str:
    return f"{HTML_TO_IMAGE_UMD}\n" + REPORT_JS_TEMPLATE.replace(
        "__SHARE_CONFIG_JSON__",
        share_config_json,
    ).replace(
        "__CSV_DATA_JSON__",
        csv_data_json,
    ).replace(
        "__MASKED_CSV_DATA_JSON__",
        masked_csv_data_json,
    )


def generate_html(data: ReportData | Mapping[str, Any], language: str | None = None) -> str:
    report_data = cast(ReportData, data)
    lang = language or _detect_lang()
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    cards = _summary_cards(report_data["summary"], lang)
    share_config_json = _share_config_json(lang)
    csv_data_json = json.dumps(_build_csv_data(report_data, lang), ensure_ascii=False).replace("</", "<\\/")
    masked_csv_data_json = json.dumps(_build_csv_data(report_data, lang, mask_projects=True), ensure_ascii=False).replace("</", "<\\/")
    title = _t(lang, "title")
    insight_surface = _render_insight_surface(report_data, lang)
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
  {_render_header(report_data, lang, title, generated_at)}
  {_render_share_dialog(lang)}
  {_render_cards_section(cards)}
  {_render_wrapped_section(report_data, lang)}
{insight_surface}  {_render_tools_section(report_data, lang)}
  {_render_project_section(report_data, lang)}
  {_render_model_section(report_data, lang)}
  {_render_trend_section(report_data, lang)}
  {_render_contribution_section(report_data, lang)}
  {_render_persona_section(report_data, lang)}
  {_render_session_section(report_data, lang)}
  {_render_ai_updates_section(report_data, lang)}
  {_render_sponsor_section(lang)}
</main>
<script>
{_render_scripts(share_config_json, csv_data_json, masked_csv_data_json)}
</script>
</body>
</html>
"""


def save_and_open(
    data: ReportData | Mapping[str, Any],
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
