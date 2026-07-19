# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# mypy: disable-error-code="import-untyped,misc"
# PyObjC modules do not ship type stubs, and their base classes resolve to Any in mypy.
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import threading
import time
import tomllib
import webbrowser
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import objc
from AppKit import (
    NSAlert,
    NSAnimationContext,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSAttributedString,
    NSFont,
    NSFontAttributeName,
    NSImage,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSMinYEdge,
    NSMutableAttributedString,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSStatusBar,
    NSTextAttachment,
    NSVariableStatusItemLength,
    NSView,
    NSViewController,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
)
from Foundation import NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer
from Quartz import CGColorCreateGenericRGB

import agy_loader
import agy_window_keeper
import codex_loader
import critter_frames
import login_item
import menubar_agy
import menubar_state
import panels
import talent_market_bridge
import update_checker
import update_gate
import usage_diagnosis_snapshot
import window_keeper
from burn_rate import BurnRateTracker
from fsevents_watch import cleanup_fsevents, setup_fsevents
from history_loader import (
    UsageEntry,
    load_entries,
)
from history_loader import (
    flush_caches_on_terminate as flush_history_cache,
)
from i18n import _t, packaged_resource_path
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
    _format_percent as _format_percent,
)
from menubar_state import (
    _group_name as _group_name,
)
from menubar_state import (
    format_human_time as format_human_time,
)
from panels.base import Panel as UsagePanel
from panels.base import (
    load_active_panel_id,
    next_panel_eviction_id,
    resolve_resource,
    save_active_panel_id,
)
from prefs import _load_preferences, _save_preferences
from pricing import calculate_cost, warm_up_pricing
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
    _set_forwarder_mode_prompt_dismissed as _set_forwarder_mode_prompt_dismissed,
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
from usage_client import ClaudeUsageClient, PollOutcome, PollState
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

BUTTON_HEIGHT = 32.0
INSTALL_BUTTON_EXTRA_HEIGHT = BUTTON_HEIGHT + 10.0
UPDATE_DISMISS_SECONDS = 24 * 3600
UPDATE_ALERT_BODY_LIMIT = 2000
SLOW_POLL_INTERVAL_S = 300.0

logger = logging.getLogger(__name__)


def _detect_language() -> str:
    return detect_lang()


def _panel_title(panel: UsagePanel, language: str) -> str:
    return _t(language, panel.i18n_key)


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


_ALERT_ICON: Any = None
_ALERT_ICON_LOADED = False
_CLAUDE_MENUBAR_ICON: Any = None
_CLAUDE_MENUBAR_ICON_LOADED = False
_CODEX_MENUBAR_ICON: Any = None
_CODEX_MENUBAR_ICON_LOADED = False
_AGY_MENUBAR_ICON: Any = None
_AGY_MENUBAR_ICON_LOADED = False
_CRITTER_IMAGE_CACHE: dict[str, Any] = {}


class _NoopAlert:
    def setIcon_(self, icon: Any) -> None:
        return

    def setMessageText_(self, text: str) -> None:
        return

    def setInformativeText_(self, text: str) -> None:
        return

    def addButtonWithTitle_(self, title: str) -> None:
        return

    def runModal(self) -> int:
        return 0


def _alert_icon() -> Any:
    # NSAlert defaults to the application icon, which from source (and for an
    # accessory app with no Dock presence) is py2app's / Python's rocket. Setting
    # NSApp.applicationIconImage does not propagate to NSAlert, so each alert must
    # set the branded icon explicitly. Loaded once and cached.
    global _ALERT_ICON, _ALERT_ICON_LOADED
    if not _ALERT_ICON_LOADED:
        _ALERT_ICON_LOADED = True
        try:
            _ALERT_ICON = NSImage.alloc().initWithContentsOfFile_(resolve_resource("usage.icns"))
        except Exception:
            _ALERT_ICON = None
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("load alert icon failed", exc_info=True)
    return _ALERT_ICON


def _load_menubar_color_icon(filename: str) -> Any:
    image = NSImage.alloc().initWithContentsOfFile_(resolve_resource(filename))
    if image is not None:
        image.setTemplate_(False)
        image.setSize_(NSMakeSize(14, 14))
    return image


def _claude_menubar_icon() -> Any:
    global _CLAUDE_MENUBAR_ICON, _CLAUDE_MENUBAR_ICON_LOADED
    if not _CLAUDE_MENUBAR_ICON_LOADED:
        _CLAUDE_MENUBAR_ICON_LOADED = True
        try:
            _CLAUDE_MENUBAR_ICON = _load_menubar_color_icon("claude_color_menubar.png")
        except Exception:
            _CLAUDE_MENUBAR_ICON = None
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("load Claude menubar icon failed", exc_info=True)
    return _CLAUDE_MENUBAR_ICON


def _codex_menubar_icon() -> Any:
    global _CODEX_MENUBAR_ICON, _CODEX_MENUBAR_ICON_LOADED
    if not _CODEX_MENUBAR_ICON_LOADED:
        _CODEX_MENUBAR_ICON_LOADED = True
        try:
            _CODEX_MENUBAR_ICON = _load_menubar_color_icon("codex_color_menubar.png")
        except Exception:
            _CODEX_MENUBAR_ICON = None
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("load Codex menubar icon failed", exc_info=True)
    return _CODEX_MENUBAR_ICON


def _agy_menubar_icon() -> Any:
    global _AGY_MENUBAR_ICON, _AGY_MENUBAR_ICON_LOADED
    if not _AGY_MENUBAR_ICON_LOADED:
        _AGY_MENUBAR_ICON_LOADED = True
        try:
            _AGY_MENUBAR_ICON = _load_menubar_color_icon("agy_color_menubar.png")
        except Exception:
            _AGY_MENUBAR_ICON = None
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("load Antigravity menubar icon failed", exc_info=True)
    return _AGY_MENUBAR_ICON


def _menubar_icon_attachment_string(image: Any) -> Any:
    attachment = NSTextAttachment.alloc().init()
    attachment.setImage_(image)
    attachment.setBounds_(NSMakeRect(0, -2.5, 14, 14))
    return NSAttributedString.attributedStringWithAttachment_(attachment)


def _critter_icon_attachment_string(image: Any) -> Any:
    attachment = NSTextAttachment.alloc().init()
    attachment.setImage_(image)
    attachment.setBounds_(NSMakeRect(0, -4.0, 18, 18))
    return NSAttributedString.attributedStringWithAttachment_(attachment)


def _critter_frame_image(path: str) -> Any:
    cached = _CRITTER_IMAGE_CACHE.get(path)
    if cached is not None:
        return cached
    image = NSImage.alloc().initWithContentsOfFile_(resolve_resource(path))
    if image is not None:
        image.setTemplate_(True)
        image.setSize_(NSMakeSize(18, 18))
    _CRITTER_IMAGE_CACHE[path] = image
    return image


def _make_alert() -> Any:
    try:
        alert = NSAlert.alloc().init()
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("create alert failed", exc_info=True)
        return _NoopAlert()
    if alert is None:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("create alert returned None")
        return _NoopAlert()
    icon = _alert_icon()
    if icon is not None:
        try:
            alert.setIcon_(icon)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("set alert icon failed", exc_info=True)
    return alert


