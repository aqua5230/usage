# mypy: disable-error-code="import-untyped,import-not-found,misc"
from __future__ import annotations

import base64
import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import objc
from AppKit import NSColor, NSFont, NSMakeRect, NSTextField, NSView
from Foundation import NSBundle, NSObject
from Quartz import CGColorCreateGenericRGB

try:
    from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration
except ModuleNotFoundError:
    with objc.autorelease_pool():
        objc.loadBundle(
            "WebKit",
            globals(),
            bundle_path="/System/Library/Frameworks/WebKit.framework",
        )
    # loadBundle gives us the classes but no method metadata, so PyObjC can't
    # infer the block signature of evaluateJavaScript:completionHandler: and
    # raises "Argument 3 is a block, but no signature available" the moment a
    # Python completion handler is passed (panels/web_panel.py:72). The proper
    # pyobjc-framework-WebKit wrapper registers this for us; when it is absent
    # (e.g. a background/non-app launch context) we register it by hand. The
    # handler is void (^)(id result, NSError *error).
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

from panels.base import resolve_resource

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from menubar import PopoverState, QuotaRowState

PANEL_WIDTH = 364.0
PANEL_HEIGHT = 812.0


def _reload_web_panel(view: Any) -> None:
    view._ready = False
    if getattr(view, "_last_payload", None) is not None:
        view._pending = view._last_payload
    view.reload()


def _handle_injection_error(view: Any, payload: dict[str, object], error: Any) -> None:
    if error is None:
        return
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning("panel state injection failed: %s", error)
    view._pending = payload
    _reload_web_panel(view)


def _i18n_path() -> Path:
    try:
        bundle_path = NSBundle.mainBundle().resourcePath()
        if bundle_path:
            candidate = Path(str(bundle_path)) / "i18n.json"
            if candidate.exists():
                return candidate
    except Exception:
        pass
    return Path(__file__).resolve().parent.parent / "i18n.json"


I18N_PATH = _i18n_path()


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


class WebPanelView(WKWebView):
    delegate_ref = objc.ivar()
    bridge = objc.ivar()
    user_content_controller = objc.ivar()
    _ready = objc.ivar()
    _pending = objc.ivar()
    _last_payload = objc.ivar()

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
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        def _completed(_value: Any, error: Any) -> None:
            _handle_injection_error(self, payload, error)

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
        self._pending = None


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
    codex_card_height: float

    def __init__(
        self,
        panel_id: str,
        i18n_key: str,
        html_filename: str,
        width: float = PANEL_WIDTH,
        height: float = PANEL_HEIGHT,
        *,
        codex_card_height: float,
    ) -> None:
        self.id = panel_id
        self.i18n_key = i18n_key
        self.html_filename = html_filename
        self.width = width
        self.height = height
        self.codex_card_height = codex_card_height

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


def _load_panel_html(filename: str) -> str:
    bundle = NSBundle.mainBundle()
    html_path: Path | None = None
    if bundle is not None:
        stem, _, ext = filename.rpartition(".")
        bundled = bundle.pathForResource_ofType_inDirectory_(stem, ext, "panels")
        if bundled:
            html_path = Path(str(bundled))
    if html_path is None:
        html_path = Path(resolve_resource(f"panels/{filename}"))
    html = html_path.read_text(encoding="utf-8")
    return (
        html.replace("{{CLAUDE_ICON}}", _data_uri("claude.webp"))
        .replace("{{CODEX_ICON}}", _data_uri("codex.webp"))
        .replace("{{I18N_BUNDLE}}", json.dumps(_load_i18n_bundle(), ensure_ascii=False))
    )


@lru_cache(maxsize=1)
def _load_i18n_bundle() -> dict[str, dict[str, str]]:
    data = json.loads(I18N_PATH.read_text(encoding="utf-8"))
    return {
        str(lang): {str(key): str(value) for key, value in values.items()}
        for lang, values in data.items()
    }


@lru_cache(maxsize=4)
def _data_uri(asset_name: str) -> str:
    path = Path(resolve_resource(asset_name))
    mime = "image/png" if path.suffix.lower() == ".png" else "image/webp"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _row_payload(row: QuotaRowState) -> dict[str, object]:
    return {
        "percent": row.percent,
        "percentText": row.percent_text,
        "resetText": row.reset_text,
        "warning": row.warning,
        "available": row.available,
    }


def _state_payload(state: PopoverState) -> dict[str, object]:
    return {
        "language": state.language,
        "claude": {
            "session": _row_payload(state.claude_session),
            "weekly": _row_payload(state.claude_weekly),
        },
        "codex": {
            "session": _row_payload(state.codex_session),
            "weekly": _row_payload(state.codex_weekly),
            "stale": state.codex_stale,
        },
        "projects": [
            {
                "name": name,
                "tokens": tokens,
                "tokensText": _fmt_tokens(tokens),
                "costText": _fmt_cost(cost),
            }
            for name, tokens, cost in state.projects
        ],
        "projects7d": [
            {
                "name": name,
                "tokens": tokens,
                "tokensText": _fmt_tokens(tokens),
                "costText": _fmt_cost(cost),
            }
            for name, tokens, cost in state.projects_7d
        ],
        "projects30d": [
            {
                "name": name,
                "tokens": tokens,
                "tokensText": _fmt_tokens(tokens),
                "costText": _fmt_cost(cost),
            }
            for name, tokens, cost in state.projects_30d
        ],
        "projectsAll": [
            {
                "name": name,
                "tokens": tokens,
                "tokensText": _fmt_tokens(tokens),
                "costText": _fmt_cost(cost),
            }
            for name, tokens, cost in state.projects_all
        ],
        "hideCodex": state.hide_codex,
        "statusline": state.statusline,
        "footer": {
            "rate": state.rate_text,
            "status": state.status_text,
            "today": state.today_text,
            "showInstall": state.show_install_button,
        },
    }


def _fmt_tokens(n: int) -> str:
    return f"{n:,}"


def _fmt_cost(cost: float | None) -> str:
    if cost is None:
        return "--"
    return f"${cost:.2f}"
