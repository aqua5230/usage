# mypy: disable-error-code="import-untyped,misc"
# PyObjC modules do not ship type stubs, and their base classes resolve to Any in mypy.
from __future__ import annotations

import asyncio
import contextlib
import ctypes
import io
import json
import logging
import os
import shlex
import tempfile
import threading
import time
import tomllib
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import objc
from AppKit import (
    NSAlert,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSMakePoint,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSMinYEdge,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSViewController,
)
from Foundation import NSLocale, NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer

import codex_loader
import login_item
import panels
import update_checker
from burn_rate import WARNING_PERCENT_FLOOR, BurnRateTracker
from history_loader import UsageEntry, load_entries
from i18n import _t, packaged_resource_path
from main import _load_preferences, _save_preferences
from panels.base import Panel as UsagePanel
from panels.base import load_active_panel_id, save_active_panel_id
from pricing import calculate_cost
from usage_client import ClaudeUsageClient, PollOutcome, PollState
from usage_rate import GROUP_NAMES, UsageRateTracker

# --- FSEvents (ctypes) for event-driven UI refresh ---
_FSEVENTS_AVAILABLE = False
_fs_callback_ref: Any = None  # prevent GC of ctypes callback

try:
    _cs_lib = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreServices.framework/CoreServices",
    )
    _cf_lib = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    )
    _FSEventStreamCallback = ctypes.CFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint64),
    )
    _cs_lib.FSEventStreamCreate.restype = ctypes.c_void_p
    _cs_lib.FSEventStreamCreate.argtypes = [
        ctypes.c_void_p,
        _FSEventStreamCallback,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.c_uint32,
    ]
    _cs_lib.FSEventStreamScheduleWithRunLoop.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _cs_lib.FSEventStreamStart.restype = ctypes.c_int
    _cs_lib.FSEventStreamStart.argtypes = [ctypes.c_void_p]
    _cs_lib.FSEventStreamStop.argtypes = [ctypes.c_void_p]
    _cs_lib.FSEventStreamInvalidate.argtypes = [ctypes.c_void_p]
    _cs_lib.FSEventStreamRelease.argtypes = [ctypes.c_void_p]
    _cf_lib.CFRunLoopGetCurrent.restype = ctypes.c_void_p
    _cf_lib.CFArrayCreate.restype = ctypes.c_void_p
    _cf_lib.CFArrayCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_long,
        ctypes.c_void_p,
    ]
    _cf_lib.CFStringCreateWithCString.restype = ctypes.c_void_p
    _cf_lib.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    _kCFStringEncodingUTF8 = 0x08000100
    _kFSEventStreamCreateFlagNoDefer = 0x00000002
    _kFSEventStreamEventIdSinceNow = 0xFFFFFFFFFFFFFFFF
    _FSEVENTS_AVAILABLE = True
except (OSError, AttributeError):
    pass


def _setup_fsevents(delegate: Any) -> Any:
    """Start FSEventStream watching ~/.claude/; returns stream handle or None."""
    global _fs_callback_ref
    if not _FSEVENTS_AVAILABLE:
        return None
    try:
        watch_path = str(Path.home() / ".claude")
        cf_path = _cf_lib.CFStringCreateWithCString(
            None,
            watch_path.encode("utf-8"),
            _kCFStringEncodingUTF8,
        )
        paths_arr = (ctypes.c_void_p * 1)(cf_path)
        cf_paths = _cf_lib.CFArrayCreate(None, paths_arr, 1, None)

        def _on_fs_event(
            _stream: Any,
            _info: Any,
            _num: Any,
            _paths: Any,
            _flags: Any,
            _ids: Any,
        ) -> None:
            delegate._refresh()

        _fs_callback_ref = _FSEventStreamCallback(_on_fs_event)
        stream = _cs_lib.FSEventStreamCreate(
            None,
            _fs_callback_ref,
            None,
            cf_paths,
            _kFSEventStreamEventIdSinceNow,
            0.5,
            _kFSEventStreamCreateFlagNoDefer,
        )
        if not stream:
            return None
        rl = _cf_lib.CFRunLoopGetCurrent()
        mode = _cf_lib.CFStringCreateWithCString(
            None,
            b"kCFRunLoopDefaultMode",
            _kCFStringEncodingUTF8,
        )
        _cs_lib.FSEventStreamScheduleWithRunLoop(stream, rl, mode)
        _cs_lib.FSEventStreamStart(stream)
        return stream
    except Exception:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("FSEvents setup failed", exc_info=True)
        return None


