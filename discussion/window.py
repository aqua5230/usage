# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""macOS window shell for the PyObjC-free AI council bridge."""

# This module is imported and type-checked on Windows CI too (its non-GUI
# helpers are tested there), but its AppKit/WebKit imports and classes are
# gated behind `if sys.platform == "darwin":`. mypy's platform narrowing
# statically skips that block on a win32 run, so every name it would have
# bound (NSWindow, WKWebView, _DiscussionWindow, ...) looks undefined to
# methods that reference them elsewhere in the file — hence `name-defined`
# joining the existing PyObjC-stub suppressions below.
# mypy: disable-error-code="import-untyped,import-not-found,misc,name-defined"
from __future__ import annotations

import base64
import contextlib
import json
import os
import shutil
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from discussion.bridge import DiscussionBridge, ParticipantSpec
from discussion.cli import DetectionResult
from discussion.session import DebateStyle
from i18n import _load_i18n_bundle, _t, packaged_resource_path
from panels.payload import _data_uri
from talent_market_bridge import list_personas, pick_folder, pick_image_file
from usage_common.usage_lang import detect_lang

ATTACHMENTS_DIR = Path(os.path.expanduser("~/.usage/discussion_attachments"))
ATTACHMENT_MAX_FILES = 50
ATTACHMENT_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
DROP_MAX_BYTES = 20 * 1024 * 1024
THUMBNAIL_MAX_PIXELS = 128


def _attachment_timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def build_attachment_name(stamp: str, index: int, suffix: str) -> str:
    """Pure filename builder so naming is testable without touching disk."""
    return f"{stamp}-{index}{suffix}"


def _next_attachment_path(suffix: str, directory: Path) -> Path:
    stamp = _attachment_timestamp()
    index = 1
    while True:
        candidate = directory / build_attachment_name(stamp, index, suffix)
        if not candidate.exists():
            return candidate
        index += 1


