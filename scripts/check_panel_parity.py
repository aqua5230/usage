#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Guard macOS and Windows panel definitions from drifting out of sync."""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Protocol, cast

MAC_ONLY_PANEL_IDS = frozenset({"talent_market"})
# talent_market depends on the macOS-only vendor/instate-cli binary.

WINDOWS_PANELS_RE = re.compile(
    r"^WINDOWS_PANELS = \(\n(?P<entries>(?:    \([^\n]+\),\n)+)\)",
    re.MULTILINE,
)
WINDOWS_PANEL_ENTRY_RE = re.compile(
    r'^    \("(?P<id>[^"]+)", "(?P<i18n_key>[^"]+)", '
    r'"(?P<html_filename>[^"]+)"\),$',
    re.MULTILINE,
)
PANEL_HEIGHTS_RE = re.compile(
    r"^PANEL_HEIGHTS = \{\n(?P<entries>(?:    [^\n]+\n)+)\}",
    re.MULTILINE,
)
PANEL_HEIGHT_ENTRY_RE = re.compile(
    r'^    "(?P<id>[^"]+)": (?P<height>\d+(?:\.\d+)?),$',
    re.MULTILINE,
)


class MacPanel(Protocol):
    id: str
    i18n_key: str
    html_filename: str
    height: float


def parse_windows_definitions(
    source: str,
) -> tuple[tuple[tuple[str, str, str], ...], dict[str, float]]:
    panels_match = WINDOWS_PANELS_RE.search(source)
    heights_match = PANEL_HEIGHTS_RE.search(source)
    if panels_match is None or heights_match is None:
        raise ValueError("could not find WINDOWS_PANELS or PANEL_HEIGHTS in wintray.py")

    windows_panels = tuple(
        (match["id"], match["i18n_key"], match["html_filename"])
        for match in WINDOWS_PANEL_ENTRY_RE.finditer(panels_match["entries"])
    )
    panel_heights = {
        match["id"]: float(match["height"])
        for match in PANEL_HEIGHT_ENTRY_RE.finditer(heights_match["entries"])
    }
    if not windows_panels or not panel_heights:
        raise ValueError("could not parse WINDOWS_PANELS or PANEL_HEIGHTS in wintray.py")
    return windows_panels, panel_heights


def load_windows_definitions() -> tuple[tuple[tuple[str, str, str], ...], dict[str, float]]:
    try:
        wintray = importlib.import_module("wintray.app")
    except Exception:
        source = (Path(__file__).resolve().parent.parent / "wintray.py").read_text(
            encoding="utf-8"
        )
        return parse_windows_definitions(source)

    return tuple(wintray.WINDOWS_PANELS), {
        panel_id: float(height) for panel_id, height in wintray.PANEL_HEIGHTS.items()
    }


def format_ids(panel_ids: set[str]) -> str:
    return ", ".join(sorted(panel_ids))


def main() -> int:
    panels = importlib.import_module("panels")
    mac_panels = cast(tuple[MacPanel, ...], panels.all_panels())
    windows_panels, panel_heights = load_windows_definitions()
    mac_by_id = {panel.id: panel for panel in mac_panels}
    windows_by_id = {
        panel_id: (i18n_key, html_filename)
        for panel_id, i18n_key, html_filename in windows_panels
    }
    mac_panel_ids = set(mac_by_id) - MAC_ONLY_PANEL_IDS
    windows_panel_ids = set(windows_by_id)
    panel_height_ids = set(panel_heights)
    errors: list[str] = []

    missing_windows_panels = mac_panel_ids - windows_panel_ids
    unexpected_windows_panels = windows_panel_ids - mac_panel_ids
    if missing_windows_panels:
        errors.append(f"WINDOWS_PANELS: missing panel IDs: {format_ids(missing_windows_panels)}")
    if unexpected_windows_panels:
        errors.append(
            f"WINDOWS_PANELS: unexpected panel IDs: {format_ids(unexpected_windows_panels)}"
        )

    missing_height_ids = windows_panel_ids - panel_height_ids
    unexpected_height_ids = panel_height_ids - windows_panel_ids
    if missing_height_ids:
        errors.append(f"PANEL_HEIGHTS: missing panel IDs: {format_ids(missing_height_ids)}")
    if unexpected_height_ids:
        errors.append(f"PANEL_HEIGHTS: unexpected panel IDs: {format_ids(unexpected_height_ids)}")

    for panel_id in sorted(windows_panel_ids & mac_panel_ids):
        mac_panel = mac_by_id[panel_id]
        windows_i18n_key, windows_html_filename = windows_by_id[panel_id]
        if panel_id in panel_heights and panel_heights[panel_id] != float(mac_panel.height):
            errors.append(
                f"PANEL_HEIGHTS: {panel_id} height mismatch "
                f"(Windows={panel_heights[panel_id]}, macOS={mac_panel.height})"
            )
        if windows_i18n_key != mac_panel.i18n_key:
            errors.append(
                f"WINDOWS_PANELS: {panel_id} i18n_key mismatch "
                f"(Windows={windows_i18n_key}, macOS={mac_panel.i18n_key})"
            )
        if windows_html_filename != mac_panel.html_filename:
            errors.append(
                f"WINDOWS_PANELS: {panel_id} html_filename mismatch "
                f"(Windows={windows_html_filename}, macOS={mac_panel.html_filename})"
            )

    if errors:
        print("FAIL: panel parity check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: panel parity check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
