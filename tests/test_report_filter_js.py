from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ui.report_filter import REPORT_FILTER_JS

NODE = shutil.which("node")


NODE_HARNESS = r"""
const assert = require('node:assert/strict');
const REPORT_FILTER_JS = __REPORT_FILTER_JS__;

class Element {
  constructor(tagName = 'div', className = '', text = '') {
    this.tagName = tagName;
    this.className = className;
    this._text = text;
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.listeners = {};
    this.hidden = false;
    this.tabIndex = -1;
    this.value = '';
  }
  get classList() {
    return {contains: (name) => this.className.split(/\s+/).includes(name)};
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join('');
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get nextElementSibling() {
    if (!this.parentNode) return null;
    const index = this.parentNode.children.indexOf(this);
    return this.parentNode.children[index + 1] || null;
  }
  append(...nodes) {
    nodes.forEach((node) => {
      node.parentNode = this;
      this.children.push(node);
    });
  }
  replaceChildren(...nodes) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    this.append(...nodes);
  }
  insertBefore(node, reference) {
    const index = this.children.indexOf(reference);
    node.parentNode = this;
    this.children.splice(index < 0 ? this.children.length : index, 0, node);
  }
  after(node) {
    const index = this.parentNode.children.indexOf(this);
    node.parentNode = this.parentNode;
    this.parentNode.children.splice(index + 1, 0, node);
  }
  remove() {
    const index = this.parentNode.children.indexOf(this);
    this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') this.className = String(value);
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  fire(type, key = '') {
    let prevented = false;
    this.listeners[type]({key, target: this, preventDefault: () => { prevented = true; }});
    return prevented;
  }
  matches(selector) {
    if (/^[a-z]+$/.test(selector)) return this.tagName === selector;
    if (/^\.[\w-]+$/.test(selector)) return this.classList.contains(selector.slice(1));
    if (selector === '[data-range]') return this.dataset.range !== undefined;
    if (selector === '[data-date-from]') return this.dataset.dateFrom !== undefined;
    if (selector === '[data-date-to]') return this.dataset.dateTo !== undefined;
    if (selector === '.arrow') return this.classList.contains('arrow');
    if (selector === '.name') return this.classList.contains('name');
    return false;
  }
  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }
  querySelector(selector) {
    if (selector === '.rank-line[data-project-index][aria-expanded="true"]') {
      return this.descendants().find((node) =>
        node.classList.contains('rank-line') &&
        node.dataset.projectIndex !== undefined &&
        node.getAttribute('aria-expanded') === 'true'
      ) || null;
    }
    return this.descendants().find((node) => node.matches(selector)) || null;
  }
  querySelectorAll(selector) {
    if (selector === '.rank-head > span') {
      const head = this.descendants().find((node) => node.classList.contains('rank-head'));
      return head ? head.children.filter((node) => node.tagName === 'span') : [];
    }
    return this.descendants().filter((node) => node.matches(selector));
  }
}

function span(className, text = '') {
  return new Element('span', className, text);
}

function rankRow(className, name, data = {}) {
  const row = new Element('div', className);
  row.dataset = {...data};
  row.append(span('arrow', '→'), span('name', name), span('pct'), span('tokens'), span('cost'));
  return row;
}

function makeEnvironment(
  cube, storageData = {}, storageThrows = false, sessionRows = [], withDateFilter = false
) {
  const cubeNode = new Element('script');
  cubeNode.textContent = JSON.stringify(cube);
  const sessionNode = new Element('script');
  sessionNode.textContent = JSON.stringify(sessionRows);

  const groupList = new Element('div', 'rank-list');
  const groups = [
    rankRow('rank-line model-group', 'Claude Code', {agentId: 'claude-code'}),
    rankRow('rank-line model-group', 'Codex', {agentId: 'codex'}),
    rankRow('rank-line model-group', 'Antigravity', {agentId: 'antigravity'}),
    rankRow('rank-line model-group', 'Grok', {agentId: 'grok'}),
  ];
  const groupChildren = [
    rankRow('rank-line model-child', 'claude-test'),
    rankRow('rank-line model-child', 'gpt-test'),
    rankRow('rank-line model-child', 'gemini-test'),
    rankRow('rank-line model-child', 'grok-test'),
  ];
  groups.forEach((group, index) => groupList.append(group, groupChildren[index]));

  const projectHead = new Element('div', 'rank-head');
  projectHead.append(
    span('', ''), span('', 'Project'), span('', 'Share'), span('', 'Tokens'), span('', 'Cost')
  );
  const projectList = new Element('div', 'rank-list');
  const projectRows = cube.projects.map((name, index) =>
    rankRow('rank-line', name, {projectIndex: String(index)})
  );
  projectList.append(...projectRows);
  const projectSection = new Element('section', 'project-section');
  projectSection.append(projectHead, projectList);

  const tools = new Element('div', 'tools');
  const toolRows = cube.agents.map((agent) => {
    const row = new Element('div', 'tool-row');
    row.dataset.agentId = agent.id;
    const head = new Element('div', 'tool-head');
    head.append(span('sub-agent', agent.name));
    row.append(head, span('pct'), span('tokens'), span('cost'));
    return row;
  });
  tools.append(...toolRows);

  const trendSection = new Element('section', 'trend-section');
  trendSection.append(
    new Element('div', 'prompt'),
    new Element('div', 'rule'),
    new Element('div', 'trend'),
  );
  const compositionSection = new Element('section', 'composition-section');
  compositionSection.append(
    new Element('div', 'prompt'),
    new Element('div', 'rule'),
    new Element('div', 'rank-list'),
    new Element('p', 'composition-hint'),
    new Element('div', 'rank-head'),
    new Element('div', 'rank-list'),
  );
  const sessionSection = new Element('section', 'session-section');
  sessionSection.append(
    new Element('div', 'prompt'),
    new Element('div', 'rule'),
    new Element('div', 'table-wrap'),
  );
  const cards = {};
  ['tokens', 'cost', 'sessions', 'messages', 'active', 'peak'].forEach((key) => {
    const card = new Element('div', 'card');
    card.dataset.card = key;
    card.append(new Element('b'), new Element('i'));
    cards[key] = card;
  });
  const period = new Element('span');
  const modelTitle = new Element('span', 'prompt-title');
  const dateFilter = new Element('div', 'date-filter');
  const fromInput = new Element('input');
  fromInput.dataset.dateFrom = '';
  const toInput = new Element('input');
  toInput.dataset.dateTo = '';
  const shortcutButtons = ['today', 'last7', 'last30', 'month', 'all'].map((key) => {
    const button = new Element('button');
    button.dataset.range = key;
    return button;
  });
  dateFilter.append(...shortcutButtons, fromInput, toInput);

  const storage = {
    getItem(key) {
      if (storageThrows) throw new Error('storage read denied');
      return storageData[key] ?? null;
    },
    setItem(key, value) {
      if (storageThrows) throw new Error('storage write denied');
      storageData[key] = value;
    },
  };
  global.window = {localStorage: storage};
  global.shareConfig = {
    collapse: 'Collapse',
    expand: 'Expand',
    chartOther: 'Other',
    cost: 'Cost',
    costUnpriced: '{tokens} tokens have no public pricing',
    emptyModels: 'No models',
    emptyProjects: 'No projects',
    modelSection: 'Most-used models',
    projectSection: 'Projects',
    projectShare: 'Share of project',
    share: 'Share',
    tokens: 'Tokens',
    vsPrevious: 'vs previous period',
    compositionCacheRead: 'Cache read',
    compositionCacheWrite: 'Cache write',
    compositionHitRate: 'Cache hit rate',
    compositionInput: 'Input',
    compositionOutput: 'Output',
    duration: 'Duration',
    emptyDaily: 'No daily usage in this period',
    emptySessions: 'No sessions to list in this period',
    model: 'Model',
    project: 'Project',
    rank: 'Rank',
    startTime: 'Start time',
    trendCompareDown: 'This week dropped {pct}% vs last week.',
    trendCompareFirst: 'First week of this period.',
    trendCompareFlat: 'Roughly flat vs last week.',
    trendCompareNew: 'This week has new usage vs last week.',
    trendCompareUp: 'This week is {ratio}× of last week.',
    trendMarkerNew: 'new',
    trendWeekInProgress: 'in progress',
    unknown: 'Unknown',
  };
  global.document = {
    querySelector(selector) {
      if (selector === '#usage-cube-data') return cubeNode;
      if (selector === '#usage-session-data') return sessionNode;
      if (selector === '.project-section') return projectSection;
      if (selector === '.tools-section .tools') return tools;
      if (selector === '.model-section .rank-list') return groupList;
      if (selector === '[data-report-period]') return period;
      if (selector === '.model-section .prompt-title') return modelTitle;
      if (selector === '.trend-section') return trendSection;
      if (selector === '.composition-section') return compositionSection;
      if (selector === '.session-section') return sessionSection;
      if (selector === '[data-date-filter]') return withDateFilter ? dateFilter : null;
      const cardMatch = /^\.card\[data-card="([^"]+)"\]$/.exec(selector);
      if (cardMatch) return cards[cardMatch[1]] || null;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === '.model-section .rank-line.model-group[data-agent-id]') {
        return groupList.children.filter((row) => row.classList.contains('model-group'));
      }
      if (selector === '.project-section .rank-line[data-project-index]') {
        return projectList.children.filter((row) => row.dataset.projectIndex !== undefined);
      }
      if (selector === '.project-section .rank-line .name') {
        return projectList.children
          .filter((row) => row.dataset.projectIndex !== undefined)
          .map((row) => row.querySelector('.name'));
      }
      if (selector === '.tools-section .tool-row') return toolRows;
      return [];
    },
    createElement(tagName) { return new Element(tagName); },
    createElementNS(_namespace, tagName) { return new Element(tagName); },
    body: {dataset: {}},
  };
  return {
    groups, groupChildren, groupList, projectHead, projectList, projectRows,
    tools, cards, period, modelTitle, dateFilter, fromInput, toInput,
    shortcutButtons, storageData, trendSection, compositionSection, sessionSection,
  };
}

function run(environment) {
  eval(REPORT_FILTER_JS);
  return environment;
}

global.document = {querySelector: () => null};
global.window = {};
assert.doesNotThrow(() => eval(REPORT_FILTER_JS));

const cube = {
  dates: ['2026-05-21'],
  agents: [{id: 'claude-code', name: 'Claude Code'}, {id: 'codex', name: 'Codex'}],
  models: [{name: 'claude-test', cost_known: true}, {name: 'gpt-test', cost_known: false}],
  projects: ['usage'],
  rows: [
    [0, 0, 0, 0, 40, 10, 5, 5, 1.25, 1],
    [0, 1, 1, 0, 20, 10, 5, 5, 9.99, 1],
  ],
};
const saved = {};
let env = run(makeEnvironment(cube, saved));
const iso = window.usageReportFilter.isoWeek;
assert.deepEqual(iso(new Date(Date.UTC(2026, 0, 1))), {year: 2026, week: 1});
assert.deepEqual(iso(new Date(Date.UTC(2025, 11, 29))), {year: 2026, week: 1});
assert.deepEqual(iso(new Date(Date.UTC(2025, 11, 28))), {year: 2025, week: 52});
assert.deepEqual(iso(new Date(Date.UTC(2027, 0, 1))), {year: 2026, week: 53});
assert.deepEqual(window.usageReportFilter.aggregateRows(cube.rows, 2, null), {
  0: {tokens: 60, cost: 1.25, costKnown: true},
  1: {tokens: 40, cost: 9.99, costKnown: false},
});
assert.deepEqual(env.groupChildren.map((row) => row.hidden), [true, true, true, true]);
assert.equal(env.groups[0].getAttribute('aria-expanded'), 'false');
assert.equal(env.groups[0].querySelector('.arrow').textContent, '▸');
env.groups[0].fire('click');
assert.equal(env.groupChildren[0].hidden, false);
assert.deepEqual(JSON.parse(saved['usage-report-model-groups']), ['claude-code']);

env = run(makeEnvironment(cube, saved));
assert.deepEqual(env.groupChildren.map((row) => row.hidden), [false, true, true, true]);
assert.equal(env.groups[1].fire('keydown', ' '), true);
assert.equal(env.groupChildren[1].hidden, false);
env.projectRows[0].fire('keydown', 'Enter');
const caption = env.projectList.children.find((row) =>
  row.classList.contains('project-detail-caption')
);
assert.equal(caption.textContent, 'Share of project');
const details = env.projectList.children.filter((row) =>
  row.classList.contains('project-model-detail') &&
  !row.classList.contains('project-detail-caption')
);
assert.equal(details.length, 2);
assert.deepEqual(details.map((row) => row.children[1].textContent), ['claude-test', 'gpt-test']);
assert.deepEqual(details.map((row) => row.children[2].textContent), ['60.0%', '40.0%']);
assert.deepEqual(details.map((row) => row.children[4].textContent), ['$1.25', '—']);
// 共用表頭只有一格，改它會把專案列自己的「佔全體」百分比一起標錯，所以基準
// 寫在展開區塊自己的標題列上，表頭全程維持不變。
assert.equal(env.projectHead.children[2].textContent, 'Share');
assert.equal(document.querySelectorAll('.project-section .rank-line .name').length, 1);
env.projectRows[0].fire('click');
assert.equal(env.projectList.children.length, 1);
assert.equal(env.projectHead.children[2].textContent, 'Share');
console.log(
  'interaction: four groups collapsed; click, keyboard, reload, project shares 100.0%; mask safe'
);

const singleCube = {
  dates: ['2026-05-21'],
  agents: [{id: 'claude-code', name: 'Claude Code'}],
  models: [{name: 'unknown', cost_known: false}],
  projects: ['single'],
  rows: [[0, 0, 0, 0, 1, 2, 3, 4, 7.5, 1]],
};
env = run(makeEnvironment(singleCube, {}, true));
env.groups[0].fire('click');
env.projectRows[0].fire('click');
const singleDetail = env.projectList.children[2];
assert.equal(singleDetail.children[2].textContent, '100.0%');
assert.equal(singleDetail.children[3].textContent, '10');
assert.equal(singleDetail.children[4].textContent, '—');
console.log('single row/model: 100.0%, 10 tokens, unpriced dash; storage errors safe');

const unpricedCube = {
  dates: ['2026-05-21'],
  agents: [],
  models: [{name: 'unknown-a', cost_known: false}, {name: 'unknown-b', cost_known: false}],
  projects: ['unpriced'],
  rows: [
    [0, 0, 0, 0, 3, 0, 0, 0, 2, 1],
    [0, 0, 1, 0, 1, 0, 0, 0, 4, 1],
  ],
};
env = run(makeEnvironment(unpricedCube));
env.projectRows[0].fire('click');
const unpricedDetails = env.projectList.children.slice(2);
assert.deepEqual(unpricedDetails.map((row) => row.children[4].textContent), ['—', '—']);
assert.deepEqual(unpricedDetails.map((row) => row.children[2].textContent), ['75.0%', '25.0%']);
console.log('all unpriced: two dashes; shares 75.0% + 25.0%');

const rangeCube = {
  dates: ['2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04', '2026-09-05'],
  agents: [{id: 'claude-code', name: 'Claude Code'}, {id: 'codex', name: 'Codex'}],
  models: [{name: 'claude-test', cost_known: true}, {name: 'gpt-test', cost_known: true}],
  projects: ['alpha', 'beta'],
  rows: [
    [0, 0, 0, 0, 10, 0, 0, 0, 1, 1],
    [1, 0, 0, 0, 20, 0, 0, 0, 2, 2],
    [2, 1, 1, 1, 30, 0, 0, 0, 3, 3],
    [4, 0, 0, 0, 50, 0, 0, 0, 5, 5],
  ],
};
const rangeEnv = run(makeEnvironment(rangeCube, {}, false, [
  {date_idx: 1}, {date_idx: 2}, {date_idx: 4},
]));
const rangeSummary = window.usageReportFilter.summarizeRange('2026-09-02', '2026-09-03');
assert.equal(rangeSummary.tokens, 50);
assert.equal(rangeSummary.cost, 5);
assert.equal(rangeSummary.messages, 5);
assert.equal(rangeSummary.sessions, 2);
assert.equal(rangeSummary.previousTokens, 10);
assert.equal(rangeSummary.previousCost, 1);
for (const groupIndex of [1, 2, 3]) {
  const grouped = window.usageReportFilter.aggregateRows(rangeSummary.rows, groupIndex);
  assert.equal(Object.values(grouped).reduce((sum, item) => sum + item.tokens, 0), 50);
  assert.equal(Object.values(grouped).reduce((sum, item) => sum + item.cost, 0), 5);
}
rangeEnv.groups[0].fire('click');
window.usageReportFilter.applyBounds(rangeSummary.bounds);
assert.equal(rangeEnv.cards.tokens.querySelector('b').textContent, '50');
assert.equal(rangeEnv.cards.cost.querySelector('b').textContent, '$5.00');
const sumVisible = (rows, className) => rows
  .map((row) => row.querySelector(className).textContent)
  .reduce((sum, value) => sum + Number(value.replace('$', '')), 0);
const currentToolRows = rangeEnv.tools.children.filter((row) => row.classList.contains('tool-row'));
assert.equal(sumVisible(currentToolRows, '.tokens'), 50);
assert.equal(sumVisible(currentToolRows, '.cost'), 5);
const currentGroups = rangeEnv.groupList.children
  .filter((row) => row.classList.contains('model-group'));
assert.equal(sumVisible(currentGroups, '.tokens'), 50);
assert.equal(sumVisible(currentGroups, '.cost'), 5);
const currentProjects = rangeEnv.projectList.children
  .filter((row) => row.dataset.projectIndex !== undefined);
assert.equal(sumVisible(currentProjects, '.tokens'), 50);
assert.equal(sumVisible(currentProjects, '.cost'), 5);
assert.equal(
  rangeEnv.projectList.parentNode.querySelector('.donut-total').textContent,
  '50'
);
const rebuiltClaude = currentGroups.find((row) => row.dataset.agentId === 'claude-code');
assert.equal(rebuiltClaude.getAttribute('aria-expanded'), 'true');
assert.equal(rebuiltClaude.nextElementSibling.hidden, false);
const empty = window.usageReportFilter.summarizeRange('2026-09-04', '2026-09-04');
assert.deepEqual([empty.tokens, empty.cost, empty.activeDays, empty.totalDays], [0, 0, 0, 1]);
const reversed = window.usageReportFilter.summarizeRange('2026-09-05', '2026-09-03');
assert.deepEqual(reversed.bounds, {from: '2026-09-03', to: '2026-09-05'});
const clamped = window.usageReportFilter.summarizeRange('2020-01-01', '2030-01-01');
assert.deepEqual(clamped.bounds, {from: '2026-09-01', to: '2026-09-05'});
const firstDay = window.usageReportFilter.summarizeRange('2026-09-01', '2026-09-01');
assert.equal(firstDay.hasPrevious, false);
const boundaryOutput = JSON.stringify({rangeSummary, empty, reversed, clamped, firstDay});
assert.equal(boundaryOutput.includes('NaN'), false);
assert.equal(boundaryOutput.includes('Infinity'), false);
const dateEnv = run(makeEnvironment(rangeCube, {}, false, [], true));
assert.deepEqual([dateEnv.fromInput.value, dateEnv.toInput.value], ['2026-09-01', '2026-09-05']);
assert.equal(dateEnv.shortcutButtons[4].getAttribute('aria-pressed'), 'true');
dateEnv.shortcutButtons[0].fire('click');
assert.deepEqual([dateEnv.fromInput.value, dateEnv.toInput.value], ['2026-09-05', '2026-09-05']);
dateEnv.fromInput.value = '2026-09-02';
dateEnv.toInput.value = '2026-09-03';
dateEnv.fromInput.fire('change');
assert.deepEqual(
  dateEnv.shortcutButtons.map((button) => button.getAttribute('aria-pressed')),
  ['false', 'false', 'false', 'false', 'false']
);
console.log('range: 50 tokens, $5, 2 sessions; empty/reversed/clamped/no-previous safe');

function sectionBody(section) {
  return section.children.filter((child) => (
    !child.classList.contains('prompt') && !child.classList.contains('rule')
  ));
}

const filterCube = {
  dates: ['2025-12-28', '2025-12-29', '2026-01-01', '2026-01-05'],
  agents: [
    {id: 'claude-code', name: 'Claude Code'},
    {id: 'codex', name: 'Codex'},
  ],
  models: [
    {name: 'claude-test', cost_known: true},
    {name: 'gpt-test', cost_known: false},
  ],
  projects: ['secret-client', 'beta'],
  rows: [
    [0, 0, 0, 0, 100, 20, 10, 70, 2, 1],
    [1, 0, 0, 0, 50, 10, 0, 40, 1, 1],
    [2, 1, 1, 1, 0, 0, 0, 0, 0, 1],
    [3, 0, 0, 0, 200, 30, 20, 150, 4, 1],
  ],
};
const filterSessions = [
  {
    date_idx: 0, project_idx: 0, model_idx: 0,
    start_time: '2025-12-28 10:00', duration_min: 90, tokens: 50, cost: 8,
  },
  {
    date_idx: 1, project_idx: 0, model_idx: 0,
    start_time: '2025-12-29 11:00', duration_min: 30, tokens: 100, cost: 1.25,
  },
  {
    date_idx: 3, project_idx: 1, model_idx: 1,
    start_time: '2026-01-05 09:00', duration_min: 5, tokens: 400, cost: 9,
  },
];
const filterEnv = run(makeEnvironment(filterCube, {}, false, filterSessions));

function applyFilter(from, to) {
  return window.usageReportFilter.applyBounds({from, to});
}

function trendRows() {
  const trend = sectionBody(filterEnv.trendSection)[0];
  return trend.children.filter((child) => child.classList.contains('trend-row'));
}

// Cross-year ISO week 2025-12-29..2026-01-04 is 2026-W1; tokens 100, cost $1.
const crossYear = applyFilter('2025-12-29', '2026-01-04');
assert.equal(crossYear.tokens, 100);
assert.equal(crossYear.cost, 1);
const crossRows = trendRows();
assert.equal(crossRows.length, 1);
assert.equal(crossRows[0].querySelector('.week').textContent, 'W1');
assert.equal(crossRows[0].querySelector('em').textContent, '100');
assert.equal(crossRows[0].getAttribute('title'), '2025-12-29 – 2026-01-04 · 100 · $1.00');
assert.equal(crossRows[0].querySelector('.delta').textContent, '');
assert.equal(
  filterEnv.trendSection.querySelector('.trend-summary').textContent,
  '→ First week of this period.'
);
const crossLists = filterEnv.compositionSection.querySelectorAll('.rank-list');
assert.equal(filterEnv.compositionSection.hidden, false);
assert.deepEqual(
  crossLists[0].children.map((row) => [
    row.querySelector('.name').textContent,
    row.querySelector('.pct').textContent,
    row.querySelector('.tokens').textContent,
  ]),
  [['Input', '50.0%', '50'], ['Cache read', '40.0%', '40'], ['Output', '10.0%', '10']]
);
assert.deepEqual(
  crossLists[1].children.map((row) => [
    row.querySelector('.name').textContent,
    row.querySelector('.pct').textContent,
  ]),
  [['Claude Code', '44.4%'], ['Codex', '—']]
);
const crossSessionRows = filterEnv.sessionSection.querySelectorAll('tr').slice(1);
assert.equal(crossSessionRows.length, 1);
assert.equal(crossSessionRows[0].children[0].textContent, '#1');
assert.equal(crossSessionRows[0].children[1].textContent, '2025-12-29 11:00');
assert.equal(crossSessionRows[0].children[2].className, 'name');
assert.equal(crossSessionRows[0].children[2].textContent, 'secret-client');
assert.equal(crossSessionRows[0].children[3].className, '');
assert.equal(crossSessionRows[0].children[3].textContent, 'claude-test');
assert.equal(crossSessionRows[0].children[4].textContent, '30m');
assert.equal(crossSessionRows[0].children[5].textContent, '100');
assert.equal(crossSessionRows[0].children[6].textContent, '$1.25');
const maskedCsv = window.usageReportFilter.buildCsv(true);
assert.equal(maskedCsv.includes('secret-client'), false);
assert.equal(maskedCsv.includes('Project 1'), true);
assert.equal(maskedCsv.includes('claude-test'), true);
const plainCsv = window.usageReportFilter.buildCsv(false);
assert.equal(
  plainCsv,
  'type,name,share_pct,tokens,cost_usd\r\nproject,secret-client,100.0,100,1.00\r\nmodel,claude-test,100.0,100,1.00\r\n'
);

// Empty range: no rows, hide composition, empty sessions, zero-token week, no NaN.
const emptyRange = applyFilter('2025-12-30', '2025-12-31');
assert.deepEqual([emptyRange.tokens, emptyRange.cost], [0, 0]);
assert.equal(filterEnv.compositionSection.hidden, true);
assert.equal(sectionBody(filterEnv.sessionSection)[0].className, 'empty');
assert.equal(trendRows()[0].querySelector('em').textContent, '0');
const emptyDump = JSON.stringify({
  summary: emptyRange,
  csv: window.usageReportFilter.buildCsv(false),
  title: trendRows()[0].getAttribute('title'),
});
assert.equal(emptyDump.includes('NaN'), false);
assert.equal(emptyDump.includes('Infinity'), false);

// Single day with data.
const oneDay = applyFilter('2026-01-05', '2026-01-05');
assert.equal(oneDay.tokens, 400);
assert.equal(trendRows().length, 1);
assert.equal(trendRows()[0].querySelector('.week').textContent, 'W2');
assert.equal(trendRows()[0].querySelector('.delta').textContent, 'in progress');
assert.equal(filterEnv.compositionSection.hidden, false);
const oneDaySessions = filterEnv.sessionSection.querySelectorAll('tr').slice(1);
assert.equal(oneDaySessions.length, 1);
assert.equal(oneDaySessions[0].children[2].textContent, 'beta');
assert.equal(oneDaySessions[0].children[3].className, '');
assert.equal(oneDaySessions[0].children[4].textContent, '5m');

// Full range: cost ranking (not tokens), in-progress last week, masked CSV still clean.
applyFilter('2025-12-28', '2026-01-05');
const fullRows = trendRows();
assert.deepEqual(
  fullRows.map((row) => row.querySelector('.week').textContent),
  ['W52', 'W1', 'W2']
);
assert.deepEqual(
  fullRows.map((row) => row.querySelector('em').textContent),
  ['200', '100', '400']
);
assert.equal(fullRows[2].querySelector('.delta').textContent, 'in progress');
assert.equal(
  filterEnv.trendSection.querySelector('.trend-summary').textContent,
  '→ This week dropped 50% vs last week.'
);
const ranked = filterEnv.sessionSection.querySelectorAll('tr').slice(1);
assert.deepEqual(ranked.map((row) => row.children[6].textContent), ['$9.00', '$8.00', '$1.25']);
assert.deepEqual(ranked.map((row) => row.children[5].textContent), ['400', '50', '100']);
assert.equal(ranked[0].children[2].className, 'name');
assert.equal(ranked[0].children[3].className, '');
assert.equal(window.usageReportFilter.buildCsv(true).includes('secret-client'), false);
assert.equal(window.usageReportFilter.buildCsv(true).includes('Project 1'), true);
const fullDump = JSON.stringify({
  weeks: fullRows.map((row) => row.getAttribute('title')),
  csv: window.usageReportFilter.buildCsv(false),
});
assert.equal(fullDump.includes('NaN'), false);
assert.equal(fullDump.includes('Infinity'), false);
console.log(
  'filter: isoWeek 2026-W1 cross-year; composition 50/40/10; sessions by cost; csv masked'
);
"""


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_collapsed_rank_lines_are_actually_hidden_by_css() -> None:
    # .rank-line 的 display:grid 權重高過瀏覽器預設的 [hidden]{display:none}，
    # 少了這條規則，收合只改到 DOM、畫面照舊全開（純 DOM 測試抓不到）。
    from ui.report_styles import REPORT_CSS

    assert ".rank-line[hidden]{display:none}" in REPORT_CSS
    assert ".composition-section[hidden]{display:none}" in REPORT_CSS


def test_report_filter_javascript_interactions_and_boundaries(tmp_path: Path) -> None:
    script = NODE_HARNESS.replace("__REPORT_FILTER_JS__", json.dumps(REPORT_FILTER_JS))
    # 走檔案而非 node -e：整份 JS 當命令列參數會超過 Windows 的長度上限（WinError 206）。
    script_path = tmp_path / "harness.cjs"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [NODE or "node", str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "interaction: four groups collapsed; click, keyboard, reload, "
        "project shares 100.0%; mask safe",
        "single row/model: 100.0%, 10 tokens, unpriced dash; storage errors safe",
        "all unpriced: two dashes; shares 75.0% + 25.0%",
        "range: 50 tokens, $5, 2 sessions; empty/reversed/clamped/no-previous safe",
        "filter: isoWeek 2026-W1 cross-year; composition 50/40/10; sessions by cost; csv masked",
    ]
