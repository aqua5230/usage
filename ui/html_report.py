from __future__ import annotations

import html
import json
import math
import os
import re
import subprocess
import sys
import webbrowser
from datetime import date, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Mapping

from i18n import _t as _i18n_t
from tips_loader import Tip, load_tip
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


def _version() -> str:
    try:
        return version("usage")
    except PackageNotFoundError:
        return "dev"


def _detect_lang(env: Mapping[str, str] | None = None) -> str:
    return detect_lang(env)



def _escape(value: object) -> str:
    return html.escape(str(value))


def _highlight_commands(escaped_text: str) -> str:
    """Wrap slash commands, CLI flags, and standalone @ in inline code tags.

    Must be called **after** html.escape() so we don't double-escape.
    Uses an alternation that matches HTML tags first (group 1) to skip them.
    """
    _CMD_RE = re.compile(
        r"(<[^>]+>)"  # group 1: HTML tag — preserve as-is
        r"|"
        r"(\/[a-z][a-z0-9-]*"  # group 2: slash command
        r"|claude\s+--?[a-z-]+"  # CLI flag
        r"|(?<!\w)@(?!\w))",  # standalone @
    )

    def _repl(m: re.Match[str]) -> str:
        if m.group(1):
            return m.group(1)
        return f'<code class="tip-cmd-inline">{m.group(2)}</code>'

    return _CMD_RE.sub(_repl, escaped_text)


def _format_tip_text(value: str) -> str:
    parts = re.split(r"(\*\*.*?\*\*)", value)
    formatted: list[str] = []
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) >= 4:
            formatted.append(f"<strong>{html.escape(part[2:-2])}</strong>")
        else:
            formatted.append(html.escape(part))
    return _highlight_commands("".join(formatted))


def _display_name(value: object, lang: str) -> str:
    text = str(value) if value else _t(lang, "unknown")
    return _t(lang, "unknown") if text == "unknown" else text


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


def _subscription_body(subs: list[dict[str, Any]], lang: str) -> str:
    if not subs:
        return _empty_line(_t(lang, "sub_empty"))
    rows = []
    for sub in subs:
        since = sub.get("since")
        since_html = (
            f'<span class="sub-since" data-mask>{_escape(_t(lang, "sub_since"))} {_escape(since)}</span>'
            if since
            else ""
        )
        rows.append(
            '<div class="sub-row">'
            f'<span class="sub-agent">{_escape(str(sub.get("agent", "")))}</span>'
            f'<span class="sub-plan">{_escape(str(sub.get("plan", "")))}</span>'
            f"{since_html}"
            "</div>"
        )
    return f'<div class="subs">{"".join(rows)}</div>'


def _tip_section(tip: Tip, lang: str) -> str:
    escaped_command = html.escape(tip.command)
    escaped_title = html.escape(tip.title)
    heading_html = (
        f'<code class="tip-cmd">{escaped_command}</code>'
        f'<button class="tip-copy" type="button"'
        f' data-cmd="{escaped_command}"'
        f' data-label="{html.escape(_t(lang, "tip_copy_btn"))}"'
        f' data-copied="{html.escape(_t(lang, "tip_copied"))}"'
        f'>📋 {html.escape(_t(lang, "tip_copy_btn"))}</button>'
        f' ← {escaped_title}'
    )
    body = "".join(
        (
            f'<div class="rank-list"><p><strong>{_escape(_t(lang, "tip_what"))}</strong></p><p>{_format_tip_text(tip.what)}</p></div>',
            f'<div class="rank-list"><p><strong>{_escape(_t(lang, "tip_when"))}</strong></p><p>{_format_tip_text(tip.when)}</p></div>',
            f'<div class="rank-list"><p><strong>{_escape(_t(lang, "tip_how"))}</strong></p><p>{_format_tip_text(tip.how)}</p></div>',
            f'<div class="rank-list"><p><strong>{_escape(_t(lang, "tip_note"))}</strong></p><p>{_format_tip_text(tip.note)}</p></div>',
            f'<div class="rank-list"><p><strong>{_escape(_t(lang, "tip_scenario"))}</strong></p><p>{_format_tip_text(tip.scenario)}</p></div>',
        )
    )
    return _section(_t(lang, "tip_section_title"), f'<div class="prompt">{heading_html}</div>{body}')


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


