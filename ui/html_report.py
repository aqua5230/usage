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
)

from i18n import _t as _i18n_t, packaged_resource_path
from usage_common.usage_lang import detect_lang
from usage_common.subprocess_utils import hidden_console_kwargs
from ui.report_charts import render_share_bar, render_trend_bar
from ui.report_filter import REPORT_FILTER_JS
from ui.report_scripts import HTML_TO_IMAGE_UMD, REPORT_JS_TEMPLATE, REPORT_THEME_INIT_JS
from ui.report_styles import REPORT_CSS



def _t(lang: str, key: str, **kwargs: object) -> str:
    return _i18n_t(lang, f"report_{key}", **kwargs)

def _fmt_tokens(value: int) -> str:
    if value >= 999_950_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 999_950:
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
        return version("usage-cli")
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


def _section(
    title: str,
    body: str,
    class_name: str = "",
    *,
    fixed_label: str = "",
    dynamic_title: bool = False,
) -> str:
    classes = "section" if not class_name else f"section {class_name}"
    if fixed_label or dynamic_title:
        title_html = f'<span class="prompt-title">{html.escape(title)}</span>'
        if fixed_label:
            title_html += f'<small class="fixed-range-tag">{html.escape(fixed_label)}</small>'
    else:
        title_html = html.escape(title)
    return f"""
    <section class="{classes}">
      <div class="prompt"><span>[usage]&gt;</span> {title_html}</div>
      <div class="rule" aria-hidden="true">────────────────────────────────────────────────────────</div>
      {body}
    </section>
    """


def _fixed_range_label(data: Mapping[str, Any], lang: str) -> str:
    return _t(lang, "fixed_range") if isinstance(data.get("cube"), Mapping) else ""


def _empty_line(label: str) -> str:
    return f'<div class="empty">→ {html.escape(label)}</div>'


def _rank_line(
    name: str,
    pct: float,
    tokens: int,
    cost: float | None,
    lang: str,
    color: str | None = None,
    *,
    row_class: str = "",
    arrow: str = "→",
    data_attributes: Mapping[str, object] | None = None,
) -> str:
    classes = "rank-line" if not row_class else f"rank-line {row_class}"
    attributes = "".join(
        f' data-{key}="{html.escape(str(value), quote=True)}"'
        for key, value in (data_attributes or {}).items()
    )
    return (
        f'<div class="{classes}"{attributes}>'
        f'<span class="arrow">{arrow}</span><span class="name">{html.escape(name)}{render_share_bar(pct, color)}</span>'
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
        f"critters/{beast}/wrapped.png",
        Path(__file__).resolve().parent.parent
        / "assets"
        / "critters"
        / beast
        / "wrapped.png",
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


def _week_is_in_progress(week: Mapping[str, int | float], date_to: date) -> bool:
    return date.fromisocalendar(int(week["year"]), int(week["week"]), 7) > date_to


def _trend_summary(
    weekly: list[dict[str, int | float]], lang: str, date_to: date
) -> str:
    completed = weekly[:-1] if weekly and _week_is_in_progress(weekly[-1], date_to) else weekly
    if len(completed) < 2:
        return f"→ {_t(lang, 'trend_compare_first')}"

    current = int(completed[-1]["tokens"])
    previous = int(completed[-2]["tokens"])
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
    "#5abfa0", "#8f86c9", "#e0885a", "#78cdb2",
    "#aaa3d4", "#dca080", "#3f9f82", "#7168ad",
]


def _project_share_colors(items: list[tuple[str, int]]) -> list[str]:
    colors = ["#8b8577"] * len(items)
    shown = 0
    for index, (_name, tokens) in enumerate(items):
        if tokens <= 0:
            continue
        if shown < 6:
            colors[index] = _PALETTE[shown % len(_PALETTE)]
        shown += 1
    return colors


def _model_share_color(model: object) -> str:
    name = str(model).lower()
    if name.startswith("claude"):
        return "#5abfa0"
    if name.startswith("gemini"):
        return "#8f86c9"
    if name.startswith("gpt"):
        return "#e0885a"
    return "#8b8577"


_AGENT_COLORS = {
    "claude-code": "#5abfa0",
    "codex": "#e0885a",
    "antigravity": "#8f86c9",
    "grok": "#78cdb2",
}


def _agent_share_color(agent_id: object) -> str:
    # Keyed on the tool, not its rank — the ordering is by tokens, so a palette
    # indexed by position would repaint every tool whenever two swap places.
    return _AGENT_COLORS.get(str(agent_id), "#8b8577")


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


