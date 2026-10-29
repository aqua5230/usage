from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ui.report_scripts import REPORT_JS_TEMPLATE


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_project_mask_covers_accessibility_attributes_and_restores_them(tmp_path: Path) -> None:
    start = REPORT_JS_TEMPLATE.index("async function withShareableReport(")
    end = REPORT_JS_TEMPLATE.index("\nasync function downloadHtml", start)
    script = r"""
const assert = require('node:assert/strict');
const make = (text, other = false, attributes = {}) => ({
  textContent: text,
  attributes,
  getAttribute: (name) => attributes[name] ?? null,
  setAttribute: (name, value) => { attributes[name] = value; },
  closest: (selector) => selector === '[data-project-other]' && other ? {} : null,
});
const names = [make(' alpha '), make('Other projects', true), make('beta[.]')];
const legend = [make('alpha'), make('Other projects', true), make('beta[.]')];
const toggle = make('', false, {
  'aria-label': 'Expand alpha; alpha / beta[.]',
  'aria-description': 'Details for beta[.]',
  title: 'alpha and beta[.]',
  alt: 'alpha logo',
  class: 'alpha',
  id: 'beta',
  'data-project-name': 'alpha',
});
const untouched = make('', false, {title: 'Other projects betaX'});
const originalAttributes = {...toggle.attributes};
const assertMasked = () => {
  assert.deepEqual(toggle.attributes, {
    ...originalAttributes,
    'aria-label': 'Expand Project 1; Project 1 / Project 2',
    'aria-description': 'Details for Project 2',
    title: 'Project 1 and Project 2',
    alt: 'Project 1 logo',
  });
  assert.deepEqual(untouched.attributes, {title: 'Other projects betaX'});
};
const document = {
  querySelectorAll: (selector) => selector === '.project-section .rank-line .name'
    ? names : selector === '.project-section .lg-name' ? legend : [],
  querySelector: () => null,
};
const reportRoot = {querySelectorAll: () => [toggle, untouched]};
function closeShareModal() {}
function stopSnakeAndRestore() {}
eval(__FUNCTION__);
(async () => {
  const expected = ['Project 1', 'Other projects', 'Project 2'];
  await withShareableReport(true, async () => {
    assert.deepEqual(names.map((el) => el.textContent), expected);
    assert.deepEqual(legend.map((el) => el.textContent), expected);
    assertMasked();
  });
  assert.deepEqual(names.map((el) => el.textContent), [' alpha ', 'Other projects', 'beta[.]']);
  assert.deepEqual(toggle.attributes, originalAttributes);
  await withShareableReport(false, async () => {
    assert.deepEqual(toggle.attributes, originalAttributes);
  });
  await assert.rejects(withShareableReport(true, async () => {
    assertMasked();
    throw new Error('export failed');
  }), /export failed/);
  assert.deepEqual(legend.map((el) => el.textContent), ['alpha', 'Other projects', 'beta[.]']);
  assert.deepEqual(toggle.attributes, originalAttributes);
})();
""".replace("__FUNCTION__", json.dumps(REPORT_JS_TEMPLATE[start:end]))
    script_path = tmp_path / "mask.cjs"
    script_path.write_text(script, encoding="utf-8")
    subprocess.run(
        [shutil.which("node") or "node", str(script_path)], check=True, capture_output=True
    )
