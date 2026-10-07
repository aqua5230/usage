# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

from i18n import packaged_resource_path


def current_version() -> str:
    try:
        return metadata.version("usage-cli")
    except metadata.PackageNotFoundError as exc:
        pyproject = packaged_resource_path(
            "pyproject.toml", Path(__file__).resolve().parent.parent / "pyproject.toml"
        )
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        if isinstance(version, str):
            return version
        raise RuntimeError("project.version missing from pyproject.toml") from exc