def save_attachment_bytes(
    data: bytes,
    suffix: str,
    directory: Path = ATTACHMENTS_DIR,
) -> Path:
    """Persist raw image bytes under the managed directory and prune old files."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = _next_attachment_path(suffix, directory)
    target.write_bytes(data)
    target.chmod(0o600)
    prune_attachments(directory=directory)
    return target


def import_attachment_file(
    src: str,
    directory: Path = ATTACHMENTS_DIR,
) -> Path | None:
    """Copy a user-picked image into the managed directory; None on bad input."""
    path = Path(src)
    if not path.is_file() or path.suffix.lower() not in ATTACHMENT_SUFFIXES:
        return None
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = _next_attachment_path(path.suffix.lower(), directory)
    shutil.copy(path, target)
    target.chmod(0o600)
    prune_attachments(directory=directory)
    return target


def attachment_thumbnail_data_uri(path: Path) -> str | None:
    """Return a small PNG data URI for a managed image, or None on failure."""
    if sys.platform != "darwin" or not path.is_file():
        return None
    try:
        from AppKit import NSBitmapImageFileTypePNG, NSBitmapImageRep, NSImage, NSMakeSize

        image = NSImage.alloc().initWithContentsOfFile_(str(path))
        if image is None:
            return None
        size = image.size()
        longest = max(float(size.width), float(size.height))
        if longest <= 0:
            return None
        scale = min(1.0, THUMBNAIL_MAX_PIXELS / longest)
        image.setSize_(NSMakeSize(size.width * scale, size.height * scale))
        tiff = image.TIFFRepresentation()
        representation = NSBitmapImageRep.imageRepWithData_(tiff)
        png = representation.representationUsingType_properties_(
            NSBitmapImageFileTypePNG, {}
        )
        if png is None:
            return None
        return "data:image/png;base64," + base64.b64encode(bytes(png)).decode("ascii")
    except Exception:
        return None


def prune_attachments(
    directory: Path = ATTACHMENTS_DIR,
    keep: int = ATTACHMENT_MAX_FILES,
) -> None:
    """Keep only the newest ``keep`` files, deleting the oldest by mtime."""
    if not directory.exists() or keep < 0:
        return
    files = [entry for entry in directory.iterdir() if entry.is_file()]
    if len(files) <= keep:
        return
    files.sort(key=lambda entry: entry.stat().st_mtime)
    for stale in files[: len(files) - keep]:
        with contextlib.suppress(OSError):
            stale.unlink()


def read_pasteboard_image() -> tuple[bytes, str] | None:
    """Read an image from the macOS pasteboard; return (bytes, suffix) or None.

    AppKit is imported lazily so the module loads on non-darwin hosts; the call
    itself only works on macOS. Screenshots land as TIFF, so both PNG and TIFF
    pasteboard types are handled, converting TIFF to PNG on the way to disk.
    """
    try:
        from AppKit import (
            NSBitmapImageFileTypePNG,
            NSBitmapImageRep,
            NSPasteboard,
            NSPasteboardTypePNG,
            NSPasteboardTypeTIFF,
        )
    except ImportError:
        return None
    pb = NSPasteboard.generalPasteboard()
    if pb is None:
        return None
    types = pb.types()
    if NSPasteboardTypePNG in types:
        raw = pb.dataForType_(NSPasteboardTypePNG)
        if raw:
            return (bytes(raw), ".png")
    if NSPasteboardTypeTIFF in types:
        tiff = pb.dataForType_(NSPasteboardTypeTIFF)
        if tiff:
            rep = NSBitmapImageRep.imageRepWithData_(tiff)
            if rep is not None:
                png = rep.representationUsingType_properties_(
                    NSBitmapImageFileTypePNG, {}
                )
                if png:
                    return (bytes(png), ".png")
    return None


SCRIPT_HANDLER_NAME = "usageDiscussion"
WINDOW_AUTOSAVE_NAME = "usage.discussion.window"
BUILTIN_PARTICIPANTS = ("claude", "codex", "agy")
PARTICIPANT_LABELS = {
    "claude": "Claude",
    "codex": "Codex",
    "agy": "Antigravity",
}
ALLOWED_MODELS: dict[str, frozenset[str]] = {
    "claude": frozenset({"opus", "sonnet", "haiku"}),
    "codex": frozenset({"gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol"}),
    "agy": frozenset({"gemini-3.6-flash-high", "gemini-3.1-pro-high"}),
}
RUNNING_STATUSES = frozenset(
    {"PREPARING", "ROUND1_RUNNING", "ROUND2_RUNNING", "SUMMARIZING", "CANCELLING"}
)

if sys.platform == "darwin":
    import objc
    from AppKit import (
        NSApp,
        NSApplicationActivateAllWindows,
        NSApplicationActivateIgnoringOtherApps,
        NSBackingStoreBuffered,
        NSMakeRect,
        NSViewHeightSizable,
        NSViewWidthSizable,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSURL, NSObject, NSRunningApplication, NSThread

    try:
        from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration
    except ModuleNotFoundError:
        with objc.autorelease_pool():
            objc.loadBundle(
                "WebKit",
                globals(),
                bundle_path="/System/Library/Frameworks/WebKit.framework",
            )

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


ActionName = Literal[
    "discussion_attach",
    "discussion_clear",
    "discussion_detect",
    "discussion_pick_folder",
    "discussion_clear_folder",
    "discussion_start",
    "discussion_stop",
    "discussion_paste_image",
    "discussion_pick_image",
    "discussion_drop_image",
    "discussion_remove_attachment",
    "discussion_submit_guidance",
]


@dataclass(frozen=True)
class DiscussionAction:
    action: ActionName
    topic: str | None = None
    participants: tuple[str, ...] = ()
    moderator_id: str | None = None
    working_directory: str | None = None
    attachments: tuple[str, ...] = ()
    total_rounds: int = 2
    include_summary: bool = True
    end_on_consensus: bool = False
    guidance_between_rounds: bool = False
    models: Mapping[str, str | None] = field(default_factory=dict)
    personas: Mapping[str, str | None] = field(default_factory=dict)
    debate_style: DebateStyle = DebateStyle.CONSTRUCTIVE
    attachment_path: str | None = None
    attachment_data: str | None = None
    attachment_name: str | None = None
    guidance_text: str | None = None


def parse_discussion_action(raw: object) -> DiscussionAction:
    """Validate one JSON-string action without touching PyObjC or the bridge."""
    if not isinstance(raw, str):
        raise ValueError("action message must be a JSON string")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("action message is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("action message must contain an object")
    action = payload.get("action")
    if action not in {
        "discussion_attach",
        "discussion_clear",
        "discussion_detect",
        "discussion_pick_folder",
        "discussion_clear_folder",
        "discussion_start",
        "discussion_stop",
        "discussion_paste_image",
        "discussion_pick_image",
        "discussion_drop_image",
        "discussion_remove_attachment",
        "discussion_submit_guidance",
    }:
        raise ValueError("unknown discussion action")
    if action == "discussion_submit_guidance":
        text_value = payload.get("text")
        if not isinstance(text_value, str):
            raise ValueError("discussion_submit_guidance requires a string text")
        return DiscussionAction(
            cast(ActionName, action),
            guidance_text=text_value,
        )
    if action == "discussion_remove_attachment":
        path_value = payload.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise ValueError("discussion_remove_attachment requires a string path")
        return DiscussionAction(
            cast(ActionName, action),
            attachment_path=path_value,
        )
    if action == "discussion_drop_image":
        data_value = payload.get("data")
        name_value = payload.get("name")
        if not isinstance(data_value, str) or not data_value.strip():
            raise ValueError("discussion_drop_image requires base64 data")
        if not isinstance(name_value, str) or not name_value.strip():
            raise ValueError("discussion_drop_image requires a filename")
        return DiscussionAction(
            cast(ActionName, action),
            attachment_data=data_value,
            attachment_name=name_value,
        )
    if action != "discussion_start":
        return DiscussionAction(cast(ActionName, action))

    topic = payload.get("topic")
    participant_value = payload.get("participants")
    moderator_value = payload.get("moderatorId")
    working_directory_value = payload.get("workingDir")
    if not isinstance(topic, str):
        raise ValueError("discussion_start requires a string topic")
    if not isinstance(participant_value, list) or not participant_value:
        raise ValueError("discussion_start requires at least one participant")
    if not all(isinstance(item, str) for item in participant_value):
        raise ValueError("discussion_start participants must be strings")
    participants = tuple(cast(list[str], participant_value))
    if len(participants) != len(set(participants)):
        raise ValueError("discussion_start participants must be unique")
    if any(item not in BUILTIN_PARTICIPANTS for item in participants):
        raise ValueError("discussion_start contains an unknown participant")
    if moderator_value is not None and not isinstance(moderator_value, str):
        raise ValueError("discussion_start moderatorId must be a string or null")
    if working_directory_value is not None and not isinstance(
        working_directory_value, str
    ):
        raise ValueError("discussion_start workingDir must be a string or null")
    attachments_value = payload.get("attachments")
    rounds_value = payload.get("totalRounds", 2)
    include_summary_value = payload.get("includeSummary", True)
    end_on_consensus_value = payload.get("endOnConsensus", False)
    guidance_between_rounds_value = payload.get("guidanceBetweenRounds", False)
    debate_style_value = payload.get("debateStyle", DebateStyle.CONSTRUCTIVE.value)
    if not isinstance(rounds_value, int) or isinstance(rounds_value, bool):
        raise ValueError("discussion_start totalRounds must be an integer")
    if not isinstance(include_summary_value, bool):
        raise ValueError("discussion_start includeSummary must be a boolean")
    if not isinstance(end_on_consensus_value, bool):
        raise ValueError("discussion_start endOnConsensus must be a boolean")
    if not isinstance(guidance_between_rounds_value, bool):
        raise ValueError("discussion_start guidanceBetweenRounds must be a boolean")
    if not isinstance(debate_style_value, str):
        raise ValueError("discussion_start debateStyle must be a string")
    try:
        debate_style = DebateStyle(debate_style_value)
    except ValueError as exc:
        raise ValueError("discussion_start has an unknown debateStyle") from exc
    if attachments_value is not None:
        if not isinstance(attachments_value, list) or not all(
            isinstance(item, str) for item in attachments_value
        ):
            raise ValueError("discussion_start attachments must be a list of strings")
        attachments = tuple(cast(list[str], attachments_value))
    else:
        attachments = ()
    moderator_id = moderator_value
    if moderator_id is not None and moderator_id not in participants:
        raise ValueError("discussion_start moderatorId must be selected")
    models = _parse_discussion_models(payload.get("models"))
    personas = _parse_discussion_personas(payload.get("personas"))
    return DiscussionAction(
        cast(ActionName, action),
        topic=topic,
        participants=participants,
        moderator_id=moderator_id,
        working_directory=working_directory_value or None,
        attachments=attachments,
        total_rounds=min(5, max(1, rounds_value)),
        include_summary=include_summary_value,
        end_on_consensus=end_on_consensus_value,
        guidance_between_rounds=guidance_between_rounds_value,
        models=models,
        personas=personas,
        debate_style=debate_style,
    )


def _parse_discussion_models(raw: object) -> dict[str, str | None]:
    """Validate the optional per-participant model map; absent means all default."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("discussion_start models must be an object")
    models: dict[str, str | None] = {}
    for key, value in raw.items():
        if key not in BUILTIN_PARTICIPANTS:
            raise ValueError("discussion_start models has an unknown participant")
        if value is None or value == "":
            models[key] = None
        elif isinstance(value, str):
            if value not in ALLOWED_MODELS[key]:
                raise ValueError("discussion_start models has an unknown model")
            models[key] = value
        else:
            raise ValueError("discussion_start models values must be strings or null")
    return models


