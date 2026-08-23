# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Shared menu descriptors for the Windows panel and recovery tray menu."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type MenuSurface = Literal["panel", "tray"]
type CheckKey = Literal[
    "active_panel",
    "hide_claude",
    "hide_codex",
    "hide_agy",
    "launch_at_login",
    "quota_notifications",
    "window_keeper",
    "session_resume",
    "terse_mode",
]

PANEL: MenuSurface = "panel"
TRAY: MenuSurface = "tray"
_PANEL_ONLY = frozenset({PANEL})
_TRAY_ONLY = frozenset({TRAY})


@dataclass(frozen=True, slots=True)
class MenuCommand:
    i18n_key: str
    action: str
    surfaces: frozenset[MenuSurface] = _PANEL_ONLY
    checked_by: CheckKey | None = None
    argument_name: str | None = None
    argument_value: str | None = None
    radio: bool = False


@dataclass(frozen=True, slots=True)
class MenuGroup:
    i18n_key: str
    children: tuple[MenuEntry, ...]
    surfaces: frozenset[MenuSurface] = _PANEL_ONLY


@dataclass(frozen=True, slots=True)
class MenuSeparator:
    surfaces: frozenset[MenuSurface]


type MenuEntry = MenuCommand | MenuGroup | MenuSeparator
type Panel = tuple[str, str, str]


def windows_menu_model(panels: tuple[Panel, ...]) -> tuple[MenuEntry, ...]:
    """Describe both Windows menus once; renderers select their own surface."""
    panel_choices: tuple[MenuEntry, ...] = tuple(
        MenuCommand(
            i18n_key,
            "switch_panel",
            checked_by="active_panel",
            argument_name="panelId",
            argument_value=panel_id,
            radio=True,
        )
        for panel_id, i18n_key, _filename in panels
    )
    hidden_sections: tuple[MenuEntry, ...] = (
        MenuCommand(
            "claude_name",
            "toggle_hide_section",
            checked_by="hide_claude",
            argument_name="preferenceKey",
            argument_value="hide_claude_section",
        ),
        MenuCommand(
            "codex_name",
            "toggle_hide_section",
            checked_by="hide_codex",
            argument_name="preferenceKey",
            argument_value="hide_codex_section",
        ),
        MenuCommand(
            "agy_name",
            "toggle_hide_section",
            checked_by="hide_agy",
            argument_name="preferenceKey",
            argument_value="hide_agy_section",
        ),
    )
    return (
        MenuCommand("panel_ai_daily", "open_ai_daily"),
        MenuSeparator(_PANEL_ONLY),
        MenuGroup("switch_panel", panel_choices),
        MenuGroup("hide_sections_menu", hidden_sections),
        MenuSeparator(_PANEL_ONLY),
        MenuCommand("launch_at_login", "toggle_login", checked_by="launch_at_login"),
        MenuCommand(
            "quota_notifications_menu",
            "toggle_quota_notifications",
            checked_by="quota_notifications",
        ),
        MenuCommand("window_keeper_menu", "toggle_window_keeper", checked_by="window_keeper"),
        # Grouped with the plain switches above it — a separate section here just
        # added a divider with no real category difference (matches macOS f74bbe0).
        MenuCommand("project_butler", "toggle_session_resume", checked_by="session_resume"),
        MenuCommand("terse_mode_menu", "toggle_terse_mode", checked_by="terse_mode"),
        MenuSeparator(_PANEL_ONLY),
        MenuCommand("check_update", "check_update"),
        MenuCommand(
            "reset_panel_position",
            "reset_panel_position",
            surfaces=_TRAY_ONLY,
        ),
        MenuSeparator(_TRAY_ONLY),
        MenuCommand("quit", "quit", surfaces=_TRAY_ONLY),
    )


def entries_for_surface(
    entries: tuple[MenuEntry, ...], surface: MenuSurface
) -> tuple[MenuEntry, ...]:
    """Select one renderer's entries while keeping separators well formed."""
    selected = [entry for entry in entries if surface in entry.surfaces]
    normalized: list[MenuEntry] = []
    for entry in selected:
        if isinstance(entry, MenuSeparator) and (
            not normalized or isinstance(normalized[-1], MenuSeparator)
        ):
            continue
        normalized.append(entry)
    if normalized and isinstance(normalized[-1], MenuSeparator):
        normalized.pop()
    return tuple(normalized)