def _user_notification_center() -> tuple[Any, dict[str, int]]:
    from UserNotifications import (
        UNAuthorizationOptionAlert,
        UNAuthorizationOptionBadge,
        UNAuthorizationOptionSound,
        UNUserNotificationCenter,
    )
    _register_user_notification_block_metadata()

    return (
        UNUserNotificationCenter.currentNotificationCenter(),
        {
            "alert": int(UNAuthorizationOptionAlert),
            "badge": int(UNAuthorizationOptionBadge),
            "sound": int(UNAuthorizationOptionSound),
        },
    )


def _user_notification_classes() -> tuple[Any, Any, Any]:
    _register_user_notification_block_metadata()
    from UserNotifications import (
        UNMutableNotificationContent,
        UNNotificationRequest,
        UNNotificationSound,
    )

    return UNMutableNotificationContent, UNNotificationRequest, UNNotificationSound


def _register_user_notification_block_metadata() -> None:
    objc.registerMetaDataForSelector(
        b"UNUserNotificationCenter",
        b"requestAuthorizationWithOptions:completionHandler:",
        {
            "arguments": {
                3: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"Z"},
                            2: {"type": b"@"},
                        },
                    },
                },
            },
        },
    )
    objc.registerMetaDataForSelector(
        b"UNUserNotificationCenter",
        b"addNotificationRequest:withCompletionHandler:",
        {
            "arguments": {
                3: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"@"},
                        },
                    },
                },
            },
        },
    )


def _notification_tool(channel: str) -> str:
    return "Claude" if channel.startswith("claude_") else "Codex"


def _notification_scope(language: str, channel: str) -> str:
    if channel.endswith("_session"):
        return _t(language, "session_label")
    return _t(language, "weekly_label")


def _notification_row(state: PopoverState, channel: str) -> QuotaRowState:
    rows = {
        "claude_session": state.claude_session,
        "claude_weekly": state.claude_weekly,
        "codex_session": state.codex_session,
        "codex_weekly": state.codex_weekly,
    }
    return rows[channel]


def _update_dismissed_recently(prefs: dict[str, Any]) -> bool:
    dismissed_at = prefs.get("update_dismissed_at")
    if isinstance(dismissed_at, int | float):
        return (time.time() - float(dismissed_at)) < UPDATE_DISMISS_SECONDS
    return False


def _current_version() -> str:
    try:
        return metadata.version("usage")
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
MAX_CACHED_PANEL_VIEWS = 6
PANEL_TRANSITION_TIMEOUT_SECONDS = 1.5
PANEL_TRANSITION_FADE_SECONDS = 0.18


