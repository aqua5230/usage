from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from menubar.state import _empty_state, _format_percent, popover_dimensions
from panels import get_panel
from panels.catalog import PANEL_SPECS, PanelSpec
from panels.payload import _row_payload


@pytest.mark.parametrize("value", [0.0, 18.5, 100.0, 18.25, 18.75, 99.99])
def test_compact_percent_matches_python(value: float) -> None:
    row = replace(_empty_state().claude_session, percent=value, available=True)
    assert _row_payload(row)["percentTextCompact"] == f"{_format_percent(value)}%"
    row.available = False
    assert _row_payload(row)["percentTextCompact"] == row.percent_text
    row.available = True
    row.reset_done = True
    assert _row_payload(row)["percentTextCompact"] == "0%"


@pytest.mark.parametrize("spec", [s for s in PANEL_SPECS if s.grok_card_height > 0])
def test_compact_initial_height(spec: PanelSpec) -> None:
    panel = get_panel(spec.id)
    state = _empty_state()
    state.hide_agy = state.hide_grok = False
    width, height = popover_dimensions(state, panel)
    measured_cards = sum(
        (
            panel.claude_card_height,
            panel.codex_card_height,
            panel.agy_card_height,
            panel.grok_card_height,
        )
    )
    assert width == 364.0
    assert height == panel.preferred_size()[1] - measured_cards + 4 * 94.0
    state.codex_session.title = ""
    assert popover_dimensions(state, panel)[1] == height
    state.codex_weekly.title = ""
    assert popover_dimensions(state, panel)[1] == height - 42.0
    state.codex_session.title = state.codex_weekly.title = "x"
    state.agy_weekly_only = True
    assert popover_dimensions(state, panel)[1] == height
    state = _empty_state()
    state.hide_agy = False
    assert popover_dimensions(state, panel)[1] == (
        panel.preferred_size()[1] - panel.grok_card_height
    )


def test_compact_toggle_and_render() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute panel JavaScript")
    source = (Path(__file__).resolve().parents[1] / "assets/panels/panel_core.js").read_text()
    toggle = source.split("      const visibleQuotaCards =", 1)[1].split("      applyCardOrder", 1)[
        0
    ]
    render = source.split("    function renderRow(", 1)[1].split("    function isCriticalRow", 1)[0]
    result = subprocess.run(
        [
            node,
            "-e",
            r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const classes = new Set();
const nodes = Object.fromEntries(['.row-title', '.percent', '.reset', '.fill'].map(k =>
  [k, {style: {}, dataset: {}}]));
const rowEl = {dataset: {rowReady: 'true'}, closest: () => ({}),
  querySelector: k => nodes[k]};
let hasCards = true;
const context = vm.createContext({
  QUOTA_CARD_IDS: ['claude', 'codex', 'agy', 'grok'],
  root: {classList: {toggle: (key, on) => on ? classes.add(key) : classes.delete(key),
    contains: key => classes.has(key)}},
  document: {querySelector: selector => selector.includes('[data-row=')
    ? rowEl : hasCards ? {} : null},
  getComputedStyle: () => ({getPropertyValue: () => 'red'}),
  window: {PanelHooks: {accentFallback: () => 'red', applyFillVisual() {}}},
  colorFor: () => 'red', labels: () => ({session: 'Session'}), t: key => key,
});
const toggle = 'function toggle(state) { const visibleQuotaCards =' + process.argv[1] + '}';
vm.runInContext(toggle, context);
vm.runInContext('function renderRow(' + process.argv[2], context);
for (const hidden of ['Claude', 'Codex', 'Agy', 'Grok']) {
  context.state = {};
  vm.runInContext('toggle(state)', context);
  assert(classes.has('compact-cards'));
  context.state['hide' + hidden] = true;
  vm.runInContext('toggle(state)', context);
  assert(!classes.has('compact-cards'));
}
hasCards = false;
vm.runInContext('toggle({})', context);
assert(!classes.has('compact-cards'));
hasCards = true;
for (const compact of [true, false, true]) {
  vm.runInContext(compact ? 'toggle({})' : 'toggle({hideGrok:true})', context);
  for (const [percent, short] of [[18.5, '18.5%'], [100, '100%']]) {
    context.data = {percent, available:true, percentText: short + ' used',
      percentTextCompact:short, resetText:'full reset', resetTextCompact:'short reset'};
    vm.runInContext('renderRow("claude", "session", data)', context);
    assert.equal(nodes['.percent'].textContent, compact ? short : short + ' used');
    assert.equal(nodes['.reset'].textContent, compact ? 'short reset' : 'full reset');
    context.data.available = false;
    context.data.percentText = 'unavailable';
    vm.runInContext('renderRow("claude", "session", data)', context);
    assert.equal(nodes['.percent'].textContent, 'unavailable');
  }
}
""",
            toggle,
            render,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