def _cleanup_fsevents(stream: Any) -> None:
    """Stop and release an FSEventStream."""
    if not _FSEVENTS_AVAILABLE or not stream:
        return
    with contextlib.suppress(Exception):
        _cs_lib.FSEventStreamStop(stream)
        _cs_lib.FSEventStreamInvalidate(stream)
        _cs_lib.FSEventStreamRelease(stream)


BUTTON_HEIGHT = 32.0
INSTALL_BUTTON_EXTRA_HEIGHT = BUTTON_HEIGHT + 10.0
CLAUDE_COLOR = (244 / 255, 145 / 255, 100 / 255)
CODEX_COLOR = (88 / 255, 214 / 255, 230 / 255)
WARN_COLOR = (255 / 255, 196 / 255, 57 / 255)
DANGER_COLOR = (255 / 255, 69 / 255, 58 / 255)
UPDATE_DISMISS_SECONDS = 24 * 3600
UPDATE_ALERT_BODY_LIMIT = 2000

logger = logging.getLogger(__name__)


def _bar_color(pct: float, brand: tuple[float, float, float]) -> tuple[float, float, float]:
    if pct >= 80:
        return DANGER_COLOR
    if pct >= 50:
        return WARN_COLOR
    return brand


def _normalize_language(code: str | None) -> str:
    if not code:
        return "en"
    normalized = code.strip().lower().replace("_", "-")
    if normalized in {"zh-tw", "zh-hant"} or normalized.startswith("zh-tw-"):
        return "zh-TW"
    if normalized in {"zh-cn", "zh-hans", "zh"} or normalized.startswith("zh-cn-"):
        return "zh-CN"
    if normalized.startswith("zh-hans"):
        return "zh-CN"
    if normalized.startswith("zh-hant"):
        return "zh-TW"
    if normalized.startswith("ja"):
        return "ja"
    if normalized.startswith("ko"):
        return "ko"
    return "en"


def _detect_language() -> str:
    if override := os.environ.get("USAGE_LANG"):
        return _normalize_language(override)
    try:
        # preferredLanguages reflects the user's system language list and is not
        # affected by the bundle's CFBundleDevelopmentRegion / .lproj mapping.
        preferred = NSLocale.preferredLanguages()
        if preferred:
            return _normalize_language(str(preferred[0]))
        locale = NSLocale.currentLocale()
        identifier_attr = getattr(locale, "localeIdentifier", None)
        identifier = identifier_attr() if callable(identifier_attr) else identifier_attr
        return _normalize_language(str(identifier) if identifier is not None else None)
    except Exception:
        return "en"


def _group_name(group: int, language: str) -> str:
    return _t(language, f"group_{GROUP_NAMES[group].lower()}")


def _panel_title(panel: UsagePanel, language: str) -> str:
    return _t(language, panel.i18n_key)


def _auto_update_check_enabled(prefs: dict[str, Any] | None = None) -> bool:
    data = _load_preferences() if prefs is None else prefs
    return data.get("auto_update_check") is not False


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


@dataclass(slots=True)
class QuotaRowState:
    title: str
    percent: float | None
    percent_text: str
    reset_text: str
    color: tuple[float, float, float]
    warning: bool = False
    available: bool = True


@dataclass(slots=True)
class PopoverState:
    language: str
    claude_session: QuotaRowState
    claude_weekly: QuotaRowState
    codex_session: QuotaRowState
    codex_weekly: QuotaRowState
    projects: list[tuple[str, int, float | None]]
    projects_7d: list[tuple[str, int, float | None]]
    projects_30d: list[tuple[str, int, float | None]]
    rate_text: str
    status_text: str
    today_text: str
    statusline: dict[str, object]
    show_install_button: bool = False


