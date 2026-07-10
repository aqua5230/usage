# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path
from typing import Any, cast

from setuptools import setup  # type: ignore[import-untyped]
from setuptools.dist import Distribution  # type: ignore[import-untyped]

APP = ["main.py"]


def _version() -> str:
    pyproject = Path(__file__).with_name("pyproject.toml")
    with pyproject.open("rb") as file:
        data = tomllib.load(file)
    return str(data["project"]["version"])


class Py2AppDistribution(Distribution):  # type: ignore[misc]
    def __init__(self, attrs: dict[str, object] | None = None) -> None:
        super().__init__(attrs)
        self.install_requires: list[str] = []

    def finalize_options(self) -> None:
        super().finalize_options()
        self.install_requires = []


def _py2app_command() -> type[Any]:
    py2app_module: Any = importlib.import_module("py2app.build_app")
    py2app_base = py2app_module.py2app

    class Py2AppCommand(py2app_base):  # type: ignore[misc, valid-type]
        def finalize_options(self) -> None:
            self.distribution.install_requires = []
            super().finalize_options()

    return Py2AppCommand


if __name__ == "__main__":
    version = _version()
    OPTIONS = {
        "argv_emulation": False,
        "iconfile": "assets/usage.icns",
        "resources": [
            "assets/claude.webp",
            "assets/claude_color_menubar.png",
            "assets/codex.webp",
            "assets/codex_color_menubar.png",
            "assets/critters",
            "assets/panels",
            "i18n.json",
            "pyproject.toml",
            "usage_statusline.py",
            "usage_statusline_forwarder.py",
            "usage_session_resume.py",
            "usage_terse_mode.py",
            "usage_terse_reminder.py",
        ],
        "includes": [
            "AppKit",
            "Foundation",
            "Quartz",
            "WebKit",
            "UserNotifications",
            "objc",
            "menubar",
            "usage_notifications",
            "tui",
            "tui_sprite",
            "usage_client",
            "usage_rate",
            "critter_frames",
            "codex_loader",
            "history_loader",
            "pricing",
            "setup_hook",
            "session_hooks",
            "update_checker",
            "i18n",
            "usage_cli",
            "talent_market_bridge",
            "rich",
            "rich.align",
            "rich.console",
            "rich.live",
            "rich.panel",
            "rich.style",
            "rich.table",
            "rich.text",
        ],
        "packages": [
            "WebKit",
            "UserNotifications",
            # Unzipped to Resources/lib/python3.13/ instead of python313.zip so the
            # report pipeline never loads through zipimport — that is where a
            # corrupted local file header surfaces as "bad local file header".
            "adapters",
            "analyzer",
            "ui",
        ],
        "excludes": [
            # Test suites and build tooling that py2app's module graph drags in
            # but the shipped app never runs. Keeping them out shrinks
            # python313.zip (was ~1665 entries: 426 CPython test, 69 _pytest)
            # and cuts the surface for a corrupt zip entry.
            "test",
            "tests",
            "pytest",
            "_pytest",
            "py2app",
            "modulegraph",
            "altgraph",
            "macholib",
            "pip",
            "wheel",
            "mypy",
            "ruff",
        ],
        "plist": {
            "CFBundleIdentifier": "com.lollapalooza.usage",
            "CFBundleName": "usage",
            "CFBundleDisplayName": "usage",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSUIElement": True,
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": (
                "Copyright © 2025-2026 lollapalooza. Licensed under AGPL-3.0-only."
            ),
        },
    }

    # Conditionally bundle the compiled instate-cli (built from the separate
    # ~/Developer/instate project) so the talent-market panel works in the
    # shipped .app. Appended at runtime — not in the literal list above — so the
    # packaged-resources test (which parses the literal) stays clean on machines
    # where vendor/instate-cli does not exist. py2app flattens a single-file
    # resource to Resources/<basename> (Resources/instate-cli), which the bridge
    # finds via NSBundle.pathForResource:ofType:.
    _instate_cli = Path(__file__).with_name("vendor") / "instate-cli"
    if _instate_cli.exists():
        cast(list[Any], OPTIONS["resources"]).append("vendor/instate-cli")

    setup(
        app=APP,
        cmdclass={"py2app": _py2app_command()},
        distclass=Py2AppDistribution,
        options={"py2app": OPTIONS},
        setup_requires=["py2app"],
        install_requires=[],
    )
