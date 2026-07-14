# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# mypy: disable-error-code="import-untyped,import-not-found,misc"
from __future__ import annotations

import json
import logging
import os
import threading
from typing import TYPE_CHECKING, Any

import objc
from AppKit import NSColor, NSFont, NSMakeRect, NSTextField, NSView
from Foundation import NSObject
from Quartz import CGColorCreateGenericRGB

import talent_market_bridge
from menubar_prefs import _save_quota_card_order, _valid_quota_card_order
from panels.payload import (
    _data_uri,
    _load_i18n_bundle,
    _load_panel_html,
    _new_state_payload,
    _row_payload,
    _state_payload,
)

__all__ = [
    "_data_uri",
    "_load_i18n_bundle",
    "_load_panel_html",
    "_new_state_payload",
    "_row_payload",
    "_state_payload",
]

try:
    from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration
except ModuleNotFoundError:
    with objc.autorelease_pool():
        objc.loadBundle(
            "WebKit",
            globals(),
            bundle_path="/System/Library/Frameworks/WebKit.framework",
        )

# py2app can import WebKit without all wrapper metadata. Register the block
# signature unconditionally; PyObjC metadata registration is idempotent.
objc.registerMetaDataForSelector(
    b"WKWebView",
    b"evaluateJavaScript:completionHandler:",
    {
        "arguments": {
            3: {
                "callable": {
                    "retval": {"type": b"v"},
                    "arguments": {
                        0: {"type": b"^v"},
                        1: {"type": b"@"},
                        2: {"type": b"@"},
                    },
                },
            },
        },
    },
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from menubar import PopoverState

PANEL_WIDTH = 364.0
PANEL_HEIGHT = 812.0
MAX_INJECTION_RELOADS = 2
NAVIGATION_MENU_IDENTIFIER_PARTS = (
    "WKMenuItemIdentifierReload",
    "WKMenuItemIdentifierGoBack",
    "WKMenuItemIdentifierGoForward",
    "WKMenuItemIdentifierOpenLink",
    "WKMenuItemIdentifierOpenImage",
    "WKMenuItemIdentifierOpenFrame",
    "WKMenuItemIdentifierDownload",
)


def _reload_web_panel(view: Any) -> None:
    view._ready = False
    view._first_paint_done = False
    view._last_injected_payload = None
    if getattr(view, "_last_payload", None) is not None:
        view._pending = view._last_payload
    html = getattr(view, "_html", None)
    if html is None:
        view.reload()
        return
    view.loadHTMLString_baseURL_(html, None)


def _is_navigation_menu_item(item: Any) -> bool:
    item_identifier = getattr(item, "itemIdentifier", None)
    if not callable(item_identifier):
        return False
    identifier = item_identifier()
    if identifier is None:
        return False
    identifier_text = str(identifier)
    return any(part in identifier_text for part in NAVIGATION_MENU_IDENTIFIER_PARTS)


def _remove_navigation_menu_items(menu: Any) -> None:
    for item in list(menu.itemArray()):
        if _is_navigation_menu_item(item):
            menu.removeItem_(item)


def _handle_injection_error(view: Any, payload: dict[str, object], error: Any) -> None:
    if error is None:
        view._injection_retry_payload = None
        view._injection_reload_count = 0
        return
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning("panel state injection failed: %s", error)
    if getattr(view, "_injection_retry_payload", None) is not payload:
        view._injection_retry_payload = payload
        view._injection_reload_count = 0
    if getattr(view, "_injection_reload_count", 0) >= MAX_INJECTION_RELOADS:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("panel state injection reload limit reached")
        view._pending = None
        return
    view._injection_reload_count += 1
    view._pending = payload
    _reload_web_panel(view)


class UsageScriptBridge(NSObject):
    delegate = objc.ivar()
    web_view = objc.ivar()

    def initWithDelegate_webView_(self, delegate: Any, web_view: Any) -> UsageScriptBridge:
        self = objc.super(UsageScriptBridge, self).init()
        if self is None:
            return None
        self.delegate = delegate
        self.web_view = web_view
        return self

    def userContentController_didReceiveScriptMessage_(self, controller: Any, message: Any) -> None:
        action = str(message.body())
        # New parametric actions arrive as a JSON string (e.g.
        # {"action":"install_role","roleId":"contract-review"}). Plain fixed-string
        # actions ("refresh", "switch", ...) never start with "{", so they skip
        # this branch unchanged.
        if action.startswith("{"):
            try:
                parsed = json.loads(action)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and "action" in parsed:
                if parsed["action"] == "set_card_order":
                    order = _valid_quota_card_order(parsed.get("order"))
                    if order is not None:
                        _save_quota_card_order(list(order))
                        # Keep the in-memory state in sync so re-injections
                        # (popover reopen, panel switch) before the next poll
                        # don't snap the cards back to the stale order.
                        state = getattr(self.delegate, "latest_state", None)
                        if state is not None:
                            state.card_order = order
                    return
                self._dispatch_talent_action(parsed)
                return
        if action == "refresh":
            self.delegate.refreshNow_(None)
        elif action == "quit":
            self.delegate.quitApp_(None)
        elif action == "install":
            self.delegate.installHook_(None)
        elif action == "switch":
            self.delegate.switchPanel_(self.web_view)
        elif action == "analyze":
            self.web_view.evaluateJavaScript_completionHandler_(
                "typeof projectRange === 'string' ? projectRange : '30d'",
                lambda value, error: self.delegate.analyzeUsage_(
                    value if error is None else "30d"
                ),
            )
        elif action in {"toggle_statusline", "toggle-statusline"}:
            self.delegate.toggleStatusline_(None)
        elif action == "install_statusline":
            self.delegate.installStatusline_(None)
        elif action == "uninstall_statusline":
            self.delegate.uninstallStatusline_(None)

    def _dispatch_talent_action(self, payload: dict[str, object]) -> None:
        action = str(payload.get("action", ""))
        role_id = str(payload.get("roleId") or "")
        if action == "set_folder":
            path = talent_market_bridge.pick_folder()
            if not path:
                return
            self._run_talent_then_refresh(lambda: talent_market_bridge.set_folder(role_id, path))
            return
        if action == "launch_role":
            task_prompt_obj = payload.get("taskPrompt")
            task_prompt = str(task_prompt_obj) if task_prompt_obj else None
            self._run_talent_then_refresh(
                lambda: talent_market_bridge.launch_role(role_id, task_prompt)
            )
            return
        if action == "install_role":
            self._run_talent_then_refresh(lambda: talent_market_bridge.install_role(role_id))
            return
        if action == "restore_role":
            self._run_talent_then_refresh(lambda: talent_market_bridge.restore_role(role_id))
            return
        if action == "ignore_drift":
            self._run_talent_then_refresh(lambda: talent_market_bridge.ignore_drift(role_id))
            return
        if action == "talent_refresh":
            self.delegate.refreshNow_(None)
            return

    def _run_talent_then_refresh(self, fn: Any) -> None:
        delegate = self.delegate

        def _work() -> None:
            try:
                fn()
            except Exception:
                if os.environ.get("USAGE_DEBUG") == "1":
                    logger.warning("talent market action failed", exc_info=True)
            if delegate is not None:
                delegate.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "refreshNow:", None, False
                )

        threading.Thread(target=_work, daemon=True).start()