def format_human_time(seconds: float, language: str = "en") -> str:
    if seconds <= 0:
        return _t(language, "duration_minutes", minutes=0)
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return _t(language, "duration_days", days=days, hours=hours)
    if hours > 0:
        return _t(language, "duration_hours", hours=hours, minutes=minutes)
    return _t(language, "duration_minutes", minutes=minutes)


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
    burn_rate_trackers = objc.ivar()
    _refresh_in_flight = objc.ivar()
    _fs_stream = objc.ivar()
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
        self.latest_state = _empty_state(self.language)
        self.active_panel = panels.get_panel(load_active_panel_id())
        self.burn_rate_trackers = {
            "claude_session": BurnRateTracker(),
            "claude_weekly": BurnRateTracker(),
            "codex_session": BurnRateTracker(),
            "codex_weekly": BurnRateTracker(),
        }
        self._refresh_in_flight = False
        self._fs_stream = None
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

        self._refresh()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            300,
            self,
            "timerFired:",
            None,
            True,
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes)
        self._fs_stream = _setup_fsevents(self)
        thread = threading.Thread(target=self._maybe_check_update_in_background, daemon=True)
        thread.start()

    def timerFired_(self, timer: Any) -> None:
        self._refresh()

    def refreshNow_(self, sender: Any) -> None:
        self._refresh()

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
        thread = threading.Thread(target=self._analyze_usage_in_background, daemon=True)
        thread.start()

    def quitApp_(self, sender: Any) -> None:
        if self.timer is not None:
            self.timer.invalidate()
        NSApp.terminate_(sender)

    def applicationWillTerminate_(self, notification: Any) -> None:
        _cleanup_fsevents(self._fs_stream)
        self._fs_stream = None

    def switchPanel_(self, sender: Any) -> None:
        menu = NSMenu.alloc().initWithTitle_(_t(self.language, "switch_panel"))
        for panel in panels.all_panels():
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                _panel_title(panel, self.language),
                "selectPanel:",
                "",
            )
            item.setTarget_(self)
            item.setRepresentedObject_(panel.id)
            item.setState_(1 if panel.id == self.active_panel.id else 0)
            menu.addItem_(item)
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
        check_update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            _t(self.language, "update_check_now"),
            "checkUpdateNow:",
            "",
        )
        check_update_item.setTarget_(self)
        menu.addItem_(check_update_item)
        menu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0, 0), sender)

    def selectPanel_(self, sender: Any) -> None:
        panel_id = str(sender.representedObject())
        self._set_active_panel_id(panel_id)

    def toggleLaunchAtLogin_(self, sender: Any) -> None:
        try:
            if login_item.is_enabled():
                login_item.disable()
            else:
                login_item.enable()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("toggle launch at login failed", exc_info=True)

    def toggleAutoUpdateCheck_(self, sender: Any) -> None:
        prefs = _load_preferences()
        enabled = not _auto_update_check_enabled(prefs)
        prefs["auto_update_check"] = enabled
        _save_preferences(prefs)
        if hasattr(sender, "setState_"):
            sender.setState_(1 if enabled else 0)

    def checkUpdateNow_(self, sender: Any) -> None:
        thread = threading.Thread(
            target=self._check_update_in_background,
            kwargs={"manual": True, "ignore_cooldown": True, "ignore_skipped": True},
            daemon=True,
        )
        thread.start()

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
        alert = NSAlert.alloc().init()
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
        alert = NSAlert.alloc().init()
        alert.setMessageText_(_t(self.language, "update_no_new_version"))
        alert.runModal()

    def _showUpdateCheckFailed_(self, result: Any) -> None:
        alert = NSAlert.alloc().init()
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

    def togglePopover_(self, sender: Any) -> None:
        if self.popover.isShown():
            self.popover.performClose_(sender)
            return
        self.popover_controller.setState_(self.latest_state)
        self.popover.setContentSize_(_popover_size(self.latest_state, self.active_panel))
        button = self.status_item.button()
        self.popover.showRelativeToRect_ofView_preferredEdge_(button.bounds(), button, NSMinYEdge)

    def _refresh(self) -> None:
        if self._refresh_in_flight:
            return
        self._refresh_in_flight = True
        thread = threading.Thread(target=self._refresh_in_background, daemon=True)
        thread.start()

    def _refresh_in_background(self) -> None:
        try:
            outcome = asyncio.run(self._fetch())
            codex_rows, codex_5h_pct = self._codex_rows()
            all_entries = self._load_history_entries()
            project_rows = self._project_rows(hours_back=24, entries=all_entries)
            project_rows_7d = self._project_rows(hours_back=168, entries=all_entries)
            project_rows_30d = self._project_rows(hours_back=720, entries=all_entries)
            state = self._state_from_outcome(
                outcome,
                codex_rows,
                project_rows,
                project_rows_7d,
                project_rows_30d,
                history_entries=all_entries,
            )
        except Exception as exc:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("refresh failed", exc_info=True)
            codex_5h_pct = None
            state = _error_state(type(exc).__name__, self.mock, self.language)

        result = {"state": state, "codex_5h_pct": codex_5h_pct}
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "_applyRefreshResult:",
            result,
            False,
        )

    def _applyRefreshResult_(self, result: dict[str, Any]) -> None:
        state = result["state"]
        codex_5h_pct = result["codex_5h_pct"]
        self.codex_5h_pct = codex_5h_pct
        self.latest_state = state
        if self.popover.isShown():
            self.popover_controller.setState_(self.latest_state)
        self.popover.setContentSize_(_popover_size(state, self.active_panel))
        self._inject_web_language(state.language)
        self.status_item.button().setTitle_(self._compose_title(state))
        self._refresh_in_flight = False

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
        alert = NSAlert.alloc().init()
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
        alert = NSAlert.alloc().init()
        alert.setMessageText_(_t(self.language, "statusline_action_failed"))
        alert.setInformativeText_(str(result.get("output") or result.get("action") or ""))
        alert.runModal()

    def _refresh_statusline_state(self) -> None:
        self.latest_state.statusline = _statusline_payload(self.language)
        self.popover_controller.setState_(self.latest_state)

    def _analyze_usage_in_background(self) -> None:
        result: dict[str, str | bool]
        try:
            saved = _generate_analysis_report()
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
        alert = NSAlert.alloc().init()
        alert.setMessageText_(_t(self.language, "analysis_failed"))
        alert.setInformativeText_(str(result["message"]))
        alert.runModal()

    async def _fetch(self) -> PollOutcome:
        client = ClaudeUsageClient(mock=self.mock)
        try:
            return await client.fetch_once()
        finally:
            await client.aclose()

    def _status_message_value(self, outcome: PollOutcome, fallback_key: str) -> str:
        if outcome.message == "awaiting_rate_limits":
            return _t(self.language, "awaiting_rate_limits")
        return outcome.message or _t(self.language, fallback_key)

    def _state_from_outcome(
        self,
        outcome: PollOutcome,
        codex_rows: tuple[QuotaRowState, QuotaRowState],
        projects: list[tuple[str, int, float | None]],
        project_rows_7d: list[tuple[str, int, float | None]],
        project_rows_30d: list[tuple[str, int, float | None]],
        history_entries: list[UsageEntry] | None = None,
    ) -> PopoverState:
        now = time.time()
        today_text = _today_title(self.mock, self.language, entries=history_entries)
        group_name = _group_name(self.tracker.group(), self.language)
        status_text = _t(
            self.language,
            "status_text",
            value=self._status_message_value(outcome, "status_loading"),
        )

        if outcome.state == PollState.SUCCESS and outcome.snapshot is not None:
            snapshot = outcome.snapshot
            if snapshot.current_percent is not None:
                self.burn_rate_trackers["claude_session"].record(
                    snapshot.polled_at,
                    float(snapshot.current_percent),
                )
            if snapshot.weekly_percent is not None:
                self.burn_rate_trackers["claude_weekly"].record(
                    snapshot.polled_at,
                    float(snapshot.weekly_percent),
                )
            claude_session = _quota_row(
                "Session",
                float(snapshot.current_percent) if snapshot.current_percent is not None else None,
                snapshot.current_reset_at,
                now,
                CLAUDE_COLOR,
                self.language,
                forecast_seconds=self.burn_rate_trackers["claude_session"].forecast_seconds(),
            )
            claude_weekly = _quota_row(
                "Weekly",
                float(snapshot.weekly_percent) if snapshot.weekly_percent is not None else None,
                snapshot.weekly_reset_at,
                now,
                CLAUDE_COLOR,
                self.language,
                forecast_seconds=self.burn_rate_trackers["claude_weekly"].forecast_seconds(),
                warning_max_seconds=24 * 3600,
            )
            status_value = outcome.message or _t(self.language, "status_synced")
            if snapshot.is_stale or snapshot.data_source != "hook":
                status_value = _t(self.language, "data_stale_hint")
            status_text = _t(
                self.language,
                "status_text",
                value=status_value,
            )
        else:
            claude_session = _missing_row("Session", CLAUDE_COLOR, self.language)
            claude_weekly = _missing_row("Weekly", CLAUDE_COLOR, self.language)
            status_text = _t(
                self.language,
                "status_text",
                value=self._status_message_value(outcome, "status_no_data"),
            )

        return PopoverState(
            language=self.language,
            claude_session=claude_session,
            claude_weekly=claude_weekly,
            codex_session=codex_rows[0],
            codex_weekly=codex_rows[1],
            projects=projects,
            projects_7d=project_rows_7d,
            projects_30d=project_rows_30d,
            rate_text=_t(self.language, "rate_text", value=group_name),
            status_text=status_text,
            today_text=today_text,
            statusline=_statusline_payload(self.language),
            show_install_button=outcome.state == PollState.TOKEN_ERROR,
        )

    def _codex_rows(self) -> tuple[tuple[QuotaRowState, QuotaRowState], int | None]:
        if self.mock:
            now = time.time()
            self.burn_rate_trackers["codex_session"].record(now, 12.0)
            self.burn_rate_trackers["codex_weekly"].record(now, 28.0)
            rows = (
                _quota_row(
                    "Session",
                    12.0,
                    now + (4 * 3600) + (15 * 60),
                    now,
                    CODEX_COLOR,
                    self.language,
                    forecast_seconds=self.burn_rate_trackers["codex_session"].forecast_seconds(),
                ),
                _quota_row(
                    "Weekly",
                    28.0,
                    now + (4 * 86400),
                    now,
                    CODEX_COLOR,
                    self.language,
                    forecast_seconds=self.burn_rate_trackers["codex_weekly"].forecast_seconds(),
                    warning_max_seconds=24 * 3600,
                ),
            )
            return rows, 12

        try:
            rate_limits = codex_loader.load_rate_limits()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("codex rate limits load failed", exc_info=True)
            rate_limits = None

        if rate_limits is None:
            rows = (
                _missing_row("Session", CODEX_COLOR, self.language),
                _missing_row("Weekly", CODEX_COLOR, self.language),
            )
            return rows, None

        now = time.time()
        codex_5h_pct = (
            round(rate_limits.five_hour_pct) if rate_limits.five_hour_pct is not None else None
        )
        if rate_limits.five_hour_pct is not None:
            self.burn_rate_trackers["codex_session"].record(now, rate_limits.five_hour_pct)
        if rate_limits.seven_day_pct is not None:
            self.burn_rate_trackers["codex_weekly"].record(now, rate_limits.seven_day_pct)
        rows = (
            _quota_row(
                "Session",
                rate_limits.five_hour_pct,
                rate_limits.five_hour_resets_at,
                now,
                CODEX_COLOR,
                self.language,
                forecast_seconds=self.burn_rate_trackers["codex_session"].forecast_seconds(),
            ),
            _quota_row(
                "Weekly",
                rate_limits.seven_day_pct,
                rate_limits.seven_day_resets_at,
                now,
                CODEX_COLOR,
                self.language,
                forecast_seconds=self.burn_rate_trackers["codex_weekly"].forecast_seconds(),
                warning_max_seconds=24 * 3600,
            ),
        )
        return rows, codex_5h_pct

    def _load_history_entries(self) -> list[UsageEntry]:
        if self.mock:
            return []
        entries: list[UsageEntry] = []
        try:
            entries.extend(load_entries(hours_back=720))
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Claude project usage load failed", exc_info=True)
        try:
            entries.extend(codex_loader.load_entries(hours_back=720))
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Codex project usage load failed", exc_info=True)
        return entries

    def _project_rows(
        self,
        hours_back: int = 24,
        entries: list[UsageEntry] | None = None,
    ) -> list[tuple[str, int, float | None]]:
        if self.mock:
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
            cutoff = datetime.now(tz=UTC) - timedelta(hours=hours_back)
            resolved = [e for e in entries if e.timestamp >= cutoff]

        aggregates: dict[str, list[float]] = {}
        for entry in resolved:
            bucket = aggregates.setdefault(entry.project, [0.0, 0.0])
            bucket[0] += entry.total_tokens
            bucket[1] += calculate_cost(entry)

        ranked = sorted(
            aggregates.items(),
            key=lambda item: (int(item[1][0]), item[0]),
            reverse=True,
        )
        rows: list[tuple[str, int, float | None]] = []
        for project, (tokens, cost) in ranked[:3]:
            rows.append(
                (
                    project,
                    int(tokens),
                    cost,
                )
            )
        return rows

    def _compose_title(self, state: PopoverState) -> str:
        base = (
            "🐾 --"
            if state.claude_session.percent is None
            else f"🐾 {_format_percent(state.claude_session.percent)}%"
        )
        if self.codex_5h_pct is None:
            return base
        return f"{base} · 📜 {self.codex_5h_pct}%"


