# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_IMPORT_ROOTS = {
    "analyzer",
    "i18n",
    "installer",
    "loaders",
    "menubar",
    "panels",
    "quota",
    "ui",
    "usage_common",
}
HOOK_SCRIPTS = (
    "usage_session_resume.py",
    "usage_statusline_forwarder.py",
    "usage_statusline.py",
    "usage_terse_mode.py",
    "usage_terse_reminder.py",
)


@pytest.mark.parametrize("script_name", HOOK_SCRIPTS)
def test_copied_hook_scripts_have_no_project_imports(script_name: str) -> None:
    project_root = Path(__file__).resolve().parents[1]
    tree = ast.parse((project_root / script_name).read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.partition(".")[0])

    assert imported_roots.isdisjoint(PROJECT_IMPORT_ROOTS)
