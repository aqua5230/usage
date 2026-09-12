# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Front-end report filtering and drill-down behavior."""

from __future__ import annotations


REPORT_FILTER_JS = r"""(() => {
  const cubeNode = document.querySelector('#usage-cube-data');
  if (!cubeNode) return;

  let cube;
  try {
    cube = JSON.parse(cubeNode.textContent);
  } catch (_) {
    return;
  }
  if (!Array.isArray(cube.dates) || !Array.isArray(cube.rows)) return;

  let sessions = [];
  const sessionNode = document.querySelector('#usage-session-data');
  if (sessionNode) {
    try {
      const parsed = JSON.parse(sessionNode.textContent);
      if (Array.isArray(parsed)) sessions = parsed;
    } catch (_) {
      sessions = [];
    }
  }

  const palette = [
    '#5abfa0', '#8f86c9', '#e0885a', '#78cdb2',
    '#aaa3d4', '#dca080', '#3f9f82', '#7168ad',
  ];
  const agentColors = {
    'claude-code': '#5abfa0',
    codex: '#e0885a',
    antigravity: '#8f86c9',
    grok: '#78cdb2',
  };
  let activeBounds = null;

  function rowTokens(row) {
    return Number(row[4]) + Number(row[5]) + Number(row[6]) + Number(row[7]);
  }

  function aggregateRows(rows, groupIndex, rowFilter = null) {
    const result = {};
    rows.forEach((row) => {
      if (rowFilter && !rowFilter(row)) return;
      const key = String(row[groupIndex]);
      if (!Object.prototype.hasOwnProperty.call(result, key)) {
        result[key] = {tokens: 0, cost: 0, costKnown: false};
      }
      const item = result[key];
      item.tokens += rowTokens(row);
      item.cost += Number(row[8]);
      const model = cube.models[Number(row[2])];
      // 只有「所有模型都沒有公開價格」才算未知；單一模型的彙總結果與該模型的旗標相同。
      item.costKnown = item.costKnown || Boolean(model && model.cost_known);
    });
    return result;
  }

  function parseDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
    if (!match) return null;
    const parsed = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function formatDate(value) {
    return value.toISOString().slice(0, 10);
  }

  function shiftDate(value, days) {
    const result = new Date(value.getTime());
    result.setUTCDate(result.getUTCDate() + days);
    return result;
  }

  function isoWeek(value) {
    const tmp = new Date(Date.UTC(
      value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate()
    ));
    const dayNum = tmp.getUTCDay() || 7;
    tmp.setUTCDate(tmp.getUTCDate() + 4 - dayNum);
    const isoYear = tmp.getUTCFullYear();
    const yearStart = new Date(Date.UTC(isoYear, 0, 1));
    const week = Math.ceil((((tmp - yearStart) / 86400000) + 1) / 7);
    return {year: isoYear, week};
  }

  function isoWeekDate(year, week, weekday) {
    const jan4 = new Date(Date.UTC(year, 0, 4));
    const day = jan4.getUTCDay() || 7;
    const result = new Date(jan4);
    result.setUTCDate(
      jan4.getUTCDate() - (day - 1) + (week - 1) * 7 + (weekday - 1)
    );
    return result;
  }

  function eachDate(from, to, visit) {
    let cursor = parseDate(from);
    const end = parseDate(to);
    if (!cursor || !end) return;
    while (cursor <= end) {
      visit(cursor, formatDate(cursor));
      cursor = shiftDate(cursor, 1);
    }
  }

  function normalizeBounds(from, to) {
    const minimum = cube.dates[0];
    const maximum = cube.dates[cube.dates.length - 1];
    if (!minimum || !maximum) return null;
    let start = parseDate(from) ? String(from) : minimum;
    let end = parseDate(to) ? String(to) : maximum;
    start = start < minimum ? minimum : start > maximum ? maximum : start;
    end = end < minimum ? minimum : end > maximum ? maximum : end;
    if (start > end) [start, end] = [end, start];
    return {from: start, to: end};
  }

  function rangeBounds(key) {
    const minimum = cube.dates[0];
    const maximum = cube.dates[cube.dates.length - 1];
    const last = parseDate(maximum);
    if (!minimum || !last) return null;
    let first = last;
    if (key === 'last7') first = shiftDate(last, -6);
    else if (key === 'last30') first = shiftDate(last, -29);
    else if (key === 'month') {
      first = new Date(Date.UTC(last.getUTCFullYear(), last.getUTCMonth(), 1));
    } else if (key === 'all') {
      return {from: minimum, to: maximum};
    }
    return normalizeBounds(formatDate(first), maximum);
  }

  function rowMatches(bounds) {
    return (row) => {
      const date = cube.dates[Number(row[0])];
      return Boolean(date && date >= bounds.from && date <= bounds.to);
    };
  }

  function summarizeRange(from, to) {
    const bounds = normalizeBounds(from, to);
    if (!bounds) return null;
    const selected = rowMatches(bounds);
    const rows = cube.rows.filter(selected);
    const startDate = parseDate(bounds.from);
    const endDate = parseDate(bounds.to);
    const totalDays = Math.max(
      1,
      Math.round((endDate - startDate) / 86400000) + 1
    );
    const previousTo = shiftDate(startDate, -1);
    const previousFrom = shiftDate(previousTo, -(totalDays - 1));
    const previousBounds = {from: formatDate(previousFrom), to: formatDate(previousTo)};
    const previousRows = cube.rows.filter(rowMatches(previousBounds));
    const byDay = {};
    let unpricedTokens = 0;
    rows.forEach((row) => {
      const tokens = rowTokens(row);
      const day = cube.dates[Number(row[0])];
      byDay[day] = (byDay[day] || 0) + tokens;
      const model = cube.models[Number(row[2])];
      if (!model || !model.cost_known) unpricedTokens += tokens;
    });
    let peakDate = bounds.from;
    let peakTokens = -1;
    cube.dates.forEach((day) => {
      if (day < bounds.from || day > bounds.to) return;
      const tokens = byDay[day] || 0;
      if (tokens > peakTokens) {
        peakDate = day;
        peakTokens = tokens;
      }
    });
    const tokenTotal = rows.reduce((total, row) => total + rowTokens(row), 0);
    const costTotal = rows.reduce((total, row) => total + Number(row[8]), 0);
    const projectTotals = aggregateRows(rows, 3);
    const modelTotals = aggregateRows(rows, 2);
    let topModel = '';
    let topModelTokens = -1;
    Object.entries(modelTotals).forEach(([modelIndex, item]) => {
      if (item.tokens <= topModelTokens) return;
      topModelTokens = item.tokens;
      const model = cube.models[Number(modelIndex)];
      topModel = model ? String(model.name) : '';
    });
    return {
      narrativeProjects: Object.keys(projectTotals).length,
      topModel,
      bounds,
      rows,
      tokens: tokenTotal,
      cost: costTotal,
      messages: rows.reduce((total, row) => total + Number(row[9]), 0),
      sessions: sessions.filter((session) => {
        const day = cube.dates[Number(session.date_idx)];
        return Boolean(day && day >= bounds.from && day <= bounds.to);
      }).length,
      activeDays: Object.values(byDay).filter((tokens) => tokens > 0).length,
      totalDays,
      peakDate,
      peakTokens: Math.max(0, peakTokens),
      unpricedTokens,
      // 前期只要有一天早於資料的第一天，那段本來就沒資料，拿來當基準會算出假成長。
      hasPrevious: previousRows.length > 0 && previousBounds.from >= cube.dates[0],
      previousTokens: previousRows.reduce((total, row) => total + rowTokens(row), 0),
      previousCost: previousRows.reduce((total, row) => total + Number(row[8]), 0),
    };
  }

  window.usageReportFilter = {cube, aggregateRows, normalizeBounds, rangeBounds, summarizeRange, isoWeek};

  function rowName(row, selector) {
    const node = row.querySelector(selector);
    return node ? node.textContent.trim() : '';
  }

  function setToggleLabel(row, expanded, name) {
    const action = expanded ? shareConfig.collapse : shareConfig.expand;
    row.setAttribute('aria-label', `${action} ${name}`.trim());
  }

  function bindKeyboardToggle(row, toggle) {
    row.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      toggle();
    });
  }

  function modelChildren(group) {
    const children = [];
    let sibling = group.nextElementSibling;
    while (sibling && !sibling.classList.contains('model-group')) {
      if (sibling.classList.contains('model-child')) children.push(sibling);
      sibling = sibling.nextElementSibling;
    }
    return children;
  }

  function applyModelGroup(group, expanded) {
    modelChildren(group).forEach((child) => {
      child.hidden = !expanded;
    });
    group.setAttribute('aria-expanded', String(expanded));
    const arrow = group.querySelector('.arrow');
    if (arrow) arrow.textContent = expanded ? '▾' : '▸';
    setToggleLabel(group, expanded, rowName(group, '.name'));
  }

  function liveModelGroups() {
    return Array.from(
      document.querySelectorAll('.model-section .rank-line.model-group[data-agent-id]')
    );
  }

  function expandedModelIds() {
    return new Set(
      liveModelGroups()
        .filter((group) => group.getAttribute('aria-expanded') === 'true')
        .map((group) => group.dataset.agentId)
    );
  }

  function saveModelGroups() {
    try {
      window.localStorage.setItem(
        'usage-report-model-groups',
        JSON.stringify(Array.from(expandedModelIds()))
      );
    } catch (_) {
      // Keep the state for this page when privacy settings deny storage.
    }
  }

  function bindModelGroup(group, expanded) {
    group.tabIndex = 0;
    applyModelGroup(group, expanded);
    const toggle = () => {
      applyModelGroup(group, group.getAttribute('aria-expanded') !== 'true');
      saveModelGroups();
    };
    group.addEventListener('click', toggle);
    bindKeyboardToggle(group, toggle);
  }

  let savedModelIds = new Set();
  try {
    const saved = JSON.parse(window.localStorage.getItem('usage-report-model-groups') || '[]');
    if (Array.isArray(saved)) {
      savedModelIds = new Set(saved.filter((value) => typeof value === 'string'));
    }
  } catch (_) {
    savedModelIds = new Set();
  }
  liveModelGroups().forEach((group) => {
    bindModelGroup(group, savedModelIds.has(group.dataset.agentId));
  });

  function formatTokens(value) {
    if (value >= 999950000) return `${(value / 1000000000).toFixed(2)}B`;
    if (value >= 999950) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return String(value);
  }

  function formatInteger(value) {
    return Math.round(value).toLocaleString('en-US');
  }

  function formatCost(value, known) {
    if (!known) return '—';
    const digits = value > 0 && value < 1 ? 4 : 2;
    return `$${value.toLocaleString('en-US', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })}`;
  }

  function formatDuration(minutes) {
    const value = Number(minutes);
    if (!Number.isFinite(value) || value < 0) return '0m';
    if (value >= 60) {
      return `${Math.floor(value / 60)}h ${Math.floor(value % 60)}m`;
    }
    return `${Math.floor(value)}m`;
  }

  function displayName(value) {
    const text = value == null ? '' : String(value);
    return (!text || text === 'unknown') ? (shareConfig.unknown || 'unknown') : text;
  }

  function modelColor(name) {
    const normalized = name.toLowerCase();
    if (normalized.startsWith('claude')) return '#5abfa0';
    if (normalized.startsWith('gemini')) return '#8f86c9';
    if (normalized.startsWith('gpt')) return '#e0885a';
    return '#8b8577';
  }

  function appendTextSpan(row, className, text, label = null) {
    const span = document.createElement('span');
    span.className = className;
    span.textContent = text;
    if (label !== null) span.dataset.label = label;
    row.append(span);
    return span;
  }

  function appendShareBar(container, share, color) {
    const bar = document.createElement('span');
    bar.className = 'share-bar';
    bar.setAttribute('aria-hidden', 'true');
    const fill = document.createElement('span');
    fill.style.width = `${Math.max(0, Math.min(100, share)).toFixed(2)}%`;
    fill.style.background = color;
    bar.append(fill);
    container.append(bar);
  }

  function createRankRow(name, item, total, color, options = {}) {
    const share = total ? item.tokens / total * 100 : 0;
    const row = document.createElement('div');
    row.className = `rank-line${options.rowClass ? ` ${options.rowClass}` : ''}`;
    if (options.agentId !== undefined) row.dataset.agentId = String(options.agentId);
    if (options.projectIndex !== undefined) row.dataset.projectIndex = String(options.projectIndex);
    appendTextSpan(row, 'arrow', options.arrow || '→');
    const nameNode = appendTextSpan(row, options.nameClass || 'name', name);
    appendShareBar(nameNode, share, color);
    appendTextSpan(row, 'pct', `${share.toFixed(1)}%`, shareConfig.share);
    appendTextSpan(row, 'tokens', formatTokens(item.tokens), shareConfig.tokens);
    const costKnown = options.costKnown === undefined ? item.costKnown : options.costKnown;
    appendTextSpan(row, 'cost', formatCost(item.cost, costKnown), shareConfig.cost);
    return row;
  }

  const projectSection = document.querySelector('.project-section');
  const projectHeadCells = projectSection
    ? Array.from(projectSection.querySelectorAll('.rank-head > span'))
    : [];
  const tokensLabel = projectHeadCells[3] ? projectHeadCells[3].textContent : shareConfig.tokens;
  const costLabel = projectHeadCells[4] ? projectHeadCells[4].textContent : shareConfig.cost;

  function createProjectDetailCaption() {
    const caption = document.createElement('div');
    caption.className = 'project-model-detail project-detail-caption';
    caption.textContent = shareConfig.projectShare;
    return caption;
  }

  function removeProjectDetails(projectRow) {
    let sibling = projectRow.nextElementSibling;
    while (sibling && sibling.classList.contains('project-model-detail')) {
      const next = sibling.nextElementSibling;
      sibling.remove();
      sibling = next;
    }
  }

  function createProjectDetail(modelIndex, item, projectTokens) {
    const model = cube.models[modelIndex];
    const modelName = model ? String(model.name) : '';
    const share = projectTokens ? item.tokens / projectTokens * 100 : 0;
    const row = document.createElement('div');
    row.className = 'rank-line model-child project-model-detail';
    appendTextSpan(row, 'arrow', '');
    const name = appendTextSpan(row, 'model-name', modelName);
    appendShareBar(name, share, modelColor(modelName));
    appendTextSpan(row, 'pct', `${share.toFixed(1)}%`, shareConfig.projectShare);
    appendTextSpan(row, 'tokens', formatTokens(item.tokens), tokensLabel);
    appendTextSpan(row, 'cost', formatCost(item.cost, item.costKnown), costLabel);
    return row;
  }

  function expandProject(projectRow) {
    const projectIndex = Number(projectRow.dataset.projectIndex);
    const byModel = aggregateRows(
      cube.rows,
      2,
      (row) => Number(row[3]) === projectIndex && (!activeBounds || rowMatches(activeBounds)(row))
    );
    const details = Object.entries(byModel)
      .map(([modelIndex, item]) => ({modelIndex: Number(modelIndex), ...item}))
      .filter((item) => item.tokens > 0 || item.cost > 0)
      .sort((left, right) => right.tokens - left.tokens || left.modelIndex - right.modelIndex);
    const projectTokens = details.reduce((total, item) => total + item.tokens, 0);
    let insertionPoint = projectRow;
    if (details.length) {
      const caption = createProjectDetailCaption();
      insertionPoint.after(caption);
      insertionPoint = caption;
    }
    details.forEach((item) => {
      const detail = createProjectDetail(item.modelIndex, item, projectTokens);
      insertionPoint.after(detail);
      insertionPoint = detail;
    });
    projectRow.setAttribute('aria-expanded', 'true');
    const arrow = projectRow.querySelector('.arrow');
    if (arrow) arrow.textContent = '▾';
    setToggleLabel(projectRow, true, rowName(projectRow, '.name'));
  }

  function collapseProject(projectRow) {
    removeProjectDetails(projectRow);
    projectRow.setAttribute('aria-expanded', 'false');
    const arrow = projectRow.querySelector('.arrow');
    if (arrow) arrow.textContent = '▸';
    setToggleLabel(projectRow, false, rowName(projectRow, '.name'));
  }

  function bindProjectRow(row) {
    row.tabIndex = 0;
    collapseProject(row);
    const toggle = () => {
      if (row.getAttribute('aria-expanded') === 'true') collapseProject(row);
      else expandProject(row);
    };
    row.addEventListener('click', toggle);
    bindKeyboardToggle(row, toggle);
  }

  document.querySelectorAll('.project-section .rank-line[data-project-index]').forEach(bindProjectRow);

  const toolMetadata = new Map();
  document.querySelectorAll('.tools-section .tool-row').forEach((row) => {
    const name = rowName(row, '.sub-agent');
    const plan = row.querySelector('.sub-plan');
    const since = row.querySelector('.sub-since');
    toolMetadata.set(row.dataset.agentId || `name:${name}`, {
      name,
      plan: plan ? plan.textContent : '',
      since: since ? since.textContent : '',
    });
  });

  function createToolRow(agent, item, total) {
    const row = document.createElement('div');
    row.className = 'tool-row';
    row.dataset.agentId = String(agent.id);
    const head = document.createElement('div');
    head.className = 'tool-head';
    appendTextSpan(head, 'sub-agent', String(agent.name));
    const metadata = toolMetadata.get(String(agent.id)) || toolMetadata.get(`name:${agent.name}`);
    if (metadata && metadata.plan) appendTextSpan(head, 'sub-plan', metadata.plan);
    if (metadata && metadata.since) appendTextSpan(head, 'sub-since', metadata.since);
    const share = total ? item.tokens / total * 100 : 0;
    appendShareBar(head, share, agentColors[agent.id] || '#8b8577');
    row.append(head);
    appendTextSpan(row, 'pct', `${share.toFixed(1)}%`, shareConfig.share);
    appendTextSpan(row, 'tokens', formatTokens(item.tokens), shareConfig.tokens);
    // _tools_body() 無條件顯示花費，這裡跟著一致
    appendTextSpan(row, 'cost', formatCost(item.cost, true), shareConfig.cost);
    return row;
  }

  function createSubscriptionOnlyRow(metadata) {
    const row = document.createElement('div');
    row.className = 'tool-row';
    const head = document.createElement('div');
    head.className = 'tool-head';
    appendTextSpan(head, 'sub-agent', metadata.name);
    if (metadata.plan) appendTextSpan(head, 'sub-plan', metadata.plan);
    if (metadata.since) appendTextSpan(head, 'sub-since', metadata.since);
    row.append(head);
    appendTextSpan(row, 'pct', '', shareConfig.share);
    appendTextSpan(row, 'tokens', '', shareConfig.tokens);
    appendTextSpan(row, 'cost', '', shareConfig.cost);
    return row;
  }

  function rebuildTools(summary) {
    const tools = document.querySelector('.tools-section .tools');
    if (!tools) return;
    tools.querySelectorAll('.tool-row').forEach((row) => row.remove());
    const byAgent = aggregateRows(summary.rows, 1);
    const entries = Object.entries(byAgent)
      .map(([agentIndex, item]) => ({agentIndex: Number(agentIndex), ...item}))
      .sort((left, right) => right.tokens - left.tokens || left.agentIndex - right.agentIndex);
    const usedIds = new Set();
    entries.forEach((item) => {
      const agent = cube.agents[item.agentIndex];
      if (!agent) return;
      usedIds.add(String(agent.id));
      tools.append(createToolRow(agent, item, summary.tokens));
    });
    toolMetadata.forEach((metadata, key) => {
      const matchedAgent = cube.agents.find((agent) => (
        String(agent.id) === key || `name:${agent.name}` === key
      ));
      if (!matchedAgent || !usedIds.has(String(matchedAgent.id))) {
        tools.append(createSubscriptionOnlyRow(metadata));
      }
    });
  }

  function rebuildModels(summary) {
    const list = document.querySelector('.model-section .rank-list');
    if (!list) return;
    const expanded = expandedModelIds();
    list.replaceChildren();
    const byAgent = aggregateRows(summary.rows, 1);
    const groups = Object.entries(byAgent)
      .map(([agentIndex, item]) => ({agentIndex: Number(agentIndex), ...item}))
      .sort((left, right) => right.tokens - left.tokens || left.agentIndex - right.agentIndex);
    groups.forEach((group) => {
      const agent = cube.agents[group.agentIndex];
      if (!agent) return;
      const groupRow = createRankRow(
        String(agent.name),
        group,
        summary.tokens,
        agentColors[agent.id] || '#8b8577',
        {rowClass: 'model-group', arrow: '▎', agentId: agent.id}
      );
      list.append(groupRow);
      const byModel = aggregateRows(
        summary.rows,
        2,
        (row) => Number(row[1]) === group.agentIndex
      );
      Object.entries(byModel)
        .map(([modelIndex, item]) => ({modelIndex: Number(modelIndex), ...item}))
        .sort((left, right) => right.tokens - left.tokens || left.modelIndex - right.modelIndex)
        .forEach((modelItem) => {
          const model = cube.models[modelItem.modelIndex];
          if (!model) return;
          list.append(createRankRow(
            String(model.name),
            modelItem,
            summary.tokens,
            modelColor(String(model.name)),
            {rowClass: 'model-child'}
          ));
        });
      bindModelGroup(groupRow, expanded.has(String(agent.id)));
    });
    if (!groups.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = `→ ${shareConfig.emptyModels}`;
      list.append(empty);
    }
  }

  function svgElement(name) {
    return document.createElementNS('http://www.w3.org/2000/svg', name);
  }

  function createDonut(projects, total) {
    if (!projects.length || total <= 0) return null;
    const shown = projects.slice(0, 6).map((project) => ({...project, other: false}));
    const rest = total - shown.reduce((sum, project) => sum + project.tokens, 0);
    if (rest > 0) shown.push({name: shareConfig.chartOther, tokens: rest, other: true});
    const wrap = document.createElement('div');
    wrap.className = 'donut-wrap';
    const svg = svgElement('svg');
    svg.setAttribute('class', 'donut');
    svg.setAttribute('viewBox', '0 0 160 160');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', shareConfig.projectSection);
    const circumference = 2 * Math.PI * 60;
    let offset = 0;
    const legend = document.createElement('ul');
    legend.className = 'donut-legend';
    shown.forEach((project, index) => {
      const fraction = project.tokens / total;
      const segmentLength = circumference * fraction;
      const color = project.other ? '#8b8577' : palette[index % palette.length];
      const circle = svgElement('circle');
      const attributes = {
        cx: '80', cy: '80', r: '60', fill: 'none', stroke: color,
        'stroke-width': '22',
        'stroke-dasharray': `${segmentLength.toFixed(2)} ${(circumference - segmentLength).toFixed(2)}`,
        'stroke-dashoffset': `${(-offset).toFixed(2)}`,
        transform: 'rotate(-90 80 80)',
      };
      Object.entries(attributes).forEach(([key, value]) => circle.setAttribute(key, value));
      svg.append(circle);
      offset += segmentLength;
      const item = document.createElement('li');
      const dot = appendTextSpan(item, 'dot', '');
      dot.style.background = color;
      appendTextSpan(item, 'lg-name', project.name);
      appendTextSpan(item, 'lg-pct', `${(fraction * 100).toFixed(1)}%`);
      legend.append(item);
    });
    const totalText = svgElement('text');
    Object.entries({x: '80', y: '77', class: 'donut-total', 'text-anchor': 'middle'})
      .forEach(([key, value]) => totalText.setAttribute(key, value));
    totalText.textContent = formatTokens(total);
    const subText = svgElement('text');
    Object.entries({x: '80', y: '95', class: 'donut-sub', 'text-anchor': 'middle'})
      .forEach(([key, value]) => subText.setAttribute(key, value));
    subText.textContent = 'tokens';
    svg.append(totalText, subText);
    wrap.append(svg, legend);
    return wrap;
  }

  function rebuildProjects(summary) {
    if (!projectSection) return;
    const list = projectSection.querySelector('.rank-list');
    const head = projectSection.querySelector('.rank-head');
    if (!list || !head) return;
    const oldDonut = projectSection.querySelector('.donut-wrap');
    if (oldDonut) oldDonut.remove();
    list.replaceChildren();
    const byProject = aggregateRows(summary.rows, 3);
    const projects = Object.entries(byProject)
      .map(([projectIndex, item]) => ({
        projectIndex: Number(projectIndex),
        name: String(cube.projects[Number(projectIndex)] || ''),
        ...item,
      }))
      .filter((item) => item.tokens > 0 || item.cost > 0)
      .sort((left, right) => right.tokens - left.tokens || left.projectIndex - right.projectIndex);
    const donut = createDonut(projects, summary.tokens);
    if (donut) projectSection.insertBefore(donut, head);
    projects.slice(0, 10).forEach((project, index) => {
      const row = createRankRow(
        project.name,
        project,
        summary.tokens,
        index < 6 ? palette[index] : '#8b8577',
        // _render_project_section() 無條件顯示花費，這裡跟著一致
        {projectIndex: project.projectIndex, costKnown: true}
      );
      list.append(row);
      bindProjectRow(row);
    });
    if (!projects.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = `→ ${shareConfig.emptyProjects}`;
      list.append(empty);
    }
  }

  function deltaText(current, previous, hasPrevious) {
    if (!hasPrevious || previous <= 0) return '';
    const pct = Math.round((current - previous) / previous * 100);
    return `${pct >= 0 ? '↑' : '↓'}${Math.abs(pct)}% ${shareConfig.vsPrevious}`;
  }

  function updateCard(key, value, subtitle) {
    const card = document.querySelector(`.card[data-card="${key}"]`);
    if (!card) return;
    const main = card.querySelector('b');
    if (main) main.textContent = value;
    let sub = card.querySelector('i');
    if (!subtitle) {
      if (sub) sub.remove();
      return;
    }
    if (!sub) {
      sub = document.createElement('i');
      card.append(sub);
    }
    sub.textContent = subtitle;
  }

  function updateSummary(summary) {
    const tokenDelta = deltaText(summary.tokens, summary.previousTokens, summary.hasPrevious);
    const tokenSub = [`≈ ${formatTokens(summary.tokens)}`, tokenDelta].filter(Boolean).join(' · ');
    const costDelta = deltaText(summary.cost, summary.previousCost, summary.hasPrevious);
    const unpriced = summary.unpricedTokens
      ? shareConfig.costUnpriced.replace('{tokens}', formatTokens(summary.unpricedTokens))
      : '';
    updateCard('tokens', formatInteger(summary.tokens), tokenSub);
    updateCard('cost', formatCost(summary.cost, true), [costDelta, unpriced].filter(Boolean).join(' · '));
    updateCard('active', `${summary.activeDays}/${summary.totalDays}`, '');
    updateCard('peak', summary.peakDate, `${formatTokens(summary.peakTokens)} ${shareConfig.tokens}`);
  }

  function updateNarrative(summary) {
    const node = document.querySelector('.narrative');
    if (!node || !shareConfig.narrative) return;
    node.textContent = shareConfig.narrative
      .replace('{tokens}', formatTokens(summary.tokens))
      .replace('{projects}', String(summary.narrativeProjects))
      .replace('{peak_date}', summary.peakDate)
      .replace('{peak_tokens}', formatTokens(summary.peakTokens))
      .replace('{top_model}', summary.topModel || shareConfig.unknown);
  }

  function updatePeriod(bounds) {
    const period = document.querySelector('[data-report-period]');
    if (period) period.textContent = `${bounds.from} -> ${bounds.to}`;
    const title = document.querySelector('.model-section .prompt-title');
    if (title) title.textContent = `${shareConfig.modelSection}  ${bounds.from} → ${bounds.to}`;
  }

  function replaceSectionBody(section, node) {
    const prompt = section.querySelector('.prompt');
    const rule = section.querySelector('.rule');
    Array.from(section.children).forEach((child) => {
      if (child !== prompt && child !== rule) child.remove();
    });
    section.append(node);
  }

  function weekIsInProgress(week, dateTo) {
    return isoWeekDate(week.year, week.week, 7) > dateTo;
  }

  function trendDelta(current, previous) {
    if (previous === 0) {
      if (current === 0) return {className: 'flat', label: '→ 0%'};
      return {className: 'up', label: `↗ ${shareConfig.trendMarkerNew}`};
    }
    const pct = Math.round((current - previous) / previous * 100);
    if (Math.abs(pct) <= 5) return {className: 'flat', label: '→ 0%'};
    if (pct > 0) return {className: 'up', label: `↗ +${pct}%`};
    return {className: 'down', label: `↘ ${pct}%`};
  }

  function trendSummaryText(weekly, dateTo) {
    const completed = weekly.length && weekIsInProgress(weekly[weekly.length - 1], dateTo)
      ? weekly.slice(0, -1)
      : weekly;
    if (completed.length < 2) return `→ ${shareConfig.trendCompareFirst}`;
    const current = completed[completed.length - 1].tokens;
    const previous = completed[completed.length - 2].tokens;
    if (previous === 0) {
      if (current === 0) return `→ ${shareConfig.trendCompareFlat}`;
      return `→ ${shareConfig.trendCompareNew}`;
    }
    const pct = Math.round((current - previous) / previous * 100);
    if (Math.abs(pct) <= 5) return `→ ${shareConfig.trendCompareFlat}`;
    if (pct > 0) {
      const ratio = (current / previous).toFixed(1);
      return `→ ${shareConfig.trendCompareUp.replace('{ratio}', ratio)}`;
    }
    return `→ ${shareConfig.trendCompareDown.replace('{pct}', String(Math.abs(pct)))}`;
  }

  function rebuildTrend(summary) {
    const section = document.querySelector('.trend-section');
    if (!section) return;
    const byDayTokens = {};
    const byDayCost = {};
    summary.rows.forEach((row) => {
      const day = cube.dates[Number(row[0])];
      if (!day) return;
      byDayTokens[day] = (byDayTokens[day] || 0) + rowTokens(row);
      byDayCost[day] = (byDayCost[day] || 0) + Number(row[8]);
    });
    const weeklyMap = {};
    const weeklyOrder = [];
    eachDate(summary.bounds.from, summary.bounds.to, (date, key) => {
      const iso = isoWeek(date);
      const bucketKey = `${iso.year}-W${String(iso.week).padStart(2, '0')}`;
      if (!Object.prototype.hasOwnProperty.call(weeklyMap, bucketKey)) {
        weeklyMap[bucketKey] = {year: iso.year, week: iso.week, tokens: 0, cost: 0};
        weeklyOrder.push(bucketKey);
      }
      const bucket = weeklyMap[bucketKey];
      bucket.tokens += byDayTokens[key] || 0;
      bucket.cost += byDayCost[key] || 0;
    });
    const weekly = weeklyOrder.map((key) => weeklyMap[key]);
    if (!weekly.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = `→ ${shareConfig.emptyDaily}`;
      replaceSectionBody(section, empty);
      return;
    }
    const dateTo = parseDate(summary.bounds.to);
    const rangeStart = parseDate(summary.bounds.from);
    const maxTokens = weekly.reduce((max, week) => Math.max(max, week.tokens), 0);
    const wrap = document.createElement('div');
    wrap.className = 'trend';
    weekly.forEach((week, idx) => {
      const isoStart = isoWeekDate(week.year, week.week, 1);
      const isoEnd = isoWeekDate(week.year, week.week, 7);
      const weekStart = rangeStart && isoStart < rangeStart ? rangeStart : isoStart;
      const weekEnd = dateTo && isoEnd > dateTo ? dateTo : isoEnd;
      const tooltip = [
        `${formatDate(weekStart)} – ${formatDate(weekEnd)}`,
        formatTokens(week.tokens),
        formatCost(week.cost, true),
      ].join(' · ');
      const row = document.createElement('div');
      row.className = 'trend-row';
      row.setAttribute('title', tooltip);
      appendTextSpan(row, 'week', `W${week.week}`);
      let width = 0;
      if (week.tokens > 0 && maxTokens > 0) {
        width = Math.max(2, Math.min(100, week.tokens / maxTokens * 100));
      }
      const bar = document.createElement('div');
      bar.className = 'trend-bar';
      bar.setAttribute('aria-hidden', 'true');
      const fill = document.createElement('div');
      fill.style.width = `${width.toFixed(2)}%`;
      bar.append(fill);
      row.append(bar);
      const tokensNode = document.createElement('em');
      tokensNode.textContent = formatTokens(week.tokens);
      row.append(tokensNode);
      const delta = document.createElement('span');
      if (idx === weekly.length - 1 && dateTo && weekIsInProgress(week, dateTo)) {
        delta.className = 'delta flat';
        delta.textContent = shareConfig.trendWeekInProgress;
      } else if (idx > 0) {
        const change = trendDelta(week.tokens, weekly[idx - 1].tokens);
        delta.className = `delta ${change.className}`;
        delta.textContent = change.label;
      } else {
        delta.className = 'delta flat';
      }
      row.append(delta);
      wrap.append(row);
    });
    const summaryNode = document.createElement('div');
    summaryNode.className = 'trend-summary';
    summaryNode.textContent = trendSummaryText(weekly, dateTo);
    wrap.append(summaryNode);
    replaceSectionBody(section, wrap);
  }

  function cacheHitRate(item) {
    const context = item.input + item.cacheWrite + item.cacheRead;
    return context === 0 ? null : item.cacheRead / context * 100;
  }

  function rebuildComposition(summary) {
    const section = document.querySelector('.composition-section');
    if (!section) return;
    let input = 0;
    let output = 0;
    let cacheWrite = 0;
    let cacheRead = 0;
    summary.rows.forEach((row) => {
      input += Number(row[4]);
      output += Number(row[5]);
      cacheWrite += Number(row[6]);
      cacheRead += Number(row[7]);
    });
    const total = input + output + cacheWrite + cacheRead;
    if (total <= 0) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    const lists = section.querySelectorAll('.rank-list');
    if (lists.length < 2) return;
    const parts = [
      {key: 'input', name: shareConfig.compositionInput, tokens: input, color: palette[0]},
      {key: 'output', name: shareConfig.compositionOutput, tokens: output, color: palette[1]},
      {key: 'cache_write', name: shareConfig.compositionCacheWrite, tokens: cacheWrite, color: palette[2]},
      {key: 'cache_read', name: shareConfig.compositionCacheRead, tokens: cacheRead, color: palette[3]},
    ]
      .filter((part) => part.tokens > 0)
      .sort((left, right) => right.tokens - left.tokens);
    lists[0].replaceChildren();
    parts.forEach((part) => {
      const share = part.tokens / total * 100;
      const row = document.createElement('div');
      row.className = 'rank-line';
      appendTextSpan(row, 'arrow', '→');
      const nameNode = appendTextSpan(row, 'name', part.name);
      appendShareBar(nameNode, share, part.color);
      appendTextSpan(row, 'pct', `${share.toFixed(1)}%`, shareConfig.share);
      appendTextSpan(row, 'tokens', formatTokens(part.tokens), shareConfig.tokens);
      lists[0].append(row);
    });
    const byAgent = {};
    summary.rows.forEach((row) => {
      const key = String(row[1]);
      if (!Object.prototype.hasOwnProperty.call(byAgent, key)) {
        byAgent[key] = {input: 0, cacheWrite: 0, cacheRead: 0};
      }
      const item = byAgent[key];
      item.input += Number(row[4]);
      item.cacheWrite += Number(row[6]);
      item.cacheRead += Number(row[7]);
    });
    const agents = Object.entries(byAgent)
      .map(([agentIndex, item]) => ({
        agentIndex: Number(agentIndex),
        rate: cacheHitRate(item),
      }))
      .sort((left, right) => (
        Number(left.rate === null) - Number(right.rate === null)
        || (right.rate || 0) - (left.rate || 0)
        || left.agentIndex - right.agentIndex
      ));
    lists[1].replaceChildren();
    agents.forEach((item) => {
      const agent = cube.agents[item.agentIndex];
      if (!agent) return;
      const row = document.createElement('div');
      row.className = 'rank-line';
      appendTextSpan(row, 'arrow', '→');
      const nameNode = appendTextSpan(row, 'name', displayName(agent.name));
      appendShareBar(nameNode, item.rate || 0, palette[3]);
      appendTextSpan(
        row,
        'pct',
        item.rate === null ? '—' : `${item.rate.toFixed(1)}%`,
        shareConfig.compositionHitRate
      );
      lists[1].append(row);
    });
  }

  function appendCell(row, text, className) {
    const cell = document.createElement('td');
    if (className) cell.className = className;
    cell.textContent = text;
    row.append(cell);
    return cell;
  }

  function rebuildSessions(summary) {
    const section = document.querySelector('.session-section');
    if (!section) return;
    const matched = sessions
      .filter((session) => {
        const day = cube.dates[Number(session.date_idx)];
        return Boolean(day && day >= summary.bounds.from && day <= summary.bounds.to);
      })
      .sort((left, right) => Number(right.cost) - Number(left.cost) || 0)
      .slice(0, 5);
    if (!matched.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = `→ ${shareConfig.emptySessions}`;
      replaceSectionBody(section, empty);
      return;
    }
    const maxTokens = matched.reduce((max, session) => Math.max(max, Number(session.tokens) || 0), 0);
    const wrap = document.createElement('div');
    wrap.className = 'table-wrap';
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    [
      shareConfig.rank, shareConfig.startTime, shareConfig.project, shareConfig.model,
      shareConfig.duration, shareConfig.tokens, shareConfig.cost,
    ].forEach((label) => {
      const cell = document.createElement('th');
      cell.textContent = label;
      headerRow.append(cell);
    });
    thead.append(headerRow);
    const tbody = document.createElement('tbody');
    matched.forEach((session, index) => {
      const row = document.createElement('tr');
      const project = cube.projects[Number(session.project_idx)];
      const model = cube.models[Number(session.model_idx)];
      const modelName = displayName(model ? model.name : '');
      const tokens = Number(session.tokens) || 0;
      appendCell(row, `#${index + 1}`);
      appendCell(row, String(session.start_time || ''));
      appendCell(row, displayName(project), 'name');
      appendCell(row, modelName);
      appendCell(row, formatDuration(session.duration_min));
      const tokenCell = appendCell(row, formatTokens(tokens), 'tokens-cell');
      const share = maxTokens ? tokens / maxTokens * 100 : 0;
      appendShareBar(tokenCell, share, modelColor(modelName));
      appendCell(row, formatCost(Number(session.cost) || 0, true));
      tbody.append(row);
    });
    table.append(thead, tbody);
    wrap.append(table);
    replaceSectionBody(section, wrap);
  }

  function csvField(value) {
    const text = String(value);
    if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
    return text;
  }

  function csvCost(value, known) {
    if (!known) return '—';
    return (value > 0 && value < 1) ? value.toFixed(4) : value.toFixed(2);
  }

  function buildCsv(maskProjects) {
    const bounds = activeBounds || normalizeBounds(
      cube.dates[0], cube.dates[cube.dates.length - 1]
    );
    const summary = bounds ? summarizeRange(bounds.from, bounds.to) : null;
    const lines = ['type,name,share_pct,tokens,cost_usd'];
    if (!summary) return `${lines[0]}\r\n`;
    const total = summary.tokens;
    const projects = Object.entries(aggregateRows(summary.rows, 3))
      .map(([projectIndex, item]) => ({
        projectIndex: Number(projectIndex),
        name: String(cube.projects[Number(projectIndex)] || ''),
        ...item,
      }))
      .filter((item) => item.tokens > 0 || item.cost > 0)
      .sort((left, right) => right.tokens - left.tokens || left.projectIndex - right.projectIndex)
      .slice(0, 10);
    projects.forEach((project, index) => {
      const name = maskProjects ? `Project ${index + 1}` : displayName(project.name);
      const share = total ? project.tokens / total * 100 : 0;
      lines.push([
        'project', csvField(name), share.toFixed(1),
        String(Math.round(project.tokens)), csvCost(project.cost, true),
      ].join(','));
    });
    const models = Object.entries(aggregateRows(summary.rows, 2))
      .map(([modelIndex, item]) => ({modelIndex: Number(modelIndex), ...item}))
      .filter((item) => item.tokens > 0 || item.cost > 0)
      .sort((left, right) => right.tokens - left.tokens || left.modelIndex - right.modelIndex);
    models.forEach((item) => {
      const model = cube.models[item.modelIndex];
      const name = displayName(model ? model.name : '');
      const share = total ? item.tokens / total * 100 : 0;
      lines.push([
        'model', csvField(name), share.toFixed(1),
        String(Math.round(item.tokens)),
        csvCost(item.cost, Boolean(model && model.cost_known)),
      ].join(','));
    });
    return `${lines.join('\r\n')}\r\n`;
  }

  function applyBounds(bounds) {
    const summary = summarizeRange(bounds.from, bounds.to);
    if (!summary) return null;
    activeBounds = summary.bounds;
    updateSummary(summary);
    updateNarrative(summary);
    rebuildTools(summary);
    rebuildProjects(summary);
    rebuildModels(summary);
    rebuildTrend(summary);
    rebuildComposition(summary);
    rebuildSessions(summary);
    updatePeriod(summary.bounds);
    return summary;
  }

  window.usageReportFilter.applyBounds = applyBounds;
  window.usageReportFilter.buildCsv = buildCsv;

  const dateFilter = document.querySelector('[data-date-filter]');
  if (!dateFilter || !cube.dates.length) return;
  const fromInput = dateFilter.querySelector('[data-date-from]');
  const toInput = dateFilter.querySelector('[data-date-to]');
  const shortcutButtons = Array.from(dateFilter.querySelectorAll('[data-range]'));

  function selectShortcut(key) {
    const bounds = rangeBounds(key) || rangeBounds('all');
    if (!bounds) return;
    fromInput.value = bounds.from;
    toInput.value = bounds.to;
    shortcutButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.range === key));
    });
    applyBounds(bounds);
  }

  shortcutButtons.forEach((button) => {
    button.addEventListener('click', () => selectShortcut(button.dataset.range));
  });

  function applyManualRange(event) {
    shortcutButtons.forEach((button) => button.setAttribute('aria-pressed', 'false'));
    let bounds = normalizeBounds(fromInput.value, toInput.value);
    if (!bounds) return;
    if (fromInput.value > toInput.value) {
      if (event && event.target === fromInput) bounds = {from: bounds.to, to: bounds.to};
      else bounds = {from: bounds.from, to: bounds.from};
    }
    fromInput.value = bounds.from;
    toInput.value = bounds.to;
    applyBounds(bounds);
  }
  fromInput.addEventListener('change', applyManualRange);
  toInput.addEventListener('change', applyManualRange);

  const defaultRange = document.body.dataset.defaultRange || 'all';
  selectShortcut(['today', 'last7', 'last30', 'month', 'all'].includes(defaultRange)
    ? defaultRange
    : 'all');
})();
"""