def _trend_ascii(daily: list[DailyTrendPoint], lang: str, date_to: date) -> str:
    weekly = _weekly_trend(daily)
    max_tokens = max((int(week["tokens"]) for week in weekly), default=0)
    data_start = min((_parse_daily_date(day["date"]) for day in daily), default=None)
    rows = []
    for idx, week in enumerate(weekly):
        tokens = int(week["tokens"])
        cost = float(week["cost"])
        week_start = date.fromisocalendar(int(week["year"]), int(week["week"]), 1)
        week_end = min(date.fromisocalendar(int(week["year"]), int(week["week"]), 7), date_to)
        if data_start is not None:
            week_start = max(week_start, data_start)
        tooltip = _escape(
            f"{week_start.isoformat()} – {week_end.isoformat()} · {_fmt_tokens(tokens)} · {_fmt_cost(cost)}"
        )
        delta_html = '<span class="delta flat"></span>'
        if idx == len(weekly) - 1 and _week_is_in_progress(week, date_to):
            delta_html = f'<span class="delta flat">{_escape(_t(lang, "trend_week_in_progress"))}</span>'
        elif idx > 0:
            delta_class, delta_label = _trend_delta(tokens, int(weekly[idx - 1]["tokens"]), lang)
            delta_html = f'<span class="delta {delta_class}">{_escape(delta_label)}</span>'
        rows.append(
            f'<div class="trend-row" title="{tooltip}">'
            f'<span class="week">W{int(week["week"])}</span>'
            f'{render_trend_bar(tokens, max_tokens)}'
            f'<em>{_fmt_tokens(tokens)}</em>'
            f"{delta_html}"
            "</div>"
        )
    if not rows:
        return _empty_line(_t(lang, "empty_daily"))

    trend_rows = "".join(rows)
    summary = f'<div class="trend-summary">{_escape(_trend_summary(weekly, lang, date_to))}</div>'
    return f'<div class="trend">{trend_rows}{summary}</div>'


def _hour_histogram_html(histogram: list[int], lang: str) -> str:
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
    peak = (
        f'<div class="persona-peak">{_escape(_t(lang, "persona_peak", count=max_count))}</div>'
        if max_count
        else ""
    )
    return f'<div class="persona-hours">{"".join(bars)}</div>{peak}'


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return max(0, int(value))


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
    active_hours = (
        '<div class="persona-card">'
        f'<h3>{_escape(_t(lang, "persona_active_hours"))}</h3>'
        f'<p class="persona-caption">{_escape(caption)}</p>'
        f'{_hour_histogram_html(values, lang)}'
        '</div>'
    )
    return active_hours


