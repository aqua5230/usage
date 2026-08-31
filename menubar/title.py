# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Menu bar title rendering."""

from __future__ import annotations

from typing import Any, Protocol

from AppKit import (
    NSAttributedString,
    NSFont,
    NSFontAttributeName,
    NSFontWeightBold,
    NSMutableAttributedString,
)

from menubar.chrome import (
    _agy_menubar_icon,
    _claude_menubar_icon,
    _codex_menubar_icon,
    _grok_menubar_icon,
    _menubar_icon_attachment_string,
)
from menubar.state import PopoverState, _format_percent


class _TitleApp(Protocol):
    _menubar_text_cache: dict[str, Any]
    codex_5h_pct: float | None
    _last_button_title_key: tuple[str] | None
    _last_plain_title_key: tuple[str] | None
    status_item: Any


_MENUBAR_FONT: Any = None


def _menubar_font() -> Any:
    # Bold at the menu bar's own point size: the percentages have to carry the
    # strip on their own, against any wallpaper.
    global _MENUBAR_FONT
    if _MENUBAR_FONT is None:
        base = NSFont.menuBarFontOfSize_(0)
        _MENUBAR_FONT = NSFont.systemFontOfSize_weight_(base.pointSize(), NSFontWeightBold)
    return _MENUBAR_FONT


def _menubar_text_string(app: _TitleApp, text: str) -> Any:
    cached = app._menubar_text_cache.get(text)
    if cached is not None:
        return cached
    attributed = NSAttributedString.alloc().initWithString_attributes_(
        text,
        {NSFontAttributeName: _menubar_font()},
    )
    app._menubar_text_cache[text] = attributed
    return attributed


def _menubar_attributed_title(app: _TitleApp, state: PopoverState) -> Any:
    title = NSMutableAttributedString.alloc().init()
    if not state.hide_claude:
        claude_percent = (
            "--"
            if state.claude_session.percent is None
            else f"{_format_percent(state.claude_session.percent)}%"
        )
        title.appendAttributedString_(_menubar_icon_attachment_string(_claude_menubar_icon()))
        title.appendAttributedString_(_menubar_text_string(app, f" {claude_percent}"))
    if not state.hide_codex and (app.codex_5h_pct is not None or state.hide_claude):
        codex_percent = (
            "--"
            if app.codex_5h_pct is None
            else f"{_format_percent(float(app.codex_5h_pct))}%"
        )
        if not state.hide_claude:
            title.appendAttributedString_(_menubar_text_string(app, "   "))
        title.appendAttributedString_(_menubar_icon_attachment_string(_codex_menubar_icon()))
        title.appendAttributedString_(_menubar_text_string(app, f" {codex_percent}"))
    agy_session_percent = state.agy_session.percent
    agy_visible = not state.hide_agy and agy_session_percent is not None
    if agy_visible:
        assert agy_session_percent is not None
        agy_percent = f"{_format_percent(agy_session_percent)}%"
        if title.length() > 0:
            title.appendAttributedString_(_menubar_text_string(app, "   "))
        title.appendAttributedString_(_menubar_icon_attachment_string(_agy_menubar_icon()))
        title.appendAttributedString_(_menubar_text_string(app, f" {agy_percent}"))
    grok_weekly_percent = state.grok_weekly.percent
    grok_visible = not state.hide_grok and grok_weekly_percent is not None
    if grok_visible:
        assert grok_weekly_percent is not None
        grok_percent = f"{_format_percent(grok_weekly_percent)}%"
        if title.length() > 0:
            title.appendAttributedString_(_menubar_text_string(app, "   "))
        title.appendAttributedString_(_menubar_icon_attachment_string(_grok_menubar_icon()))
        title.appendAttributedString_(_menubar_text_string(app, f" {grok_percent}"))
    if title.length() == 0:
        # Both providers hidden: keep a recognizable, clickable status item.
        title.appendAttributedString_(_menubar_icon_attachment_string(_claude_menubar_icon()))
    return title


def _set_button_title(app: _TitleApp, state: PopoverState) -> None:
    title = _compose_title(app, state)
    title_key = (title,)
    if app._last_button_title_key == title_key:
        return

    button = app.status_item.button()
    plain_key = (title,)
    if app._last_plain_title_key != plain_key:
        button.setTitle_(title)
        app._last_plain_title_key = plain_key
    button.setAttributedTitle_(_menubar_attributed_title(app, state))
    app._last_button_title_key = title_key


def _compose_title(app: _TitleApp, state: PopoverState) -> str:
    parts: list[str] = []
    if not state.hide_claude:
        claude = (
            "--"
            if state.claude_session.percent is None
            else f"{_format_percent(state.claude_session.percent)}%"
        )
        parts.append(claude)
    if not state.hide_codex and (app.codex_5h_pct is not None or state.hide_claude):
        codex = (
            "--"
            if app.codex_5h_pct is None
            else f"{_format_percent(float(app.codex_5h_pct))}%"
        )
        parts.append(codex)
    if not state.hide_agy and state.agy_session.percent is not None:
        agy = f"{_format_percent(state.agy_session.percent)}%"
        parts.append(agy)
    if not state.hide_grok and state.grok_weekly.percent is not None:
        grok = f"{_format_percent(state.grok_weekly.percent)}%"
        parts.append(grok)
    # Both providers hidden: keep a recognizable, clickable status item.
    return " · ".join(parts) if parts else "usage"
