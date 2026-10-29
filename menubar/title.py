# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Menu bar title rendering."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
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
    _muse_menubar_icon,
)
from menubar.state import PopoverState, QuotaRowState, _format_percent


class _TitleApp(Protocol):
    _menubar_text_cache: dict[str, Any]
    codex_5h_pct: float | None
    _last_button_title_key: tuple[str] | None
    _last_plain_title_key: tuple[str] | None
    status_item: Any
    interval: float

    def _reschedule_poll_timer(self, interval: float) -> None: ...

    def _panel_window_is_visible(self) -> bool: ...


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


# A wider strip slides behind the notch; the panel still lists every source.
_MENUBAR_MAX_ITEMS = 3
SLOW_POLL_INTERVAL_S = 300.0


def _format_countdown(seconds: float) -> str:
    minutes = math.ceil(seconds / 60)
    if minutes >= 1440:
        return f"{minutes // 1440}d{minutes % 1440 // 60}h"
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60}m"
    return f"{minutes}m"


def _quota_countdown(rows: tuple[QuotaRowState, ...], now: float) -> str | None:
    full = [row for row in rows if row.display_percent is not None and row.display_percent >= 100]
    if not full:
        return None
    resets = []
    for row in full:
        if row.resets_at is None or row.resets_at <= now:
            return None
        resets.append(row.resets_at)
    return _format_countdown(max(resets) - now)


def menubar_poll_interval(app: _TitleApp, state: PopoverState) -> float:
    if app._panel_window_is_visible() or any(
        text != "--" and not text.endswith("%") for _icon, text in _menubar_items(app, state)
    ):
        return app.interval
    return max(app.interval, SLOW_POLL_INTERVAL_S)


def _menubar_items(
    app: _TitleApp, state: PopoverState, now: float | None = None
) -> list[tuple[Callable[[], Any], str]]:
    """Visible icon/text pairs, keeping the highest-usage sources in order."""
    now = time.time() if now is None else now
    items: list[tuple[Callable[[], Any], float | None]] = []
    if not state.hide_claude:
        items.append((_claude_menubar_icon, state.claude_session.display_percent))
    if not state.hide_codex and (app.codex_5h_pct is not None or state.hide_claude):
        codex_row = (
            state.codex_session if state.codex_session.percent is not None else state.codex_weekly
        )
        codex_used = 0.0 if codex_row.reset_done else app.codex_5h_pct
        items.append((_codex_menubar_icon, None if codex_used is None else float(codex_used)))
    for hidden, icon, percent in (
        (state.hide_agy, _agy_menubar_icon, state.agy_session.display_percent),
        (state.hide_grok, _grok_menubar_icon, state.grok_weekly.display_percent),
        (state.hide_muse, _muse_menubar_icon, state.muse_session.display_percent),
    ):
        if not hidden and percent is not None:
            items.append((icon, percent))
    rows_by_icon = {
        _claude_menubar_icon: (state.claude_session, state.claude_weekly),
        _codex_menubar_icon: (state.codex_session, state.codex_weekly),
        _agy_menubar_icon: (state.agy_session, state.agy_weekly),
        _grok_menubar_icon: (state.grok_weekly,),
        _muse_menubar_icon: (state.muse_session, state.muse_weekly),
    }
    countdowns = [_quota_countdown(rows_by_icon[icon], now) for icon, _percent in items]
    if len(items) > _MENUBAR_MAX_ITEMS:
        # Stable sort, so ties keep the fixed order; an unknown "--" ranks last.
        ranks = [
            100.0 if countdowns[i] is not None else -1.0 if percent is None else percent
            for i, (_icon, percent) in enumerate(items)
        ]
        ranked = sorted(range(len(items)), key=ranks.__getitem__, reverse=True)
        selected = sorted(ranked[:_MENUBAR_MAX_ITEMS])
    else:
        selected = list(range(len(items)))
    rendered = [
        (icon, countdown or ("--" if percent is None else f"{_format_percent(percent)}%"))
        for (icon, percent), countdown in zip(items, countdowns, strict=True)
    ]
    return [rendered[i] for i in selected]


def _menubar_attributed_title(app: _TitleApp, state: PopoverState) -> Any:
    title = NSMutableAttributedString.alloc().init()
    for icon, percent in _menubar_items(app, state):
        if title.length() > 0:
            title.appendAttributedString_(_menubar_text_string(app, "  "))
        title.appendAttributedString_(_menubar_icon_attachment_string(icon()))
        title.appendAttributedString_(_menubar_text_string(app, f" {percent}"))
    if title.length() == 0:
        # Both providers hidden: keep a recognizable, clickable status item.
        title.appendAttributedString_(_menubar_icon_attachment_string(_claude_menubar_icon()))
    return title


def _set_button_title(app: _TitleApp, state: PopoverState) -> None:
    app._reschedule_poll_timer(menubar_poll_interval(app, state))
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
    parts = [percent for _icon, percent in _menubar_items(app, state)]
    # Both providers hidden: keep a recognizable, clickable status item.
    return " · ".join(parts) if parts else "usage"