class PopoverViewController(NSViewController):
    content_view = objc.ivar()
    panel = objc.ivar()
    delegate = objc.ivar()
    panel_views = objc.ivar()
    panel_lru = objc.ivar()
    transition_overlays = objc.ivar()
    latest_state = objc.ivar()
    pending_panel_evictions = objc.ivar()

    def initWithPanel_delegate_(self, panel: UsagePanel, delegate: Any) -> PopoverViewController:
        self = objc.super(PopoverViewController, self).init()
        if self is None:
            return None
        self.panel = panel
        self.delegate = delegate
        self.panel_views = {}
        self.panel_lru = []
        self.transition_overlays = {}
        self.pending_panel_evictions = set()
        self.latest_state = None
        self.content_view = panel.build_view(delegate)
        container = NSView.alloc().initWithFrame_(self.content_view.frame())
        container.setWantsLayer_(True)
        self.setView_(container)
        self.preparePanelView_(self.content_view)
        container.addSubview_(self.content_view)
        # Only cache a real web view; a failed build (ErrorPanelView, no JS
        # bridge) is shown but left uncached so a later switch rebuilds it.
        if hasattr(self.content_view, "evaluateJavaScript_completionHandler_"):
            self.panel_views[panel.id] = self.content_view
            self.panel_lru.append(panel.id)
        return self

    def setState_(self, state: PopoverState) -> None:
        self.latest_state = state
        self.view().setFrameSize_(_popover_size(state, self.panel))
        self.syncPanelFrames()
        self.panel.apply_state(self.content_view, state)

    def switchToPanel_(self, panel: UsagePanel) -> None:
        previous = self.content_view
        self.panel = panel
        content_view = self.panel_views.get(panel.id)
        if content_view is None:
            content_view = panel.build_view(self.delegate)
            content_view.setHidden_(True)
            self.preparePanelView_(content_view)
            self.view().addSubview_(content_view)
            # Only cache a real web view. A failed build returns ErrorPanelView
            # (no JS bridge); caching it would pin the error even after the file
            # recovers, so leave it uncached and rebuild on the next switch.
            if hasattr(content_view, "evaluateJavaScript_completionHandler_"):
                self.panel_views[panel.id] = content_view
                self.beginPanelTransitionForPanelId_view_(panel.id, content_view)
        # Drop the previously shown view if it was an uncached error fallback,
        # so it doesn't linger stacked in the container behind the new panel.
        if (
            previous is not None
            and previous is not content_view
            and previous not in self.panel_views.values()
        ):
            if hasattr(previous, "teardown"):
                previous.teardown()
            previous.removeFromSuperview()
        self.content_view = content_view
        if panel.id in self.panel_views:
            self.markPanelUsed_(panel.id)
        for panel_id, view in list(self.panel_views.items()):
            view.setHidden_(panel_id != panel.id)
        content_view.setHidden_(False)
        if self.latest_state is not None:
            self.setState_(self.latest_state)
        self.evictPanelViewsIfNeeded()

    def currentContentView(self) -> Any:
        return self.content_view

    def panelDidFirstPaint_(self, view: Any) -> None:
        if view is self.content_view:
            self.endPanelTransitionForPanelView_(view)

    def beginPanelTransitionForPanelId_view_(self, panel_id: str, view: Any) -> None:
        self.removeTransitionOverlay_(panel_id)
        overlay = NSView.alloc().initWithFrame_(view.bounds())
        overlay.setWantsLayer_(True)
        overlay.setAlphaValue_(1.0)
        overlay.setAutoresizingMask_(int(NSViewWidthSizable) | int(NSViewHeightSizable))
        layer = overlay.layer()
        if layer is not None:
            layer.setBackgroundColor_(
                CGColorCreateGenericRGB(10 / 255, 15 / 255, 20 / 255, 1.0)
            )
        view.addSubview_(overlay)
        self.transition_overlays[panel_id] = overlay
        self.performSelector_withObject_afterDelay_(
            "transitionTimeoutElapsed:",
            overlay,
            PANEL_TRANSITION_TIMEOUT_SECONDS,
        )

    def transitionTimeoutElapsed_(self, overlay: Any) -> None:
        # Match by the overlay object itself, not the panel id: if this panel was
        # evicted and rebuilt, a stale timer must not fade the new overlay. A timer
        # whose overlay is already gone from the map simply finds nothing and stops.
        for panel_id, current_overlay in list(self.transition_overlays.items()):
            if current_overlay is overlay:
                self.endPanelTransitionForPanelId_(panel_id)
                return

    def endPanelTransitionForPanelView_(self, view: Any) -> None:
        for panel_id, panel_view in list(self.panel_views.items()):
            if panel_view is view:
                self.endPanelTransitionForPanelId_(panel_id)
                return

    def endPanelTransitionForPanelId_(self, panel_id: str) -> None:
        overlay = self.transition_overlays.pop(panel_id, None)
        if overlay is None:
            return

        def _fade(context: Any) -> None:
            context.setDuration_(PANEL_TRANSITION_FADE_SECONDS)
            overlay.animator().setAlphaValue_(0.0)

        def _remove() -> None:
            overlay.removeFromSuperview()

        NSAnimationContext.runAnimationGroup_completionHandler_(_fade, _remove)

    def teardown(self) -> None:
        for panel_id, view in list(self.panel_views.items()):
            self.removeTransitionOverlay_(panel_id)
            if hasattr(view, "teardown"):
                view.teardown()
            view.removeFromSuperview()
        self.panel_views.clear()
        self.panel_lru.clear()
        self.content_view = None

    def preparePanelView_(self, view: Any) -> None:
        view.setFrame_(self.view().bounds() if self.view() is not None else view.frame())
        view.setAutoresizingMask_(int(NSViewWidthSizable) | int(NSViewHeightSizable))

    def syncPanelFrames(self) -> None:
        bounds = self.view().bounds()
        for view in self.panel_views.values():
            view.setFrame_(bounds)

    def markPanelUsed_(self, panel_id: str) -> None:
        self.panel_lru = [cached_id for cached_id in self.panel_lru if cached_id != panel_id]
        self.panel_lru.append(panel_id)

    def evictPanelViewsIfNeeded(self) -> None:
        self._schedulePanelEvictionIfNeeded()

    def _schedulePanelEvictionIfNeeded(self) -> None:
        if self.panel is None or len(self.panel_views) <= MAX_CACHED_PANEL_VIEWS:
            return
        evict_id = next_panel_eviction_id(
            self.panel_lru,
            self.panel.id,
            self.pending_panel_evictions,
        )
        if evict_id is None:
            return
        self.pending_panel_evictions.add(evict_id)
        self.performSelector_withObject_afterDelay_("evictPanelViewForId:", evict_id, 0.0)

    def evictPanelViewForId_(self, panel_id: str) -> None:
        self.pending_panel_evictions.discard(panel_id)
        # A user can return to this panel before the next run-loop turn. In
        # that case it remains live; schedule another LRU candidate instead.
        if self.panel is None or panel_id == self.panel.id:
            self._schedulePanelEvictionIfNeeded()
            return
        view = self.panel_views.get(panel_id)
        if view is None:
            self._schedulePanelEvictionIfNeeded()
            return
        self.panel_lru = [cached_id for cached_id in self.panel_lru if cached_id != panel_id]
        self.panel_views.pop(panel_id, None)
        self.removeTransitionOverlay_(panel_id)
        if hasattr(view, "teardown"):
            view.teardown()
        view.removeFromSuperview()
        self._schedulePanelEvictionIfNeeded()

    def removeTransitionOverlay_(self, panel_id: str) -> None:
        overlay = self.transition_overlays.pop(panel_id, None)
        if overlay is not None:
            overlay.removeFromSuperview()


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
    _history_load_error_key = objc.ivar()
    _quota_notifier = objc.ivar()
    _switch_menu_action_taken = objc.ivar()
    _pre_talent_panel_id = objc.ivar()
    critter_timer = objc.ivar()
    critter_frame = objc.ivar()
    critter_interval = objc.ivar()
    dragon_timer = objc.ivar()
    dragon_frame = objc.ivar()
    dragon_interval = objc.ivar()
    lion_timer = objc.ivar()
    lion_frame = objc.ivar()
    lion_interval = objc.ivar()
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
        self._history_load_error_key = None
        self._switch_menu_action_taken = False
        self._pre_talent_panel_id = None
        self.critter_timer = None
        self.critter_frame = 0
        self.critter_interval = 0.0
        self.dragon_timer = None
        self.dragon_frame = 0
        self.dragon_interval = 0.0
        self.lion_timer = None
        self.lion_frame = 0
        self.lion_interval = 0.0
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
        self.popover = NSPopover.alloc().init()
        self.popover.setBehavior_(NSPopoverBehaviorTransient)
        self.popover.setDelegate_(self)
        self.popover.setContentSize_(_popover_size(self.latest_state, self.active_panel))
        self.popover.setContentViewController_(self.popover_controller)

        self._request_notification_authorization()
        self._refresh()
        self._reschedule_poll_timer(max(self.interval, SLOW_POLL_INTERVAL_S))
        self._fs_stream = setup_fsevents(self)
        warm_up_pricing(self._refresh_after_pricing_warm_up)
        thread = threading.Thread(target=self._maybe_check_update_in_background, daemon=True)
        thread.start()

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

    def popoverWillShow_(self, notification: Any) -> None:
        self._reschedule_poll_timer(self.interval)

    def popoverDidShow_(self, notification: Any) -> None:
        self.refreshNow_(None)

    def popoverDidClose_(self, notification: Any) -> None:
        self._reschedule_poll_timer(max(self.interval, SLOW_POLL_INTERVAL_S))

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
        self._stop_dragon_timer()
        self._stop_lion_timer()
        if self._file_event_refresh_timer is not None:
            self._file_event_refresh_timer.invalidate()
            self._file_event_refresh_timer = None
        flush_history_cache()
        codex_loader.flush_caches_on_terminate()
        agy_loader.flush_caches_on_terminate()
        if hasattr(self, "popover_controller") and self.popover_controller is not None:
            self.popover_controller.teardown()

    def switchPanel_(self, sender: Any) -> None:
        menu = NSMenu.alloc().initWithTitle_(_t(self.language, "switch_panel"))
        # AI 人才市場 is a feature panel, not a cosmetic skin — it gets its own
        # top-level row instead of hiding inside "面板主題 ▸" next to Matrix/Win95.
        talent_market_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "panel_talent_market"),
            "toggleTalentMarket:",
            "",
        )
        talent_market_item.setTarget_(self)
        talent_market_item.setRepresentedObject_("talent_market")
        talent_market_item.setState_(1 if self.active_panel.id == "talent_market" else 0)
        menu.addItem_(talent_market_item)
        ai_daily_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "panel_ai_daily"), "toggleAiDaily:", ""
        )
        ai_daily_item.setTarget_(self)
        menu.addItem_(ai_daily_item)
        menu.addItem_(NSMenuItem.separatorItem())
        # Panel themes live in a submenu so the menu stays short — one "面板主題 ▸"
        # row that expands on demand instead of nine inline rows. talent_market is
        # excluded here since it already has its own top-level row above.
        panel_submenu = NSMenu.alloc().initWithTitle_(_t(self.language, "switch_panel"))
        for panel in panels.all_panels():
            if panel.id == "talent_market":
                continue
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                _panel_title(panel, self.language),
                "selectPanel:",
                "",
            )
            item.setTarget_(self)
            item.setRepresentedObject_(panel.id)
            item.setState_(1 if panel.id == self.active_panel.id else 0)
            panel_submenu.addItem_(item)
        panel_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "switch_panel"), "", ""
        )
        panel_parent.setSubmenu_(panel_submenu)
        menu.addItem_(panel_parent)
        # Provider visibility lives in one "Hide Sections ▸" submenu row, grouped
        # with the panel-themes submenu: both are drill-in rows that shape what
        # the popover shows.
        hide_submenu = NSMenu.alloc().initWithTitle_(_t(self.language, "hide_sections_menu"))
        hide_claude_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "claude_name"),
            "toggleHideClaude:",
            "",
        )
        hide_claude_item.setTarget_(self)
        hide_claude_item.setState_(1 if _hide_claude_enabled() else 0)
        hide_submenu.addItem_(hide_claude_item)
        hide_codex_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "codex_name"),
            "toggleHideCodex:",
            "",
        )
        hide_codex_item.setTarget_(self)
        hide_codex_item.setState_(1 if _hide_codex_enabled() else 0)
        hide_submenu.addItem_(hide_codex_item)
        hide_agy_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "agy_name"),
            "toggleHideAgy:",
            "",
        )
        hide_agy_item.setTarget_(self)
        hide_agy_item.setState_(1 if _hide_agy_enabled() else 0)
        hide_submenu.addItem_(hide_agy_item)
        hide_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "hide_sections_menu"), "", ""
        )
        hide_parent.setSubmenu_(hide_submenu)
        menu.addItem_(hide_parent)
        # Plain on/off switches sit together in the second group.
        menu.addItem_(NSMenuItem.separatorItem())
        launch_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "launch_at_login"),
            "toggleLaunchAtLogin:",
            "",
        )
        launch_item.setTarget_(self)
        launch_item.setState_(1 if login_item.is_enabled() else 0)
        menu.addItem_(launch_item)
        quota_notifications_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "quota_notifications_menu"),
            "toggleQuotaNotifications:",
            "",
        )
        quota_notifications_item.setTarget_(self)
        quota_notifications_item.setState_(1 if _quota_notifications_enabled() else 0)
        menu.addItem_(quota_notifications_item)
        window_keeper_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "window_keeper_menu"),
            "toggleWindowKeeper:",
            "",
        )
        window_keeper_item.setTarget_(self)
        window_keeper_item.setState_(1 if _window_keeper_enabled() else 0)
        window_keeper_item.setToolTip_(_t(self.language, "window_keeper_tooltip"))
        menu.addItem_(window_keeper_item)
        # Project Butler: one toggle that hands last session's progress to the next
        # one. Tooltip carries the full explanation so the menu line stays short.
        menu.addItem_(NSMenuItem.separatorItem())
        butler_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "project_butler"),
            "toggleSessionResume:",
            "",
        )
        butler_item.setTarget_(self)
        butler_item.setState_(1 if _session_resume_enabled() else 0)
        butler_item.setToolTip_(_t(self.language, "project_butler_tooltip"))
        menu.addItem_(butler_item)
        terse_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "terse_mode_menu"),
            "toggleTerseMode:",
            "",
        )
        terse_item.setTarget_(self)
        terse_item.setState_(1 if _terse_mode_enabled() else 0)
        terse_item.setToolTip_(_t(self.language, "terse_mode_tooltip"))
        menu.addItem_(terse_item)
        self._switch_menu_action_taken = False
        menu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0, 0), sender)
        if self._switch_menu_action_taken:
            self._resync_popover_after_menu()
        else:
            self._close_popover_after_menu()

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
        self._set_button_title(self.latest_state)

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
        self._set_button_title(self.latest_state)

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
        self._set_button_title(self.latest_state)

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
        import session_hooks

        output = io.StringIO()
        ok = True
        enabled = False
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                if session_hooks.is_resume_enabled():
                    session_hooks.disable_session_resume()
                else:
                    ok = session_hooks.enable_session_resume() == 0
                    enabled = ok
        except SystemExit as exc:
            if exc.code:
                ok = False
                print(exc.code, file=output)
        except Exception as exc:
            ok = False
            print(f"{type(exc).__name__}: {exc}", file=output)

        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "_finishSessionResume:",
            {"ok": ok, "enabled": enabled, "output": output.getvalue().strip()},
            False,
        )

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
        import session_hooks

        output = io.StringIO()
        ok = True
        enabled = False
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                if session_hooks.is_terse_mode_enabled():
                    session_hooks.disable_terse_mode()
                else:
                    ok = session_hooks.enable_terse_mode() == 0
                    enabled = ok
        except SystemExit as exc:
            if exc.code:
                ok = False
                print(exc.code, file=output)
        except Exception as exc:
            ok = False
            print(f"{type(exc).__name__}: {exc}", file=output)

        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "_finishTerseMode:",
            {"ok": ok, "enabled": enabled, "output": output.getvalue().strip()},
            False,
        )

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
        try:
            current_version = _current_version()
            prefs = _load_preferences()
            updated_cache = update_gate.stale_cache_reset(prefs, current_version)
            if updated_cache is not None:
                prefs["last_update_check"] = updated_cache
                _save_preferences(prefs)
        except Exception:
            pass

    def _maybe_check_update_in_background(self) -> None:
        usage_diagnosis_snapshot.maybe_schedule_refresh()
        self._check_update_in_background(
            manual=False,
            ignore_cooldown=False,
            ignore_skipped=False,
        )

    def _check_update_in_background(
        self,
        *,
        manual: bool,
        ignore_cooldown: bool,
        ignore_skipped: bool,
    ) -> None:
        prefs = _load_preferences()
        if not manual and not _auto_update_check_enabled(prefs):
            return

        if not ignore_cooldown and _update_dismissed_recently(prefs):
            return

        try:
            current_version = _current_version()
            check_result = update_checker.check_latest_release_result(current_version)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("update check failed", exc_info=True)
            if manual:
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "_showUpdateCheckFailed:",
                    None,
                    False,
                )
            return

        if check_result.failed:
            if manual:
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
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
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "_showNoUpdateAvailable:",
                    None,
                    False,
                )
            return

        if not ignore_skipped and prefs.get("update_skipped_version") == release.version:
            return

        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "_showUpdateAlert:",
            release,
            False,
        )

    def _showUpdateAlert_(self, release: update_checker.ReleaseInfo) -> None:
        alert = _make_alert()
        alert.setMessageText_(_t(self.language, "update_alert_title", version=release.version))
        alert.setInformativeText_(release.body[:UPDATE_ALERT_BODY_LIMIT])
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
        self.popover.setContentSize_(_popover_size(self.latest_state, panel))
        if panel.id == "talent_market":
            # Talent data is fetched in the background refresh; switchToPanel_
            # injected the last (talent-less) state, so kick a refresh to fill it.
            self._refresh()

    def _show_popover_from_button(self, button: Any) -> None:
        self.popover.showRelativeToRect_ofView_preferredEdge_(
            button.bounds(),
            button,
            NSMinYEdge,
        )
        window = self.popover_controller.view().window()
        if window is None:
            return
        behavior = int(window.collectionBehavior())
        behavior |= int(NSWindowCollectionBehaviorCanJoinAllSpaces)
        behavior |= int(NSWindowCollectionBehaviorFullScreenAuxiliary)
        window.setCollectionBehavior_(behavior)
        window.orderFront_(None)

    def _mark_switch_menu_action(self) -> None:
        self._switch_menu_action_taken = True

    def _close_popover_after_menu(self) -> None:
        if not hasattr(self, "popover") or self.popover is None:
            return
        if not self.popover.isShown():
            return
        self.popover.performClose_(None)

    def _resync_popover_after_menu(self) -> None:
        if not hasattr(self, "popover") or not hasattr(self, "popover_controller"):
            return
        if not hasattr(self, "status_item"):
            return
        if self.popover is None or self.popover_controller is None or self.status_item is None:
            return
        if not self.popover.isShown():
            return
        self.popover_controller.setState_(self.latest_state)
        self.popover.setContentSize_(_popover_size(self.latest_state, self.active_panel))

    def animateCritters_(self, timer: Any) -> None:
        interval = self._current_critter_interval()
        if interval <= 0:
            self.critter_frame = 0
            self._stop_critter_timer()
            self._set_button_title(self.latest_state)
            return
        self.critter_frame = (int(self.critter_frame) + 1) % len(critter_frames.PHOENIX_FRAMES)
        self._set_button_title(self.latest_state)

    def animateDragon_(self, timer: Any) -> None:
        interval = self._current_dragon_interval()
        if interval <= 0:
            self.dragon_frame = 0
            self._stop_dragon_timer()
            self._set_button_title(self.latest_state)
            return
        self.dragon_frame = (int(self.dragon_frame) + 1) % len(critter_frames.DRAGON_FRAMES)
        self._set_button_title(self.latest_state)

    def animateLion_(self, timer: Any) -> None:
        interval = self._current_lion_interval()
        if interval <= 0:
            self.lion_frame = 0
            self._stop_lion_timer()
            self._set_button_title(self.latest_state)
            return
        self.lion_frame = (int(self.lion_frame) + 1) % len(critter_frames.LION_FRAMES)
        self._set_button_title(self.latest_state)

    def _current_critter_interval(self) -> float:
        try:
            group = int(self.tracker.group())
        except Exception:
            group = 0
        return critter_frames.group_to_interval(group)

    def _current_dragon_interval(self) -> float:
        try:
            group = int(self.codex_tracker.group())
        except Exception:
            group = 0
        return critter_frames.group_to_interval(group)

    def _current_lion_interval(self) -> float:
        try:
            group = int(self.agy_tracker.group())
        except Exception:
            group = 0
        return critter_frames.group_to_interval(group)

    def _sync_critter_timer(self) -> None:
        interval = self._current_critter_interval()
        if interval <= 0:
            self.critter_frame = 0
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

    def _sync_dragon_timer(self) -> None:
        interval = self._current_dragon_interval()
        if interval <= 0:
            self.dragon_frame = 0
            self._stop_dragon_timer()
            return
        if self.dragon_timer is not None and self.dragon_interval == interval:
            return
        self._stop_dragon_timer()
        self.dragon_interval = interval
        scheduled_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_
        self.dragon_timer = scheduled_timer(interval, self, "animateDragon:", None, True)
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.dragon_timer, NSRunLoopCommonModes)

    def _stop_dragon_timer(self) -> None:
        timer = self.dragon_timer
        self.dragon_timer = None
        self.dragon_interval = 0.0
        if timer is not None:
            timer.invalidate()

    def _sync_lion_timer(self) -> None:
        interval = self._current_lion_interval()
        if interval <= 0:
            self.lion_frame = 0
            self._stop_lion_timer()
            return
        if self.lion_timer is not None and self.lion_interval == interval:
            return
        self._stop_lion_timer()
        self.lion_interval = interval
        scheduled_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_
        self.lion_timer = scheduled_timer(interval, self, "animateLion:", None, True)
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.lion_timer, NSRunLoopCommonModes)

    def _stop_lion_timer(self) -> None:
        timer = self.lion_timer
        self.lion_timer = None
        self.lion_interval = 0.0
        if timer is not None:
            timer.invalidate()

    def togglePopover_(self, sender: Any) -> None:
        if self.popover.isShown():
            self.popover.performClose_(sender)
            return
        self.popover_controller.setState_(self.latest_state)
        self.popover.setContentSize_(_popover_size(self.latest_state, self.active_panel))
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

    def refreshFromFileEvent_(self, _sender: Any) -> None:
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
        debug_timing = os.environ.get("USAGE_DEBUG") == "1"

        def measure(stage: str, started_at: float) -> None:
            if debug_timing:
                elapsed_ms = (time.monotonic() - started_at) * 1000
                logger.debug("refresh_timing stage=%s elapsed_ms=%.1f", stage, elapsed_ms)

        try:
            started_at = time.monotonic() if debug_timing else 0.0
            codex_result = self._load_codex_refresh_result()
            measure("codex_load", started_at)
            started_at = time.monotonic() if debug_timing else 0.0
            agy_result = menubar_agy.load_refresh_result(self.language)
            measure("agy_load", started_at)
            agy_projection = agy_result.projection or menubar_agy.fallback_projection(
                self.language
            )
            started_at = time.monotonic() if debug_timing else 0.0
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_applyCodexRefreshResult:",
                codex_result,
                True,
            )
            measure("main_apply_codex", started_at)
            fallback_state = getattr(self, "latest_state", _empty_state(self.language))
            project_rows = list(fallback_state.projects)
            project_rows_7d = list(fallback_state.projects_7d)
            project_rows_30d = list(fallback_state.projects_30d)
            project_rows_all = list(fallback_state.projects_all)
            today_text = fallback_state.today_text
            statusline = fallback_state.statusline
            hide_claude = fallback_state.hide_claude
            hide_codex = fallback_state.hide_codex
            hide_agy = agy_result.hide_agy or _hide_agy_enabled()
            card_order = _quota_card_order()
            try:
                started_at = time.monotonic() if debug_timing else 0.0
                all_entries = self._load_history_entries()
                measure("history_load", started_at)
                started_at = time.monotonic() if debug_timing else 0.0
                if self.mock:
                    project_rows = self._project_rows(hours_back=24, entries=all_entries)
                    project_rows_7d = self._project_rows(hours_back=168, entries=all_entries)
                    project_rows_30d = self._project_rows(hours_back=720, entries=all_entries)
                    project_rows_all = self._project_rows(hours_back=0, entries=all_entries)
                else:
                    (
                        project_rows,
                        project_rows_7d,
                        project_rows_30d,
                        project_rows_all,
                    ) = menubar_state.project_rows_for_windows(all_entries)
                measure("project_rows_windows", started_at)
                today_text = _today_title(self.mock, self.language, entries=all_entries)
                statusline = _statusline_payload(self.language)
                hide_claude = _hide_claude_enabled()
                hide_codex = _hide_codex_enabled()
                hide_agy = agy_result.hide_agy or _hide_agy_enabled()
            except Exception:
                if os.environ.get("USAGE_DEBUG") == "1":
                    logger.warning("local usage refresh failed", exc_info=True)
            try:
                started_at = time.monotonic() if debug_timing else 0.0
                outcome = asyncio.run(self._fetch())
                measure("fetch", started_at)
                codex_rows = codex_result["codex_rows"]
                codex_5h_pct = codex_result["codex_5h_pct"]
                codex_model = codex_result.get("codex_model", "unknown")
                codex_stale = codex_result.get("codex_stale")
                show_install_button = (
                    not hide_claude
                    and outcome.state == PollState.TOKEN_ERROR
                    and self._statusline_setup_available()
                )
                group = self.tracker.group()
                state = menubar_state.build_popover_state(
                    outcome=outcome,
                    codex_rows=codex_rows,
                    agy_rows=(agy_projection.session, agy_projection.weekly),
                    agy_group_name=agy_projection.group_name,
                    projects=project_rows,
                    projects_7d=project_rows_7d,
                    projects_30d=project_rows_30d,
                    projects_all=project_rows_all,
                    language=self.language,
                    group=group,
                    burn_rate_trackers=self.burn_rate_trackers,
                    today_text=today_text,
                    statusline=statusline,
                    show_install_button=show_install_button,
                    hide_claude=hide_claude,
                    hide_codex=hide_codex,
                    hide_agy=hide_agy,
                    codex_stale=codex_stale,
                    agy_stale=agy_projection.stale,
                    card_order=card_order,
                    history_error=menubar_state.history_load_error_state(
                        self._history_load_error_key, self.language
                    ),
                )
                if outcome.snapshot is not None:
                    window_keeper.maybe_ping(
                        outcome.snapshot.current_reset_at,
                        outcome.snapshot.current_percent,
                        outcome.snapshot.data_source,
                        self.mock,
                    )
                agy_window_keeper.maybe_ping(agy_result, self.mock)
            except Exception as exc:
                if os.environ.get("USAGE_DEBUG") == "1":
                    logger.warning("refresh failed", exc_info=True)
                codex_rows = codex_result["codex_rows"]
                codex_5h_pct = codex_result["codex_5h_pct"]
                codex_model = codex_result.get("codex_model", "unknown")
                state = _error_state(type(exc).__name__, self.mock, self.language)
                state.codex_session = codex_rows[0]
                state.codex_weekly = codex_rows[1]
                state.codex_stale = codex_result.get("codex_stale")
                state.agy_session = agy_projection.session
                state.agy_weekly = agy_projection.weekly
                state.agy_group_name = agy_projection.group_name
                state.agy_stale = agy_projection.stale
                state.history_error = menubar_state.history_load_error_state(
                    self._history_load_error_key, self.language
                )
                state.projects = project_rows
                state.projects_7d = project_rows_7d
                state.projects_30d = project_rows_30d
                state.projects_all = project_rows_all
                state.today_text = today_text
                state.statusline = statusline
                state.hide_claude = hide_claude
                state.hide_codex = hide_codex
                state.hide_agy = hide_agy
                state.card_order = card_order

            # Talent-market data is panel-local (no quota numbers). Fetch it
            # only when that panel is active so classic/matrix users never pay
            # the subprocess cost. list_state already swallows CLI errors and
            # returns {ok:False,...}, so the panel shows its empty state.
            active_panel = getattr(self, "active_panel", None)
            if active_panel is not None and active_panel.id == "talent_market":
                try:
                    state.talent = talent_market_bridge.list_state(self.language)
                except Exception:
                    if os.environ.get("USAGE_DEBUG") == "1":
                        logger.warning("talent market state load failed", exc_info=True)

            result = {"state": state, "codex_5h_pct": codex_5h_pct, "codex_model": codex_model}
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
            self._process_quota_notifications(state)
            if self.popover.isShown():
                self.popover_controller.setState_(self.latest_state)
            self.popover.setContentSize_(_popover_size(state, self.active_panel))
            self._inject_web_language(state.language)
            self._set_button_title(state)
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
        try:
            codex_rows, codex_5h_pct, codex_model, codex_stale = menubar_state.codex_rows(
                mock=self.mock,
                language=self.language,
                burn_rate_trackers=self.burn_rate_trackers,
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
        return {
            "codex_rows": codex_rows,
            "codex_5h_pct": codex_5h_pct,
            "codex_model": codex_model,
            "codex_stale": codex_stale,
        }

    def _applyCodexRefreshResult_(self, result: dict[str, Any]) -> None:
        started_at = time.monotonic() if os.environ.get("USAGE_DEBUG") == "1" else 0.0
        codex_rows = result["codex_rows"]
        self.latest_state.codex_session = codex_rows[0]
        self.latest_state.codex_weekly = codex_rows[1]
        self.latest_state.codex_stale = result.get("codex_stale")
        self.codex_5h_pct = result["codex_5h_pct"]
        self.codex_model = result.get("codex_model", "unknown")
        if self.popover.isShown():
            self.popover_controller.setState_(self.latest_state)
        self.popover.setContentSize_(_popover_size(self.latest_state, self.active_panel))
        self._set_button_title(self.latest_state)
        if started_at:
            logger.debug(
                "refresh_timing stage=main_apply_codex_ui elapsed_ms=%.1f",
                (time.monotonic() - started_at) * 1000,
            )

    def _request_notification_authorization(self) -> None:
        if self.mock or not _quota_notifications_enabled():
            return
        try:
            center, constants = _user_notification_center()
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
            center, _constants = _user_notification_center()
            content_cls, request_cls, sound_cls = _user_notification_classes()
            row = _notification_row(state, event.channel)
            title_key = f"notif_{event.kind}_title"
            body_key = f"notif_{event.kind}_body"
            content = content_cls.alloc().init()
            content.setTitle_(_t(self.language, title_key))
            content.setBody_(
                _t(
                    self.language,
                    body_key,
                    tool=_notification_tool(event.channel),
                    # row.title carries the window-aware label (e.g. Codex free
                    # plan shows "Monthly"); fall back to the slot's scope text.
                    scope=row.title or _notification_scope(self.language, event.channel),
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
        output = io.StringIO()
        exit_code = 1
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                import session_hooks
                import setup_hook

                exit_code = setup_hook.setup()
                if exit_code == 0:
                    session_hooks._migrate_bundled_python_commands_if_needed()
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
            if exc.code:
                print(exc.code, file=output)
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=output)

        result = {
            "success": exit_code == 0,
            "message": output.getvalue().strip(),
        }
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "_finishHookInstall:",
            result,
            False,
        )

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
        output = io.StringIO()
        ok = True
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                if action == "toggle":
                    _toggle_statusline_settings()
                elif action == "uninstall":
                    _disable_statusline_settings()
                else:
                    _enable_statusline_settings()
        except SystemExit as exc:
            if exc.code:
                ok = False
                print(exc.code, file=output)
        except Exception as exc:
            ok = False
            print(f"{type(exc).__name__}: {exc}", file=output)

        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "_finishStatuslineAction:",
            {"ok": ok, "action": action, "output": output.getvalue().strip()},
            False,
        )

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
        result: dict[str, str | bool]
        try:
            saved = _generate_analysis_report(period=period, language=self.language)
            result = {"success": True, "message": saved}
        except Exception as exc:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("analysis report failed", exc_info=True)
            result = {"success": False, "message": f"{type(exc).__name__}: {exc}"}
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "_finishAnalyzeUsage:",
            result,
            False,
        )

    def _finishAnalyzeUsage_(self, result: dict[str, Any]) -> None:
        if result["success"]:
            return
        alert = _make_alert()
        alert.setMessageText_(_t(self.language, "analysis_failed"))
        alert.setInformativeText_(str(result["message"]))
        alert.runModal()

    async def _fetch(self) -> PollOutcome:
        client = ClaudeUsageClient(mock=self.mock)
        try:
            return await client.fetch_once()
        finally:
            await client.aclose()

    def _statusline_setup_available(self) -> bool:
        try:
            import setup_hook

            return setup_hook.CLAUDE_SETTINGS.parent.exists() or setup_hook.CODEX_CONFIG.exists()
        except Exception:
            return False

    def _history_sources_fingerprint(self) -> tuple[tuple[str, int, float], ...]:
        return self._history_source_scan().fingerprint

    def _history_source_scan(self) -> menubar_state.HistorySourceScan:
        return menubar_state.history_source_scan()

    def _load_history_entries(self) -> list[UsageEntry]:
        if self.mock:
            return []
        scan = self._history_source_scan()
        fingerprint = scan.fingerprint
        if (
            self._history_entries_cache is not None
            and self._history_entries_cache_fingerprint == fingerprint
        ):
            return list(self._history_entries_cache)

        entries: list[UsageEntry] = []
        error_key: str | None = None
        try:
            entries.extend(load_entries(hours_back=0, jsonl_paths=scan.claude_paths))
        except Exception as exc:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Claude project usage load failed", exc_info=True)
            error_key = _classify_history_load_error(exc)
        try:
            entries.extend(codex_loader.load_entries(hours_back=0, jsonl_paths=scan.codex_paths))
        except Exception as exc:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Codex project usage load failed", exc_info=True)
            error_key = _classify_history_load_error(exc)
        self._history_load_error_key = error_key
        self._history_entries_cache = list(entries)
        self._history_entries_cache_fingerprint = fingerprint
        return entries

    def _project_rows(
        self,
        hours_back: int = 24,
        entries: list[UsageEntry] | None = None,
    ) -> list[tuple[str, int, float | None]]:
        if self.mock:
            if hours_back <= 0:
                return [
                    ("usage", 624_000_000, 361.00),
                    ("FinMind", 172_800_000, 100.24),
                    ("AI客服", 44_000_000, 26.40),
                ]
            if hours_back <= 24:
                return [
                    ("usage", 11_200_000, 6.47),
                    ("FinMind", 3_100_000, 1.82),
                    ("AI客服", 800_000, 0.48),
                ]
            if hours_back <= 168:
                return [
                    ("usage", 78_400_000, 45.20),
                    ("FinMind", 21_700_000, 12.74),
                    ("AI客服", 5_600_000, 3.36),
                ]
            return [
                ("usage", 312_000_000, 180.50),
                ("FinMind", 86_400_000, 50.12),
                ("AI客服", 22_000_000, 13.20),
            ]

        if entries is None:
            try:
                resolved = load_entries(hours_back=hours_back)
            except Exception:
                if os.environ.get("USAGE_DEBUG") == "1":
                    logger.warning("project usage load failed", exc_info=True)
                return []
        else:
            if hours_back == 24:
                today = datetime.now().astimezone().date()
                resolved = [e for e in entries if e.timestamp.astimezone().date() == today]
            elif hours_back > 0:
                cutoff = datetime.now(tz=UTC) - timedelta(hours=hours_back)
                resolved = [e for e in entries if e.timestamp >= cutoff]
            else:
                resolved = entries
        return menubar_state.project_rows(resolved)

    def _menubar_text_string(self, text: str) -> Any:
        return NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: NSFont.menuBarFontOfSize_(0)},
        )

    def _menubar_attributed_title(self, state: PopoverState) -> Any:
        title = NSMutableAttributedString.alloc().init()
        phoenix_frame = int(self.critter_frame) % len(critter_frames.PHOENIX_FRAMES)
        dragon_frame = int(self.dragon_frame) % len(critter_frames.DRAGON_FRAMES)
        lion_frame = int(self.lion_frame) % len(critter_frames.LION_FRAMES)
        if not state.hide_claude:
            claude_percent = (
                "--"
                if state.claude_session.percent is None
                else f"{_format_percent(state.claude_session.percent)}%"
            )
            title.appendAttributedString_(_menubar_icon_attachment_string(_claude_menubar_icon()))
            title.appendAttributedString_(self._menubar_text_string(f" {claude_percent}"))
            phoenix = _critter_frame_image(critter_frames.PHOENIX_FRAMES[phoenix_frame])
            if phoenix is not None:
                title.appendAttributedString_(self._menubar_text_string(" "))
                title.appendAttributedString_(_critter_icon_attachment_string(phoenix))
        if not state.hide_codex and (self.codex_5h_pct is not None or state.hide_claude):
            codex_percent = (
                "--"
                if self.codex_5h_pct is None
                else f"{_format_percent(float(self.codex_5h_pct))}%"
            )
            if not state.hide_claude:
                title.appendAttributedString_(self._menubar_text_string(" · "))
            title.appendAttributedString_(_menubar_icon_attachment_string(_codex_menubar_icon()))
            title.appendAttributedString_(self._menubar_text_string(f" {codex_percent}"))
            dragon = _critter_frame_image(critter_frames.DRAGON_FRAMES[dragon_frame])
            if dragon is not None:
                title.appendAttributedString_(self._menubar_text_string(" "))
                title.appendAttributedString_(_critter_icon_attachment_string(dragon))
        agy_session_percent = state.agy_session.percent
        agy_visible = not state.hide_agy and agy_session_percent is not None
        if agy_visible:
            assert agy_session_percent is not None
            agy_percent = f"{_format_percent(agy_session_percent)}%"
            if title.length() > 0:
                title.appendAttributedString_(self._menubar_text_string(" · "))
            title.appendAttributedString_(_menubar_icon_attachment_string(_agy_menubar_icon()))
            title.appendAttributedString_(self._menubar_text_string(f" {agy_percent}"))
            lion = _critter_frame_image(critter_frames.LION_FRAMES[lion_frame])
            if lion is not None:
                title.appendAttributedString_(self._menubar_text_string(" "))
                title.appendAttributedString_(_critter_icon_attachment_string(lion))
        if title.length() == 0:
            # Both providers hidden: keep a recognizable, clickable status item.
            title.appendAttributedString_(_menubar_icon_attachment_string(_claude_menubar_icon()))
        return title

    def _set_button_title(self, state: PopoverState) -> None:
        self._sync_critter_timer()
        self._sync_dragon_timer()
        self._sync_lion_timer()
        title = self._compose_title(state)
        phoenix_frame = int(self.critter_frame) if not state.hide_claude else None
        dragon_visible = not state.hide_codex and (
            self.codex_5h_pct is not None or state.hide_claude
        )
        dragon_frame = int(self.dragon_frame) if dragon_visible else None
        lion_visible = not state.hide_agy and state.agy_session.percent is not None
        lion_frame = int(self.lion_frame) if lion_visible else None
        title_key = (title, phoenix_frame, dragon_frame, lion_frame)
        if self._last_button_title_key == title_key:
            return

        button = self.status_item.button()
        # setTitle: forces a full NSStatusItem relayout (_adjustLength) that
        # cascades into the popover's frame/corner-mask recompute even while
        # it's hidden. attributedTitle is what's actually rendered, so during
        # critter/dragon/lion animation (their frame values changing every
        # 0.05-0.18s) only push the plain title when its own text changed —
        # not on every sprite frame — to avoid paying that relayout per frame.
        plain_key = (title,)
        if self._last_plain_title_key != plain_key:
            button.setTitle_(title)
            self._last_plain_title_key = plain_key
        button.setAttributedTitle_(self._menubar_attributed_title(state))
        self._last_button_title_key = title_key

    def _compose_title(self, state: PopoverState) -> str:
        parts: list[str] = []
        if not state.hide_claude:
            claude = (
                "--"
                if state.claude_session.percent is None
                else f"{_format_percent(state.claude_session.percent)}%"
            )
            parts.append(f"🐾 {claude}")
        if not state.hide_codex and (self.codex_5h_pct is not None or state.hide_claude):
            codex = (
                "--"
                if self.codex_5h_pct is None
                else f"{_format_percent(float(self.codex_5h_pct))}%"
            )
            parts.append(f"📜 {codex}")
        if not state.hide_agy and state.agy_session.percent is not None:
            agy = f"{_format_percent(state.agy_session.percent)}%"
            parts.append(f"🦁 {agy}")
        # Both providers hidden: keep a recognizable, clickable status item.
        return " · ".join(parts) if parts else "🐾"


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


