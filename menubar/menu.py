# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from typing import Any, Protocol

from AppKit import NSMakePoint, NSMenu, NSMenuItem

from i18n import _t
from installer import claude_pane, login_item
from menubar.new_badge import apply_badge
from menubar.prefs import (
    _hide_agy_enabled,
    _hide_claude_enabled,
    _hide_codex_enabled,
    _hide_grok_enabled,
    _quota_notifications_enabled,
    _window_keeper_enabled,
)


class _SwitchMenuApp(Protocol):
    language: str
    active_panel: Any
    _switch_menu_action_taken: bool
    _beginner_menu_target: Any

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
    if title_key == "window_keeper_menu" and state:
        from quota.keeper_outcome import failure_tooltip

        failures = failure_tooltip(language)
        if failures:
            item.setTitle_(_t(language, title_key) + " ⚠")
            item.setToolTip_(failures + "\n" + _t(language, "window_keeper_tooltip"))
    if title_key == "terse_mode_menu" and state:
        from installer.codex_hook_trust import codex_terse_hook_trust

        trust = codex_terse_hook_trust()
        if trust in ("untrusted", "disabled"):
            item.setTitle_(_t(language, title_key) + " ⚠")
            item.setToolTip_(_t(language, f"terse_codex_hook_{trust}"))
    return item


def build_switch_menu(app: _SwitchMenuApp, sender: Any) -> None:
    import panels
    from menubar.app import _session_resume_enabled, _terse_mode_enabled

    menu = NSMenu.alloc().initWithTitle_(_t(app.language, "switch_panel"))
    menu.addItem_(build_menu_item(app.language, "panel_ai_daily", "toggleAiDaily:", target=app))
    menu.addItem_(NSMenuItem.separatorItem())
    # Panel themes live in a submenu so the menu stays short — one "面板主題 ▸"
    # row that expands on demand instead of fourteen inline rows.
    panel_submenu = NSMenu.alloc().initWithTitle_(_t(app.language, "switch_panel"))
    for panel in panels.all_panels():
        panel_submenu.addItem_(
            build_menu_item(
                app.language,
                panel.i18n_key,
                "selectPanel:",
                target=app,
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
            app.language,
            "claude_name",
            "toggleHideClaude:",
            target=app,
            state=_hide_claude_enabled(),
        )
    )
    hide_submenu.addItem_(
        build_menu_item(
            app.language,
            "codex_name",
            "toggleHideCodex:",
            target=app,
            state=_hide_codex_enabled(),
        )
    )
    hide_submenu.addItem_(
        build_menu_item(
            app.language,
            "agy_name",
            "toggleHideAgy:",
            target=app,
            state=_hide_agy_enabled(),
        )
    )
    hide_submenu.addItem_(
        build_menu_item(
            app.language,
            "grok_name",
            "toggleHideGrok:",
            target=app,
            state=_hide_grok_enabled(),
        )
    )
    hide_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        _t(app.language, "hide_sections_menu"), "", ""
    )
    hide_parent.setSubmenu_(hide_submenu)
    menu.addItem_(hide_parent)
    # General app settings.
    menu.addItem_(NSMenuItem.separatorItem())
    menu.addItem_(
        build_menu_item(
            app.language,
            "launch_at_login",
            "toggleLaunchAtLogin:",
            target=app,
            state=login_item.is_enabled(),
        )
    )
    menu.addItem_(
        build_menu_item(
            app.language,
            "quota_notifications_menu",
            "toggleQuotaNotifications:",
            target=app,
            state=_quota_notifications_enabled(),
        )
    )
    menu.addItem_(
        build_menu_item(
            app.language,
            "window_keeper_menu",
            "toggleWindowKeeper:",
            target=app,
            state=_window_keeper_enabled(),
            tooltip_key="window_keeper_tooltip",
        )
    )
    menu.addItem_(NSMenuItem.separatorItem())
    menu.addItem_(
        build_menu_item(
            app.language,
            "project_butler",
            "toggleSessionResume:",
            target=app,
            state=_session_resume_enabled(),
            tooltip_key="project_butler_tooltip",
        )
    )
    menu.addItem_(
        build_menu_item(
            app.language,
            "terse_mode_menu",
            "toggleTerseMode:",
            target=app,
            state=_terse_mode_enabled(),
            tooltip_key="terse_mode_tooltip",
        )
    )
    menu.addItem_(NSMenuItem.separatorItem())
    section_title = _t(app.language, "claude_code_section")
    if NSMenuItem.respondsToSelector_("sectionHeaderWithTitle:"):
        section = NSMenuItem.sectionHeaderWithTitle_(section_title)
    else:
        section = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(section_title, "", "")
        section.setEnabled_(False)
    menu.addItem_(section)
    claude_pane_item = build_menu_item(
        app.language,
        "claude_pane_section_menu",
        "toggleClaudePane:",
        target=app,
        state=claude_pane.is_claude_pane_enabled(),
        tooltip_key="claude_pane_tooltip",
    )
    claude_pane_item.setIndentationLevel_(1)
    apply_badge(claude_pane_item, app.language, "claude_pane")
    menu.addItem_(claude_pane_item)
    from menubar.actions import BeginnerMenuTarget

    beginner_target = BeginnerMenuTarget.alloc().init()
    beginner_target.app = app
    # NSMenuItem does not retain its target; hold it through background completion.
    app._beginner_menu_target = beginner_target
    beginner_item = build_menu_item(
        app.language,
        "claude_beginner_menu",
        "toggleClaudeBeginner:",
        target=beginner_target,
        state=claude_pane.is_claude_beginner_enabled(),
        tooltip_key="claude_beginner_tooltip",
    )
    beginner_item.setIndentationLevel_(1)
    menu.addItem_(beginner_item)
    app._switch_menu_action_taken = False
    menu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0, 0), sender)
    # Dismissing the menu without picking anything used to close the panel:
    # a transient popover was already gone by then, so closing it was just
    # cleanup. The floating window survives the menu, so the same call would
    # read as "cancelling the menu threw my panel away".
    app._resync_popover_after_menu()
