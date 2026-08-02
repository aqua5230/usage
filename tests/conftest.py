from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import ResumeHookPaths, SetupHookPaths, TerseHookPaths
from tests.helpers import patch_resume_hook_paths as _patch_resume_hook_paths
from tests.helpers import patch_setup_hook_paths as _patch_setup_hook_paths
from tests.helpers import patch_terse_hook_paths as _patch_terse_hook_paths

# These modules import PyObjC-backed code (menubar, login_item, panels.web_panel)
# at module level, so they can only be collected on macOS.
collect_ignore = (
    []
    if sys.platform == "darwin"
    else [
        "test_analyzer_pipeline.py",
        "test_login_item.py",
        "test_menubar.py",
        "test_panels.py",
        "test_web_panel_payload.py",
    ]
)


@pytest.fixture(autouse=True)
def _isolate_log_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep every test out of the real ~/Library/Logs/usage directory.

    ``main.main()`` calls ``_setup_logging()``, so any test that exercises it
    attaches a RotatingFileHandler to the root logger. Without this the handler
    points at the user's real log file and every later test writes into it.
    """
    import usage_logging

    monkeypatch.setattr(usage_logging, "LOG_DIR", tmp_path / "logs")


@pytest.fixture
def patch_setup_hook_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Callable[..., SetupHookPaths]:
    def factory(**kwargs: Any) -> SetupHookPaths:
        return _patch_setup_hook_paths(monkeypatch, tmp_path, **kwargs)

    return factory


@pytest.fixture
def patch_resume_hook_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Callable[..., ResumeHookPaths]:
    def factory(**kwargs: Any) -> ResumeHookPaths:
        return _patch_resume_hook_paths(monkeypatch, tmp_path, **kwargs)

    return factory


@pytest.fixture
def patch_terse_hook_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Callable[..., TerseHookPaths]:
    def factory(**kwargs: Any) -> TerseHookPaths:
        return _patch_terse_hook_paths(monkeypatch, tmp_path, **kwargs)

    return factory
