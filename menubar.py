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
from typing import Any

import objc
from AppKit import (
    NSAlert,
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
    NSViewController,
)
from Foundation import NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer

import codex_loader
import login_item
import menubar_state
import panels
import update_checker
from burn_rate import BurnRateTracker
from fsevents_watch import cleanup_fsevents, setup_fsevents
from history_loader import UsageEntry, load_entries
from i18n import _t, packaged_resource_path
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
from panels.base import load_active_panel_id, resolve_resource, save_active_panel_id
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
]

BUTTON_HEIGHT = 32.0
INSTALL_BUTTON_EXTRA_HEIGHT = BUTTON_HEIGHT + 10.0
UPDATE_DISMISS_SECONDS = 24 * 3600
UPDATE_ALERT_BODY_LIMIT = 2000

logger = logging.getLogger(__name__)


def _detect_language() -> str:
    return detect_lang()


def _panel_title(panel: UsagePanel, language: str) -> str:
    return _t(language, panel.i18n_key)


def _auto_update_check_enabled(prefs: dict[str, Any] | None = None) -> bool:
    data = _load_preferences() if prefs is None else prefs
    return data.get("auto_update_check") is not False


def _hide_codex_enabled(prefs: dict[str, Any] | None = None) -> bool:
    data = _load_preferences() if prefs is None else prefs
    return data.get("hide_codex_section") is True


def _quota_notifications_enabled(prefs: dict[str, Any] | None = None) -> bool:
    data = _load_preferences() if prefs is None else prefs
    return data.get("quota_notifications") is not False


def _quota_notification_thresholds(prefs: dict[str, Any] | None = None) -> list[float]:
    data = _load_preferences() if prefs is None else prefs
    raw = data.get("quota_notification_thresholds")
    if not isinstance(raw, list):
        return [90.0]
    thresholds: list[float] = []
    for value in raw:
        if isinstance(value, int | float) and 0 < float(value) <= 100:
            thresholds.append(float(value))
    return thresholds or [90.0]


def _session_resume_enabled() -> bool:
    # State lives in ~/.claude/settings.json (a hook), not in usage's prefs file.
    try:
        import setup_hook

        return setup_hook.is_resume_enabled()
    except Exception:
        return False


_ALERT_ICON: Any = None
_ALERT_ICON_LOADED = False
_CLAUDE_MENUBAR_ICON: Any = None
_CLAUDE_MENUBAR_ICON_LOADED = False
_CODEX_MENUBAR_ICON: Any = None
_CODEX_MENUBAR_ICON_LOADED = False


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


def _menubar_icon_attachment_string(image: Any) -> Any:
    attachment = NSTextAttachment.alloc().init()
    attachment.setImage_(image)
    attachment.setBounds_(NSMakeRect(0, -2.5, 14, 14))
    return NSAttributedString.attributedStringWithAttachment_(attachment)


def _make_alert() -> Any:
    alert = NSAlert.alloc().init()
    icon = _alert_icon()
    if icon is not None:
        alert.setIcon_(icon)
    return alert


def _user_notification_center() -> tuple[Any, dict[str, int]]:
    from UserNotifications import (
        UNAuthorizationOptionAlert,
        UNAuthorizationOptionBadge,
        UNAuthorizationOptionSound,
        UNUserNotificationCenter,
    )

    return (
        UNUserNotificationCenter.currentNotificationCenter(),
        {
            "alert": int(UNAuthorizationOptionAlert),
            "badge": int(UNAuthorizationOptionBadge),
            "sound": int(UNAuthorizationOptionSound),
        },
    )


def _user_notification_classes() -> tuple[Any, Any, Any]:
    from UserNotifications import (
        UNMutableNotificationContent,
        UNNotificationRequest,
        UNNotificationSound,
    )

    return UNMutableNotificationContent, UNNotificationRequest, UNNotificationSound


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


