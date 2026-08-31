from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
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
    import usage_common.usage_logging as usage_logging

    monkeypatch.setattr(usage_logging, "LOG_DIR", tmp_path / "logs")


@pytest.fixture(autouse=True)
def _isolate_user_state_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep shared startup workers out of the user's real config directories."""
    import prefs
    import service_status
    import usage_diagnosis_snapshot

    state_dir = tmp_path / "user-state"
    monkeypatch.setattr(prefs, "PREFERENCES_FILE", state_dir / "usage-preferences.json")
    monkeypatch.setattr(
        usage_diagnosis_snapshot,
        "SNAPSHOT_PATH",
        state_dir / "usage-diagnosis.json",
    )
    monkeypatch.setattr(
        service_status,
        "ALERT_STATE_PATH",
        state_dir / "service-alert-state.json",
    )
    monkeypatch.setattr(
        service_status,
        "CLAUDE_STATUS",
        replace(
            service_status.CLAUDE_STATUS,
            cache_path=state_dir / "anthropic-status-cache.json",
        ),
    )
    monkeypatch.setattr(
        service_status,
        "CODEX_STATUS",
        replace(
            service_status.CODEX_STATUS,
            cache_path=state_dir / "openai-status-cache.json",
        ),
    )


@pytest.fixture(autouse=True)
def _isolate_codex_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent self_heal from writing a user's real Codex, Antigravity or Grok config."""
    from installer import setup_hook

    codex_dir = tmp_path / "codex"
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", codex_dir / "config.toml")
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", codex_dir / "usage-backup.json")
    monkeypatch.setattr(setup_hook, "LEGACY_CODEX_BACKUP", codex_dir / "tt-backup.json")
    agy_dir = tmp_path / "antigravity-cli"
    monkeypatch.setattr(setup_hook, "AGY_SETTINGS", agy_dir / "settings.json")
    monkeypatch.setattr(setup_hook, "AGY_HOOK_TARGET", agy_dir / "usage-statusline-agy.py")
    monkeypatch.setattr(
        setup_hook,
        "AGY_PREVIOUS_STATUSLINE",
        agy_dir / "usage-previous-statusline.json",
    )
    grok_dir = tmp_path / "grok"
    monkeypatch.setattr(setup_hook, "GROK_SETTINGS", grok_dir / "config.toml")
    monkeypatch.setattr(setup_hook, "GROK_HOOK_TARGET", grok_dir / "usage-statusline-grok.py")
    monkeypatch.setattr(
        setup_hook,
        "GROK_PREVIOUS_STATUSLINE",
        grok_dir / "usage-previous-statusline-grok.json",
    )


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