def run_app(mock: bool = False, interval: int = 60) -> None:
    global _APP_DELEGATE
    app = NSApplication.sharedApplication()
    _APP_DELEGATE = AppDelegate.alloc().initWithMock_interval_(mock, interval)
    app.setDelegate_(_APP_DELEGATE)
    app.run()


def _generate_analysis_report(period: str = "month") -> str:
    from adapters.registry import detect_agents
    from analyzer.reporter import build_report_data
    from ui.html_report import save_and_open

    agents = detect_agents()
    data = build_report_data(agents, period)
    return cast(str, save_and_open(data))


def _popover_size(state: PopoverState, panel: UsagePanel | None = None) -> Any:
    active_panel = panel if panel is not None else panels.get_panel("classic")
    width, base_height = active_panel.preferred_size()
    height = base_height + (INSTALL_BUTTON_EXTRA_HEIGHT if state.show_install_button else 0.0)
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
        rate_text=_t(language, "rate_text", value="--"),
        status_text=_t(language, "status_text", value=_t(language, "status_loading")),
        today_text=_t(language, "today_text", cost="0.00", tokens="0"),
        statusline=_statusline_payload(language),
        show_install_button=False,
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


def _quota_row(
    title: str,
    pct: float | None,
    resets_at: float | None,
    now: float,
    color: tuple[float, float, float],
    language: str = "en",
    forecast_seconds: float | None = None,
    warning_max_seconds: float | None = None,
) -> QuotaRowState:
    if pct is None or resets_at is None:
        return _missing_row(title, color, language)
    pct = max(0.0, min(100.0, float(pct)))
    time_to_reset = resets_at - now
    warning_seconds: float | None = None
    if (
        forecast_seconds is not None
        and 0 < forecast_seconds < time_to_reset
        and (warning_max_seconds is None or forecast_seconds < warning_max_seconds)
        and pct >= WARNING_PERCENT_FLOOR
    ):
        warning_seconds = forecast_seconds
    warning = warning_seconds is not None
    if warning_seconds is not None:
        reset_text = _t(
            language,
            "burn_warning",
            empty=format_human_time(warning_seconds, language),
            reset=format_human_time(time_to_reset, language),
        )
    else:
        reset_text = _t(language, "reset_in", time=format_human_time(time_to_reset, language))
    return QuotaRowState(
        title=title,
        percent=pct,
        percent_text=_t(language, "percent_used", value=_format_percent(pct)),
        reset_text=reset_text,
        color=_bar_color(pct, color),
        warning=warning,
        available=True,
    )


