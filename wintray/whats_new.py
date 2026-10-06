# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Windows post-update notice in the same native message box as the update alert."""

from __future__ import annotations

import ctypes
from collections.abc import Mapping
from typing import Any

from i18n import _t
from updates.checker import ReleaseInfo
from updates.release_notes import alert_release_notes
from updates.whats_new import start_notice

# MessageBoxW needs no comctl32 v6 activation context, which the bundle's manifest does not
# request; TaskDialogIndirect does. Yes/No labels come from the system language.
_MB_YESNO_INFORMATION = 0x44
_IDYES = 6


def _message_box(text: str, style: int) -> int:
    library_name = "windll"
    windll: Any = getattr(ctypes, library_name)
    return int(windll.user32.MessageBoxW(0, text, "usage", style))


def show_notice(release: ReleaseInfo, language: str) -> bool:
    from wintray.app import UPDATE_ALERT_BODY_LIMIT

    title = _t(language, "whats_new_title", version=release.version)
    body = alert_release_notes(release.body, language, UPDATE_ALERT_BODY_LIMIT)
    prompt = _t(language, "whats_new_open_prompt")
    return _message_box(f"{title}\n\n{body}\n\n{prompt}", _MB_YESNO_INFORMATION) == _IDYES


def start(version: str, snapshot: Mapping[str, Any], language: str) -> None:
    # Native dialogs own their message loop and can run on the fetch thread.
    start_notice(
        version,
        snapshot,
        lambda release: show_notice(release, language),
        lambda callback: callback(),
    )