class WebPanelView(WKWebView):
    delegate_ref = objc.ivar()
    bridge = objc.ivar()
    user_content_controller = objc.ivar()
    _ready = objc.ivar()
    _pending = objc.ivar()
    _last_payload = objc.ivar()
    _last_injected_payload = objc.ivar()
    _injection_retry_payload = objc.ivar()
    _injection_reload_count = objc.ivar()
    _html = objc.ivar()
    _first_paint_done = objc.ivar()

    def initWithFrame_configuration_delegate_(
        self,
        frame: Any,
        configuration: Any,
        delegate: Any,
    ) -> WebPanelView:
        self = objc.super(WebPanelView, self).initWithFrame_configuration_(frame, configuration)
        if self is None:
            return None
        self.delegate_ref = delegate
        self.bridge = None
        self.user_content_controller = configuration.userContentController()
        self._ready = False
        self._pending = None
        self._last_payload = None
        self._last_injected_payload = None
        self._injection_retry_payload = None
        self._injection_reload_count = 0
        self._html = None
        self._first_paint_done = False
        self.setNavigationDelegate_(self)
        self.setValue_forKey_(False, "drawsBackground")
        self.setWantsLayer_(True)
        layer = self.layer()
        if layer is not None:
            layer.setBackgroundColor_(
                CGColorCreateGenericRGB(10 / 255, 15 / 255, 20 / 255, 1.0)
            )
        return self

    def webView_didFinishNavigation_(self, web_view: Any, navigation: Any) -> None:
        self._ready = True
        if self._pending is not None:
            payload = self._pending
            self._pending = None
            self.injectState_(payload)

    def webView_didFailNavigation_withError_(
        self, web_view: Any, navigation: Any, error: Any
    ) -> None:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("panel navigation failed: %s", error)

    def webView_didFailProvisionalNavigation_withError_(
        self, web_view: Any, navigation: Any, error: Any
    ) -> None:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("panel provisional navigation failed: %s", error)

    def webViewWebContentProcessDidTerminate_(self, web_view: Any) -> None:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("panel web content process terminated; reloading")
        _reload_web_panel(self)

    def willOpenMenu_withEvent_(self, menu: Any, event: Any) -> None:
        _remove_navigation_menu_items(menu)

    def renderTimeoutElapsed_(self, _arg: Any) -> None:
        # If the HTML never finished rendering, the popover shows only the dark
        # backing layer (a "grey window"). Surface that in the debug log so a
        # reporter's USAGE_DEBUG output points straight at it instead of leaving
        # us guessing.
        if not self._ready and os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("panel HTML did not finish rendering within timeout")

    def setBridge_(self, bridge: Any) -> None:
        self.bridge = bridge

    def injectState_(self, payload: dict[str, object]) -> None:
        self._last_payload = payload
        if not self._ready:
            self._pending = payload
            return
        encoded = _new_state_payload(self, payload)
        if encoded is None:
            return

        def _completed(_value: Any, error: Any) -> None:
            _handle_injection_error(self, payload, error)
            if error is None and not self._first_paint_done:
                self._first_paint_done = True
                delegate = self.delegate_ref
                if delegate is not None and hasattr(delegate, "panelDidFirstPaint_"):
                    delegate.panelDidFirstPaint_(self)

        self.evaluateJavaScript_completionHandler_(
            f"window.usageApplyState({encoded})",
            _completed,
        )

    def teardown(self) -> None:
        controller = self.user_content_controller
        if controller is not None:
            controller.removeScriptMessageHandlerForName_("usage")
        self.setNavigationDelegate_(None)
        self.bridge = None
        self.delegate_ref = None
        self.user_content_controller = None
        self._last_payload = None
        self._last_injected_payload = None
        self._pending = None
        self._html = None


