# mypy: disable-error-code="import-untyped,misc"
from __future__ import annotations

import logging
import os
from typing import Any

from AppKit import NSAlert, NSAttributedString, NSImage, NSMakeRect, NSMakeSize, NSTextAttachment

from panels.base import resolve_resource

logger = logging.getLogger(__name__)

_ALERT_ICON: Any = None
_ALERT_ICON_LOADED = False
_CLAUDE_MENUBAR_ICON: Any = None
_CLAUDE_MENUBAR_ICON_LOADED = False
_CODEX_MENUBAR_ICON: Any = None
_CODEX_MENUBAR_ICON_LOADED = False
_AGY_MENUBAR_ICON: Any = None
_AGY_MENUBAR_ICON_LOADED = False
_CRITTER_IMAGE_CACHE: dict[str, Any] = {}
_CRITTER_ATTACHMENT_STRING_CACHE: dict[str, Any] = {}


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


def _critter_icon_attachment_string(path: str, image: Any) -> Any:
    cached = _CRITTER_ATTACHMENT_STRING_CACHE.get(path)
    if cached is not None:
        return cached
    attachment = NSTextAttachment.alloc().init()
    attachment.setImage_(image)
    attachment.setBounds_(NSMakeRect(0, -4.0, 18, 18))
    attributed = NSAttributedString.attributedStringWithAttachment_(attachment)
    _CRITTER_ATTACHMENT_STRING_CACHE[path] = attributed
    return attributed


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
