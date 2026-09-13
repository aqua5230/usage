# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Daily usage and pricing-confidence report fragments."""

from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Any, Callable, Mapping


AGENT_COLORS = {
    "claude-code": "#5abfa0",
    "codex": "#e0885a",
    "antigravity": "#8f86c9",
    "grok": "#c7839f",
}
_FALLBACK_COLOR = "#8b8577"


def _row_tokens(row: list[Any]) -> int:
    return sum(int(value or 0) for value in row[4:8])


def daily_usage(cube: Mapping[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Return cube usage by day and tool, including zero-use dates."""
    dates = [str(value) for value in cube.get("dates", [])]
    agents = list(cube.get("agents", []))
    values: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0, 0.0])
    for row in cube.get("rows", []):
        if not isinstance(row, list) or len(row) < 9:
            continue
        day_index, agent_index = int(row[0]), int(row[1])
        if not 0 <= day_index < len(dates) or not 0 <= agent_index < len(agents):
            continue
        bucket = values[day_index, agent_index]
        bucket[0] += _row_tokens(row)
        bucket[1] += float(row[8] or 0)
    result = []
    for index, agent in enumerate(agents):
        result.append(
            {
                "id": str(agent.get("id", "")),
                "name": str(agent.get("name", agent.get("id", ""))),
                "color": AGENT_COLORS.get(str(agent.get("id", "")), _FALLBACK_COLOR),
                "tokens": [int(values[day, index][0]) for day in range(len(dates))],
                "cost": [float(values[day, index][1]) for day in range(len(dates))],
            }
        )
    return dates, result


def pricing_usage(cube: Mapping[str, Any]) -> tuple[int, int, list[str]]:
    """Return priced tokens, unpriced tokens, and up to all unpriced models."""
    models = list(cube.get("models", []))
    priced = 0
    unpriced = 0
    unknown_models: dict[str, int] = defaultdict(int)
    for row in cube.get("rows", []):
        if not isinstance(row, list) or len(row) < 8:
            continue
        tokens = _row_tokens(row)
        model = models[int(row[2])] if 0 <= int(row[2]) < len(models) else {}
        if model.get("cost_known"):
            priced += tokens
        else:
            unpriced += tokens
            unknown_models[str(model.get("name", "unknown"))] += tokens
    names = [name for name, _tokens in sorted(unknown_models.items(), key=lambda item: -item[1])]
    return priced, unpriced, names


def _pct(value: int, total: int) -> str:
    return f"{value / total * 100:.1f}%" if total else "0.0%"


def render_daily_chart(
    cube: Mapping[str, Any],
    t: Callable[[str], str],
    fmt_tokens: Callable[[int], str],
    fmt_cost: Callable[[float], str],
) -> str:
    """Render the initial inline-SVG daily chart; the browser redraws it on filters."""
    dates, agents = daily_usage(cube)
    totals = [sum(agent["tokens"][index] for agent in agents) for index in range(len(dates))]
    if not dates or max(totals, default=0) <= 0:
        return f'<div class="daily-chart-wrap">{_empty(t("empty_daily"))}</div>'

    width, height, left, right, top, bottom = 760, 180, 48, 8, 18, 32
    plot_width = width - left - right
    plot_height = height - top - bottom
    maximum = max(totals)
    step = plot_width / len(dates)
    if len(dates) <= 31:
        bar_width = max(1, step * 0.55)
        bar_offset = (step - bar_width) / 2
    else:
        gap = 0 if len(dates) > 120 else 1 if len(dates) > 45 else min(4, step * 0.25)
        bar_width = max(1, step - gap)
        bar_offset = gap / 2
    svg: list[str] = [
        f'<svg class="daily-chart-svg" viewBox="0 0 {width} {height}" role="img" '
        f'preserveAspectRatio="none" aria-label="{escape(t("daily_chart_title"), quote=True)}">'
    ]
    labels: list[str] = []
    for fraction in (1, 0.5, 0):
        y = top + plot_height * (1 - fraction)
        label = fmt_tokens(round(maximum * fraction))
        svg.append(
            f'<line class="daily-grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" '
            f'y2="{y:.1f}" vector-effect="non-scaling-stroke"/>'
        )
        labels.append(
            f'<span class="daily-chart-label daily-y-label" style="left:{(left - 7) / width * 100:.2f}%;'
            f'top:{y / height * 100:.2f}%">{escape(label)}</span>'
        )
    peak = totals.index(maximum)
    for index, total in enumerate(totals):
        x = left + index * step + bar_offset
        cursor = top + plot_height
        for agent_index, agent in enumerate(agents):
            value = agent["tokens"][index]
            if not value:
                continue
            bar_height = value / maximum * plot_height
            cursor -= bar_height
            rounded = (
                " rx=\"2\" ry=\"2\""
                if not any(other["tokens"][index] > 0 for other in agents[agent_index + 1:])
                else ""
            )
            svg.append(
                f'<rect class="daily-segment" x="{x:.2f}" y="{cursor:.2f}" width="{bar_width:.2f}" '
                f'height="{bar_height:.2f}" fill="{escape(agent["color"], quote=True)}"{rounded}/>'
            )
        if index == peak:
            labels.append(
                f'<span class="daily-chart-label daily-peak-label" style="left:{(x + bar_width / 2) / width * 100:.2f}%;'
                f'top:{max(12, cursor - 5) / height * 100:.2f}%">{escape(fmt_tokens(total))}</span>'
            )
    for index in sorted({0, len(dates) // 2, len(dates) - 1}):
        x = left + index * step + step / 2
        labels.append(
            f'<span class="daily-chart-label daily-x-label" style="left:{x / width * 100:.2f}%;'
            f'top:{(height - 7) / height * 100:.2f}%">{escape(dates[index][5:])}</span>'
        )
    svg.append("</svg>")
    legend = "".join(
        f'<span class="daily-legend-item"><i style="background:{escape(agent["color"], quote=True)}"></i>'
        f'{escape(agent["name"])} <b>{escape(fmt_tokens(sum(agent["tokens"])))}</b></span>'
        for agent in agents
        if sum(agent["tokens"]) > 0
    )
    return (
        '<div class="daily-chart-wrap"><div class="daily-chart-head"><strong>'
        f'{escape(t("daily_chart_title"))}</strong><div class="daily-chart-toggle">'
        f'<button type="button" data-daily-mode="tokens" aria-pressed="true">{escape(t("daily_chart_mode_tokens"))}</button>'
        f'<button type="button" data-daily-mode="cost" aria-pressed="false">{escape(t("daily_chart_mode_cost"))}</button>'
        f'</div></div><div class="daily-chart-canvas">{"".join(svg)}{"".join(labels)}</div><div class="daily-chart-legend">{legend}</div></div>'
    )


def render_pricing_section(
    cube: Mapping[str, Any],
    t: Callable[[str], str],
    fmt_tokens: Callable[[int], str],
    display_name: Callable[[str], str],
    model_separator: str,
) -> str:
    priced, unpriced, names = pricing_usage(cube)
    return (
        '<section class="section pricing-section"><div class="prompt"><span>[usage]&gt;</span> '
        f'{escape(t("pricing_section"))}</div><div class="rule" aria-hidden="true">'
        f'────────────────────────────────────────────────────────</div>{render_pricing_body(priced, unpriced, names, t, fmt_tokens, display_name, model_separator)}</section>'
    )


def render_pricing_body(
    priced: int,
    unpriced: int,
    names: list[str],
    t: Callable[[str], str],
    fmt_tokens: Callable[[int], str],
    display_name: Callable[[str], str],
    model_separator: str,
) -> str:
    total = priced + unpriced
    hint = f'<p class="pricing-hint">{escape(t("pricing_hint"))}</p>'
    if unpriced <= 0:
        return f'<div class="pricing-all">{escape(t("pricing_all_priced"))}</div>{hint}'
    displayed = names[:3]
    suffix = f" +{len(names) - 3}" if len(names) > 3 else ""
    model_text = model_separator.join(display_name(name) for name in displayed) + suffix
    priced_pct, unpriced_pct = _pct(priced, total), _pct(unpriced, total)
    return (
        f'<div class="pricing-bar" aria-hidden="true"><i style="width:{priced_pct};background:var(--cost)"></i><i style="width:{unpriced_pct};background:#8b8577"></i></div>'
        f'<div class="rank-list pricing-list"><div class="rank-line pricing-line"><span class="left-tick"></span><span class="arrow">→</span><span class="name">{escape(t("pricing_priced"))}</span><span class="pct">{priced_pct}</span><span class="tokens">{escape(fmt_tokens(priced))}</span></div>'
        f'<div class="rank-line pricing-line"><span class="left-tick" style="background:#8b8577"></span><span class="arrow">→</span><span class="name">{escape(t("pricing_unpriced"))}<span class="pricing-models">{escape(model_text)}</span></span><span class="pct">{unpriced_pct}</span><span class="tokens">{escape(fmt_tokens(unpriced))}</span></div></div>{hint}'
    )


def _empty(label: str) -> str:
    return f'<div class="empty">→ {escape(label)}</div>'


REPORT_DAILY_CHART_JS = r"""(() => {
  const node = document.querySelector('#usage-cube-data');
  if (!node) return;
  let cube;
  try { cube = JSON.parse(node.textContent); } catch (_) { return; }
  if (!Array.isArray(cube.dates) || !Array.isArray(cube.rows)) return;
  const svgNs = 'http://www.w3.org/2000/svg';
  const agentColors = {
    'claude-code': '#5abfa0', codex: '#e0885a', antigravity: '#8f86c9', grok: '#c7839f',
  };
  let mode = 'tokens';
  let lastSummary = null;

  function tokens(row) {
    return Number(row[4]) + Number(row[5]) + Number(row[6]) + Number(row[7]);
  }
  function textNode(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    item.textContent = text;
    return item;
  }
  function svgNode(tag, className, attributes, text = '') {
    const item = document.createElementNS(svgNs, tag);
    if (className) item.setAttribute('class', className);
    Object.entries(attributes).forEach(([key, value]) => item.setAttribute(key, String(value)));
    if (text) item.textContent = text;
    return item;
  }
  function formatTokens(value) {
    const number = Math.max(0, Number(value) || 0);
    if (number >= 999950000) return `${(number / 1000000000).toFixed(2)}B`;
    if (number >= 999950) return `${(number / 1000000).toFixed(1)}M`;
    if (number >= 1000) return `${(number / 1000).toFixed(1)}K`;
    return String(Math.round(number));
  }
  function formatCost(value) {
    const number = Math.max(0, Number(value) || 0);
    return number > 0 && number < 1 ? `$${number.toFixed(4)}` : `$${number.toFixed(2)}`;
  }
  function modeValue(item, day) { return mode === 'cost' ? item.cost[day] : item.tokens[day]; }
  function displayName(value) {
    const filter = window.usageReportFilter;
    if (filter && filter.displayName) return filter.displayName(value);
    const text = value == null ? '' : String(value);
    return (!text || text === 'unknown') ? (shareConfig.unknown || 'unknown') : text;
  }
  function rangeDays(summary) {
    return cube.dates.filter((day) => day >= summary.bounds.from && day <= summary.bounds.to);
  }
  function dailyData(summary) {
    const days = rangeDays(summary);
    const positions = Object.fromEntries(cube.dates.map((day, index) => [day, index]));
    const agents = (cube.agents || []).map((agent, index) => ({
      id: String(agent.id || ''), name: String(agent.name || agent.id || ''),
      color: agentColors[String(agent.id || '')] || '#8b8577',
      tokens: Array(days.length).fill(0), cost: Array(days.length).fill(0), index,
    }));
    summary.rows.forEach((row) => {
      const day = cube.dates[Number(row[0])];
      const dayIndex = days.indexOf(day);
      const agent = agents[Number(row[1])];
      if (dayIndex < 0 || !agent) return;
      agent.tokens[dayIndex] += tokens(row);
      agent.cost[dayIndex] += Number(row[8]) || 0;
    });
    return {days, agents, positions};
  }
  function clearHover(svg, tooltip) {
    svg.className.baseVal = 'daily-chart-svg';
    tooltip.hidden = true;
  }
  function setHover(svg, tooltip, data, dayIndex) {
    svg.setAttribute('class', 'daily-chart-svg is-hovering');
    const day = data.days[dayIndex];
    tooltip.replaceChildren();
    tooltip.append(textNode('strong', 'daily-tooltip-date', day));
    const values = data.agents.filter((agent) => modeValue(agent, dayIndex) > 0);
    values.forEach((agent) => {
      const line = textNode('span', 'daily-tooltip-line', '');
      const dot = textNode('i', '', '');
      dot.style.background = agent.color;
      line.append(dot, textNode('b', '', agent.name), textNode('em', '', mode === 'cost'
        ? formatCost(agent.cost[dayIndex]) : formatTokens(agent.tokens[dayIndex])));
      tooltip.append(line);
    });
    const total = values.reduce((sum, agent) => sum + modeValue(agent, dayIndex), 0);
    tooltip.append(textNode('span', 'daily-tooltip-total', `${shareConfig.dailyChartTotal}: ${mode === 'cost' ? formatCost(total) : formatTokens(total)}`));
    const edge = dayIndex === 0 ? ' is-left' : dayIndex === data.days.length - 1 ? ' is-right' : '';
    tooltip.className = `daily-tooltip${edge}`;
    tooltip.style.left = dayIndex === 0 ? '0' : dayIndex === data.days.length - 1
      ? '100%' : `${((dayIndex + .5) / data.days.length * 100).toFixed(1)}%`;
    tooltip.hidden = false;
  }
  function buildDailyChart(summary) {
    lastSummary = summary;
    const data = dailyData(summary);
    const totals = data.days.map((_day, index) => data.agents.reduce((sum, agent) => sum + modeValue(agent, index), 0));
    const wrap = textNode('div', 'daily-chart-wrap', '');
    const head = textNode('div', 'daily-chart-head', '');
    head.append(textNode('strong', '', shareConfig.dailyChartTitle));
    const toggle = textNode('div', 'daily-chart-toggle', '');
    [['tokens', shareConfig.dailyChartModeTokens], ['cost', shareConfig.dailyChartModeCost]].forEach(([key, label]) => {
      const button = textNode('button', '', label);
      button.type = 'button';
      button.dataset.dailyMode = key;
      button.setAttribute('aria-pressed', String(mode === key));
      button.addEventListener('click', () => {
        if (mode === key || !lastSummary) return;
        mode = key;
        const section = document.querySelector('.trend-section');
        const previous = section && section.querySelector('.daily-chart-wrap');
        const next = buildDailyChart(lastSummary);
        if (previous && previous.parentNode) {
          previous.parentNode.insertBefore(next, previous);
          previous.remove();
        }
      });
      toggle.append(button);
    });
    head.append(toggle);
    wrap.append(head);
    if (!data.days.length || Math.max(...totals, 0) <= 0) {
      wrap.append(textNode('div', 'empty', `→ ${shareConfig.emptyDaily}`));
      return wrap;
    }
    const canvas = textNode('div', 'daily-chart-canvas', '');
    const tooltip = textNode('div', 'daily-tooltip', '');
    tooltip.hidden = true;
    const width = 760; const height = 180; const left = 48; const right = 8; const top = 18; const bottom = 32;
    const plotWidth = width - left - right; const plotHeight = height - top - bottom;
    const maximum = Math.max(...totals); const step = plotWidth / data.days.length;
    const compactBars = data.days.length <= 31;
    const gap = compactBars ? 0 : data.days.length > 120 ? 0 : data.days.length > 45 ? 1 : Math.min(4, step * .25);
    const barWidth = compactBars ? Math.max(1, step * .55) : Math.max(1, step - gap);
    const barOffset = compactBars ? (step - barWidth) / 2 : gap / 2;
    const svg = svgNode('svg', 'daily-chart-svg', {viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': shareConfig.dailyChartTitle});
    const label = (className, text, x, y) => {
      const item = textNode('span', `daily-chart-label ${className}`, text);
      item.style.left = `${(x / width * 100).toFixed(2)}%`;
      item.style.top = `${(y / height * 100).toFixed(2)}%`;
      return item;
    };
    canvas.append(svg);
    [1, .5, 0].forEach((fraction) => {
      const y = top + plotHeight * (1 - fraction);
      svg.append(svgNode('line', 'daily-grid', {x1: left, y1: y, x2: width - right, y2: y, 'vector-effect': 'non-scaling-stroke'}));
      canvas.append(label('daily-y-label', mode === 'cost' ? formatCost(maximum * fraction) : formatTokens(maximum * fraction), left - 7, y));
    });
    const peak = totals.indexOf(maximum);
    data.days.forEach((_day, dayIndex) => {
      const x = left + dayIndex * step + barOffset;
      let cursor = top + plotHeight;
      const group = svgNode('g', 'daily-bar', {'data-day-index': dayIndex});
      data.agents.forEach((agent, agentIndex) => {
        const value = modeValue(agent, dayIndex);
        if (!value) return;
        const barHeight = value / maximum * plotHeight;
        cursor -= barHeight;
        const topSegment = !data.agents.slice(agentIndex + 1).some((other) => modeValue(other, dayIndex) > 0);
        group.append(svgNode('rect', 'daily-segment', {x, y: cursor, width: barWidth, height: barHeight, fill: agent.color, rx: topSegment ? 2 : 0, ry: topSegment ? 2 : 0}));
      });
      group.addEventListener('mouseenter', () => setHover(svg, tooltip, data, dayIndex));
      group.addEventListener('mouseleave', () => clearHover(svg, tooltip));
      group.addEventListener('focus', () => setHover(svg, tooltip, data, dayIndex));
      group.addEventListener('blur', () => clearHover(svg, tooltip));
      group.setAttribute('tabindex', '0');
      svg.append(group);
      if (dayIndex === peak) canvas.append(label('daily-peak-label', mode === 'cost' ? formatCost(totals[dayIndex]) : formatTokens(totals[dayIndex]), x + barWidth / 2, Math.max(12, cursor - 5)));
    });
    [...new Set([0, Math.floor((data.days.length - 1) / 2), data.days.length - 1])].forEach((index) => {
      canvas.append(label('daily-x-label', data.days[index].slice(5), left + index * step + step / 2, height - 7));
    });
    canvas.append(tooltip); wrap.append(canvas);
    const legend = textNode('div', 'daily-chart-legend', '');
    data.agents.filter((agent) => agent.tokens.some((value) => value > 0)).forEach((agent) => {
      const item = textNode('span', 'daily-legend-item', '');
      const dot = textNode('i', '', ''); dot.style.background = agent.color;
      const total = agent[mode === 'cost' ? 'cost' : 'tokens'].reduce((sum, value) => sum + value, 0);
      item.append(dot, textNode('span', '', agent.name), textNode('b', '', mode === 'cost' ? formatCost(total) : formatTokens(total)));
      legend.append(item);
    });
    wrap.append(legend);
    return wrap;
  }
  function pricingData(summary) {
    let priced = 0; let unpriced = 0; const models = {};
    summary.rows.forEach((row) => {
      const value = tokens(row); const model = cube.models[Number(row[2])];
      if (model && model.cost_known) priced += value;
      else { unpriced += value; const name = String((model && model.name) || 'unknown'); models[name] = (models[name] || 0) + value; }
    });
    return {priced, unpriced, names: Object.entries(models).sort((a, b) => b[1] - a[1]).map(([name]) => name)};
  }
  function pricingPercent(value, total) { return total ? `${(value / total * 100).toFixed(1)}%` : '0.0%'; }
  function pricingLine(name, percent, value, color, models = '') {
    const line = textNode('div', 'rank-line pricing-line', '');
    const tick = textNode('span', 'left-tick', ''); tick.style.background = color;
    const label = textNode('span', 'name', name);
    if (models) label.append(textNode('span', 'pricing-models', models));
    line.append(tick, textNode('span', 'arrow', '→'), label, textNode('span', 'pct', percent), textNode('span', 'tokens', formatTokens(value)));
    return line;
  }
  function rebuildPricing(summary) {
    const section = document.querySelector('.pricing-section');
    if (!section) return;
    const body = textNode('div', 'pricing-body', ''); const data = pricingData(summary); const total = data.priced + data.unpriced;
    if (!data.unpriced) body.append(textNode('div', 'pricing-all', shareConfig.pricingAllPriced));
    else {
      const bar = textNode('div', 'pricing-bar', ''); bar.setAttribute('aria-hidden', 'true');
      [[data.priced, 'var(--cost)'], [data.unpriced, '#8b8577']].forEach(([value, color]) => { const segment = textNode('i', '', ''); segment.style.width = pricingPercent(value, total); segment.style.background = color; bar.append(segment); });
      const list = textNode('div', 'rank-list pricing-list', '');
      const models = data.names.slice(0, 3).map(displayName).join(shareConfig.pricingModelSeparator || ', ');
      const suffix = data.names.length > 3 ? ` +${data.names.length - 3}` : '';
      list.append(pricingLine(shareConfig.pricingPriced, pricingPercent(data.priced, total), data.priced, 'var(--cost)'), pricingLine(shareConfig.pricingUnpriced, pricingPercent(data.unpriced, total), data.unpriced, '#8b8577', `${models}${suffix}`));
      body.append(bar, list);
    }
    body.append(textNode('p', 'pricing-hint', shareConfig.pricingHint));
    const prompt = section.querySelector('.prompt'); const rule = section.querySelector('.rule');
    Array.from(section.children).forEach((child) => { if (child !== prompt && child !== rule) child.remove(); });
    section.append(body);
  }
  window.usageReportDaily = {buildDailyChart, rebuildPricing};
})();
"""
