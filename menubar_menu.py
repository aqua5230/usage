# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from typing import Any, Protocol

from AppKit import NSMakePoint, NSMenu, NSMenuItem

import login_item
from i18n import _t
from menubar_prefs import (
    _hide_agy_enabled,
    _hide_claude_enabled,
    _hide_codex_enabled,
    _quota_notifications_enabled,
    _window_keeper_enabled,
)


class _SwitchMenuApp(Protocol):
    language: str
    active_panel: Any
    _switch_menu_action_taken: bool

    def _resync_popover_after_menu(self) -> None: ...


def build_menu_item(
    language: str,
    title_key: str,
    selector: str,
    *,
    target: Any,
    represented: Any | None = None,
    state: bool | None = None,
    tooltip_key: str | None = None,
) -> Any:
    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        _t(language, title_key), selector, ""
    )
    item.setTarget_(target)
    if represented is not None:
        item.setRepresentedObject_(represented)
    if state is not None:
        item.setState_(1 if state else 0)
    if tooltip_key is not None:
        item.setToolTip_(_t(language, tooltip_key))
    return item


def build_switch_menu(app: _SwitchMenuApp, sender: Any) -> None:
    import panels
    from menubar import _session_resume_enabled, _terse_mode_enabled

    menu = NSMenu.alloc().initWithTitle_(_t(app.language, "switch_panel"))
    # AI 人才市場 is a feature panel, not a cosmetic skin — it gets its own
    # top-level row instead of hiding inside "面板主題 ▸" next to Matrix/Win95.
    menu.addItem_(
        build_menu_item(
            app.language, "panel_talent_market", "toggleTalentMarket:", target=app,
            represented="talent_market",
            state=app.active_panel.id == "talent_market",
        )
    )
    menu.addItem_(
        build_menu_item(
            app.language, "discussion_window_title", "toggleDiscussion:", target=app
        )
    )
    menu.addItem_(
        build_menu_item(app.language, "panel_ai_daily", "toggleAiDaily:", target=app)
    )
    menu.addItem_(NSMenuItem.separatorItem())
    # Panel themes live in a submenu so the menu stays short — one "面板主題 ▸"
    # row that expands on demand instead of nine inline rows. talent_market is
    # excluded here since it already has its own top-level row above.
    panel_submenu = NSMenu.alloc().initWithTitle_(_t(app.language, "switch_panel"))
    for panel in panels.all_panels():
        if panel.id == "talent_market":
            continue
        panel_submenu.addItem_(
            build_menu_item(
                app.language, panel.i18n_key, "selectPanel:", target=app,
                represented=panel.id,
                state=panel.id == app.active_panel.id,
            )
        )
    panel_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        _t(app.language, "switch_panel"), "", ""
    )
    panel_parent.setSubmenu_(panel_submenu)
    menu.addItem_(panel_parent)
    # Provider visibility lives in one "Hide Sections ▸" submenu row, grouped
    # with the panel-themes submenu: both are drill-in rows that shape what
    # the popover shows.
    hide_submenu = NSMenu.alloc().initWithTitle_(_t(app.language, "hide_sections_menu"))
    hide_submenu.addItem_(
        build_menu_item(
            app.language, "claude_name", "toggleHideClaude:", target=app,
            state=_hide_claude_enabled(),
        )
    )
    hide_submenu.addItem_(
        build_menu_item(
            app.language, "codex_name", "toggleHideCodex:", target=app,
            state=_hide_codex_enabled(),
        )
    )
    hide_submenu.addItem_(
        build_menu_item(
            app.language, "agy_name", "toggleHideAgy:", target=app,
            state=_hide_agy_enabled(),
        )
    )
    hide_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        _t(app.language, "hide_sections_menu"), "", ""
    )
    hide_parent.setSubmenu_(hide_submenu)
    menu.addItem_(hide_parent)
    # Plain on/off switches sit together in the second group.
    menu.addItem_(NSMenuItem.separatorItem())
    menu.addItem_(
        build_menu_item(
            app.language, "launch_at_login", "toggleLaunchAtLogin:", target=app,
            state=login_item.is_enabled(),
        )
    )
    menu.addItem_(
        build_menu_item(
            app.language, "quota_notifications_menu", "toggleQuotaNotifications:", target=app,
            state=_quota_notifications_enabled(),
        )
    )
    menu.addItem_(
        build_menu_item(
            app.language, "window_keeper_menu", "toggleWindowKeeper:", target=app,
            state=_window_keeper_enabled(),
            tooltip_key="window_keeper_tooltip",
        )
    )
    # Project Butler: one toggle that hands last session's progress to the next
    # one. Tooltip carries the full explanation so the menu line stays short.
    menu.addItem_(NSMenuItem.separatorItem())
    menu.addItem_(
        build_menu_item(
            app.language, "project_butler", "toggleSessionResume:", target=app,
            state=_session_resume_enabled(),
            tooltip_key="project_butler_tooltip",
        )
    )
    menu.addItem_(
        build_menu_item(
            app.language, "terse_mode_menu", "toggleTerseMode:", target=app,
            state=_terse_mode_enabled(),
            tooltip_key="terse_mode_tooltip",
        )
    )
    app._switch_menu_action_taken = False
    menu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0, 0), sender)
    # Dismissing the menu without picking anything used to close the panel:
    # a transient popover was already gone by then, so closing it was just
    # cleanup. The floating window survives the menu, so the same call would
    # read as "cancelling the menu threw my panel away".
    app._resync_popover_after_menu()
