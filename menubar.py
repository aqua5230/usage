# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# mypy: disable-error-code="import-untyped,misc"
# PyObjC modules do not ship type stubs, and their base classes resolve to Any in mypy.
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import tomllib
import webbrowser
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSScreen,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer

import agy_loader
import codex_loader
import critter_frames
import login_item
import menubar_actions
import menubar_menu
import menubar_notify
import menubar_refresh
import menubar_state
import menubar_title
import menubar_update
import panel_window_state
import panels
import update_checker
import update_gate
from burn_rate import BurnRateTracker
from fsevents_watch import FileEventChanges, cleanup_fsevents, setup_fsevents
from history_loader import (
    UsageEntry,
)
from history_loader import (
    flush_caches_on_terminate as flush_history_cache,
)
from i18n import _t, packaged_resource_path
from menubar_actions import (
    show_forwarder_mode_prompt_if_needed as show_forwarder_mode_prompt_if_needed,
)
from menubar_chrome import (
    _make_alert,
)
from menubar_popover import PopoverViewController, _popover_size
from menubar_prefs import (
    _auto_update_check_enabled,
    _hide_agy_enabled,
    _hide_claude_enabled,
    _hide_codex_enabled,
    _quota_card_order,
    _quota_notification_thresholds,
    _quota_notifications_enabled,
    _window_keeper_enabled,
)
from menubar_state import (
    CLAUDE_COLOR as CLAUDE_COLOR,
)
from menubar_state import (
    CODEX_COLOR as CODEX_COLOR,
)
from menubar_state import (
    DANGER_COLOR as DANGER_COLOR,
)
from menubar_state import (
    SERVICE_ALERT_GAP as SERVICE_ALERT_GAP,
)
from menubar_state import (
    WARN_COLOR as WARN_COLOR,
)
from menubar_state import (
    WEEKLY_FORECAST_MIN_SPAN_SECONDS,
    WEEKLY_FORECAST_WINDOW_SECONDS,
    CodexStaleState,
    PopoverState,
    QuotaRowState,
    _missing_row,
    _quota_row,
)
from menubar_state import (
    _bar_color as _bar_color,
)
from menubar_state import (
    _classify_history_load_error as _classify_history_load_error,
)
from menubar_state import (
    _empty_state as _empty_state,
)
from menubar_state import (
    _error_state as _error_state,
)
from menubar_state import (
    _format_percent as _format_percent,
)
from menubar_state import (
    _group_name as _group_name,
)
from menubar_state import (
    _statusline_payload as _statusline_payload,
)
from menubar_state import (
    _today_title as _today_title,
)
from menubar_state import (
    format_human_time as format_human_time,
)
from panel_window import PanelWindow
from panel_window_state import save_panel_window_top_left
from panels.base import (
    load_active_panel_id,
    save_active_panel_id,
)
from panels.dynamic_height import clamp_content_height
from prefs import _load_preferences, _save_preferences
from pricing import warm_up_pricing
from statusline_settings import (
    _claude_settings_path as _claude_settings_path,
)
from statusline_settings import (
    _disable_statusline_settings as _disable_statusline_settings,
)
from statusline_settings import (
    _enable_statusline_settings as _enable_statusline_settings,
)
from statusline_settings import (
    _load_claude_settings as _load_claude_settings,
)
from statusline_settings import (
    _save_claude_settings as _save_claude_settings,
)
from statusline_settings import (
    _statusline_command_target_exists as _statusline_command_target_exists,
)
from statusline_settings import (
    _statusline_enabled as _statusline_enabled,
)
from statusline_settings import (
    _toggle_statusline_settings as _toggle_statusline_settings,
)
from update_release_notes import format_release_notes
from usage_client import ClaudeUsageClient, PollOutcome
from usage_lang import detect_lang
from usage_notifications import NotificationEvent, QuotaNotifier
from usage_rate import UsageRateTracker

__all__ = [
    "CLAUDE_COLOR",
    "CODEX_COLOR",
    "DANGER_COLOR",
    "WARN_COLOR",
    "WEEKLY_FORECAST_MIN_SPAN_SECONDS",
    "WEEKLY_FORECAST_WINDOW_SECONDS",
    "CodexStaleState",
    "PopoverState",
    "QuotaRowState",
    "_bar_color",
    "_format_percent",
    "_group_name",
    "_missing_row",
    "_quota_row",
    "format_human_time",
    "_auto_update_check_enabled",
    "_hide_agy_enabled",
    "_hide_claude_enabled",
    "_hide_codex_enabled",
    "_quota_card_order",
    "_quota_notification_thresholds",
    "_quota_notifications_enabled",
    "_window_keeper_enabled",
]

UPDATE_ALERT_BODY_LIMIT = 2000
SLOW_POLL_INTERVAL_S = 300.0

logger = logging.getLogger(__name__)


def _detect_language() -> str:
    return detect_lang()