def _missing_row(
    title: str,
    color: tuple[float, float, float],
    language: str = "en",
) -> QuotaRowState:
    return QuotaRowState(
        title=title,
        percent=None,
        percent_text="--",
        reset_text=_t(language, "reset_placeholder"),
        color=color,
        available=False,
    )



def _statusline_payload(language: str) -> dict[str, object]:
    return {
        "enabled": _statusline_enabled(),
        "enabledText": _t(language, "cli_enabled"),
        "disabledText": _t(language, "cli_disabled"),
    }


def _claude_settings_path() -> Path:
    return Path(os.path.expanduser("~/.claude/settings.json"))


def _load_claude_settings() -> dict[str, Any]:
    settings_path = _claude_settings_path()
    if not settings_path.exists():
        return {}
    with settings_path.open(encoding="utf-8") as file:
        settings = json.load(file)
    if not isinstance(settings, dict):
        raise ValueError(f"{settings_path} must be a JSON object")
    return settings


def _save_claude_settings(settings: dict[str, Any]) -> None:
    settings_path = _claude_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    trailing_newline = True
    with contextlib.suppress(OSError):
        trailing_newline = settings_path.read_bytes().endswith(b"\n")
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=settings_path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2, ensure_ascii=False)
            if trailing_newline:
                file.write("\n")
        os.replace(tmp_path, settings_path)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def _statusline_command_target_exists(statusline: object) -> bool:
    if not isinstance(statusline, dict):
        return True
    command = statusline.get("command")
    if not isinstance(command, str):
        return True
    try:
        parts = shlex.split(command)
    except ValueError:
        return True
    for part in parts:
        if "statusline" not in part or not part.endswith(".py"):
            continue
        return Path(os.path.expanduser(part)).exists()
    return True


