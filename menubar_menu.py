# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from typing import Any

from AppKit import NSMenuItem

from i18n import _t


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
