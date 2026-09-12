# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Front-end report filtering and drill-down behavior."""

from __future__ import annotations


REPORT_FILTER_JS = """(() => {
  const cubeNode = document.querySelector('#usage-cube-data');
  if (!cubeNode) return;

  let cube;
  try {
    cube = JSON.parse(cubeNode.textContent);
  } catch (_) {
    return;
  }

  function aggregateRows(rows, groupIndex, rowFilter = null) {
    const result = {};
    rows.forEach((row) => {
      if (rowFilter && !rowFilter(row)) return;
      const key = String(row[groupIndex]);
      if (!Object.prototype.hasOwnProperty.call(result, key)) {
        result[key] = {tokens: 0, cost: 0, costKnown: true};
      }
      const item = result[key];
      item.tokens += Number(row[4]) + Number(row[5]) + Number(row[6]) + Number(row[7]);
      item.cost += Number(row[8]);
      const model = cube.models[Number(row[2])];
      item.costKnown = item.costKnown && Boolean(model && model.cost_known);
    });
    return result;
  }

  window.usageReportFilter = {cube, aggregateRows};

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

  const modelGroups = Array.from(
    document.querySelectorAll('.model-section .rank-line.model-group[data-agent-id]')
  );
  let expandedAgentIds = new Set();
  try {
    const saved = JSON.parse(window.localStorage.getItem('usage-report-model-groups') || '[]');
    if (Array.isArray(saved)) {
      expandedAgentIds = new Set(saved.filter((value) => typeof value === 'string'));
    }
  } catch (_) {
    expandedAgentIds = new Set();
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

  function saveModelGroups() {
    const expanded = modelGroups
      .filter((group) => group.getAttribute('aria-expanded') === 'true')
      .map((group) => group.dataset.agentId);
    try {
      window.localStorage.setItem('usage-report-model-groups', JSON.stringify(expanded));
    } catch (_) {
      // Keep the state for this page when privacy settings deny storage.
    }
  }

  modelGroups.forEach((group) => {
    const agentId = group.dataset.agentId;
    group.tabIndex = 0;
    applyModelGroup(group, expandedAgentIds.has(agentId));
    const toggle = () => {
      applyModelGroup(group, group.getAttribute('aria-expanded') !== 'true');
      saveModelGroups();
    };
    group.addEventListener('click', toggle);
    bindKeyboardToggle(group, toggle);
  });

  function formatTokens(value) {
    if (value >= 999950000) return `${(value / 1000000000).toFixed(2)}B`;
    if (value >= 999950) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return String(value);
  }

  function formatCost(value, known) {
    if (!known) return '—';
    const digits = value > 0 && value < 1 ? 4 : 2;
    return `$${value.toLocaleString('en-US', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })}`;
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

  const projectSection = document.querySelector('.project-section');
  const projectHeadCells = projectSection
    ? Array.from(projectSection.querySelectorAll('.rank-head > span'))
    : [];
  const tokensLabel = projectHeadCells[3] ? projectHeadCells[3].textContent : '';
  const costLabel = projectHeadCells[4] ? projectHeadCells[4].textContent : '';

  // 明細列的佔比分母是「這個專案」，專案列自己的佔比分母是全體。共用的表頭
  // 只有一格，改它會把專案列那幾行一起標錯，所以基準寫在展開區塊自己的標題列上。
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
    const bar = document.createElement('span');
    bar.className = 'share-bar';
    bar.setAttribute('aria-hidden', 'true');
    const fill = document.createElement('span');
    fill.style.width = `${Math.max(0, Math.min(100, share))}%`;
    fill.style.background = modelColor(modelName);
    bar.append(fill);
    name.append(bar);
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
      (row) => Number(row[3]) === projectIndex
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

  document.querySelectorAll('.project-section .rank-line[data-project-index]').forEach((row) => {
    row.tabIndex = 0;
    collapseProject(row);
    const toggle = () => {
      if (row.getAttribute('aria-expanded') === 'true') collapseProject(row);
      else expandProject(row);
    };
    row.addEventListener('click', toggle);
    bindKeyboardToggle(row, toggle);
  });
})();
"""