def _disable_statusline_settings() -> int:
    settings = _load_claude_settings()
    if "statusLine" not in settings:
        return 0
    usage_settings = settings.setdefault("usage", {})
    if not isinstance(usage_settings, dict):
        usage_settings = {}
        settings["usage"] = usage_settings
    usage_settings["previousStatusLine"] = settings["statusLine"]
    del settings["statusLine"]
    _save_claude_settings(settings)
    return 0


def _enable_statusline_settings() -> int:
    settings = _load_claude_settings()
    if "statusLine" in settings:
        return 0
    raw_usage_settings = settings.get("usage")
    usage_settings = raw_usage_settings if isinstance(raw_usage_settings, dict) else None
    previous = usage_settings.get("previousStatusLine") if usage_settings is not None else None
    if previous:
        assert usage_settings is not None
        if not _statusline_command_target_exists(previous):
            del usage_settings["previousStatusLine"]
            if not usage_settings:
                del settings["usage"]
            _save_claude_settings(settings)
            import setup_hook

            return setup_hook.setup()
        settings["statusLine"] = previous
        del usage_settings["previousStatusLine"]
        if not usage_settings:
            del settings["usage"]
        _save_claude_settings(settings)
        return 0

    import setup_hook

    return setup_hook.setup()


def _toggle_statusline_settings() -> tuple[str, int]:
    if _statusline_enabled():
        return "uninstall", _disable_statusline_settings()
    return "install", _enable_statusline_settings()


def _statusline_enabled() -> bool:
    try:
        settings = _load_claude_settings()
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return "statusLine" in settings


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

        history = entries if entries is not None else load_entries(hours_back=24)
        all_entries = list(history) + codex_loader.load_entries(hours_back=24)
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


def _format_percent(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}"
