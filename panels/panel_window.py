# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# mypy: disable-error-code="import-untyped,misc"
from __future__ import annotations

from typing import Any

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSMakePoint,
    NSPanel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)

PANEL_CORNER_RADIUS = 12.0


class PanelWindow(NSPanel):
    def initWithContentRect_(self, content_rect: Any) -> PanelWindow:
        style_mask = int(NSWindowStyleMaskBorderless) | int(
            NSWindowStyleMaskNonactivatingPanel
        )
        self = objc.super(PanelWindow, self).initWithContentRect_styleMask_backing_defer_(
            content_rect,
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        if self is None:
            return None
        self.setOpaque_(False)
        self.setBackgroundColor_(NSColor.clearColor())
        self.setHasShadow_(True)
        self.setLevel_(NSFloatingWindowLevel)
        self.setMovableByWindowBackground_(True)
        self.setHidesOnDeactivate_(False)
        self.setReleasedWhenClosed_(False)
        behavior = int(NSWindowCollectionBehaviorCanJoinAllSpaces) | int(
            NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.setCollectionBehavior_(behavior)
        return self

    def canBecomeKeyWindow(self) -> bool:
        return True

    def cancelOperation_(self, sender: Any) -> None:
        self.close()

    def setRoundedContentView_(self, view: Any) -> None:
        view.setWantsLayer_(True)
        layer = view.layer()
        if layer is not None:
            layer.setCornerRadius_(PANEL_CORNER_RADIUS)
            layer.setMasksToBounds_(True)
        self.setContentView_(view)

    def setContentSizeKeepingTopLeft_(self, size: Any) -> None:
        frame = self.frame()
        top = float(frame.origin.y) + float(frame.size.height)
        self.setContentSize_(size)
        resized_frame = self.frame()
        self.setFrameOrigin_(
            NSMakePoint(
                float(resized_frame.origin.x),
                top - float(resized_frame.size.height),
            )
        )
