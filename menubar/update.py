# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Background-safe release-check scheduling and update-cache maintenance."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Protocol

import usage_diagnosis_snapshot
from installer import claude_pane
from menubar.prefs import _auto_update_check_enabled
from prefs import _load_preferences, _save_preferences
from updates import checker as update_checker
from updates import gate as update_gate

logger = logging.getLogger(__name__)


class _UpdateApp(Protocol):
    language: str
    _auto_check_schedule: update_gate.AutoCheckSchedule

    def checkForUpdates_(self, sender: Any) -> None: ...

    def performSelectorOnMainThread_withObject_waitUntilDone_(
        self, selector: str, obj: Any, wait: bool
    ) -> None: ...

    def _check_update_in_background(
        self,
        *,
        manual: bool,
        ignore_cooldown: bool,
        ignore_skipped: bool,
    ) -> bool: ...


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
    try:
        claude_pane.refresh_claude_pane()
    except (OSError, SystemExit):
        logger.warning("Claude Code pane refresh failed", exc_info=True)
    if app._auto_check_schedule.try_begin(time.time()):
        _run_auto_check(app)


def _run_auto_check(app: _UpdateApp) -> None:
    failed = True
    try:
        failed = bool(
            app._check_update_in_background(
                manual=False,
                ignore_cooldown=False,
                ignore_skipped=False,
            )
        )
    finally:
        app._auto_check_schedule.finish(time.time(), failed=failed)


def on_poll_tick(app: _UpdateApp) -> None:
    clear_stale_update_cache()
    if app._auto_check_schedule.try_begin(time.time()):
        threading.Thread(target=_run_auto_check, args=(app,), daemon=True).start()


def check_manually(app: _UpdateApp) -> None:
    threading.Thread(
        target=app._check_update_in_background,
        kwargs={"manual": True, "ignore_cooldown": True, "ignore_skipped": True},
        daemon=True,
    ).start()


def show_update_check_failed(app: _UpdateApp, reason: str | None) -> None:
    from i18n import _t
    from menubar.chrome import _make_alert

    alert = _make_alert()
    alert.setMessageText_(_t(app.language, "update_check_failed"))
    if reason is not None:
        alert.setInformativeText_(_t(app.language, "update_check_failed_" + reason))
    alert.addButtonWithTitle_(_t(app.language, "update_btn_retry"))
    alert.addButtonWithTitle_(_t(app.language, "report_share_close"))
    if int(alert.runModal()) == 1000:
        app.checkForUpdates_(None)


def check_update_in_background(
    app: _UpdateApp,
    *,
    manual: bool,
    ignore_cooldown: bool,
    ignore_skipped: bool,
) -> bool:
    from menubar.app import _current_version

    prefs = _load_preferences()
    if not manual and not _auto_update_check_enabled(prefs):
        return False

    if not manual and not update_gate.auto_check_is_due(prefs):
        return False

    if not ignore_cooldown and update_gate.dismissed_recently(prefs):
        return False

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
        return True

    if check_result.failed:
        if manual:
            app.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_showUpdateCheckFailed:",
                check_result.failure_reason,
                False,
            )
        return True

    release = check_result.release
    # Re-read: the network check can take seconds, and a toggle saved meanwhile must survive.
    prefs = _load_preferences()
    prefs["last_update_check"] = update_gate.build_check_cache_entry(current_version, release)
    _save_preferences(prefs)

    if release is None:
        if manual:
            app.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_showNoUpdateAvailable:",
                None,
                False,
            )
        return False

    if not ignore_skipped and prefs.get("update_skipped_version") == release.version:
        return False

    app.performSelectorOnMainThread_withObject_waitUntilDone_(
        "_showUpdateAlert:",
        release,
        False,
    )
    return False
