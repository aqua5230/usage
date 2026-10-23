"""Opt-in real-browser regression; uses an existing Playwright installation.

Run with USAGE_BROWSER_TESTS=1 and Node's playwright module available (NODE_PATH
can point at an external installation). Set USAGE_BROWSER_ENGINE=webkit to
exercise WebKit as well. Neither engine is a Windows WebView2 app test.
No browser dependency is added to usage.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(
    os.environ.get("USAGE_BROWSER_TESTS") != "1" or sys.platform != "darwin",
    reason="opt-in browser test using the macOS demo generator",
)
@pytest.mark.parametrize("script", ["panel_footer_layout.cjs", "panel_height_feedback.cjs"])
def test_footer_layout(tmp_path: Path, script: str) -> None:
    node = shutil.which("node")
    assert node, "USAGE_BROWSER_TESTS requires Node and an existing playwright installation"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/make_panel_demo.py"), str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [node, str(ROOT / "tests" / script), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_agy_group_button_visibility() -> None:
    # The app loads assets/panels/panel_core.js; docs/panels are generated demo copies.
    source = (ROOT / "assets" / "panels" / "panel_core.js").read_text(encoding="utf-8")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute panel JavaScript")
    render_agy = source.split("    function renderAgy(agy) {", 1)[1].split(
        "    function renderGrok(", 1
    )[0]
    script = "function renderAgy(agy) {" + render_agy
    result = subprocess.run(
        [
            node,
            "-e",
            """
const assert = require('node:assert/strict');
const vm = require('node:vm');
const button = { hidden: false, dataset: {}, setAttribute() {} };
const context = vm.createContext({
  document: { querySelector: selector => selector.includes('set_agy_quota_group')
    ? button : null },
  applyCard() {}, t: key => key,
});
vm.runInContext(process.argv[1], context);
for (const agy of [null, {}, { groupSwitchable: false },
  { groupSwitchable: true }, { groupSwitchable: false },
  { groupSwitchable: true, groupName: 'CLAUDE AND GPT MODELS' },
  { groupSwitchable: true, groupName: 'Gemini 4 Argon' }]) {
  context.agy = agy && { ...agy, availableGroups: ['gemini', 'claude_gpt', 'argon'] };
  vm.runInContext('renderAgy(agy)', context);
  assert.equal(button.hidden, !(agy && agy.groupSwitchable));
  if (agy && agy.groupSwitchable) {
    const current = agy.groupName === 'Gemini 4 Argon' ? 'argon'
      : agy.groupName ? 'claude_gpt' : 'gemini';
    assert.equal(button.textContent, 'agy_group_' + current);
    assert.equal(button.dataset.group,
      { gemini: 'claude_gpt', claude_gpt: 'argon', argon: 'gemini' }[current]);
  }
}
const names = { gemini: 'GEMINI MODELS', claude_gpt: 'CLAUDE AND GPT MODELS',
  argon: 'GEMINI 4 ARGON' };
let current = 'gemini';
for (const next of ['claude_gpt', 'argon', 'gemini']) {
  context.agy = { groupSwitchable: true, groupName: names[current],
    availableGroups: ['gemini', 'claude_gpt', 'argon'] };
  vm.runInContext('renderAgy(agy)', context);
  assert.equal(button.textContent, 'agy_group_' + current);
  assert.equal(button.dataset.group, next);
  current = button.dataset.group;
}
current = 'claude_gpt';
for (const next of ['argon', 'claude_gpt', 'argon', 'claude_gpt']) {
  context.agy = { groupSwitchable: true, groupName: names[current],
    availableGroups: ['claude_gpt', 'argon'] };
  vm.runInContext('renderAgy(agy)', context);
  assert.equal(button.dataset.group, next);
  current = button.dataset.group;
}
""",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