def generate_html(data: dict[str, Any], language: str | None = None) -> str:
    lang = language or _detect_lang()
    tip = load_tip(lang)
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    summary = data["summary"]
    total_tokens = int(summary["total_tokens"])
    cost_main, cost_sub = _cost_value(float(summary["cost_usd"]), lang)
    cards = [
        (_t(lang, "kpi_tokens"), f"{total_tokens:,}", f"≈ {_fmt_tokens(total_tokens)}"),
        (_t(lang, "kpi_cost"), cost_main, cost_sub),
        (_t(lang, "kpi_sessions"), f'{int(summary["sessions"]):,}', ""),
        (_t(lang, "kpi_messages"), f'{int(summary["messages"]):,}', ""),
        (_t(lang, "kpi_active"), f'{int(summary["active_days"])}/{int(summary["total_days"])}', ""),
    ]

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

    agent_rows = [
        _rank_line(
            _display_name(agent["name"], lang),
            float(agent["pct"]),
            int(agent["tokens"]),
            float(agent["cost"]),
            lang,
        )
        for agent in data.get("by_agent", [])
    ]
    agent_rows_html = "".join(agent_rows)
    agent_body = (
        f'<div class="rank-head"><span></span><span>{_escape(_t(lang, "agent"))}</span><span>{_escape(_t(lang, "share"))}</span><span>{_escape(_t(lang, "tokens"))}</span><span>{_escape(_t(lang, "cost"))}</span></div>'
        f'<div class="rank-list">{agent_rows_html}</div>'
        if agent_rows
        else _empty_line(_t(lang, "empty_projects"))
    )

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

    share_config = {
        "copied": _t(lang, "share_copied"),
        "pathCopied": _t(lang, "share_path_copied"),
    }
    share_config_json = json.dumps(share_config, ensure_ascii=False).replace("</", "<\\/")
    subscription_body = _subscription_body(data.get("subscriptions", []), lang)
    persona_body = _persona_body(data.get("persona"), lang)
    title = _t(lang, "title")
    return f"""<!doctype html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#050505;--panel:#0d0f12;--soft:#15181d;--text:#f2f4f8;--muted:#8b949e;--faint:#343941;--token:#58a6ff;--cost:#3fb950;--warn:#d29922;}}
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
.cards{{display:grid;grid-template-columns:1.5fr 1.4fr 1fr 1fr 1fr;gap:10px;margin:22px 0 12px}}
.card{{background:var(--panel);padding:16px 14px;border-radius:6px;min-height:108px;display:flex;flex-direction:column}}
.card span{{display:block;color:var(--muted);font-size:.75rem;text-transform:uppercase;margin-bottom:10px}}
.card b{{display:block;font-size:clamp(.9rem,1.25vw,1.15rem);color:var(--text);white-space:nowrap;overflow-wrap:normal;line-height:1.2;font-weight:700;letter-spacing:0}}
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
.tip-cmd{{background:rgba(56,139,253,0.15);color:#58a6ff;padding:2px 10px;border-radius:4px;font-family:ui-monospace,'SF Mono',monospace;font-size:0.95em}}
.tip-cmd-inline{{background:rgba(56,139,253,0.10);color:#58a6ff;padding:1px 5px;border-radius:3px;font-size:0.92em}}
.tip-copy{{background:transparent;border:1px solid #30363d;color:#8b949e;padding:2px 10px;margin-left:8px;border-radius:4px;cursor:pointer;font-size:12px;font-family:inherit;transition:color 0.15s,border-color 0.15s}}
.tip-copy:hover{{color:#e6edf3;border-color:#58a6ff}}
.tip-copy.copied{{color:#56d364;border-color:#56d364}}
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
.subs{{display:grid;gap:10px}}
.sub-row{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:12px 14px;border:1px solid #30363d;border-radius:7px;background:#090b0e}}
.sub-agent{{font-weight:700;color:#f0f6fc;min-width:96px}}
.sub-plan{{color:var(--token);background:rgba(56,139,253,0.12);padding:3px 11px;border-radius:999px;font-size:.86rem}}
.sub-since{{margin-left:auto;color:var(--muted);font-size:.84rem}}
@media (max-width:780px){{.wrap{{padding:28px 14px}}header{{display:block}}.meta{{text-align:left;margin-top:16px}}.header-actions{{align-items:flex-start;margin-top:16px}}.cards{{grid-template-columns:repeat(2,1fr)}}.rank-head{{display:none}}.rank-list{{display:grid;gap:10px}}.rank-line{{display:grid;grid-template-columns:1fr;gap:8px;padding:12px;border:1px solid #30363d;border-radius:6px;background:#090b0e}}.rank-line .arrow{{display:none}}.rank-line .name{{white-space:normal;font-weight:700;color:#f0f6fc}}.rank-line .pct,.rank-line .tokens,.rank-line .cost{{display:flex;justify-content:space-between;gap:14px;text-align:left}}.rank-line .pct::before,.rank-line .tokens::before,.rank-line .cost::before{{content:attr(data-label);color:var(--muted)}}}}
@media (max-width:480px){{.wrap{{padding:22px 12px 28px}}h1{{white-space:normal}}.cards{{grid-template-columns:repeat(2,1fr);gap:8px}}.card{{min-height:96px;padding:13px 11px}}.share-dialog{{width:100vw;max-width:none;height:100dvh;max-height:none;margin:0;border:0;border-radius:0}}.share-modal{{min-height:100dvh;padding:16px 12px 18px}}.share-section{{padding:12px}}.share-action{{min-height:42px;font-size:.72rem;gap:4px;white-space:normal}}.share-file-actions{{grid-template-columns:1fr}}.section{{padding:16px 12px}}}}
</style>
</head>
<body>
<main class="wrap">
  <header>
    <div>
      <div class="eyebrow"><span>$ usage report</span> --period {html.escape(str(data["period_label"]))}<span class="cursor">_</span></div>
      <h1>{html.escape(title)}</h1>
      <p class="narrative">{html.escape(_narrative(data, lang))}</p>
    </div>
    <div class="header-actions">
      <div class="meta">{html.escape(_t(lang, "generated"))} {html.escape(generated_at)}<br>usage {_escape(_t(lang, "version"))} {_escape(_version())}</div>
      <button class="share-trigger" type="button" data-share-open><span aria-hidden="true">↗</span>{html.escape(_t(lang, "share_button_label"))}</button>
    </div>
  </header>
  <dialog class="share-dialog" data-share-dialog>
    <div class="share-modal">
      <button class="share-close" type="button" data-share-close aria-label="{html.escape(_t(lang, "share_close"))}">×</button>
      <h2>{html.escape(_t(lang, "share_modal_title"))}</h2>
      <section class="share-section">
        <h3>{html.escape(_t(lang, "share_file_title"))}</h3>
        <label class="share-file-mask"><input type="checkbox" data-share-file-mask checked> {html.escape(_t(lang, "share_file_mask_toggle"))}</label>
        <div class="share-file-actions">
          <button class="share-action" type="button" data-share-file="download"><span class="share-icon" aria-hidden="true">📥</span>{html.escape(_t(lang, "share_download_html"))}</button>
          <button class="share-action" type="button" data-share-file="path"><span class="share-icon" aria-hidden="true">📋</span>{html.escape(_t(lang, "share_copy_path"))}</button>
        </div>
        <p class="share-file-hint">{html.escape(_t(lang, "share_file_hint"))}</p>
      </section>
      <div class="share-toast" data-share-toast role="status" aria-live="polite"></div>
    </div>
  </dialog>
  <section class="cards">{''.join(f'<div class="card"><span>{html.escape(label)}</span><b>{html.escape(value)}</b>' + (f'<i>{html.escape(sub)}</i>' if sub else '') + '</div>' for label, value, sub in cards)}</section>
  {_section(_t(lang, "sub_section"), subscription_body, "sub-section")}
  {_section(_t(lang, "agent_section"), agent_body)}
  {_section(_t(lang, "project_section"), project_body, "project-section")}
  {_section(_t(lang, "model_section"), model_body)}
  {_section(_t(lang, "trend_section"), _trend_ascii(data.get("daily_trend", []), lang))}
  {_section(_t(lang, "persona_section"), persona_body, "persona-section")}
  {_section(_t(lang, "session_section"), session_body, "session-section")}
  {_tip_section(tip, lang) if tip else ''}
  <p class="sponsor">
    <a href="https://ko-fi.com/lollapalooza" target="_blank" rel="noopener" aria-label="Buy me a coffee on Ko-fi"><img src="https://img.shields.io/badge/Ko--fi-FF5E5B?logo=ko-fi&amp;logoColor=white" alt="Ko-fi"></a>
    <span class="tagline">{html.escape(_t(lang, "sponsor"))}</span>
    <a href="https://ko-fi.com/lollapalooza" target="_blank" rel="noopener" aria-label="Buy me a coffee on Ko-fi"><img src="https://img.shields.io/badge/Ko--fi-FF5E5B?logo=ko-fi&amp;logoColor=white" alt="Ko-fi"></a>
  </p>
  <p class="sponsor-link"><a href="https://github.com/aqua5230/usage" target="_blank" rel="noopener">github.com/aqua5230/usage</a></p>
</main>
<script>
const shareConfig = {share_config_json};
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

document.addEventListener('click', async (e) => {{
  const btn = e.target.closest('[data-share-file]');
  if (!btn) return;
  const action = btn.dataset.shareFile;
  if (action === 'download') {{
    downloadHtml(Boolean(shareFileMask?.checked));
    return;
  }}
  if (action === 'path') {{
    const path = window.location.protocol === 'file:' ? decodeURIComponent(window.location.href) : decodeURIComponent(window.location.pathname);
    const copied = await copyText(path);
    if (copied) showShareToast(shareConfig.pathCopied);
  }}
}});

document.addEventListener('click', async (e) => {{
  const btn = e.target.closest('.tip-copy');
  if (!btn) return;
  const cmd = btn.dataset.cmd;
  const ok = btn.dataset.copied;
  const label = btn.dataset.label;
  const success = await copyText(cmd);
  if (success) {{
    btn.classList.add('copied');
    btn.textContent = '✓ ' + ok;
    setTimeout(() => {{
      btn.classList.remove('copied');
      btn.textContent = '📋 ' + label;
    }}, 2000);
  }}
}});

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