def _session_resume_enabled() -> bool:
    # State lives in ~/.claude/settings.json (a hook), not in usage's prefs file.
    try:
        import session_hooks

        return session_hooks.is_resume_enabled()
    except Exception:
        return False


def _terse_mode_enabled() -> bool:
    try:
        import session_hooks

        return session_hooks.is_terse_mode_enabled()
    except Exception:
        return False


def _current_version() -> str:
    try:
        return metadata.version("usage-cli")
    except metadata.PackageNotFoundError as exc:
        pyproject = packaged_resource_path(
            "pyproject.toml", Path(__file__).with_name("pyproject.toml")
        )
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        if isinstance(version, str):
            return version
        raise RuntimeError("project.version missing from pyproject.toml") from exc


_APP_DELEGATE: AppDelegate | None = None


class AppDelegate(NSObject):
    status_item = objc.ivar()
    popover = objc.ivar()
    popover_controller = objc.ivar()
    timer = objc.ivar()
    timer_interval = objc.ivar()
    mock = objc.ivar()
    interval = objc.ivar()
    tracker = objc.ivar()
    codex_tracker = objc.ivar()
    agy_tracker = objc.ivar()
    latest_state = objc.ivar()
    active_panel = objc.ivar()
    codex_5h_pct = objc.ivar()
    codex_model = objc.ivar()
    burn_rate_trackers = objc.ivar()
    _refresh_in_flight = objc.ivar()
    _refresh_queued = objc.ivar()
    _file_event_refresh_timer = objc.ivar()
    _last_file_event_refresh_started_at = objc.ivar()
    _fs_stream = objc.ivar()
    _history_entries_cache = objc.ivar()
    _history_entries_cache_fingerprint = objc.ivar()
    _history_source_tracker = objc.ivar()
    _history_load_error_key = objc.ivar()
    _quota_notifier = objc.ivar()
    _switch_menu_action_taken = objc.ivar()
    _pre_talent_panel_id = objc.ivar()
    _discussion_window_controller = objc.ivar()
    _usage_client = objc.ivar()
    critter_timer = objc.ivar()
    critter_frame = objc.ivar()
    critter_interval = objc.ivar()
    critter_group = objc.ivar()
    critter_last_advanced_at = objc.ivar()
    dragon_frame = objc.ivar()
    dragon_group = objc.ivar()
    dragon_last_advanced_at = objc.ivar()
    lion_frame = objc.ivar()
    lion_group = objc.ivar()
    lion_last_advanced_at = objc.ivar()
    language = objc.ivar()

    def initWithMock_interval_(self, mock: bool, interval: int) -> AppDelegate:
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.mock = mock
        self.interval = max(30, interval)
        self.timer = None
        self.timer_interval = 0.0
        self.tracker = UsageRateTracker(mock=mock)
        self.codex_tracker = UsageRateTracker(mock=mock, load=codex_loader.load_entries)
        self.agy_tracker = UsageRateTracker(mock=mock, load=cast(Any, agy_loader.load_entries))
        self.language = _detect_language()
        self.codex_5h_pct = None
        self.codex_model = "unknown"
        self.latest_state = _empty_state(self.language)
        self.active_panel = panels.get_panel(load_active_panel_id())
        self.burn_rate_trackers = {
            "claude_session": BurnRateTracker(),
            "claude_weekly": BurnRateTracker(),
            "codex_session": BurnRateTracker(),
            "codex_weekly": BurnRateTracker(),
        }
        self._quota_notifier = QuotaNotifier(_quota_notification_thresholds())
        self._refresh_in_flight = False
        self._refresh_queued = False
        self._file_event_refresh_timer = None
        self._last_file_event_refresh_started_at = None
        self._fs_stream = None
        self._history_entries_cache = None
        self._history_entries_cache_fingerprint = None
        self._history_source_tracker = menubar_state.HistorySourceTracker()
        self._history_load_error_key = None
        self._switch_menu_action_taken = False
        self._pre_talent_panel_id = None
        self._discussion_window_controller = None
        self._usage_client = ClaudeUsageClient(mock=mock)
        self.critter_timer = None
        self.critter_frame = 0
        self.critter_interval = 0.0
        self.critter_group = 0
        self.critter_last_advanced_at = 0.0
        self.dragon_frame = 0
        self.dragon_group = 0
        self.dragon_last_advanced_at = 0.0
        self.lion_frame = 0
        self.lion_group = 0
        self.lion_last_advanced_at = 0.0
        self._menubar_text_cache: dict[str, Any] = {}
        self._last_button_title_key: tuple[str, int | None, int | None, int | None] | None = None
        self._last_plain_title_key: tuple[str] | None = None
        return self

    def applicationDidFinishLaunching_(self, notification: Any) -> None:
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength,
        )
        # Do not change this string; it is the stable identity for saved menu bar position.
        self.status_item.setAutosaveName_("usage")
        button = self.status_item.button()
        button.setTitle_("🐾 ...")
        button.setTarget_(self)
        button.setAction_("togglePopover:")

        self.popover_controller = PopoverViewController.alloc().initWithPanel_delegate_(
            self.active_panel,
            self,
        )
        size = _popover_size(self.latest_state, self.active_panel)
        self.popover = PanelWindow.alloc().initWithContentRect_(
            NSMakeRect(0.0, 0.0, size.width, size.height)
        )
        self.popover.setRoundedContentView_(self.popover_controller.view())
        self.popover.setDelegate_(self)

        self._request_notification_authorization()
        self._refresh()
        self._reschedule_poll_timer(max(self.interval, SLOW_POLL_INTERVAL_S))
        self._fs_stream = setup_fsevents(self)
        self._history_source_tracker.set_incremental_enabled(self._fs_stream is not None)
        warm_up_pricing(self._refresh_after_pricing_warm_up)
        thread = threading.Thread(target=self._maybe_check_update_in_background, daemon=True)
        thread.start()

    def panelContentHeight_forView_(self, value: object, view: Any) -> None:
        if view is not self.popover_controller.currentContentView():
            return
        screen = NSScreen.mainScreen()
        maximum = (
            self.active_panel.preferred_size()[1]
            if screen is None
            else float(screen.visibleFrame().size.height) - 24.0
        )
        height = clamp_content_height(value, maximum)
        if height is None:
            return
        panel_window_state.save_panel_content_height(self.active_panel.id, height)
        size = NSMakeSize(self.active_panel.preferred_size()[0], height)
        self._set_panel_window_size(size)
        self.popover_controller.view().setFrameSize_(size)
        self.popover_controller.syncPanelFrames()

    def panelBeginWindowDrag_(self, view: Any) -> None:
        if view is not self.popover_controller.currentContentView():
            return
        event = NSApplication.sharedApplication().currentEvent()
        if event is not None:
            self.popover.performWindowDragWithEvent_(event)

    def _refresh_after_pricing_warm_up(self) -> None:
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "refreshNow:",
            None,
            False,
        )

    def timerFired_(self, timer: Any) -> None:
        self._refresh()
        self._clear_stale_update_cache()

    def _reschedule_poll_timer(self, interval: float) -> None:
        if self.timer is not None and self.timer_interval == interval:
            return
        self._stop_poll_timer()
        scheduled_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_
        self.timer = scheduled_timer(interval, self, "timerFired:", None, True)
        self.timer_interval = interval
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes)

    def _stop_poll_timer(self) -> None:
        timer = self.timer
        self.timer = None
        self.timer_interval = 0.0
        if timer is not None:
            timer.invalidate()

    def _panel_window_will_show(self) -> None:
        self._reschedule_poll_timer(self.interval)

    def _panel_window_did_show(self) -> None:
        self.refreshNow_(None)

    def _panel_window_did_hide(self) -> None:
        self._reschedule_poll_timer(max(self.interval, SLOW_POLL_INTERVAL_S))

    def windowDidMove_(self, notification: Any) -> None:
        if notification.object() is self.popover and self._panel_window_is_visible():
            self._save_panel_window_top_left()

    def windowWillClose_(self, notification: Any) -> None:
        if notification.object() is self.popover:
            self._save_panel_window_top_left()
            self._panel_window_did_hide()

    def refreshNow_(self, sender: Any) -> None:
        self._refresh(queue_if_busy=True)

    def installHook_(self, sender: Any) -> None:
        thread = threading.Thread(target=self._install_hook_in_background, daemon=True)
        thread.start()

    def toggleStatusline_(self, sender: Any) -> None:
        thread = threading.Thread(target=self._toggle_statusline_in_background, daemon=True)
        thread.start()

    def installStatusline_(self, sender: Any) -> None:
        thread = threading.Thread(
            target=self._statusline_action_in_background,
            args=("install",),
            daemon=True,
        )
        thread.start()

    def uninstallStatusline_(self, sender: Any) -> None:
        thread = threading.Thread(
            target=self._statusline_action_in_background,
            args=("uninstall",),
            daemon=True,
        )
        thread.start()

    def analyzeUsage_(self, sender: Any) -> None:
        period = _analysis_period_from_project_range(str(sender or "30d"))
        thread = threading.Thread(
            target=self._analyze_usage_in_background,
            args=(period,),
            daemon=True,
        )
        thread.start()

    def quitApp_(self, sender: Any) -> None:
        self._stop_poll_timer()
        NSApp.terminate_(sender)

    def applicationWillTerminate_(self, notification: Any) -> None:
        self._stop_poll_timer()
        cleanup_fsevents(self._fs_stream)
        self._fs_stream = None
        self._stop_critter_timer()
        asyncio.run(self._usage_client.aclose())
        if self._file_event_refresh_timer is not None:
            self._file_event_refresh_timer.invalidate()
            self._file_event_refresh_timer = None
        flush_history_cache()
        codex_loader.flush_caches_on_terminate()
        agy_loader.flush_caches_on_terminate()
        if self._discussion_window_controller is not None:
            self._discussion_window_controller.shutdown()
        if (
            hasattr(self, "popover")
            and self.popover is not None
            and self._panel_window_is_visible()
        ):
            self._save_panel_window_top_left()
        if hasattr(self, "popover_controller") and self.popover_controller is not None:
            self.popover_controller.teardown()

    def switchPanel_(self, sender: Any) -> None:
        menubar_menu.build_switch_menu(self, sender)

    def selectPanel_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        panel_id = str(sender.representedObject())
        self._set_active_panel_id(panel_id)

    def toggleTalentMarket_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        if self.active_panel.id != "talent_market":
            self._pre_talent_panel_id = self.active_panel.id
            self._set_active_panel_id("talent_market")
            return

        target_panel_id = self._pre_talent_panel_id or "classic"
        self._set_active_panel_id(target_panel_id)

    def toggleAiDaily_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        self._close_popover_after_menu()
        webbrowser.open("https://aqua5230.github.io/ai-updates/")

    def toggleDiscussion_(self, sender: Any) -> None:
        from discussion_window import DiscussionWindowController

        self._mark_switch_menu_action()
        if self._discussion_window_controller is None:
            self._discussion_window_controller = DiscussionWindowController()
        self._discussion_window_controller.show(
            close_popover=self._close_popover_after_menu,
        )

    def toggleLaunchAtLogin_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        try:
            if login_item.is_enabled():
                login_item.disable()
            else:
                login_item.enable()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("toggle launch at login failed", exc_info=True)

    def toggleHideClaude_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        prefs = _load_preferences()
        enabled = not _hide_claude_enabled(prefs)
        prefs["hide_claude_section"] = enabled
        _save_preferences(prefs)
        if hasattr(sender, "setState_"):
            sender.setState_(1 if enabled else 0)
        self.latest_state.hide_claude = enabled
        self.popover_controller.setState_(self.latest_state)
        menubar_title._set_button_title(self, self.latest_state)

    def toggleHideCodex_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        prefs = _load_preferences()
        enabled = not _hide_codex_enabled(prefs)
        prefs["hide_codex_section"] = enabled
        _save_preferences(prefs)
        if hasattr(sender, "setState_"):
            sender.setState_(1 if enabled else 0)
        self.latest_state.hide_codex = enabled
        self.popover_controller.setState_(self.latest_state)
        menubar_title._set_button_title(self, self.latest_state)

    def toggleHideAgy_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        prefs = _load_preferences()
        enabled = not _hide_agy_enabled(prefs)
        prefs["hide_agy_section"] = enabled
        _save_preferences(prefs)
        if hasattr(sender, "setState_"):
            sender.setState_(1 if enabled else 0)
        self.latest_state.hide_agy = enabled
        self.popover_controller.setState_(self.latest_state)
        menubar_title._set_button_title(self, self.latest_state)

    def toggleQuotaNotifications_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        prefs = _load_preferences()
        enabled = not _quota_notifications_enabled(prefs)
        prefs["quota_notifications"] = enabled
        _save_preferences(prefs)
        if hasattr(sender, "setState_"):
            sender.setState_(1 if enabled else 0)
        if enabled:
            self._request_notification_authorization()

    def toggleWindowKeeper_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        prefs = _load_preferences()
        enabled = not _window_keeper_enabled(prefs)
        prefs["window_keeper"] = enabled
        prefs.pop("agy_window_keeper", None)
        _save_preferences(prefs)
        if hasattr(sender, "setState_"):
            sender.setState_(1 if enabled else 0)
        if enabled:
            alert = _make_alert()
            alert.setMessageText_(_t(self.language, "window_keeper_sleep_title"))
            alert.setInformativeText_(_t(self.language, "window_keeper_sleep_body"))
            alert.runModal()

    def toggleSessionResume_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        thread = threading.Thread(target=self._toggle_session_resume_in_background, daemon=True)
        thread.start()

    def _toggle_session_resume_in_background(self) -> None:
        menubar_actions.toggle_session_resume_in_background(self)

    def _finishSessionResume_(self, result: dict[str, Any]) -> None:
        alert = _make_alert()
        if result.get("ok", True):
            key = "resume_enabled_restart" if result.get("enabled") else "resume_disabled_msg"
            alert.setMessageText_(_t(self.language, key))
        else:
            alert.setMessageText_(_t(self.language, "resume_action_failed"))
            alert.setInformativeText_(str(result.get("output") or ""))
        alert.runModal()
        self._refresh()

    def toggleTerseMode_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        thread = threading.Thread(target=self._toggle_terse_mode_in_background, daemon=True)
        thread.start()

    def _toggle_terse_mode_in_background(self) -> None:
        menubar_actions.toggle_terse_mode_in_background(self)

    def _finishTerseMode_(self, result: dict[str, Any]) -> None:
        alert = _make_alert()
        if result.get("ok", True):
            key = "terse_mode_enabled_msg" if result.get("enabled") else "terse_mode_disabled_msg"
            alert.setMessageText_(_t(self.language, key))
        else:
            alert.setMessageText_(_t(self.language, "resume_action_failed"))
            alert.setInformativeText_(str(result.get("output") or ""))
        alert.runModal()
        self._refresh()

    def _clear_stale_update_cache(self) -> None:
        menubar_update.clear_stale_update_cache()

    def _maybe_check_update_in_background(self) -> None:
        menubar_update.maybe_check_update_in_background(self)

    def _check_update_in_background(
        self,
        *,
        manual: bool,
        ignore_cooldown: bool,
        ignore_skipped: bool,
    ) -> None:
        menubar_update.check_update_in_background(
            self,
            manual=manual,
            ignore_cooldown=ignore_cooldown,
            ignore_skipped=ignore_skipped,
        )

    def _showUpdateAlert_(self, release: update_checker.ReleaseInfo) -> None:
        alert = _make_alert()
        alert.setMessageText_(_t(self.language, "update_alert_title", version=release.version))
        alert.setInformativeText_(format_release_notes(release.body, UPDATE_ALERT_BODY_LIMIT))
        alert.addButtonWithTitle_(_t(self.language, "update_btn_download"))
        alert.addButtonWithTitle_(_t(self.language, "update_btn_later"))
        alert.addButtonWithTitle_(_t(self.language, "update_btn_skip"))
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

    def _showNoUpdateAvailable_(self, result: Any) -> None:
        alert = _make_alert()
        alert.setMessageText_(_t(self.language, "update_no_new_version"))
        alert.runModal()

    def _showUpdateCheckFailed_(self, result: Any) -> None:
        alert = _make_alert()
        alert.setMessageText_(_t(self.language, "update_check_failed"))
        alert.runModal()

    def _set_active_panel_id(self, panel_id: str) -> None:
        panel = panels.get_panel(panel_id)
        save_active_panel_id(panel.id)
        self.active_panel = panel
        self.popover_controller.switchToPanel_(panel)
        self._set_panel_window_size(_popover_size(self.latest_state, panel))
        if panel.id == "talent_market":
            # Talent data is fetched in the background refresh; switchToPanel_
            # injected the last (talent-less) state, so kick a refresh to fill it.
            self._refresh()

    def _show_popover_from_button(self, button: Any) -> None:
        frame = self.popover.frame()
        size = (float(frame.size.width), float(frame.size.height))
        if (top_left := panel_window_state.load_panel_window_top_left()) is not None:
            origin: tuple[float, float] | None = (top_left[0], top_left[1] - size[1])
        else:
            origin = panel_window_state.load_panel_window_origin()
        if origin is None:
            button_window = button.window()
            button_rect = button.convertRect_toView_(button.bounds(), None)
            screen_rect = button_window.convertRectToScreen_(button_rect)
            origin = (
                float(screen_rect.origin.x)
                + (float(screen_rect.size.width) - size[0]) / 2.0,
                float(screen_rect.origin.y) - size[1],
            )
        visible_frames = [
            (
                float(screen.visibleFrame().origin.x),
                float(screen.visibleFrame().origin.y),
                float(screen.visibleFrame().size.width),
                float(screen.visibleFrame().size.height),
            )
            for screen in NSScreen.screens()
        ]
        origin = panel_window_state.clamp_origin_to_visible_frames(
            origin, size, visible_frames
        )
        self.popover.setFrameOrigin_(NSMakePoint(*origin))
        self._panel_window_will_show()
        self.popover.makeKeyAndOrderFront_(None)
        self._panel_window_did_show()

    def _set_panel_window_size(self, size: Any) -> None:
        self.popover.setContentSizeKeepingTopLeft_(size)

    def _panel_window_is_visible(self) -> bool:
        return bool(self.popover.isVisible())

    def _save_panel_window_top_left(self) -> None:
        if not hasattr(self, "popover") or self.popover is None:
            return
        frame = self.popover.frame()
        top_left = (float(frame.origin.x), float(frame.origin.y) + float(frame.size.height))
        save_panel_window_top_left(top_left)

    def _mark_switch_menu_action(self) -> None:
        self._switch_menu_action_taken = True

    def _close_popover_after_menu(self) -> None:
        if not hasattr(self, "popover") or self.popover is None:
            return
        if not self._panel_window_is_visible():
            return
        self.popover.close()

    def _resync_popover_after_menu(self) -> None:
        if not hasattr(self, "popover") or not hasattr(self, "popover_controller"):
            return
        if not hasattr(self, "status_item"):
            return
        if self.popover is None or self.popover_controller is None or self.status_item is None:
            return
        if not self._panel_window_is_visible():
            return
        self.popover_controller.setState_(self.latest_state)
        self._set_panel_window_size(_popover_size(self.latest_state, self.active_panel))

    def animateCritters_(self, timer: Any) -> None:
        now = time.monotonic()
        intervals = self._critter_intervals()
        previous = (
            float(self.critter_last_advanced_at),
            float(self.dragon_last_advanced_at),
            float(self.lion_last_advanced_at),
        )
        tick = menubar_state.critter_animation_tick(now, intervals, previous)
        if tick.timer_interval <= 0:
            self._stop_critter_timer()
            return
        if tick.advance[0]:
            self.critter_frame = (
                int(self.critter_frame) + 1
            ) % len(critter_frames.PHOENIX_FRAMES)
            self.critter_last_advanced_at = previous[0] + intervals[0]
        if tick.advance[1]:
            self.dragon_frame = (
                int(self.dragon_frame) + 1
            ) % len(critter_frames.DRAGON_FRAMES)
            self.dragon_last_advanced_at = previous[1] + intervals[1]
        if tick.advance[2]:
            self.lion_frame = (
                int(self.lion_frame) + 1
            ) % len(critter_frames.LION_FRAMES)
            self.lion_last_advanced_at = previous[2] + intervals[2]
        if any(tick.advance):
            menubar_title._set_button_title(self, self.latest_state)

    def _critter_intervals(self) -> tuple[float, float, float]:
        return (
            critter_frames.group_to_interval(int(self.critter_group)),
            critter_frames.group_to_interval(int(self.dragon_group)),
            critter_frames.group_to_interval(int(self.lion_group)),
        )

    def _sync_critter_timer(self) -> None:
        intervals = self._critter_intervals()
        interval = min((value for value in intervals if value > 0), default=0.0)
        now = time.monotonic()
        self.critter_last_advanced_at = now
        self.dragon_last_advanced_at = now
        self.lion_last_advanced_at = now
        if intervals[0] <= 0:
            self.critter_frame = 0
        if intervals[1] <= 0:
            self.dragon_frame = 0
        if intervals[2] <= 0:
            self.lion_frame = 0
        if interval <= 0:
            self._stop_critter_timer()
            return
        if self.critter_timer is not None and self.critter_interval == interval:
            return
        self._stop_critter_timer()
        self.critter_interval = interval
        scheduled_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_
        self.critter_timer = scheduled_timer(interval, self, "animateCritters:", None, True)
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.critter_timer, NSRunLoopCommonModes)

    def _stop_critter_timer(self) -> None:
        timer = self.critter_timer
        self.critter_timer = None
        self.critter_interval = 0.0
        if timer is not None:
            timer.invalidate()

    def togglePopover_(self, sender: Any) -> None:
        if self._panel_window_is_visible():
            self.popover.close()
            return
        self.popover_controller.setState_(self.latest_state)
        self._set_panel_window_size(_popover_size(self.latest_state, self.active_panel))
        button = self.status_item.button()
        self._show_popover_from_button(button)

    def _refresh(self, queue_if_busy: bool = False) -> None:
        if self._refresh_in_flight:
            if queue_if_busy:
                self._refresh_queued = True
            return
        self._refresh_in_flight = True
        thread = threading.Thread(target=self._refresh_in_background, daemon=True)
        thread.start()

    def refreshFromFileEvent_(self, changes: FileEventChanges) -> None:
        self._history_source_tracker.record_changes(
            set(changes.paths),
            needs_full_scan=changes.needs_full_scan,
        )
        now = time.monotonic()
        decision = menubar_state.file_event_refresh_decision(
            now,
            self._last_file_event_refresh_started_at,
            self._file_event_refresh_timer is not None,
        )
        if decision.refresh_now:
            self._last_file_event_refresh_started_at = now
            self._refresh(queue_if_busy=True)
        elif decision.trailing_delay is not None:
            self._file_event_refresh_timer = (
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    decision.trailing_delay,
                    self,
                    "refreshFromTrailingFileEvent:",
                    None,
                    False,
                )
            )

    def refreshFromTrailingFileEvent_(self, _sender: Any) -> None:
        self._file_event_refresh_timer = None
        self._last_file_event_refresh_started_at = time.monotonic()
        self._refresh(queue_if_busy=True)

    def _refresh_in_background(self) -> None:
        submitted = False
        try:
            sources = menubar_refresh.load_sources(self)
            started_at = time.monotonic() if sources.debug_timing else 0.0
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_applyCodexRefreshResult:",
                sources.codex_result,
                True,
            )
            sources.measure("main_apply_codex", started_at)
            result = menubar_refresh.build_result(self, sources)
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_applyRefreshResult:",
                result,
                False,
            )
            submitted = True
        finally:
            if not submitted:
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "_clearRefreshInFlight:",
                    None,
                    False,
                )

    def _applyRefreshResult_(self, result: dict[str, Any]) -> None:
        started_at = time.monotonic() if os.environ.get("USAGE_DEBUG") == "1" else 0.0
        should_refresh_again = False
        try:
            state = result["state"]
            codex_5h_pct = result["codex_5h_pct"]
            codex_model = result.get("codex_model", "unknown")
            self.codex_5h_pct = codex_5h_pct
            self.codex_model = codex_model
            self.latest_state = state
            animation_groups = tuple(
                int(group)
                for group in result.get(
                    "animation_groups",
                    (self.critter_group, self.dragon_group, self.lion_group),
                )
            )
            previous_groups = (
                int(self.critter_group),
                int(self.dragon_group),
                int(self.lion_group),
            )
            self.critter_group, self.dragon_group, self.lion_group = animation_groups
            if animation_groups != previous_groups:
                self._sync_critter_timer()
            self._process_quota_notifications(state)
            if self._panel_window_is_visible():
                self.popover_controller.setState_(self.latest_state)
            self._set_panel_window_size(_popover_size(state, self.active_panel))
            self._inject_web_language(state.language)
            menubar_title._set_button_title(self, state)
        finally:
            should_refresh_again = bool(self._refresh_queued)
            self._refresh_queued = False
            self._refresh_in_flight = False
        if should_refresh_again:
            self._refresh()
        if started_at:
            logger.debug(
                "refresh_timing stage=main_apply elapsed_ms=%.1f",
                (time.monotonic() - started_at) * 1000,
            )

    def _clearRefreshInFlight_(self, _sender: Any) -> None:
        self._refresh_in_flight = False

    def _load_codex_refresh_result(self) -> dict[str, Any]:
        history_scan = None if self.mock else self._history_source_scan()
        try:
            (
                codex_rows,
                codex_5h_pct,
                codex_model,
                codex_stale,
                codex_credits,
            ) = menubar_state.codex_rows(
                mock=self.mock,
                language=self.language,
                burn_rate_trackers=self.burn_rate_trackers,
                jsonl_candidates=(
                    None
                    if history_scan is None
                    else history_scan.codex_rate_limit_candidates
                ),
            )
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Codex quota refresh failed", exc_info=True)
            codex_rows = (
                _missing_row(_t(self.language, "session_label"), CODEX_COLOR, self.language),
                _missing_row(_t(self.language, "weekly_label"), CODEX_COLOR, self.language),
            )
            codex_5h_pct = None
            codex_model = "unknown"
            codex_stale = None
            codex_credits = None
        return {
            "codex_rows": codex_rows,
            "codex_5h_pct": codex_5h_pct,
            "codex_model": codex_model,
            "codex_stale": codex_stale,
            "codex_credits": codex_credits,
            "_history_scan": history_scan,
        }

    def _applyCodexRefreshResult_(self, result: dict[str, Any]) -> None:
        started_at = time.monotonic() if os.environ.get("USAGE_DEBUG") == "1" else 0.0
        codex_rows = result["codex_rows"]
        self.latest_state.codex_session = codex_rows[0]
        self.latest_state.codex_weekly = codex_rows[1]
        self.latest_state.codex_stale = result.get("codex_stale")
        self.latest_state.codex_credits = result.get("codex_credits")
        self.codex_5h_pct = result["codex_5h_pct"]
        self.codex_model = result.get("codex_model", "unknown")
        if self._panel_window_is_visible():
            self.popover_controller.setState_(self.latest_state)
        self._set_panel_window_size(_popover_size(self.latest_state, self.active_panel))
        menubar_title._set_button_title(self, self.latest_state)
        if started_at:
            logger.debug(
                "refresh_timing stage=main_apply_codex_ui elapsed_ms=%.1f",
                (time.monotonic() - started_at) * 1000,
            )

    def _request_notification_authorization(self) -> None:
        if self.mock or not _quota_notifications_enabled():
            return
        try:
            center, constants = menubar_notify.user_notification_center()
            options = constants["badge"] | constants["sound"] | constants["alert"]
            center.requestAuthorizationWithOptions_completionHandler_(
                options,
                lambda granted, error: None,
            )
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("notification authorization failed", exc_info=True)

    def _process_quota_notifications(self, state: PopoverState) -> None:
        try:
            events = self._quota_notifier.update(
                {
                    "claude_session": (
                        state.claude_session.percent,
                        state.claude_session.available,
                    ),
                    "claude_weekly": (state.claude_weekly.percent, state.claude_weekly.available),
                    "codex_session": (state.codex_session.percent, state.codex_session.available),
                    "codex_weekly": (state.codex_weekly.percent, state.codex_weekly.available),
                }
            )
            for event in events:
                if _quota_notifications_enabled() and not self.mock:
                    self._send_quota_notification(event, state)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("quota notification processing failed", exc_info=True)

    def _send_quota_notification(self, event: NotificationEvent, state: PopoverState) -> None:
        try:
            center, _constants = menubar_notify.user_notification_center()
            content_cls, request_cls, sound_cls = menubar_notify.user_notification_classes()
            row = menubar_notify.notification_row(state, event.channel)
            title_key = f"notif_{event.kind}_title"
            body_key = f"notif_{event.kind}_body"
            content = content_cls.alloc().init()
            content.setTitle_(_t(self.language, title_key))
            content.setBody_(
                _t(
                    self.language,
                    body_key,
                    tool=menubar_notify.notification_tool(event.channel),
                    # row.title carries the window-aware label (e.g. Codex free
                    # plan shows "Monthly"); fall back to the slot's scope text.
                    scope=row.title
                    or menubar_notify.notification_scope(self.language, event.channel),
                    pct=_format_percent(row.percent or event.threshold or 0.0),
                    reset=row.reset_text,
                )
            )
            content.setSound_(sound_cls.defaultSound())
            request = request_cls.requestWithIdentifier_content_trigger_(
                f"usage.{event.channel}.{event.kind}.{int(time.time() * 1000)}",
                content,
                None,
            )
            center.addNotificationRequest_withCompletionHandler_(request, lambda error: None)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("send quota notification failed", exc_info=True)

    def _inject_web_language(self, language: str) -> None:
        content_view = self.popover_controller.currentContentView()
        if not hasattr(content_view, "evaluateJavaScript_completionHandler_"):
            return
        content_view.evaluateJavaScript_completionHandler_(
            f"window.usageSetLanguage && window.usageSetLanguage({json.dumps(language)})",
            None,
        )

    def panelDidFirstPaint_(self, view: Any) -> None:
        self.popover_controller.panelDidFirstPaint_(view)

    def _install_hook_in_background(self) -> None:
        menubar_actions.install_hook_in_background(self)

    def _finishHookInstall_(self, result: dict[str, Any]) -> None:
        alert = _make_alert()
        if result["success"]:
            alert.setMessageText_(_t(self.language, "hook_installed_restart"))
        else:
            alert.setMessageText_(_t(self.language, "hook_install_failed"))
            alert.setInformativeText_(
                result["message"] or _t(self.language, "hook_install_failed_default")
            )
        alert.runModal()
        self._refresh()

    def _toggle_statusline_in_background(self) -> None:
        self._statusline_action_in_background("toggle")

    def _statusline_action_in_background(self, action: str) -> None:
        menubar_actions.statusline_action_in_background(self, action)

    def _finishStatuslineAction_(self, result: dict[str, Any]) -> None:
        self._refresh()
        self._refresh_statusline_state()
        if result.get("ok", True):
            return
        alert = _make_alert()
        alert.setMessageText_(_t(self.language, "statusline_action_failed"))
        alert.setInformativeText_(str(result.get("output") or result.get("action") or ""))
        alert.runModal()

    def _refresh_statusline_state(self) -> None:
        self.latest_state.statusline = _statusline_payload(self.language)
        self.popover_controller.setState_(self.latest_state)

    def _analyze_usage_in_background(self, period: str) -> None:
        menubar_actions.analyze_usage_in_background(self, period)

    def _finishAnalyzeUsage_(self, result: dict[str, Any]) -> None:
        if result["success"]:
            return
        alert = _make_alert()
        alert.setMessageText_(_t(self.language, "analysis_failed"))
        alert.setInformativeText_(str(result["message"]))
        alert.runModal()

    async def _fetch(self) -> PollOutcome:
        return cast(PollOutcome, await self._usage_client.fetch_once())

    def _statusline_setup_available(self) -> bool:
        try:
            import setup_hook

            return setup_hook.CLAUDE_SETTINGS.parent.exists() or setup_hook.CODEX_CONFIG.exists()
        except Exception:
            return False

    def _history_sources_fingerprint(self) -> tuple[tuple[str, int, float], ...]:
        return menubar_state.app_history_sources_fingerprint(self)

    def _history_source_scan(self) -> menubar_state.HistorySourceScan:
        return menubar_state.app_history_source_scan(self)

    def _load_history_entries(
        self,
        *,
        scan: menubar_state.HistorySourceScan | None = None,
    ) -> list[UsageEntry]:
        return menubar_state.app_load_history_entries(self, scan=scan)

    def _project_rows(
        self,
        hours_back: int = 24,
        entries: list[UsageEntry] | None = None,
    ) -> list[tuple[str, int, float | None]]:
        return menubar_state.app_project_rows(self, hours_back=hours_back, entries=entries)

def run_app(mock: bool = False, interval: int = 60) -> None:
    global _APP_DELEGATE
    app = NSApplication.sharedApplication()
    _APP_DELEGATE = AppDelegate.alloc().initWithMock_interval_(mock, interval)
    app.setDelegate_(_APP_DELEGATE)
    app.run()


def _generate_analysis_report(period: str = "month", language: str | None = None) -> str:
    from adapters.registry import detect_agents
    from analyzer.reporter import build_report_data
    from ui.html_report import save_and_open

    agents = detect_agents()
    data = build_report_data(agents, period)
    return save_and_open(data, language=language)


def _analysis_period_from_project_range(project_range: str) -> str:
    if project_range == "1d":
        return "today"
    if project_range == "7d":
        return "last7"
    if project_range == "30d":
        return "last30"
    if project_range == "all":
        return "all"
    return "month"
