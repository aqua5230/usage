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
def test_footer_layout(tmp_path: Path) -> None:
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
        [node, str(ROOT / "tests/panel_footer_layout.cjs"), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