class PopoverViewController(NSViewController):
    content_view = objc.ivar()
    panel = objc.ivar()
    delegate = objc.ivar()

    def initWithPanel_delegate_(self, panel: UsagePanel, delegate: Any) -> PopoverViewController:
        self = objc.super(PopoverViewController, self).init()
        if self is None:
            return None
        self.panel = panel
        self.delegate = delegate
        self.content_view = panel.build_view(delegate)
        self.setView_(self.content_view)
        return self

    def rebuildWithPanel_(self, panel: UsagePanel) -> None:
        if hasattr(self.content_view, "teardown"):
            self.content_view.teardown()
        self.panel = panel
        self.content_view = panel.build_view(self.delegate)
        self.setView_(self.content_view)

    def setState_(self, state: PopoverState) -> None:
        self.view().setFrameSize_(_popover_size(state, self.panel))
        self.panel.apply_state(self.content_view, state)


class AppDelegate(NSObject):
    status_item = objc.ivar()
    popover = objc.ivar()
    popover_controller = objc.ivar()
    timer = objc.ivar()
    mock = objc.ivar()
    interval = objc.ivar()
    tracker = objc.ivar()
    latest_state = objc.ivar()
    active_panel = objc.ivar()
    codex_5h_pct = objc.ivar()
    codex_model = objc.ivar()
    burn_rate_trackers = objc.ivar()
    _refresh_in_flight = objc.ivar()
    _refresh_queued = objc.ivar()
    _fs_stream = objc.ivar()
    _history_entries_cache = objc.ivar()
    _history_entries_cache_fingerprint = objc.ivar()
    _quota_notifier = objc.ivar()
    _switch_menu_action_taken = objc.ivar()
    language = objc.ivar()

    def initWithMock_interval_(self, mock: bool, interval: int) -> AppDelegate:
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.mock = mock
        self.interval = max(30, interval)
        self.tracker = UsageRateTracker(mock=mock)
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
        self._fs_stream = None
        self._history_entries_cache = None
        self._history_entries_cache_fingerprint = None
        self._switch_menu_action_taken = False
        return self

    def applicationDidFinishLaunching_(self, notification: Any) -> None:
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength,
        )
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
        self.popover.setContentSize_(_popover_size(self.latest_state, self.active_panel))
        self.popover.setContentViewController_(self.popover_controller)

        self._request_notification_authorization()
        self._refresh()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.interval,
            self,
            "timerFired:",
            None,
            True,
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes)
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
        if self.timer is not None:
            self.timer.invalidate()
        NSApp.terminate_(sender)

    def applicationWillTerminate_(self, notification: Any) -> None:
        cleanup_fsevents(self._fs_stream)
        self._fs_stream = None

    def switchPanel_(self, sender: Any) -> None:
        menu = NSMenu.alloc().initWithTitle_(_t(self.language, "switch_panel"))
        # Panel themes live in a submenu so the menu stays short — one "面板主題 ▸"
        # row that expands on demand instead of nine inline rows.
        panel_submenu = NSMenu.alloc().initWithTitle_(_t(self.language, "switch_panel"))
        for panel in panels.all_panels():
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
        menu.addItem_(NSMenuItem.separatorItem())
        launch_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "launch_at_login"),
            "toggleLaunchAtLogin:",
            "",
        )
        launch_item.setTarget_(self)
        launch_item.setState_(1 if login_item.is_enabled() else 0)
        menu.addItem_(launch_item)
        menu.addItem_(NSMenuItem.separatorItem())
        auto_update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "auto_update_check"),
            "toggleAutoUpdateCheck:",
            "",
        )
        auto_update_item.setTarget_(self)
        auto_update_item.setState_(1 if _auto_update_check_enabled() else 0)
        menu.addItem_(auto_update_item)
        menu.addItem_(NSMenuItem.separatorItem())
        hide_codex_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "hide_codex_section"),
            "toggleHideCodex:",
            "",
        )
        hide_codex_item.setTarget_(self)
        hide_codex_item.setState_(1 if _hide_codex_enabled() else 0)
        menu.addItem_(hide_codex_item)
        quota_notifications_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "quota_notifications_menu"),
            "toggleQuotaNotifications:",
            "",
        )
        quota_notifications_item.setTarget_(self)
        quota_notifications_item.setState_(1 if _quota_notifications_enabled() else 0)
        menu.addItem_(quota_notifications_item)
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

    def toggleAutoUpdateCheck_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        prefs = _load_preferences()
        enabled = not _auto_update_check_enabled(prefs)
        prefs["auto_update_check"] = enabled
        _save_preferences(prefs)
        if hasattr(sender, "setState_"):
            sender.setState_(1 if enabled else 0)
        if enabled:
            thread = threading.Thread(
                target=self._check_update_in_background,
                kwargs={"manual": True, "ignore_cooldown": True, "ignore_skipped": True},
                daemon=True,
            )
            thread.start()

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

    def toggleSessionResume_(self, sender: Any) -> None:
        self._mark_switch_menu_action()
        thread = threading.Thread(target=self._toggle_session_resume_in_background, daemon=True)
        thread.start()

    def _toggle_session_resume_in_background(self) -> None:
        import setup_hook

        output = io.StringIO()
        ok = True
        enabled = False
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                if setup_hook.is_resume_enabled():
                    setup_hook.disable_session_resume()
                else:
                    ok = setup_hook.enable_session_resume() == 0
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

    def _clear_stale_update_cache(self) -> None:
        try:
            current_version = _current_version()
            prefs = _load_preferences()
            cached = prefs.get("last_update_check")
            if (
                isinstance(cached, dict)
                and isinstance(cached.get("latest_version"), str)
                and cached.get("current_version") != current_version
                and update_checker.compare_versions(current_version, cached["latest_version"]) >= 0
            ):
                prefs["last_update_check"] = {
                    **cached,
                    "current_version": current_version,
                    "latest_version": current_version,
                }
                _save_preferences(prefs)
        except Exception:
            pass

    def _maybe_check_update_in_background(self) -> None:
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
        prefs["last_update_check"] = {
            "checked_at": time.time(),
            "current_version": current_version,
            "latest_version": release.version if release else current_version,
            "release_url": release.html_url if release else None,
        }
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
        if result == 1000:
            webbrowser.open(release.html_url)
            return

        prefs = _load_preferences()
        if result == 1002:
            prefs["update_skipped_version"] = release.version
        else:
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
        was_shown = bool(self.popover.isShown())
        if was_shown:
            self.popover.performClose_(None)
        save_active_panel_id(panel.id)
        self.active_panel = panel
        self.popover_controller.rebuildWithPanel_(panel)
        self.popover_controller.setState_(self.latest_state)
        self.popover.setContentSize_(_popover_size(self.latest_state, panel))
        if was_shown:
            button = self.status_item.button()
            self.popover.showRelativeToRect_ofView_preferredEdge_(
                button.bounds(),
                button,
                NSMinYEdge,
            )

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

    def togglePopover_(self, sender: Any) -> None:
        if self.popover.isShown():
            self.popover.performClose_(sender)
            return
        self.popover_controller.setState_(self.latest_state)
        self.popover.setContentSize_(_popover_size(self.latest_state, self.active_panel))
        button = self.status_item.button()
        self.popover.showRelativeToRect_ofView_preferredEdge_(button.bounds(), button, NSMinYEdge)

    def _refresh(self, queue_if_busy: bool = False) -> None:
        if self._refresh_in_flight:
            if queue_if_busy:
                self._refresh_queued = True
            return
        self._refresh_in_flight = True
        thread = threading.Thread(target=self._refresh_in_background, daemon=True)
        thread.start()

    def refreshFromFileEvent_(self, _sender: Any) -> None:
        self._refresh(queue_if_busy=True)

    def _refresh_in_background(self) -> None:
        submitted = False
        try:
            codex_result = self._load_codex_refresh_result()
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "_applyCodexRefreshResult:",
                codex_result,
                False,
            )
            try:
                outcome = asyncio.run(self._fetch())
                codex_rows = codex_result["codex_rows"]
                codex_5h_pct = codex_result["codex_5h_pct"]
                codex_model = codex_result.get("codex_model", "unknown")
                codex_stale = codex_result.get("codex_stale")
                all_entries = self._load_history_entries()
                project_rows = self._project_rows(hours_back=24, entries=all_entries)
                project_rows_7d = self._project_rows(hours_back=168, entries=all_entries)
                project_rows_30d = self._project_rows(hours_back=720, entries=all_entries)
                project_rows_all = self._project_rows(hours_back=0, entries=all_entries)
                today_text = _today_title(self.mock, self.language, entries=all_entries)
                statusline = _statusline_payload(self.language)
                show_install_button = (
                    outcome.state == PollState.TOKEN_ERROR and self._statusline_setup_available()
                )
                hide_codex = _hide_codex_enabled()
                group = self.tracker.group()
                state = menubar_state.build_popover_state(
                    outcome=outcome,
                    codex_rows=codex_rows,
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
                    hide_codex=hide_codex,
                    codex_stale=codex_stale,
                )
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
                _missing_row("Session", CODEX_COLOR, self.language),
                _missing_row("Weekly", CODEX_COLOR, self.language),
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
                    scope=_notification_scope(self.language, event.channel),
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
        content_view = self.popover_controller.content_view
        if not hasattr(content_view, "evaluateJavaScript_completionHandler_"):
            return
        content_view.evaluateJavaScript_completionHandler_(
            f"window.usageSetLanguage && window.usageSetLanguage({json.dumps(language)})",
            None,
        )

    def _install_hook_in_background(self) -> None:
        output = io.StringIO()
        exit_code = 1
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                import setup_hook

                exit_code = setup_hook.setup()
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
        return menubar_state.history_sources_fingerprint()

    def _load_history_entries(self) -> list[UsageEntry]:
        if self.mock:
            return []
        fingerprint = self._history_sources_fingerprint()
        if (
            self._history_entries_cache is not None
            and self._history_entries_cache_fingerprint == fingerprint
        ):
            return list(self._history_entries_cache)

        entries: list[UsageEntry] = []
        try:
            entries.extend(load_entries(hours_back=0))
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Claude project usage load failed", exc_info=True)
        try:
            entries.extend(codex_loader.load_entries(hours_back=0))
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Codex project usage load failed", exc_info=True)
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
        claude_percent = (
            "--"
            if state.claude_session.percent is None
            else f"{_format_percent(state.claude_session.percent)}%"
        )
        title.appendAttributedString_(_menubar_icon_attachment_string(_claude_menubar_icon()))
        title.appendAttributedString_(self._menubar_text_string(f" {claude_percent}"))
        if self.codex_5h_pct is not None:
            title.appendAttributedString_(self._menubar_text_string(" · "))
            title.appendAttributedString_(_menubar_icon_attachment_string(_codex_menubar_icon()))
            title.appendAttributedString_(
                self._menubar_text_string(f" {_format_percent(float(self.codex_5h_pct))}%"),
            )
        return title

    def _set_button_title(self, state: PopoverState) -> None:
        button = self.status_item.button()
        button.setTitle_(self._compose_title(state))
        button.setAttributedTitle_(self._menubar_attributed_title(state))

    def _compose_title(self, state: PopoverState) -> str:
        base = (
            "🐾 --"
            if state.claude_session.percent is None
            else f"🐾 {_format_percent(state.claude_session.percent)}%"
        )
        if self.codex_5h_pct is None:
            return base
        return f"{base} · 📜 {_format_percent(float(self.codex_5h_pct))}%"


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
        return "week"
    if project_range == "all":
        return "all"
    return "month"


