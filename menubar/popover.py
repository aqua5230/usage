# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# mypy: disable-error-code="import-untyped,misc"
# PyObjC modules do not ship type stubs, and their base classes resolve to Any in mypy.
from __future__ import annotations

from typing import Any

import objc
from AppKit import (
    NSAnimationContext,
    NSApp,
    NSMakeSize,
    NSScreen,
    NSView,
    NSViewController,
    NSViewHeightSizable,
    NSViewWidthSizable,
)
from Quartz import CGColorCreateGenericRGB

from menubar.state import PopoverState
from panels import panel_window_state
from panels.base import Panel as UsagePanel
from panels.base import next_panel_eviction_id
from panels.panel_scale import fit_panel_size, fit_scale

MAX_CACHED_PANEL_VIEWS = 6
PANEL_TRANSITION_TIMEOUT_SECONDS = 1.5
PANEL_TRANSITION_FADE_SECONDS = 0.18


class PopoverViewController(NSViewController):
    content_view = objc.ivar()
    panel = objc.ivar()
    delegate = objc.ivar()
    panel_views = objc.ivar()
    panel_lru = objc.ivar()
    transition_overlays = objc.ivar()
    latest_state = objc.ivar()
    pending_panel_evictions = objc.ivar()
    panel_scales = objc.ivar()

    def initWithPanel_delegate_(self, panel: UsagePanel, delegate: Any) -> PopoverViewController:
        self = objc.super(PopoverViewController, self).init()
        if self is None:
            return None
        self.panel = panel
        self.delegate = delegate
        self.panel_views = {}
        self.panel_lru = []
        self.transition_overlays = {}
        self.pending_panel_evictions = set()
        self.panel_scales = {}
        self.latest_state = None
        self.content_view = panel.build_view(delegate)
        container = NSView.alloc().initWithFrame_(self.content_view.frame())
        container.setWantsLayer_(True)
        self.setView_(container)
        self.preparePanelView_(self.content_view)
        container.addSubview_(self.content_view)
        # Only cache a real web view; a failed build (ErrorPanelView, no JS
        # bridge) is shown but left uncached so a later switch rebuilds it.
        if hasattr(self.content_view, "evaluateJavaScript_completionHandler_"):
            self.panel_views[panel.id] = self.content_view
            self.panel_lru.append(panel.id)
        return self

    def setState_(self, state: PopoverState) -> None:
        self.latest_state = state
        self.view().setFrameSize_(_popover_size(state, self.panel))
        self.syncPanelFrames()
        self.panel.apply_state(self.content_view, state)

    def switchToPanel_(self, panel: UsagePanel) -> None:
        previous = self.content_view
        self.panel = panel
        content_view = self.panel_views.get(panel.id)
        if content_view is None:
            content_view = panel.build_view(self.delegate)
            self.panel_scales.pop(panel.id, None)
            content_view.setHidden_(True)
            self.preparePanelView_(content_view)
            self.view().addSubview_(content_view)
            # Only cache a real web view. A failed build returns ErrorPanelView
            # (no JS bridge); caching it would pin the error even after the file
            # recovers, so leave it uncached and rebuild on the next switch.
            if hasattr(content_view, "evaluateJavaScript_completionHandler_"):
                self.panel_views[panel.id] = content_view
                self.beginPanelTransitionForPanelId_view_(panel.id, content_view)
        # Drop the previously shown view if it was an uncached error fallback,
        # so it doesn't linger stacked in the container behind the new panel.
        if (
            previous is not None
            and previous is not content_view
            and previous not in self.panel_views.values()
        ):
            if hasattr(previous, "teardown"):
                previous.teardown()
            previous.removeFromSuperview()
        self.content_view = content_view
        if panel.id in self.panel_views:
            self.markPanelUsed_(panel.id)
        for panel_id, view in list(self.panel_views.items()):
            view.setHidden_(panel_id != panel.id)
        content_view.setHidden_(False)
        if self.latest_state is not None:
            self.setState_(self.latest_state)
        self.evictPanelViewsIfNeeded()

    def currentContentView(self) -> Any:
        return self.content_view

    def panelDidFirstPaint_(self, view: Any) -> None:
        if view is self.content_view:
            if self.panel is not None:
                self.panel_scales.pop(self.panel.id, None)
            self.applyPanelScale()
            self.endPanelTransitionForPanelView_(view)

    def beginPanelTransitionForPanelId_view_(self, panel_id: str, view: Any) -> None:
        self.removeTransitionOverlay_(panel_id)
        overlay = NSView.alloc().initWithFrame_(view.bounds())
        overlay.setWantsLayer_(True)
        overlay.setAlphaValue_(1.0)
        overlay.setAutoresizingMask_(int(NSViewWidthSizable) | int(NSViewHeightSizable))
        layer = overlay.layer()
        if layer is not None:
            layer.setBackgroundColor_(
                CGColorCreateGenericRGB(10 / 255, 15 / 255, 20 / 255, 1.0)
            )
        view.addSubview_(overlay)
        self.transition_overlays[panel_id] = overlay
        self.performSelector_withObject_afterDelay_(
            "transitionTimeoutElapsed:",
            overlay,
            PANEL_TRANSITION_TIMEOUT_SECONDS,
        )

    def transitionTimeoutElapsed_(self, overlay: Any) -> None:
        # Match by the overlay object itself, not the panel id: if this panel was
        # evicted and rebuilt, a stale timer must not fade the new overlay. A timer
        # whose overlay is already gone from the map simply finds nothing and stops.
        for panel_id, current_overlay in list(self.transition_overlays.items()):
            if current_overlay is overlay:
                self.endPanelTransitionForPanelId_(panel_id)
                return

    def endPanelTransitionForPanelView_(self, view: Any) -> None:
        for panel_id, panel_view in list(self.panel_views.items()):
            if panel_view is view:
                self.endPanelTransitionForPanelId_(panel_id)
                return

    def endPanelTransitionForPanelId_(self, panel_id: str) -> None:
        overlay = self.transition_overlays.pop(panel_id, None)
        if overlay is None:
            return

        def _fade(context: Any) -> None:
            context.setDuration_(PANEL_TRANSITION_FADE_SECONDS)
            overlay.animator().setAlphaValue_(0.0)

        def _remove() -> None:
            overlay.removeFromSuperview()

        NSAnimationContext.runAnimationGroup_completionHandler_(_fade, _remove)

    def teardown(self) -> None:
        for panel_id, view in list(self.panel_views.items()):
            self.removeTransitionOverlay_(panel_id)
            if hasattr(view, "teardown"):
                view.teardown()
            view.removeFromSuperview()
        self.panel_views.clear()
        self.panel_lru.clear()
        self.content_view = None

    def preparePanelView_(self, view: Any) -> None:
        view.setFrame_(self.view().bounds() if self.view() is not None else view.frame())
        view.setAutoresizingMask_(int(NSViewWidthSizable) | int(NSViewHeightSizable))
        view.setWantsLayer_(True)
        layer = view.layer()
        if layer is not None:
            layer.setMasksToBounds_(True)

    def syncPanelFrames(self) -> None:
        bounds = self.view().bounds()
        for view in self.panel_views.values():
            view.setFrame_(bounds)
        self.applyPanelScale()

    def applyPanelScale(self) -> None:
        if self.latest_state is None or self.panel is None:
            return
        scale = panel_scale(self.latest_state, self.panel)
        panel_id = self.panel.id
        if self.panel_scales.get(panel_id) == scale:
            return
        view = self.content_view
        if not hasattr(view, "evaluateJavaScript_completionHandler_"):
            return

        def _completed(value: Any, error: Any) -> None:
            if (
                value
                and error is None
                and self.panel is not None
                and self.panel.id == panel_id
                and self.content_view is view
            ):
                self.panel_scales[panel_id] = scale

        view.evaluateJavaScript_completionHandler_(
            "typeof window.usageApplyPanelZoom === 'function' ? "
            f"window.usageApplyPanelZoom({scale}) : false",
            _completed,
        )

    def markPanelUsed_(self, panel_id: str) -> None:
        self.panel_lru = [cached_id for cached_id in self.panel_lru if cached_id != panel_id]
        self.panel_lru.append(panel_id)

    def evictPanelViewsIfNeeded(self) -> None:
        self._schedulePanelEvictionIfNeeded()

    def _schedulePanelEvictionIfNeeded(self) -> None:
        if self.panel is None or len(self.panel_views) <= MAX_CACHED_PANEL_VIEWS:
            return
        evict_id = next_panel_eviction_id(
            self.panel_lru,
            self.panel.id,
            self.pending_panel_evictions,
        )
        if evict_id is None:
            return
        self.pending_panel_evictions.add(evict_id)
        self.performSelector_withObject_afterDelay_("evictPanelViewForId:", evict_id, 0.0)

    def evictPanelViewForId_(self, panel_id: str) -> None:
        self.pending_panel_evictions.discard(panel_id)
        # A user can return to this panel before the next run-loop turn. In
        # that case it remains live; schedule another LRU candidate instead.
        if self.panel is None or panel_id == self.panel.id:
            self._schedulePanelEvictionIfNeeded()
            return
        view = self.panel_views.get(panel_id)
        if view is None:
            self._schedulePanelEvictionIfNeeded()
            return
        self.panel_lru = [cached_id for cached_id in self.panel_lru if cached_id != panel_id]
        self.panel_views.pop(panel_id, None)
        self.panel_scales.pop(panel_id, None)
        self.removeTransitionOverlay_(panel_id)
        if hasattr(view, "teardown"):
            view.teardown()
        view.removeFromSuperview()
        self._schedulePanelEvictionIfNeeded()

    def removeTransitionOverlay_(self, panel_id: str) -> None:
        overlay = self.transition_overlays.pop(panel_id, None)
        if overlay is not None:
            overlay.removeFromSuperview()


def panel_scale(state: PopoverState, panel: UsagePanel | None = None) -> float:
    _, height = panel_window_state.resolve_panel_size(state, panel)
    screen = None if NSApp() is None else NSScreen.mainScreen()
    maximum = height if screen is None else float(screen.visibleFrame().size.height) - 24.0
    return fit_scale(height, maximum)


def _popover_size(state: PopoverState, panel: UsagePanel | None = None) -> Any:
    width, height = panel_window_state.resolve_panel_size(state, panel)
    screen = None if NSApp() is None else NSScreen.mainScreen()
    maximum = height if screen is None else float(screen.visibleFrame().size.height) - 24.0
    fitted_width, fitted_height, _ = fit_panel_size(width, height, maximum)
    return NSMakeSize(fitted_width, fitted_height)
