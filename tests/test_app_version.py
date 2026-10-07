from __future__ import annotations

import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from usage_common import app_version

ROOT = Path(__file__).resolve().parent.parent


def test_falls_back_to_repository_pyproject_without_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # menubar/ and wintray/ once resolved the fallback next to their own
    # module, where no pyproject.toml exists.
    def missing(_name: str) -> str:
        raise metadata.PackageNotFoundError("usage-cli")

    monkeypatch.setattr(metadata, "version", missing)
    monkeypatch.delenv("RESOURCEPATH", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert app_version.current_version() == expected["project"]["version"]
