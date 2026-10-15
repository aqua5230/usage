from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ui.report_scripts import REPORT_JS_TEMPLATE


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_project_mask_skips_other_without_consuming_a_number(tmp_path: Path) -> None:
    start = REPORT_JS_TEMPLATE.index("async function withShareableReport(")
    end = REPORT_JS_TEMPLATE.index("\nasync function downloadHtml", start)
    script = r"""
const assert = require('node:assert/strict');
const make = (text, other = false) => ({
  textContent: text,
  closest: (selector) => selector === '[data-project-other]' && other ? {} : null,
});
const names = [make('alpha'), make('Other projects', true), make('beta')];
const legend = [make('alpha'), make('Other projects', true), make('beta')];
const document = {
  querySelectorAll: (selector) => selector === '.project-section .rank-line .name'
    ? names : selector === '.project-section .lg-name' ? legend : [],
  querySelector: () => null,
};
const reportRoot = {};
function closeShareModal() {}
function stopSnakeAndRestore() {}
eval(__FUNCTION__);
(async () => {
  const expected = ['Project 1', 'Other projects', 'Project 2'];
  await withShareableReport(true, async () => {
    assert.deepEqual(names.map((el) => el.textContent), expected);
    assert.deepEqual(legend.map((el) => el.textContent), expected);
  });
  assert.deepEqual(names.map((el) => el.textContent), ['alpha', 'Other projects', 'beta']);
  await assert.rejects(withShareableReport(true, async () => {
    throw new Error('export failed');
  }));
  assert.deepEqual(legend.map((el) => el.textContent), ['alpha', 'Other projects', 'beta']);
})();
""".replace("__FUNCTION__", json.dumps(REPORT_JS_TEMPLATE[start:end]))
    script_path = tmp_path / "mask.cjs"
    script_path.write_text(script, encoding="utf-8")
    subprocess.run(
        [shutil.which("node") or "node", str(script_path)], check=True, capture_output=True
    )
