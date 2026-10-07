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
import webbrowser
from typing import Any, Protocol

import usage_diagnosis_snapshot
from i18n import _t
from installer import claude_pane
from prefs import _load_preferences, _save_preferences
from updates import checker as update_checker
from updates import gate as update_gate
from updates.release_notes import alert_release_notes
from usage_common.app_version import current_version as _current_version

logger = logging.getLogger(__name__)


class _UpdateApp(Protocol):
    language: str
    _auto_check_schedule: update_gate.AutoCheckSchedule

    def performSelectorOnMainThread_withObject_waitUntilDone_(
        self, selector: str, obj: Any, wait: bool
    ) -> None: ...

    def _check_update_in_background(self) -> bool: ...


def clear_stale_update_cache() -> None:
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
        failed = bool(app._check_update_in_background())
    finally:
        app._auto_check_schedule.finish(time.time(), failed=failed)


def on_poll_tick(app: _UpdateApp) -> None:
    clear_stale_update_cache()
    if app._auto_check_schedule.try_begin(time.time()):
        threading.Thread(target=_run_auto_check, args=(app,), daemon=True).start()


def check_update_in_background(app: _UpdateApp) -> bool:
    prefs = _load_preferences()
    if not update_gate.auto_check_is_due(prefs):
        return False

    if update_gate.dismissed_recently(prefs):
        return False

    try:
        current_version = _current_version()
        check_result = update_checker.check_latest_release_result(current_version)
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("update check failed", exc_info=True)
        return True

    if check_result.failed:
        return True

    release = check_result.release
    # Re-read: the network check can take seconds, and a toggle saved meanwhile must survive.
    prefs = _load_preferences()
    prefs["last_update_check"] = update_gate.build_check_cache_entry(current_version, release)
    _save_preferences(prefs)

    if release is None:
        return False

    if prefs.get("update_skipped_version") == release.version:
        return False

    app.performSelectorOnMainThread_withObject_waitUntilDone_(
        "_showUpdateAlert:",
        release,
        False,
    )
    return False


def show_update_alert(app: _UpdateApp, release: update_checker.ReleaseInfo, alert: Any) -> None:
    from menubar.app import UPDATE_ALERT_BODY_LIMIT

    alert.setMessageText_(_t(app.language, "update_alert_title", version=release.version))
    alert.setInformativeText_(
        alert_release_notes(release.body, app.language, UPDATE_ALERT_BODY_LIMIT)
    )
    alert.addButtonWithTitle_(_t(app.language, "update_btn_download"))
    alert.addButtonWithTitle_(_t(app.language, "update_btn_later"))
    alert.addButtonWithTitle_(_t(app.language, "update_btn_skip"))
    result = int(alert.runModal())
    action, pref_updates = update_gate.resolve_alert_choice(result, release.version)
    if action == "open":
        webbrowser.open(release.html_url)
        return

    prefs = _load_preferences()
    prefs.update(pref_updates)
    if action == "dismiss":
        prefs["update_dismissed_at"] = time.time()
    _save_preferences(prefs)
