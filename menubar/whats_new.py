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

from menubar import notice_panel
from updates.checker import ReleaseInfo
from updates.release_notes import alert_release_notes
from updates.whats_new import start_notice
from usage_common.i18n import _t

_OPEN_NOTES = notice_panel.FIRST_BUTTON + 1


def show_notice(release: ReleaseInfo, language: str) -> bool:
    from menubar.app import UPDATE_ALERT_BODY_LIMIT

    def choose(choice: int) -> None:
        if choice == _OPEN_NOTES:
            webbrowser.open(release.html_url)

    notice_panel.present(
        _t(language, "whats_new_title", version=release.version),
        alert_release_notes(release.body, language, UPDATE_ALERT_BODY_LIMIT),
        [_t(language, "whats_new_ok"), _t(language, "whats_new_open")],
        choose,
    )
    return False  # The panel opens the notes itself when its button is clicked.


def _dispatch(callback: Callable[[], None]) -> None:
    from PyObjCTools.AppHelper import callAfter

    callAfter(callback)


def start(version: str, snapshot: Mapping[str, Any], language: str) -> None:
    start_notice(version, snapshot, lambda release: show_notice(release, language), _dispatch)
