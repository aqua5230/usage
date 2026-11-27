# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Present post-update notes on the Cocoa main thread."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Mapping
from typing import Any

from Foundation import NSObject

from updates.checker import ReleaseInfo
from updates.release_notes import alert_release_notes
from updates.whats_new import start_notice
from usage_common.i18n import _t

_OPEN_NOTES_TAG = 1
# Strong references until a button is clicked; the buttons hold their target weakly.
_open_notices: set[Any] = set()


class _NoticeHandler(NSObject):  # type: ignore[misc]
    def noticeButtonClicked_(self, sender: Any) -> None:
        self.alert.window().orderOut_(None)
        _open_notices.discard(self)
        if int(sender.tag()) == _OPEN_NOTES_TAG:
            webbrowser.open(self.url)


def show_notice(release: ReleaseInfo, language: str) -> bool:
    from AppKit import NSApp

    from menubar.app import UPDATE_ALERT_BODY_LIMIT
    from menubar.chrome import _make_alert

    alert = _make_alert()
    alert.setMessageText_(_t(language, "whats_new_title", version=release.version))
    alert.setInformativeText_(alert_release_notes(release.body, language, UPDATE_ALERT_BODY_LIMIT))
    alert.addButtonWithTitle_(_t(language, "whats_new_ok"))
    alert.addButtonWithTitle_(_t(language, "whats_new_open"))
    if not hasattr(alert, "window"):
        return False  # _make_alert fell back to its no-op stand-in.
    # Not runModal: a modal nobody answers (another Space, an unattended relaunch)
    # holds the main thread and ignores AppleScript quit (#457).
    handler = _NoticeHandler.alloc().init()
    handler.alert = alert
    handler.url = release.html_url
    for tag, button in enumerate(alert.buttons()):
        button.setTag_(tag)
        button.setTarget_(handler)
        button.setAction_("noticeButtonClicked:")
    _open_notices.add(handler)
    alert.layout()
    window = alert.window()
    window.center()
    NSApp.activateIgnoringOtherApps_(True)
    window.makeKeyAndOrderFront_(None)
    return False  # The window opens the notes itself when its button is clicked.


def _dispatch(callback: Callable[[], None]) -> None:
    from PyObjCTools.AppHelper import callAfter

    callAfter(callback)


def start(version: str, snapshot: Mapping[str, Any], language: str) -> None:
    start_notice(version, snapshot, lambda release: show_notice(release, language), _dispatch)