def _popover_size(state: PopoverState, panel: UsagePanel | None = None) -> Any:
    active_panel = panel if panel is not None else panels.get_panel("classic")
    width, base_height = active_panel.preferred_size()
    claude_deduct = active_panel.claude_card_height if state.hide_claude else 0.0
    codex_deduct = active_panel.codex_card_height if state.hide_codex else 0.0
    codex_missing_rows = sum(
        not row.title for row in (state.codex_session, state.codex_weekly)
    )
    codex_row_deduct = (
        getattr(active_panel, "codex_row_height", 0.0) * codex_missing_rows
        if not state.hide_codex and active_panel.codex_card_height > 0
        else 0.0
    )
    agy_card_height = getattr(active_panel, "agy_card_height", 0.0)
    agy_deduct = agy_card_height if state.hide_agy else 0.0
    install_extra = INSTALL_BUTTON_EXTRA_HEIGHT if state.show_install_button else 0.0
    height = (
        base_height
        + install_extra
        - claude_deduct
        - codex_deduct
        - codex_row_deduct
        - agy_deduct
    )
    return NSMakeSize(width, height)


def _classify_history_load_error(exc: Exception) -> str:
    if isinstance(exc, OSError):
        return "history_load_error_file"
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return "history_load_error_parse"
    return "history_load_error_unknown"