def _popover_size(state: PopoverState, panel: UsagePanel | None = None) -> Any:
    active_panel = panel if panel is not None else panels.get_panel("classic")
    width, base_height = active_panel.preferred_size()
    codex_deduct = active_panel.codex_card_height if state.hide_codex else 0.0
    install_extra = INSTALL_BUTTON_EXTRA_HEIGHT if state.show_install_button else 0.0
    height = base_height + install_extra - codex_deduct
    return NSMakeSize(width, height)


def _empty_state(language: str = "en") -> PopoverState:
    return PopoverState(
        language=language,
        claude_session=_missing_row("Session", CLAUDE_COLOR, language),
        claude_weekly=_missing_row("Weekly", CLAUDE_COLOR, language),
        codex_session=_missing_row("Session", CODEX_COLOR, language),
        codex_weekly=_missing_row("Weekly", CODEX_COLOR, language),
        projects=[],
        projects_7d=[],
        projects_30d=[],
        projects_all=[],
        rate_text=_t(language, "rate_text", value="--"),
        status_text=_t(language, "status_text", value=_t(language, "status_loading")),
        today_text=_t(language, "today_text", cost="0.00", tokens="0"),
        statusline=_statusline_payload(language),
        show_install_button=False,
        hide_codex=_hide_codex_enabled(),
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
            setup_hook.setup(force_forwarder=True)
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
