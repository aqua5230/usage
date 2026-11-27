# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Present post-update notes on the Cocoa main thread."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Mapping
from typing import Any

from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSFloatingWindowLevel,
    NSFont,
    NSImageView,
    NSMakeRect,
    NSPanel,
    NSScrollView,
    NSTextField,
    NSTextView,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from updates.checker import ReleaseInfo
from updates.release_notes import alert_release_notes
from updates.whats_new import start_notice
from usage_common.i18n import _t

_WIDTH = 440.0
_MARGIN = 20.0
_ICON = 64.0
_TEXT_X = _MARGIN + _ICON + 16.0
_TEXT_WIDTH = _WIDTH - _TEXT_X - _MARGIN
_BODY_MAX_HEIGHT = 280.0
_BUTTON_HEIGHT = 32.0
# Strong references until the panel closes; window delegates are held weakly.
_open_notices: set[Any] = set()


class _NoticePanel(NSPanel):  # type: ignore[misc]
    def canBecomeKeyWindow(self) -> bool:
        return True

    def cancelOperation_(self, sender: Any) -> None:
        self.close()


class _NoticeController(NSObject):  # type: ignore[misc]
    def okClicked_(self, sender: Any) -> None:
        self.panel.close()

    def notesClicked_(self, sender: Any) -> None:
        self.panel.close()
        webbrowser.open(self.url)

    def windowWillClose_(self, notification: Any) -> None:
        _open_notices.discard(self)


def _label(text: str, font: Any) -> Any:
    label = NSTextField.wrappingLabelWithString_(text)
    label.setFont_(font)
    label.setSelectable_(False)
    label.setPreferredMaxLayoutWidth_(_TEXT_WIDTH)
    size = label.fittingSize()
    label.setFrame_(NSMakeRect(_TEXT_X, 0.0, _TEXT_WIDTH, size.height))
    return label


def _body(text: str) -> Any:
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(_TEXT_X, 0.0, _TEXT_WIDTH, 10.0))
    scroll.setDrawsBackground_(False)
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    view = NSTextView.alloc().initWithFrame_(NSMakeRect(0.0, 0.0, _TEXT_WIDTH, 10.0))
    view.setEditable_(False)
    view.setDrawsBackground_(False)
    view.setTextContainerInset_((0.0, 0.0))
    view.textContainer().setLineFragmentPadding_(0.0)
    view.setFont_(NSFont.systemFontOfSize_(NSFont.smallSystemFontSize()))
    view.setString_(text)
    view.layoutManager().ensureLayoutForTextContainer_(view.textContainer())
    height = view.layoutManager().usedRectForTextContainer_(view.textContainer()).size.height
    view.setFrame_(NSMakeRect(0.0, 0.0, _TEXT_WIDTH, height))
    scroll.setDocumentView_(view)
    scroll.setFrame_(NSMakeRect(_TEXT_X, 0.0, _TEXT_WIDTH, min(height, _BODY_MAX_HEIGHT)))
    return scroll


def _button(title: str, controller: Any, action: str, key: str) -> Any:
    button = NSButton.buttonWithTitle_target_action_(title, controller, action)
    button.setKeyEquivalent_(key)
    button.sizeToFit()
    return button


def build_notice(release: ReleaseInfo, language: str) -> Any:
    from menubar.app import UPDATE_ALERT_BODY_LIMIT
    from menubar.chrome import _alert_icon

    controller = _NoticeController.alloc().init()
    controller.url = release.html_url
    title = _label(
        _t(language, "whats_new_title", version=release.version),
        NSFont.boldSystemFontOfSize_(NSFont.systemFontSize()),
    )
    body = _body(alert_release_notes(release.body, language, UPDATE_ALERT_BODY_LIMIT))
    ok = _button(_t(language, "whats_new_ok"), controller, "okClicked:", "\r")
    notes = _button(_t(language, "whats_new_open"), controller, "notesClicked:", "")

    text_height = title.frame().size.height + 8.0 + body.frame().size.height
    height = _MARGIN + max(_ICON, text_height) + _MARGIN + _BUTTON_HEIGHT + _MARGIN
    top = height - _MARGIN
    title.setFrameOrigin_((_TEXT_X, top - title.frame().size.height))
    body.setFrameOrigin_((_TEXT_X, title.frame().origin.y - 8.0 - body.frame().size.height))
    ok_width = max(ok.frame().size.width, 88.0)
    ok.setFrame_(NSMakeRect(_WIDTH - _MARGIN - ok_width, _MARGIN, ok_width, _BUTTON_HEIGHT))
    notes_width = max(notes.frame().size.width, 88.0)
    notes_x = ok.frame().origin.x - 12.0 - notes_width
    notes.setFrame_(NSMakeRect(notes_x, _MARGIN, notes_width, _BUTTON_HEIGHT))

    content = NSView.alloc().initWithFrame_(NSMakeRect(0.0, 0.0, _WIDTH, height))
    icon = _alert_icon()
    if icon is not None:
        image = NSImageView.imageViewWithImage_(icon)
        image.setFrame_(NSMakeRect(_MARGIN, top - _ICON, _ICON, _ICON))
        content.addSubview_(image)
    for view in (title, body, notes, ok):
        content.addSubview_(view)

    style = (
        int(NSWindowStyleMaskTitled)
        | int(NSWindowStyleMaskClosable)
        | int(NSWindowStyleMaskNonactivatingPanel)
    )
    panel = _NoticePanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0.0, 0.0, _WIDTH, height), style, NSBackingStoreBuffered, False
    )
    panel.setTitle_("usage")
    panel.setContentView_(content)
    panel.setReleasedWhenClosed_(False)
    panel.setHidesOnDeactivate_(False)
    panel.setLevel_(NSFloatingWindowLevel)
    panel.setCollectionBehavior_(
        int(NSWindowCollectionBehaviorCanJoinAllSpaces)
        | int(NSWindowCollectionBehaviorFullScreenAuxiliary)
    )
    panel.setDelegate_(controller)
    controller.panel = panel
    return controller


def show_notice(release: ReleaseInfo, language: str) -> bool:
    # Not NSAlert.runModal: a modal nobody answers (another Space, an unattended
    # relaunch) holds the main thread and ignores AppleScript quit (#457). The panel
    # floats on every Space without activating the app, so it never takes keystrokes
    # meant for the app the person is typing in.
    controller = build_notice(release, language)
    _open_notices.add(controller)
    controller.panel.center()
    controller.panel.orderFrontRegardless()
    return False  # The panel opens the notes itself when its button is clicked.


def _dispatch(callback: Callable[[], None]) -> None:
    from PyObjCTools.AppHelper import callAfter

    callAfter(callback)


def start(version: str, snapshot: Mapping[str, Any], language: str) -> None:
    start_notice(version, snapshot, lambda release: show_notice(release, language), _dispatch)