def _empty_state(language: str = "en") -> PopoverState:
    return PopoverState(
        language=language,
        claude_session=_missing_row(_t(language, "session_label"), CLAUDE_COLOR, language),
        claude_weekly=_missing_row(_t(language, "weekly_label"), CLAUDE_COLOR, language),
        codex_session=_missing_row(_t(language, "session_label"), CODEX_COLOR, language),
        codex_weekly=_missing_row(_t(language, "weekly_label"), CODEX_COLOR, language),
        agy_session=_missing_row(_t(language, "session_label"), menubar_state.AGY_COLOR, language),
        agy_weekly=_missing_row(_t(language, "weekly_label"), menubar_state.AGY_COLOR, language),
        agy_group_name="",
        projects=[],
        projects_7d=[],
        projects_30d=[],
        projects_all=[],
        rate_text=_t(language, "rate_text", value="--"),
        status_text=_t(language, "status_text", value=_t(language, "status_loading")),
        today_text=_t(language, "today_text", cost="0.00", tokens="0"),
        statusline=_statusline_payload(language),
        show_install_button=False,
        hide_claude=_hide_claude_enabled(),
        hide_codex=_hide_codex_enabled(),
        # Keep the card mounted while the first background probe is running.
        # Otherwise startup shows the shorter layout until agy finishes, which
        # looks like the integration never loaded even though the child process
        # is already active.
        hide_agy=menubar_agy.find_agy() is None,
        card_order=_quota_card_order(),
    )


