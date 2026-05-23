# mypy: disable-error-code="import-untyped,import-not-found,misc"
from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import objc
from AppKit import NSMakeRect, NSView
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

from panels.base import resolve_resource

if TYPE_CHECKING:
    from menubar import PopoverState, QuotaRowState

PANEL_WIDTH = 364.0
PANEL_HEIGHT = 812.0


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
            self.delegate.analyzeUsage_(None)


class WebPanelView(WKWebView):
    delegate_ref = objc.ivar()
    bridge = objc.ivar()
    user_content_controller = objc.ivar()
    _ready = objc.ivar()
    _pending = objc.ivar()

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

    def setBridge_(self, bridge: Any) -> None:
        self.bridge = bridge

    def injectState_(self, payload: dict[str, object]) -> None:
        if not self._ready:
            self._pending = payload
            return
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.evaluateJavaScript_completionHandler_(f"window.usageApplyState({encoded})", None)

    def teardown(self) -> None:
        controller = self.user_content_controller
        if controller is not None:
            controller.removeScriptMessageHandlerForName_("usage")
        self.setNavigationDelegate_(None)
        self.bridge = None
        self.delegate_ref = None
        self.user_content_controller = None


class HTMLPanel:
    id: str
    display_name: str
    html_filename: str
    width: float
    height: float

    def __init__(
        self,
        panel_id: str,
        display_name: str,
        html_filename: str,
        width: float = PANEL_WIDTH,
        height: float = PANEL_HEIGHT,
    ) -> None:
        self.id = panel_id
        self.display_name = display_name
        self.html_filename = html_filename
        self.width = width
        self.height = height

    def build_view(self, delegate: Any) -> NSView:
        if WKUserContentController is None or WKWebViewConfiguration is None:
            raise RuntimeError("pyobjc-framework-WebKit is required to build HTMLPanel")
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
        return web_view

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
        },
        "projects": [
            {"name": name, "tokensText": _fmt_tokens(tokens), "costText": _fmt_cost(cost)}
            for name, tokens, cost in state.projects
        ],
        "projects7d": [
            {"name": name, "tokensText": _fmt_tokens(tokens), "costText": _fmt_cost(cost)}
            for name, tokens, cost in state.projects_7d
        ],
        "projects30d": [
            {"name": name, "tokensText": _fmt_tokens(tokens), "costText": _fmt_cost(cost)}
            for name, tokens, cost in state.projects_30d
        ],
        "cli": state.cli_status,
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
