from __future__ import annotations

import importlib
import tomllib
from pathlib import Path
from typing import Any

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
        "resources": ["assets/claude.webp", "assets/codex.webp", "usage_statusline.py"],
        "includes": [
            "AppKit",
            "Foundation",
            "objc",
            "rich",
            "rich.align",
            "rich.console",
            "rich.live",
            "rich.panel",
            "rich.style",
            "rich.table",
            "rich.text",
        ],
        "plist": {
            "CFBundleIdentifier": "com.lollapalooza.usage",
            "CFBundleName": "usage",
            "CFBundleDisplayName": "usage",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSUIElement": True,
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": "MIT License",
        },
    }

    setup(
        app=APP,
        cmdclass={"py2app": _py2app_command()},
        distclass=Py2AppDistribution,
        options={"py2app": OPTIONS},
        setup_requires=["py2app"],
        install_requires=[],
    )