def _error_state(message: str, mock: bool, language: str = "en") -> PopoverState:
    state = _empty_state(language)
    state.status_text = _t(
        language,
        "status_text",
        value=_t(language, "status_error", message=message),
    )
    state.today_text = _today_title(mock, language)
    state.show_install_button = False
    return state


def _statusline_payload(language: str) -> dict[str, object]:
    return {
        "enabled": _statusline_enabled(),
        "enabledText": _t(language, "cli_enabled"),
        "disabledText": _t(language, "cli_disabled"),
    }


def show_forwarder_mode_prompt_if_needed(language: str | None = None) -> None:
    import setup_hook

    try:
        settings = setup_hook._load_settings()
        usage_settings = settings.get(setup_hook.BACKUP_KEY)
        dismissed = (
            isinstance(usage_settings, dict)
            and usage_settings.get("forwarderModePromptDismissed") is True
        )
        if dismissed or setup_hook._detect_current_state(settings) != "external":
            return
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("forwarder prompt check failed", exc_info=True)
        return

    lang = language or detect_lang()
    alert = _make_alert()
    alert.setMessageText_(_t(lang, "alert_forwarder_title"))
    alert.setInformativeText_(_t(lang, "alert_forwarder_body"))
    alert.addButtonWithTitle_(_t(lang, "alert_forwarder_enable"))
    alert.addButtonWithTitle_(_t(lang, "alert_forwarder_keep"))
    result = int(alert.runModal())

    try:
        if result == 1000:
            import session_hooks

            setup_hook.setup(force_forwarder=True)
            session_hooks._migrate_bundled_python_commands_if_needed()
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("forwarder setup failed", exc_info=True)
    finally:
        try:
            _set_forwarder_mode_prompt_dismissed()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("forwarder prompt dismissal failed", exc_info=True)


def _today_title(
    mock: bool = False,
    language: str = "en",
    entries: list[UsageEntry] | None = None,
) -> str:
    if mock:
        return _t(language, "today_text", cost="45.20", tokens="50,193,442")

    try:
        today = datetime.now().astimezone().date()
        total_tokens = 0
        total_cost = 0.0

        all_entries = (
            entries
            if entries is not None
            else list(load_entries(hours_back=24)) + codex_loader.load_entries(hours_back=24)
        )
        for entry in all_entries:
            if entry.timestamp.astimezone().date() != today:
                continue
            total_tokens += entry.total_tokens
            total_cost += calculate_cost(entry)
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("today totals load failed", exc_info=True)
        return _t(language, "today_text", cost="0.00", tokens="0")

    return _t(language, "today_text", cost=f"{total_cost:.2f}", tokens=f"{total_tokens:,}")
