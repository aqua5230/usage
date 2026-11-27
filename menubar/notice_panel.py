# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""A floating alert-style panel for notices nobody may be there to answer.

NSAlert.runModal holds the main thread until a button is clicked. Shown on
another Space or after an unattended relaunch, it froze the app and ignored
AppleScript quit (#457). This panel floats on every Space without activating
the app, so it never takes keystrokes meant for the app the person is typing in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
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

# Same codes as NSAlertFirstButtonReturn and onwards, so callers that used
# runModal keep their result handling.
FIRST_BUTTON = 1000

_WIDTH = 440.0
_MARGIN = 20.0
_ICON = 64.0
_TEXT_X = _MARGIN + _ICON + 16.0
_TEXT_WIDTH = _WIDTH - _TEXT_X - _MARGIN
_BODY_MAX_HEIGHT = 280.0
_BUTTON_HEIGHT = 32.0
_BUTTON_GAP = 12.0
# Strong references until the panel closes; window delegates are held weakly.
_open_notices: set[Any] = set()


class _NoticePanel(NSPanel):  # type: ignore[misc]
    def canBecomeKeyWindow(self) -> bool:
        return True

    def cancelOperation_(self, sender: Any) -> None:
        self.close()


class _NoticeController(NSObject):  # type: ignore[misc]
    def buttonClicked_(self, sender: Any) -> None:
        self.choice = FIRST_BUTTON + int(sender.tag())
        self.panel.close()

    def windowWillClose_(self, notification: Any) -> None:
        _open_notices.discard(self)
        choice = self.choice if self.choice is not None else self.cancel
        if choice is not None and self.on_choice is not None:
            self.on_choice(choice)


def _label(text: str) -> Any:
    label = NSTextField.wrappingLabelWithString_(text)
    label.setFont_(NSFont.boldSystemFontOfSize_(NSFont.systemFontSize()))
    label.setSelectable_(False)
    label.setPreferredMaxLayoutWidth_(_TEXT_WIDTH)
    label.setFrame_(NSMakeRect(_TEXT_X, 0.0, _TEXT_WIDTH, label.fittingSize().height))
    return label


def _body(text: str) -> Any:
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
    scroll = NSScrollView.alloc().initWithFrame_(
        NSMakeRect(_TEXT_X, 0.0, _TEXT_WIDTH, min(height, _BODY_MAX_HEIGHT))
    )
    scroll.setDrawsBackground_(False)
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    scroll.setDocumentView_(view)
    return scroll


def build(
    title: str,
    body: str,
    buttons: Sequence[str],
    on_choice: Callable[[int], None] | None = None,
    cancel: int | None = None,
) -> Any:
    """Lay out the panel without showing it; ``present`` shows it."""
    from menubar.chrome import _alert_icon

    controller = _NoticeController.alloc().init()
    controller.choice = None
    controller.cancel = cancel
    controller.on_choice = on_choice
    title_view = _label(title)
    body_view = _body(body)
    text_height = title_view.frame().size.height + 8.0 + body_view.frame().size.height
    height = _MARGIN + max(_ICON, text_height) + _MARGIN + _BUTTON_HEIGHT + _MARGIN
    top = height - _MARGIN
    title_view.setFrameOrigin_((_TEXT_X, top - title_view.frame().size.height))
    body_view.setFrameOrigin_(
        (_TEXT_X, title_view.frame().origin.y - 8.0 - body_view.frame().size.height)
    )

    content = NSView.alloc().initWithFrame_(NSMakeRect(0.0, 0.0, _WIDTH, height))
    icon = _alert_icon()
    if icon is not None:
        image = NSImageView.imageViewWithImage_(icon)
        image.setFrame_(NSMakeRect(_MARGIN, top - _ICON, _ICON, _ICON))
        content.addSubview_(image)
    content.addSubview_(title_view)
    content.addSubview_(body_view)
    # Like NSAlert: the first button is the default (Return) and sits rightmost.
    right = _WIDTH - _MARGIN
    for tag, button_title in enumerate(buttons):
        button = NSButton.buttonWithTitle_target_action_(button_title, controller, "buttonClicked:")
        button.setTag_(tag)
        button.setKeyEquivalent_("\r" if tag == 0 else "")
        button.sizeToFit()
        width = max(button.frame().size.width, 88.0)
        button.setFrame_(NSMakeRect(right - width, _MARGIN, width, _BUTTON_HEIGHT))
        right -= width + _BUTTON_GAP
        content.addSubview_(button)

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


def present(
    title: str,
    body: str,
    buttons: Sequence[str],
    on_choice: Callable[[int], None] | None = None,
    cancel: int | None = None,
) -> None:
    """Show the panel on the main thread; ``on_choice`` gets the button's code.

    Escape and the close button report ``cancel`` (or nothing when it is None).
    """
    controller = build(title, body, buttons, on_choice, cancel)
    _open_notices.add(controller)
    controller.panel.center()
    controller.panel.orderFrontRegardless()