def _parse_discussion_personas(raw: object) -> dict[str, str | None]:
    """Validate the optional per-participant persona map; absent means neutral."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("discussion_start personas must be an object")
    personas: dict[str, str | None] = {}
    for key, value in raw.items():
        if key not in BUILTIN_PARTICIPANTS:
            raise ValueError("discussion_start personas has an unknown participant")
        if value is None or value == "":
            personas[key] = None
        elif isinstance(value, str):
            personas[key] = value
        else:
            raise ValueError("discussion_start personas values must be strings or null")
    return personas


def serialize_javascript_call(function_name: str, payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"window.{function_name}({encoded})"


def serialize_event_batch(
    events: Sequence[Mapping[str, object]],
    snapshot: Mapping[str, object],
) -> str:
    """Add snapshot-only turn metadata before sending one JavaScript batch."""
    turn_streaming: dict[str, bool] = {}
    turns = snapshot.get("turns")
    if isinstance(turns, list):
        for item in turns:
            if not isinstance(item, dict):
                continue
            turn_id = item.get("id")
            supports_stream = item.get("supports_token_stream")
            if isinstance(turn_id, str) and isinstance(supports_stream, bool):
                turn_streaming[turn_id] = supports_stream

    enriched: list[dict[str, object]] = []
    for source_event in events:
        event = dict(source_event)
        turn_id = event.get("turn_id")
        payload_value = event.get("payload")
        payload = dict(payload_value) if isinstance(payload_value, dict) else {}
        if isinstance(turn_id, str) and turn_id in turn_streaming:
            payload["supports_token_stream"] = turn_streaming[turn_id]
        event["payload"] = payload
        enriched.append(event)
    return serialize_javascript_call("discussionApplyEvents", enriched)


def _load_discussion_html(language: str | None = None) -> str:
    path = packaged_resource_path(
        "windows/discussion.html",
        Path(__file__).resolve().parent.parent / "assets" / "windows" / "discussion.html",
    )
    html = path.read_text(encoding="utf-8")
    return (
        html.replace("{{CLAUDE_ICON}}", _data_uri("claude.webp"))
        .replace("{{CODEX_ICON}}", _data_uri("codex.webp"))
        .replace(
            "{{I18N_BUNDLE}}",
            json.dumps(_load_i18n_bundle(), ensure_ascii=False),
        )
        .replace(
            "{{INITIAL_LANGUAGE}}",
            json.dumps(language or detect_lang()),
        )
    )


if sys.platform == "darwin":

    class _DiscussionWindow(NSWindow):
        def canBecomeMainWindow(self) -> bool:
            return True

        def canBecomeKeyWindow(self) -> bool:
            return True


    class _DiscussionScriptHandler(NSObject):
        controller = objc.ivar()

        def initWithController_(self, controller: Any) -> Any:
            self = objc.super(_DiscussionScriptHandler, self).init()
            if self is None:
                return None
            self.controller = controller
            return self

        def userContentController_didReceiveScriptMessage_(
            self,
            user_content_controller: Any,
            message: Any,
        ) -> None:
            self.controller._receive_action(message.body())


    class _DiscussionWindowDelegate(NSObject):
        controller = objc.ivar()

        def initWithController_(self, controller: Any) -> Any:
            self = objc.super(_DiscussionWindowDelegate, self).init()
            if self is None:
                return None
            self.controller = controller
            return self

        def windowWillClose_(self, notification: Any) -> None:
            self.controller._detach()

        def webView_didFinishNavigation_(self, webview: Any, navigation: Any) -> None:
            self.controller._webview_did_finish()


    class _MainThreadDispatcher(NSObject):
        controller = objc.ivar()

        def initWithController_(self, controller: Any) -> Any:
            self = objc.super(_MainThreadDispatcher, self).init()
            if self is None:
                return None
            self.controller = controller
            return self

        def drainDiscussionEvents_(self, sender: Any) -> None:
            self.controller._drain_events_on_main_thread()


class DiscussionWindowController:
    """Own the standalone NSWindow and forward bridge state to its web view."""

    def __init__(self, bridge: DiscussionBridge | None = None) -> None:
        self.bridge = bridge or DiscussionBridge()
        self.window: Any | None = None
        self.webview: Any | None = None
        self._content_controller: Any | None = None
        self._script_handler: Any | None = None
        self._window_delegate: Any | None = None
        self._dispatcher: Any | None = None
        self._attached = False
        self._web_ready = False
        self._shutdown = False
        self._drain_scheduled = False
        self._drain_lock = threading.Lock()
        self._language = detect_lang()
        snapshot = self.bridge.snapshot()
        snapshot_working_directory = snapshot.get("working_directory")
        self._working_directory = (
            snapshot_working_directory
            if isinstance(snapshot_working_directory, str)
            else None
        )
        self._attachments: list[dict[str, str]] = []
        self._personas: list[dict[str, str]] = []
        if sys.platform == "darwin":
            self._dispatcher = _MainThreadDispatcher.alloc().initWithController_(self)

    def show(self, close_popover: Callable[[], None] | None = None) -> None:
        self._require_main_thread()
        if self._shutdown:
            raise RuntimeError("discussion window controller is shut down")
        if close_popover is not None:
            close_popover()
        if self.window is None:
            self._create_window()
        window = self.window
        assert window is not None
        self._attach()
        NSApp.activateIgnoringOtherApps_(True)
        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
        )
        window.makeMainWindow()
        window.makeKeyWindow()
        window.makeKeyAndOrderFront_(None)
        window.orderFrontRegardless()
        if self._web_ready:
            self._apply_full_state()
        self._schedule_drain_on_main_thread()

    def close(self) -> None:
        self._require_main_thread()
        if self.window is not None:
            self.window.performClose_(None)

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        self._require_main_thread()
        if self._shutdown:
            return
        self._shutdown = True
        self._detach()
        self.bridge.shutdown(timeout_seconds)
        if self._content_controller is not None:
            self._content_controller.removeScriptMessageHandlerForName_(SCRIPT_HANDLER_NAME)
        if self.webview is not None:
            self.webview.setNavigationDelegate_(None)
            self.webview.stopLoading()
        if self.window is not None:
            self.window.setDelegate_(None)
            self.window.orderOut_(None)
        self.webview = None
        self.window = None
        self._content_controller = None
        self._script_handler = None
        self._window_delegate = None

    def _create_window(self) -> None:
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
        )
        self.window = _DiscussionWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 900, 640),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_(_t(self._language, "discussion_window_title"))
        self.window.setReleasedWhenClosed_(False)
        self.window.setFrameAutosaveName_(WINDOW_AUTOSAVE_NAME)
        self._window_delegate = _DiscussionWindowDelegate.alloc().initWithController_(self)
        self.window.setDelegate_(self._window_delegate)
        self.window.center()

        configuration = WKWebViewConfiguration.alloc().init()
        self._content_controller = WKUserContentController.alloc().init()
        self._script_handler = _DiscussionScriptHandler.alloc().initWithController_(self)
        self._content_controller.addScriptMessageHandler_name_(
            self._script_handler,
            SCRIPT_HANDLER_NAME,
        )
        configuration.setUserContentController_(self._content_controller)
        self.webview = WKWebView.alloc().initWithFrame_configuration_(
            self.window.contentView().bounds(),
            configuration,
        )
        self.webview.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.webview.setNavigationDelegate_(self._window_delegate)
        self.window.setContentView_(self.webview)
        html_path = packaged_resource_path(
            "windows/discussion.html",
            Path(__file__).resolve().parent.parent / "assets" / "windows" / "discussion.html",
        )
        base_url = NSURL.fileURLWithPath_(str(html_path.parent))
        self.webview.loadHTMLString_baseURL_(_load_discussion_html(self._language), base_url)

    def _attach(self) -> None:
        self._attached = True
        self.bridge.set_event_listener(self._bridge_events_ready)

    def _detach(self) -> None:
        self._attached = False
        self.bridge.set_event_listener(None)
        with self._drain_lock:
            self._drain_scheduled = False

    def _bridge_events_ready(self) -> None:
        if not self._attached or self._shutdown or self._dispatcher is None:
            return
        self._dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            "drainDiscussionEvents:",
            None,
            False,
        )

    def _schedule_drain_on_main_thread(self) -> None:
        self._require_main_thread()
        if not self._attached or not self._web_ready or self.webview is None:
            return
        with self._drain_lock:
            if self._drain_scheduled:
                return
            self._drain_scheduled = True
        dispatcher = self._dispatcher
        assert dispatcher is not None
        dispatcher.performSelector_withObject_afterDelay_(
            "drainDiscussionEvents:",
            None,
            0.0,
        )

    def _drain_events_on_main_thread(self) -> None:
        self._require_main_thread()
        with self._drain_lock:
            self._drain_scheduled = False
        if not self._attached or not self._web_ready or self.webview is None:
            return
        events = self.bridge.drain_events(50)
        if events:
            script = serialize_event_batch(events, self.bridge.snapshot())
            self.webview.evaluateJavaScript_completionHandler_(script, None)
        if len(events) == 50:
            self._schedule_drain_on_main_thread()

    def _webview_did_finish(self) -> None:
        self._require_main_thread()
        if self._shutdown or self.webview is None:
            return
        self._web_ready = True
        if self._attached:
            self._apply_full_state()
            self._schedule_drain_on_main_thread()

    def _receive_action(self, raw: object) -> None:
        self._require_main_thread()
        try:
            action = parse_discussion_action(raw)
            if action.action == "discussion_attach":
                self._apply_full_state()
            elif action.action == "discussion_detect":
                self._apply_detection()
            elif action.action == "discussion_pick_folder":
                selected = pick_folder()
                if selected is not None:
                    self._working_directory = selected
                    self._apply_working_directory()
            elif action.action == "discussion_clear_folder":
                self._working_directory = None
                self._apply_working_directory()
            elif action.action == "discussion_paste_image":
                self._handle_paste_image()
            elif action.action == "discussion_drop_image":
                assert action.attachment_data is not None
                assert action.attachment_name is not None
                self._handle_drop_image(action.attachment_data, action.attachment_name)
            elif action.action == "discussion_pick_image":
                self._handle_pick_image()
            elif action.action == "discussion_remove_attachment":
                assert action.attachment_path is not None
                self._remove_attachment(action.attachment_path)
            elif action.action == "discussion_stop":
                self.bridge.stop()
                self._apply_snapshot()
            elif action.action == "discussion_submit_guidance":
                assert action.guidance_text is not None
                self.bridge.submit_guidance(action.guidance_text)
            elif action.action == "discussion_clear":
                result = self.bridge.clear()
                if result.get("status") == "busy":
                    self._evaluate(
                        "discussionApplyError",
                        _t(self._language, "discussion_clear_busy"),
                    )
                else:
                    self._apply_snapshot()
            else:
                assert action.topic is not None
                personas_by_id = {
                    persona["id"]: persona for persona in self._personas
                }
                specs: list[ParticipantSpec] = []
                for participant_id in action.participants:
                    persona_id = action.personas.get(participant_id)
                    persona = (
                        personas_by_id.get(persona_id)
                        if persona_id is not None
                        else None
                    )
                    specs.append(
                        ParticipantSpec(
                            id=participant_id,
                            label=PARTICIPANT_LABELS[participant_id],
                            adapter_id=participant_id,
                            model=action.models.get(participant_id),
                            persona_prompt=(
                                persona["system_prompt"] if persona else None
                            ),
                            persona_label=persona["name"] if persona else None,
                        )
                    )
                self.bridge.start(
                    action.topic,
                    specs,
                    action.moderator_id,
                    working_directory=action.working_directory,
                    attachments=action.attachments,
                    total_rounds=action.total_rounds,
                    include_summary=action.include_summary,
                    end_on_consensus=action.end_on_consensus,
                    guidance_between_rounds=action.guidance_between_rounds,
                    debate_style=action.debate_style,
                )
                snapshot = self.bridge.snapshot()
                snapshot_working_directory = snapshot.get("working_directory")
                self._working_directory = (
                    snapshot_working_directory
                    if isinstance(snapshot_working_directory, str)
                    else None
                )
                self._apply_snapshot()
        except Exception as exc:
            self._evaluate("discussionApplyError", str(exc))

    def _apply_full_state(self) -> None:
        if not self._attached or not self._web_ready:
            return
        self._apply_snapshot()
        self._apply_working_directory()
        self._apply_detection()
        self._apply_personas()
        self._apply_attachments()

    def _apply_snapshot(self) -> None:
        self._evaluate("discussionApplySnapshot", self.bridge.snapshot())

    def _apply_detection(self) -> None:
        detections: list[DetectionResult] = self.bridge.detect_participants()
        self._evaluate(
            "discussionApplyDetection",
            [asdict(detection) for detection in detections],
        )

    def _apply_personas(self) -> None:
        self._personas = list_personas(self._language)
        self._evaluate("discussionApplyPersonas", self._personas)

    def _apply_working_directory(self) -> None:
        self._evaluate("discussionApplyWorkingDir", self._working_directory)

    def _apply_attachments(self, hint: str | None = None) -> None:
        self._evaluate(
            "discussionApplyAttachments",
            {"attachments": list(self._attachments), "hint": hint},
        )

    def _handle_paste_image(self) -> None:
        result = read_pasteboard_image()
        if result is None:
            self._apply_attachments(
                hint=_t(self._language, "discussion_paste_no_image")
            )
            return
        data, suffix = result
        if len(data) > DROP_MAX_BYTES:
            self._apply_attachments(
                hint=_t(self._language, "discussion_drop_too_large", name="")
            )
            return
        try:
            target = save_attachment_bytes(data, suffix)
        except OSError:
            self._apply_attachments(hint=_t(self._language, "discussion_drop_failed"))
            return
        self._add_attachment(target)
        self._apply_attachments()

    def _handle_drop_image(self, data: str, name: str) -> None:
        suffix = Path(name).suffix.lower()
        if suffix not in ATTACHMENT_SUFFIXES:
            self._apply_attachments(
                hint=_t(self._language, "discussion_drop_not_image")
            )
            return
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError:
            self._apply_attachments(hint=_t(self._language, "discussion_drop_failed"))
            return
        if len(raw) > DROP_MAX_BYTES:
            self._apply_attachments(
                hint=_t(self._language, "discussion_drop_too_large")
            )
            return
        try:
            target = save_attachment_bytes(raw, suffix)
        except OSError:
            self._apply_attachments(hint=_t(self._language, "discussion_drop_failed"))
            return
        self._add_attachment(target)
        self._apply_attachments()

    def _handle_pick_image(self) -> None:
        selected = pick_image_file()
        if selected is None:
            return
        try:
            target = import_attachment_file(selected)
        except OSError:
            self._apply_attachments(hint=_t(self._language, "discussion_drop_failed"))
            return
        if target is None:
            self._apply_attachments(
                hint=_t(self._language, "discussion_paste_no_image")
            )
            return
        self._add_attachment(target)
        self._apply_attachments()

    def _add_attachment(self, target: Path) -> None:
        attachment = {"name": target.name, "path": str(target)}
        thumbnail = attachment_thumbnail_data_uri(target)
        if thumbnail is not None:
            attachment["thumbnail"] = thumbnail
        self._attachments.append(attachment)

    def _remove_attachment(self, path: str) -> None:
        before = len(self._attachments)
        self._attachments = [
            attachment for attachment in self._attachments if attachment["path"] != path
        ]
        if len(self._attachments) == before:
            return
        with contextlib.suppress(OSError):
            Path(path).unlink()
        self._apply_attachments()

    def _evaluate(self, function_name: str, payload: object) -> None:
        self._require_main_thread()
        if not self._attached or not self._web_ready or self.webview is None:
            return
        self.webview.evaluateJavaScript_completionHandler_(
            serialize_javascript_call(function_name, payload),
            None,
        )

    @staticmethod
    def _require_main_thread() -> None:
        if sys.platform != "darwin":
            raise RuntimeError("discussion window is available only on macOS")
        if not NSThread.isMainThread():
            raise RuntimeError("discussion window operations require the main thread")
