# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Build a prefilled GitHub bug-report URL with privacy-safe environment info."""

from __future__ import annotations

import platform
import sys
import urllib.parse
import webbrowser
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from usage_common.app_version import current_version
from usage_common.prefs import _load_preferences

ISSUE_URL_BASE = "https://github.com/aqua5230/usage/issues/new"

_PROVIDERS = (
    ("Claude", "hide_claude_section"),
    ("Codex", "hide_codex_section"),
    ("Antigravity", "hide_agy_section"),
    ("Grok", "hide_grok_section"),
    ("Muse", "hide_muse_section"),
)


@dataclass(frozen=True, slots=True)
class IssueEnvironment:
    usage_version: str
    install_method: str
    os_name: str
    os_version: str
    cpu_arch: str
    python_version: str
    language: str
    panel_theme: str
    visible_cards: Mapping[str, bool] = field(default_factory=dict)


def _os_info() -> tuple[str, str]:
    system = platform.system() or "unknown"
    if sys.platform == "darwin":
        system = "macOS"
        version = platform.mac_ver()[0] or platform.release()
    elif sys.platform == "win32":
        version = platform.win32_ver()[0] or platform.release()
    else:
        version = platform.release()
    return system, version or "unknown"


def detect_install_method() -> str:
    if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
        return "app bundle"
    if "site-packages" in Path(__file__).parts or "dist-packages" in Path(__file__).parts:
        return "pip"
    return "source"


def collect_environment(
    language: str,
    panel_theme: str,
    prefs: Mapping[str, object] | None = None,
) -> IssueEnvironment:
    data: Mapping[str, object] = _load_preferences() if prefs is None else prefs
    try:
        version = current_version()
    except Exception:
        version = "unknown"
    os_name, os_version = _os_info()
    return IssueEnvironment(
        usage_version=version,
        install_method=detect_install_method(),
        os_name=os_name,
        os_version=os_version,
        cpu_arch=platform.machine() or "unknown",
        python_version=platform.python_version() or "unknown",
        language=language,
        panel_theme=panel_theme,
        visible_cards={name: data.get(key) is not True for name, key in _PROVIDERS},
    )


def build_issue_body(environment: IssueEnvironment) -> str:
    cards = ", ".join(
        f"{name}={'shown' if visible else 'hidden'}"
        for name, visible in environment.visible_cards.items()
    )
    return (
        "**Describe the bug**\n\n"
        "**Steps to reproduce**\n"
        "1.\n2.\n3.\n\n"
        "**Expected behavior**\n\n"
        "**Environment**\n"
        f"- usage version: {environment.usage_version}\n"
        f"- Install method: {environment.install_method}\n"
        f"- Operating system: {environment.os_name} {environment.os_version}\n"
        f"- CPU architecture: {environment.cpu_arch}\n"
        f"- Python version: {environment.python_version}\n"
        f"- Interface language: {environment.language}\n"
        f"- Panel theme: {environment.panel_theme}\n"
        f"- AI cards: {cards}\n\n"
        "**Additional context**\n"
    )


def build_issue_url(environment: IssueEnvironment) -> str:
    query = urllib.parse.urlencode({"labels": "bug", "body": build_issue_body(environment)})
    return f"{ISSUE_URL_BASE}?{query}"


def open_issue_report(
    language: str,
    panel_theme: str,
    prefs: Mapping[str, object] | None = None,
) -> str:
    url = build_issue_url(collect_environment(language, panel_theme, prefs))
    webbrowser.open(url)
    return url