def _donut_svg(items: list[tuple[str, int]], lang: str, *, total: int) -> str:
    data = [(name, tok) for name, tok in items if tok > 0]
    if not data:
        return ""
    data_total = sum(tok for _, tok in data)
    if total <= 0 or total < data_total:
        total = data_total
    shown = [(name, tok, False) for name, tok in data[:6]]
    rest = total - sum(tok for _, tok, _is_other in shown)
    if rest > 0:
        shown = [*shown, (_t(lang, "chart_other"), rest, True)]
    colors = _project_share_colors(data)

    cx = cy = 80.0
    radius = 60.0
    circ = 2 * math.pi * radius
    segs: list[str] = []
    legend: list[str] = []
    offset = 0.0
    for idx, (name, tok, is_other) in enumerate(shown):
        frac = tok / total
        seg_len = circ * frac
        color = "#8b8577" if is_other else colors[idx]
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

    def _row(
        name: str,
        plan_html: str,
        stats_html: str,
        share_html: str = "",
        agent_id: str = "",
    ) -> str:
        agent_attr = (
            f' data-agent-id="{html.escape(agent_id, quote=True)}"' if agent_id else ""
        )
        return (
            f'<div class="tool-row"{agent_attr}>'
            f'<div class="tool-head"><span class="sub-agent">{_escape(name)}</span>{plan_html}'
            f"{share_html}</div>"
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
        rows.append(
            _row(
                name,
                _plan_html(by_name.get(str(agent["name"]))),
                stats_html,
                render_share_bar(float(agent["pct"]), _agent_share_color(agent["id"])),
                str(agent["id"]),
            )
        )

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


def _peak_day(daily: list[DailyTrendPoint]) -> tuple[str, int] | None:
    if not daily:
        return None
    peak = max(daily, key=lambda day: int(day["tokens"]))
    return str(peak["date"]), int(peak["tokens"])


def _narrative(data: ReportData, lang: str, is_empty: bool) -> str:
    if is_empty:
        return _t(lang, "empty_state_hint")

    summary = data["summary"]
    peak = _peak_day(data.get("daily_trend", []))
    peak_date = peak[0] if peak else data.get("date_to", "---- -- --")
    peak_tokens = peak[1] if peak else 0
    top_model = data.get("by_model", [{}])[0].get("model", _t(lang, "unknown")) if data.get("by_model") else _t(lang, "unknown")
    return _t(
        lang,
        "narrative",
        tokens=_fmt_tokens(int(summary["total_tokens"])),
        projects=int(summary.get("projects", len(data.get("by_project", [])))),
        peak_date=str(peak_date),
        peak_tokens=_fmt_tokens(int(peak_tokens)),
        top_model=_display_name(top_model, lang),
    )


def _cost_value(cost_usd: float, lang: str) -> tuple[str, str]:
    main = _fmt_cost(cost_usd)
    return main, ""


def _render_cards_section(
    cards: list[tuple[str, str, str]], *, interactive: bool = False
) -> str:
    keys = ("tokens", "cost", "sessions", "messages", "active", "peak")
    rendered = []
    for index, (label, value, sub) in enumerate(cards):
        card_key = f' data-card="{keys[index]}"' if interactive else ""
        sub_html = f'<i>{html.escape(sub)}</i>' if sub else ""
        rendered.append(
            f'<div class="card"{card_key}><span>{html.escape(label)}</span>'
            f'<b>{html.escape(value)}</b>{sub_html}</div>'
        )
    return f'<section class="cards">{"".join(rendered)}</section>'


def _delta_sub(current: float, prev: float, vs_prev_label: str) -> str:
    if prev <= 0:
        return ""
    pct = round((current - prev) / prev * 100)
    arrow = "↑" if pct >= 0 else "↓"
    return f"{arrow}{abs(pct)}% {vs_prev_label}"


def _summary_cards(data: ReportData, lang: str) -> list[tuple[str, str, str]]:
    summary = data["summary"]
    comparison = data["comparison"]
    total_tokens = int(summary["total_tokens"])
    cost_usd = float(summary["cost_usd"])
    total_days = int(summary["total_days"])
    cost_main, cost_sub = _cost_value(cost_usd, lang)
    tokens_sub = f"≈ {_fmt_tokens(total_tokens)}"

    if comparison.get("has_prev"):
        vs_prev_label = _t(lang, "kpi_vs_prev_period")
        tokens_delta = _delta_sub(total_tokens, float(comparison.get("prev_tokens", 0)), vs_prev_label)
        if tokens_delta:
            tokens_sub = f"{tokens_sub} · {tokens_delta}"
        cost_delta = _delta_sub(cost_usd, float(comparison.get("prev_cost", 0)), vs_prev_label)
        if cost_delta:
            cost_sub = f"{cost_sub} · {cost_delta}" if cost_sub else cost_delta

    unpriced_tokens = sum(
        int(model["tokens"])
        for model in data["by_model"]
        if not model.get("cost_known", True) and int(model["tokens"]) > 0
    )
    if unpriced_tokens:
        cost_unpriced = _t(
            lang, "kpi_cost_unpriced", tokens=_fmt_tokens(unpriced_tokens)
        )
        cost_sub = f"{cost_sub} · {cost_unpriced}" if cost_sub else cost_unpriced

    cards: list[tuple[str, str, str]] = [
        (_t(lang, "kpi_tokens"), f"{total_tokens:,}", tokens_sub),
        (_t(lang, "kpi_cost"), cost_main, cost_sub),
    ]

    if isinstance(data.get("cube"), Mapping):
        cards.extend(
            [
                (_t(lang, "sessions"), f'{int(summary["sessions"]):,}', ""),
                (_t(lang, "messages"), f'{int(summary["messages"]):,}', ""),
                (_t(lang, "kpi_active"), f'{int(summary["active_days"])}/{total_days}', ""),
            ]
        )
        peak = _peak_day(data.get("daily_trend", []))
        peak_date, peak_tokens = peak if peak is not None else (str(data["date_from"]), 0)
        cards.append(
            (_t(lang, "kpi_peak_day"), peak_date, f"{_fmt_tokens(peak_tokens)} {_t(lang, 'tokens')}")
        )
        return cards

    if total_days > 1:
        cards.append(
            (_t(lang, "kpi_active"), f'{int(summary["active_days"])}/{total_days}', "")
        )
        peak = _peak_day(data.get("daily_trend", []))
        if peak is not None:
            peak_date, peak_tokens = peak
            cards.append((_t(lang, "kpi_peak_day"), peak_date, f"{_fmt_tokens(peak_tokens)} {_t(lang, 'tokens')}"))

    return cards


def _date_filter(data: Mapping[str, Any], lang: str) -> str:
    cube = data.get("cube")
    if not isinstance(cube, Mapping):
        return ""
    dates = cube.get("dates")
    if not isinstance(dates, list) or not dates:
        return ""
    date_min = _escape(dates[0])
    date_max = _escape(dates[-1])
    buttons = "".join(
        f'<button type="button" data-range="{key}">{_escape(_t(lang, label))}</button>'
        for key, label in (
            ("today", "range_today"),
            ("last7", "range_last7"),
            ("last30", "range_last30"),
            ("month", "range_month"),
            ("all", "range_all"),
        )
    )
    return (
        '<div class="date-filter" data-date-filter>'
        f'<div class="date-shortcuts">{buttons}</div>'
        '<div class="date-inputs">'
        f'<label>{_escape(_t(lang, "date_from"))}<input type="date" data-date-from min="{date_min}" max="{date_max}"></label>'
        f'<label>{_escape(_t(lang, "date_to"))}<input type="date" data-date-to min="{date_min}" max="{date_max}"></label>'
        '</div></div>'
    )


def _render_header(data: ReportData, lang: str, title: str, generated_at: str, is_empty: bool) -> str:
    period = html.escape(str(data["period_label"]))
    if isinstance(data.get("cube"), Mapping):
        period = f'<span data-report-period>{period}</span>'
    date_filter_html = ""
    return f"""<header>
    <div>
      <div class="eyebrow"><span>$ usage report</span> --period {period}<span class="cursor">_</span></div>{date_filter_html}
      <h1>{html.escape(title)}</h1>
      <p class="narrative">{html.escape(_narrative(data, lang, is_empty))}</p>
    </div>
    <div class="header-actions">
      <div class="meta">{html.escape(_t(lang, "generated"))} {html.escape(generated_at)}<br>usage {_escape(_t(lang, "version"))} {_escape(_version())}</div>
      <div class="header-buttons">
        <button class="share-trigger" type="button" data-theme-toggle data-light-label="{html.escape(_t(lang, 'theme_light'))}" data-dark-label="{html.escape(_t(lang, 'theme_dark'))}" data-light-aria="{html.escape(_t(lang, 'theme_switch_light'))}" data-dark-aria="{html.escape(_t(lang, 'theme_switch_dark'))}" aria-label="{html.escape(_t(lang, 'theme_switch_light'))}"><span data-theme-icon aria-hidden="true">☀</span><span data-theme-label>{html.escape(_t(lang, 'theme_light'))}</span></button>
      <button class="share-trigger" type="button" data-share-open><span aria-hidden="true">↗</span>{html.escape(_t(lang, "share_button_label"))}</button>
      </div>
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
          <button class="share-action" type="button" data-share-file="download"><span class="share-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14"/></svg></span>{html.escape(_t(lang, "share_download_html"))}</button>
          <button class="share-action" type="button" data-share-file="csv"><span class="share-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20V10h4v10M10 20V4h4v16M16 20v-7h4v7M3 20h18"/></svg></span>{html.escape(_t(lang, "share_download_csv"))}</button>
          <button class="share-action" type="button" data-share-file="png"><span class="share-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9" r="1.5"/><path d="m4 17 5-5 4 4 2-2 5 5"/></svg></span>{html.escape(_t(lang, "share_download_png"))}</button>
        </div>
        <p class="share-file-hint">{html.escape(_t(lang, "share_file_hint"))}</p>
      </section>
      <div class="share-toast" data-share-toast role="status" aria-live="polite"></div>
    </div>
  </dialog>"""


def _render_project_section(data: Mapping[str, Any], lang: str) -> str:
    projects = data.get("by_project", [])
    cube = data.get("cube")
    cube_projects = cube.get("projects", []) if isinstance(cube, Mapping) else []
    project_indices = {
        str(project): index for index, project in enumerate(cube_projects)
    }
    colors = _project_share_colors(
        [(_display_name(project["project"], lang), int(project["tokens"])) for project in projects]
    )
    project_rows = [
        _rank_line(
            _display_name(project["project"], lang),
            float(project["pct"]),
            int(project["tokens"]),
            float(project["cost"]),
            lang,
            colors[index],
            data_attributes=(
                {"project-index": project_indices[str(project["project"])]}
                if str(project["project"]) in project_indices
                else None
            ),
        )
        for index, project in enumerate(projects)
    ]
    project_rows_html = "".join(project_rows)
    project_donut = _donut_svg(
        [(_display_name(project["project"], lang), int(project["tokens"])) for project in projects],
        lang,
        total=int(data["summary"]["total_tokens"]),
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
    grouped_models = data.get("by_agent_model")
    has_cube = isinstance(data.get("cube"), Mapping)
    if grouped_models:
        model_rows = []
        for group in grouped_models:
            model_rows.append(
                _rank_line(
                    _display_name(group["name"], lang),
                    float(group["pct"]),
                    int(group["tokens"]),
                    None if not group.get("cost_known", True) else float(group["cost"]),
                    lang,
                    _agent_share_color(group["agent_id"]),
                    row_class="model-group",
                    arrow="▎",
                    data_attributes=(
                        {"agent-id": group["agent_id"]} if has_cube else None
                    ),
                )
            )
            model_rows.extend(
                _rank_line(
                    _display_name(model["model"], lang),
                    float(model["pct"]),
                    int(model["tokens"]),
                    None if not model.get("cost_known", True) else float(model["cost"]),
                    lang,
                    _model_share_color(model["model"]),
                    row_class="model-child",
                )
                for model in group["models"]
            )
        title = _t(lang, "model_section")
        if data.get("date_from") and data.get("date_to"):
            title = f'{title}  {data["date_from"]} → {data["date_to"]}'
    else:
        model_rows = [
            _rank_line(
                _display_name(model["model"], lang),
                float(model["pct"]),
                int(model["tokens"]),
                None if not model.get("cost_known", True) else float(model["cost"]),
                lang,
                _model_share_color(model["model"]),
            )
            for model in data.get("by_model", [])
        ]
        title = _t(lang, "model_section")
    model_rows_html = "".join(model_rows)
    model_body = (
        f'<div class="rank-head"><span></span><span>{_escape(_t(lang, "model"))}</span><span>{_escape(_t(lang, "share"))}</span><span>{_escape(_t(lang, "tokens"))}</span><span>{_escape(_t(lang, "cost"))}</span></div>'
        f'<div class="rank-list">{model_rows_html}</div>'
        if model_rows
        else _empty_line(_t(lang, "empty_models"))
    )
    return _section(
        title,
        model_body,
        "model-section",
        dynamic_title=has_cube,
    )


def _render_tools_section(data: Mapping[str, Any], lang: str) -> str:
    tools_body = _tools_body(data.get("subscriptions", []), data.get("by_agent", []), lang)
    return _section(_t(lang, "tools_section"), tools_body, "tools-section")


def _cache_hit_rate(row: Mapping[str, Any]) -> float | None:
    cache_read = int(row.get("cache_read_tokens", 0))
    context_tokens = (
        int(row.get("input_tokens", 0))
        + int(row.get("cache_creation_tokens", 0))
        + cache_read
    )
    return None if context_tokens == 0 else cache_read / context_tokens * 100


def _render_composition_section(data: Mapping[str, Any], lang: str) -> str:
    summary = data["summary"]
    parts = [
        ("input", int(summary.get("input_tokens", 0))),
        ("output", int(summary.get("output_tokens", 0))),
        ("cache_write", int(summary.get("cache_creation_tokens", 0))),
        ("cache_read", int(summary.get("cache_read_tokens", 0))),
    ]
    total = sum(tokens for _key, tokens in parts)
    if total <= 0:
        return ""
    colors = {key: _PALETTE[index] for index, (key, _tokens) in enumerate(parts)}

    # One row per class rather than a single stacked bar: cache reads dominate the
    # total so heavily that every other segment collapses into an unreadable sliver.
    rows = "".join(
        '<div class="rank-line">'
        '<span class="arrow">&rarr;</span>'
        f'<span class="name">{_escape(_t(lang, f"composition_{key}"))}'
        f'{render_share_bar(tokens / total * 100, colors[key])}</span>'
        f'<span class="pct" data-label="{_escape(_t(lang, "share"))}">'
        f'{tokens / total * 100:>5.1f}%</span>'
        f'<span class="tokens" data-label="{_escape(_t(lang, "tokens"))}">'
        f'{_fmt_tokens(tokens)}</span>'
        "</div>"
        for key, tokens in sorted(parts, key=lambda item: -item[1])
        if tokens > 0
    )

    agent_rows = []
    for agent in sorted(
        data.get("by_agent", []),
        key=lambda row: (_cache_hit_rate(row) is None, -(_cache_hit_rate(row) or 0.0)),
    ):
        rate = _cache_hit_rate(agent)
        agent_rows.append(
            '<div class="rank-line">'
            '<span class="arrow">&rarr;</span>'
            f'<span class="name">{_escape(_display_name(agent["name"], lang))}'
            f'{render_share_bar(rate or 0.0, _PALETTE[3])}</span>'
            f'<span class="pct" data-label="{_escape(_t(lang, "composition_hit_rate"))}">'
            f'{"&mdash;" if rate is None else f"{rate:>5.1f}%"}</span>'
            "</div>"
        )

    body = (
        f'<div class="rank-list">{rows}</div>'
        f'<p class="composition-hint">{_escape(_t(lang, "composition_hint"))}</p>'
        f'<div class="rank-head"><span></span>'
        f'<span>{_escape(_t(lang, "composition_hit_rate"))}</span></div>'
        f'<div class="rank-list">{"".join(agent_rows)}</div>'
    )
    return _section(
        _t(lang, "composition_section"),
        body,
        "composition-section",
    )


def _render_insight_note(
    component: dict[str, Any], lang: str, mask_labels: Mapping[str, str]
) -> str:
    return (
        '<div class="insight-note">'
        f'{_t(lang, component["key"], **_insight_kwargs(component, mask_labels))}'
        '</div>'
    )


def _render_insight_action(
    component: dict[str, Any], lang: str, mask_labels: Mapping[str, str]
) -> str:
    return (
        '<div class="insight-action">'
        f'{_t(lang, component["key"], **_insight_kwargs(component, mask_labels))}'
        '</div>'
    )


def _insight_kwargs(
    component: dict[str, Any], mask_labels: Mapping[str, str]
) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    for key, value in component.items():
        if key in {"key", "type", "direction", "delta_pct"}:
            continue
        if key == "tokens" or key == "mean_tokens":
            kwargs[key] = _fmt_tokens(int(value))
        elif key == "cost_usd":
            kwargs[key] = _fmt_cost(float(value))
        elif key == "project":
            kwargs[key] = (
                f'<span class="insight-project" '
                f'data-mask-as="{_escape(mask_labels.get(str(value), "Project"))}">'
                f"{_escape(value)}</span>"
            )
        elif key in {"model", "higher_model", "lower_model", "date"}:
            kwargs[key] = _escape(value)
        else:
            kwargs[key] = value
    return kwargs


def _render_insight_surface(data: Mapping[str, Any], lang: str) -> str:
    from analyzer.insights import build_insights

    components = build_insights(dict(data))
    mask_labels = {
        str(project["project"]): f"Project {index}"
        for index, project in enumerate(data.get("by_project", []), start=1)
    }
    quiet = f'<div class="insight-note">{_t(lang, "insights_quiet")}</div>'
    if not components:
        return _section(
            _t(lang, "insights_section"),
            quiet,
            "insights-section",
            fixed_label=_fixed_range_label(data, lang),
        )

    renderers = {
        "change_headline": _render_insight_note,
        "spike": _render_insight_note,
        "shift": _render_insight_note,
        "pace_note": _render_insight_note,
        "action": _render_insight_action,
    }
    body = "".join(
        renderer(component, lang, mask_labels)
        for component in components
        if (renderer := renderers.get(str(component.get("type")))) is not None
    )
    if not body:
        body = quiet
    return _section(
        _t(lang, "insights_section"),
        body,
        "insights-section",
        fixed_label=_fixed_range_label(data, lang),
    )


def _render_trend_section(data: Mapping[str, Any], lang: str, date_to: date) -> str:
    daily = data.get("daily_trend", [])
    return _section(
        _t(lang, "trend_section"),
        _trend_ascii(daily, lang, date_to),
        "trend-section",
    )


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
    labeled_month: int | None = None
    last_label_col = -3
    for col, week in enumerate(weeks):
        parsed = _parse_daily_date(week[3].get("date", ""))
        label = ""
        if parsed.month != labeled_month and col - last_label_col >= 3:
            label = _month_label(parsed.month, lang)
            last_label_col = col
            labeled_month = parsed.month
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
    return _section(
        _t(lang, "contribution_section"),
        body,
        "contribution-section",
        fixed_label=_fixed_range_label(data, lang),
    )


def _render_recent_titles_section(data: Mapping[str, Any], lang: str) -> str:
    persona = data.get("persona")
    if not isinstance(persona, Mapping):
        return ""
    raw_titles = persona.get("recent_titles", [])
    if not isinstance(raw_titles, list):
        return ""
    titles = [title for title in raw_titles if isinstance(title, str) and title.strip()]
    if not titles:
        return ""
    rows = "".join(
        f'<div class="recent-title" data-mask>→ {_escape(title)}</div>'
        for title in titles
    )
    return _section(
        _t(lang, "recent_titles_heading"),
        f'<div class="recent-titles">{rows}</div>',
        "recent-titles-section",
        fixed_label=_fixed_range_label(data, lang),
    )


def _render_wrapped_section(data: Mapping[str, Any], lang: str) -> str:
    wrapped = data.get("wrapped")
    if not isinstance(wrapped, dict):
        return ""

    beast = wrapped.get("beast")
    if beast not in {"phoenix", "dragon"}:
        return ""

    weeks = wrapped.get("weeks", 53)
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
        f'<p class="wrapped-total-label">{_escape(_t(lang, "wrapped_total_tokens", weeks=weeks))}</p>'
        f'<p class="wrapped-analogy">{_escape(_t(lang, "wrapped_books_equivalent", books=_fmt_int(books)))}</p>'
        '</div>'
        '<div class="wrapped-art">'
        f'<img src="{_escape(_sprite_data_uri(str(beast)))}" alt="{_escape(beast_name)}">'
        '</div>'
        '<div class="wrapped-metrics">'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_total_cost", weeks=weeks))}</span><b>{_escape(_fmt_cost(float(wrapped.get("total_cost", 0.0))))}</b></div>'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_active_days"))}</span><b>{_escape(_fmt_int(int(wrapped.get("active_days", 0))))}</b></div>'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_longest_streak"))}</span><b>{_escape(_fmt_int(int(wrapped.get("longest_streak", 0))))} {_escape(_t(lang, "contribution_days_unit"))}</b></div>'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_top_model"))}</span><b>{_escape(top_model)}</b></div>'
        f'<div class="wrapped-metric"><span>{_escape(_t(lang, "wrapped_top_project"))}</span><b data-mask>{_escape(top_project)}</b></div>'
        '</div>'
        '</div>'
    )
    return _section(
        _t(lang, "wrapped_section"),
        body,
        "wrapped-section",
        fixed_label=_fixed_range_label(data, lang),
    )