class ErrorPanelView(NSView):
    # Native fallback shown when the WKWebView panel can't be built or loaded,
    # so the popover never degrades to a silent grey window. Exposes the same
    # injectState_/teardown surface as WebPanelView so the controller can drive
    # it without special-casing.
    def initWithFrame_message_(self, frame: Any, message: str) -> ErrorPanelView:
        self = objc.super(ErrorPanelView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setWantsLayer_(True)
        layer = self.layer()
        if layer is not None:
            layer.setBackgroundColor_(CGColorCreateGenericRGB(10 / 255, 15 / 255, 20 / 255, 1.0))
        inset = 24.0
        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(inset, inset, frame.size.width - 2 * inset, frame.size.height - 2 * inset)
        )
        label.setStringValue_(message)
        label.setEditable_(False)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setSelectable_(True)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_(13.0))
        label.cell().setWraps_(True)
        self.addSubview_(label)
        return self

    def injectState_(self, payload: dict[str, object]) -> None:
        pass

    def teardown(self) -> None:
        pass


class HTMLPanel:
    id: str
    i18n_key: str
    html_filename: str
    width: float
    height: float
    claude_card_height: float
    codex_card_height: float
    codex_row_height: float
    agy_card_height: float

    def __init__(
        self,
        panel_id: str,
        i18n_key: str,
        html_filename: str,
        width: float = PANEL_WIDTH,
        height: float = PANEL_HEIGHT,
        *,
        claude_card_height: float,
        codex_card_height: float,
        codex_row_height: float = 64.0,
        agy_card_height: float = 0.0,
    ) -> None:
        self.id = panel_id
        self.i18n_key = i18n_key
        self.html_filename = html_filename
        self.width = width
        self.height = height
        self.claude_card_height = claude_card_height
        self.codex_card_height = codex_card_height
        self.codex_row_height = codex_row_height
        self.agy_card_height = agy_card_height

    def build_view(self, delegate: Any) -> NSView:
        try:
            if WKUserContentController is None or WKWebViewConfiguration is None:
                raise RuntimeError("pyobjc-framework-WebKit is unavailable")
            html = _load_panel_html(self.html_filename)
            configuration = WKWebViewConfiguration.alloc().init()
            controller = WKUserContentController.alloc().init()
            configuration.setUserContentController_(controller)
            web_view = WebPanelView.alloc().initWithFrame_configuration_delegate_(
                NSMakeRect(0, 0, self.width, self.height),
                configuration,
                delegate,
            )
            bridge = UsageScriptBridge.alloc().initWithDelegate_webView_(delegate, web_view)
            web_view.setBridge_(bridge)
            controller.addScriptMessageHandler_name_(bridge, "usage")
            web_view._html = html
            web_view.loadHTMLString_baseURL_(html, None)
            web_view.performSelector_withObject_afterDelay_("renderTimeoutElapsed:", None, 4.0)
            return web_view
        except Exception as exc:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("panel build failed", exc_info=True)
            return self._error_view(delegate, exc)

    def _error_view(self, delegate: Any, exc: BaseException) -> NSView:
        language = getattr(delegate, "language", "en")
        bundle = _load_i18n_bundle()
        prompt = bundle.get(language, bundle.get("en", {})).get(
            "panel_load_error", "Panel failed to load. Please report this:"
        )
        detail = f"{type(exc).__name__}: {exc}"
        message = f"{prompt}\n\n{detail}\n\nhttps://github.com/aqua5230/usage/issues"
        return ErrorPanelView.alloc().initWithFrame_message_(
            NSMakeRect(0, 0, self.width, self.height),
            message,
        )

    def apply_state(self, view: NSView, state: PopoverState) -> None:
        view.injectState_(_state_payload(state))

    def preferred_size(self) -> tuple[float, float]:
        return (self.width, self.height)
