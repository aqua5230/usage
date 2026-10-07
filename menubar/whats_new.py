# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Present post-update notes on the Cocoa main thread."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from updates.checker import ReleaseInfo
from updates.release_notes import alert_release_notes
from updates.whats_new import start_notice
from usage_common.i18n import _t


def show_notice(release: ReleaseInfo, language: str) -> bool:
    from menubar.app import UPDATE_ALERT_BODY_LIMIT
    from menubar.chrome import _make_alert

    alert = _make_alert()
    alert.setMessageText_(_t(language, "whats_new_title", version=release.version))
    alert.setInformativeText_(alert_release_notes(release.body, language, UPDATE_ALERT_BODY_LIMIT))
    alert.addButtonWithTitle_(_t(language, "whats_new_ok"))
    alert.addButtonWithTitle_(_t(language, "whats_new_open"))
    return int(alert.runModal()) == 1001


def _dispatch(callback: Callable[[], None]) -> None:
    from PyObjCTools.AppHelper import callAfter

    callAfter(callback)


def start(version: str, snapshot: Mapping[str, Any], language: str) -> None:
    start_notice(version, snapshot, lambda release: show_notice(release, language), _dispatch)