def _render_persona_section(data: Mapping[str, Any], lang: str) -> str:
    persona_body = _persona_body(data.get("persona"), lang)
    return _section(
        _t(lang, "persona_section"),
        persona_body,
        "persona-section",
        fixed_label=_fixed_range_label(data, lang),
    )


def _render_session_section(data: Mapping[str, Any], lang: str) -> str:
    sessions = list(data.get("top_sessions", []))
    max_tokens = max((int(session["tokens"]) for session in sessions), default=0)
    session_rows = []
    for idx, session in enumerate(sessions, 1):
        tokens = int(session["tokens"])
        share = tokens / max_tokens * 100 if max_tokens else 0.0
        session_rows.append(f"""
        <tr>
          <td>#{idx}</td>
          <td>{_escape(session["start_time"])}</td>
          <td class="name">{_escape(_display_name(session["project"], lang))}</td>
          <td>{_escape(_display_name(session["model"], lang))}</td>
          <td>{_fmt_duration(float(session["duration_min"]))}</td>
          <td class="tokens-cell">{_fmt_tokens(tokens)}\
{render_share_bar(share, _model_share_color(session["model"]))}</td>
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
    return _section(
        _t(lang, "session_section"),
        session_body,
        "session-section",
    )


def _share_config_json(lang: str, *, interactive: bool = False) -> str:
    share_config = {
        "collapse": _t(lang, "collapse"),
        "copied": _t(lang, "share_copied"),
        "expand": _t(lang, "expand"),
        "pathCopied": _t(lang, "share_path_copied"),
        "projectShare": _t(lang, "project_share"),
    }
    if interactive:
        share_config.update(
            {
                "chartOther": _t(lang, "chart_other"),
                "cost": _t(lang, "cost"),
                "costUnpriced": _t(
                    lang, "kpi_cost_unpriced", tokens="{tokens}"
                ),
                "emptyModels": _t(lang, "empty_models"),
                "emptyProjects": _t(lang, "empty_projects"),
                "modelSection": _t(lang, "model_section"),
                "narrative": _t(
                    lang,
                    "narrative",
                    tokens="{tokens}",
                    projects="{projects}",
                    peak_date="{peak_date}",
                    peak_tokens="{peak_tokens}",
                    top_model="{top_model}",
                ),
                "projectSection": _t(lang, "project_section"),
                "share": _t(lang, "share"),
                "tokens": _t(lang, "tokens"),
                "unknown": _t(lang, "unknown"),
                "vsPrevious": _t(lang, "kpi_vs_prev_period"),
                "compositionCacheRead": _t(lang, "composition_cache_read"),
                "compositionCacheWrite": _t(lang, "composition_cache_write"),
                "compositionHitRate": _t(lang, "composition_hit_rate"),
                "compositionInput": _t(lang, "composition_input"),
                "compositionOutput": _t(lang, "composition_output"),
                "duration": _t(lang, "duration"),
                "emptyDaily": _t(lang, "empty_daily"),
                "emptySessions": _t(lang, "empty_sessions"),
                "model": _t(lang, "model"),
                "project": _t(lang, "project"),
                "rank": _t(lang, "rank"),
                "startTime": _t(lang, "start_time"),
                "trendCompareDown": _t(lang, "trend_compare_down", pct="{pct}"),
                "trendCompareFirst": _t(lang, "trend_compare_first"),
                "trendCompareFlat": _t(lang, "trend_compare_flat"),
                "trendCompareNew": _t(lang, "trend_compare_new"),
                "trendCompareUp": _t(lang, "trend_compare_up", ratio="{ratio}"),
                "trendMarkerNew": _t(lang, "trend_marker_new"),
                "trendWeekInProgress": _t(lang, "trend_week_in_progress"),
            }
        )
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


def _render_scripts(share_config_json: str) -> str:
    report_js = REPORT_JS_TEMPLATE.replace("__SHARE_CONFIG_JSON__", share_config_json)
    return f"{HTML_TO_IMAGE_UMD}\n{report_js}\n{REPORT_FILTER_JS}"


def generate_html(
    data: ReportData | Mapping[str, Any],
    language: str | None = None,
    default_range: str | None = None,
) -> str:
    report_data = cast(ReportData, data)
    lang = language or _detect_lang()
    date_to = _parse_daily_date(report_data["date_to"])
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    cards = _summary_cards(report_data, lang)
    is_empty = (
        int(report_data["summary"]["total_tokens"]) <= 0
        and int(report_data["summary"]["messages"]) <= 0
    )
    has_cube = isinstance(report_data.get("cube"), Mapping)
    share_config_json = _share_config_json(lang, interactive=has_cube)
    csv_data_json = json.dumps(_build_csv_data(report_data, lang), ensure_ascii=False).replace("</", "<\\/")
    masked_csv_data_json = json.dumps(_build_csv_data(report_data, lang, mask_projects=True), ensure_ascii=False).replace("</", "<\\/")
    cube_data_node = ""
    if "cube" in report_data:
        cube_data_json = json.dumps(
            report_data["cube"], ensure_ascii=False, separators=(",", ":")
        ).replace("</", "<\\/")
        cube_data_node = f'<script type="application/json" id="usage-cube-data">{cube_data_json}</script>\n'
    session_data_node = ""
    if "sessions" in report_data:
        session_data_json = json.dumps(
            report_data["sessions"], ensure_ascii=False, separators=(",", ":")
        ).replace("</", "<\\/")
        session_data_node = f'<script type="application/json" id="usage-session-data">{session_data_json}</script>\n'
    title = _t(lang, "title")
    detail_sections = ""
    if not is_empty:
        insight_surface = _render_insight_surface(report_data, lang)
        detail_sections = (
            f"  {_render_wrapped_section(report_data, lang)}\n"
            f"{insight_surface.rstrip()}{_render_tools_section(report_data, lang)}\n"
            f"  {_render_composition_section(report_data, lang)}\n"
            f"  {_render_project_section(report_data, lang)}\n"
            f"  {_render_model_section(report_data, lang)}\n"
            f"  {_render_trend_section(report_data, lang, date_to)}\n"
            f"  {_render_contribution_section(report_data, lang)}\n"
            f"  {_render_recent_titles_section(report_data, lang)}{_render_persona_section(report_data, lang)}\n"
            f"  {_render_session_section(report_data, lang)}\n"
        )
    default_range_attr = (
        f' data-default-range="{html.escape(default_range, quote=True)}"'
        if default_range
        else ""
    )
    return f"""<!doctype html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<script>{REPORT_THEME_INIT_JS}</script>
<style>
{_render_styles()}
</style>
</head>
<body{default_range_attr}>
<main class="wrap">
  {_render_header(report_data, lang, title, generated_at, is_empty)}
  {_date_filter(report_data, lang)}
  {_render_share_dialog(lang)}
  {_render_cards_section(cards, interactive=has_cube)}
{detail_sections}  {_render_sponsor_section(lang)}
</main>
<script type="application/json" id="usage-csv-data">{csv_data_json}</script>
<script type="application/json" id="usage-masked-csv-data">{masked_csv_data_json}</script>
{cube_data_node}{session_data_node}<script>
{_render_scripts(share_config_json)}
</script>
</body>
</html>
"""


def save_and_open(
    data: ReportData | Mapping[str, Any],
    out_path: str | None = None,
    language: str | None = None,
    default_range: str | None = None,
) -> str:
    if out_path:
        path = Path(os.path.expanduser(out_path))
        display_path = str(path.expanduser())
    else:
        reports_dir = Path.home() / ".usage-reports"
        reports_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = reports_dir / f"usage-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
        display_path = f"~/.usage-reports/{path.name}"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(
        generate_html(data, language=language, default_range=default_range),
        encoding="utf-8",
    )
    path.chmod(0o600)
    if out_path is None:
        if sys.platform == "darwin":
            subprocess.run(
                ["/usr/bin/open", str(path.resolve())],
                check=False,
                stdin=subprocess.DEVNULL,
                **hidden_console_kwargs(),
            )
        else:
            webbrowser.open(path.resolve().as_uri())
    return display_path
