# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_importing_panels_package_does_not_import_web_panel() -> None:
    # Regression: panels/__init__ used to import panels.web_panel (PyObjC)
    # eagerly, which crashed any panels.payload import on Windows and took the
    # whole tray down with it. Run in a subprocess so this session's module
    # cache cannot mask an eager import.
    code = (
        "import sys; "
        "import panels; "
        "import panels.payload; "
        "assert 'panels.web_panel' not in sys.modules, "
        "'panels.web_panel was imported eagerly'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
