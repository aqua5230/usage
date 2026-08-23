# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Background-safe release-check scheduling and update-cache maintenance."""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol

import update_checker
import update_gate
import usage_diagnosis_snapshot
from menubar.prefs import _auto_update_check_enabled
from prefs import _load_preferences, _save_preferences

logger = logging.getLogger(__name__)


class _UpdateApp(Protocol):
    def performSelectorOnMainThread_withObject_waitUntilDone_(
        self, selector: str, obj: Any, wait: bool
    ) -> None: ...

    def _check_update_in_background(
        self,
        *,
        manual: bool,
        ignore_cooldown: bool,
        ignore_skipped: bool,
    ) -> None: ...


def clear_stale_update_cache() -> None:
    from menubar.app import _current_version

    try:
        current_version = _current_version()
        prefs = _load_preferences()
        updated_cache = update_gate.stale_cache_reset(prefs, current_version)
        if updated_cache is not None:
            prefs["last_update_check"] = updated_cache
            _save_preferences(prefs)
    except Exception:
        pass


def maybe_check_update_in_background(app: _UpdateApp) -> None:
    usage_diagnosis_snapshot.maybe_schedule_refresh()
    app._check_update_in_background(
        manual=False,
        ignore_cooldown=False,
        ignore_skipped=False,
    )


def check_update_in_background(
    app: _UpdateApp,
    *,
    manual: bool,
    ignore_cooldown: bool,
    ignore_skipped: bool,
) -> None:
    from menubar.app import _current_version

    prefs = _load_preferences()
    if not manual and not _auto_update_check_enabled(prefs):
        return

    if not manual and not update_gate.auto_check_is_due(prefs):
        return

    if not ignore_cooldown and update_gate.dismissed_recently(prefs):
        return

    try:
        current_version = _current_version()
        check_result = update_checker.check_latest_release_result(current_version)
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("update check failed", exc_info=True)
        if manual:
            app.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_showUpdateCheckFailed:",
                None,
                False,
            )
        return

    if check_result.failed:
        if manual:
            app.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_showUpdateCheckFailed:",
                None,
                False,
            )
        return

    release = check_result.release
    prefs["last_update_check"] = update_gate.build_check_cache_entry(current_version, release)
    _save_preferences(prefs)

    if release is None:
        if manual:
            app.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_showNoUpdateAvailable:",
                None,
                False,
            )
        return

    if not ignore_skipped and prefs.get("update_skipped_version") == release.version:
        return

    app.performSelectorOnMainThread_withObject_waitUntilDone_(
        "_showUpdateAlert:",
        release,
        False,
    )
