from __future__ import annotations

import json
import shutil
import subprocess

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
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  fire(type, key = '') {
    let prevented = false;
    this.listeners[type]({key, preventDefault: () => { prevented = true; }});
    return prevented;
  }
  matches(selector) {
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

function makeEnvironment(cube, storageData = {}, storageThrows = false) {
  const cubeNode = new Element('script');
  cubeNode.textContent = JSON.stringify(cube);

  const groupList = new Element();
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
  const projectList = new Element();
  const projectRows = cube.projects.map((name, index) =>
    rankRow('rank-line', name, {projectIndex: String(index)})
  );
  projectList.append(...projectRows);
  const projectSection = new Element('section', 'project-section');
  projectSection.append(projectHead, projectList);

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
    projectShare: 'Share of project',
  };
  global.document = {
    querySelector(selector) {
      if (selector === '#usage-cube-data') return cubeNode;
      if (selector === '.project-section') return projectSection;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === '.model-section .rank-line.model-group[data-agent-id]') return groups;
      if (selector === '.project-section .rank-line[data-project-index]') return projectRows;
      if (selector === '.project-section .rank-line .name') {
        return projectRows.map((row) => row.querySelector('.name'));
      }
      return [];
    },
    createElement(tagName) { return new Element(tagName); },
  };
  return {groups, groupChildren, projectHead, projectList, projectRows, storageData};
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
"""


@pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")
def test_collapsed_rank_lines_are_actually_hidden_by_css() -> None:
    # .rank-line 的 display:grid 權重高過瀏覽器預設的 [hidden]{display:none}，
    # 少了這條規則，收合只改到 DOM、畫面照舊全開（純 DOM 測試抓不到）。
    from ui.report_styles import REPORT_CSS

    assert ".rank-line[hidden]{display:none}" in REPORT_CSS


def test_report_filter_javascript_interactions_and_boundaries() -> None:
    script = NODE_HARNESS.replace("__REPORT_FILTER_JS__", json.dumps(REPORT_FILTER_JS))

    result = subprocess.run(
        [NODE or "node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "interaction: four groups collapsed; click, keyboard, reload, "
        "project shares 100.0%; mask safe",
        "single row/model: 100.0%, 10 tokens, unpriced dash; storage errors safe",
        "all unpriced: two dashes; shares 75.0% + 25.0%",
    ]
