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


@pytest.mark.parametrize("panel", sorted((ROOT / "docs" / "panels").glob("*.html")))
def test_agy_group_button_visibility(panel: Path) -> None:
    source = panel.read_text(encoding="utf-8")
    if 'data-action="set_agy_quota_group"' not in source:
        pytest.skip("panel has no Antigravity group button")
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
  { groupSwitchable: true, groupName: 'CLAUDE AND GPT MODELS' }]) {
  context.agy = agy;
  vm.runInContext('renderAgy(agy)', context);
  assert.equal(button.hidden, !(agy && agy.groupSwitchable));
  if (agy && agy.groupSwitchable) {
    assert.equal(button.dataset.group, agy.groupName ? 'gemini' : 'claude_gpt');
  }
}
""",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
