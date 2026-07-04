from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import ResumeHookPaths, SetupHookPaths, TerseHookPaths
from tests.helpers import patch_resume_hook_paths as _patch_resume_hook_paths
from tests.helpers import patch_setup_hook_paths as _patch_setup_hook_paths
from tests.helpers import patch_terse_hook_paths as _patch_terse_hook_paths


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
