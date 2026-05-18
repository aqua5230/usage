# mypy: disable-error-code="import-untyped,misc"
# PyObjC modules do not ship type stubs, and their base classes resolve to Any in mypy.
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import objc
from AppKit import (
    NSAlert,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBezierPath,
    NSButton,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGradient,
    NSImage,
    NSMakeRect,
    NSMakeSize,
    NSMinYEdge,
    NSParagraphStyleAttributeName,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSRectFill,
    NSStatusBar,
    NSStrokeColorAttributeName,
    NSTextAlignmentRight,
    NSTextField,
    NSVariableStatusItemLength,
    NSView,
    NSViewController,
)
from Foundation import (
    NSBundle,
    NSMutableParagraphStyle,
    NSObject,
    NSRunLoop,
    NSRunLoopCommonModes,
    NSTimer,
)

import codex_loader
from history_loader import load_entries
from pricing import calculate_cost
from usage_client import ClaudeUsageClient, PollOutcome, PollState
from usage_rate import GROUP_NAMES, UsageRateTracker

POPOVER_WIDTH = 364.0
CONTENT_HEIGHT = 574.0
PADDING = 14.0
TRACK_HEIGHT = 8.0
CARD_HEIGHT = 184.0
FOOTER_HEIGHT = 152.0
CARD_RADIUS = 18.0
CARD_HEADER_TOP = 22.0
CARD_ROW_TOP = 66.0
CARD_ROW_GAP = 64.0
CARD_SIDE_INSET = 18.0
SECTION_GAP = 14.0
FOOTER_GAP = 12.0
FOOTER_LINE_GAP = 18.0
BUTTON_TOP_GAP = 18.0
BUTTON_HEIGHT = 32.0
INSTALL_BUTTON_EXTRA_HEIGHT = BUTTON_HEIGHT + 10.0
CLAUDE_COLOR = (244 / 255, 145 / 255, 100 / 255)
CODEX_COLOR = (88 / 255, 214 / 255, 230 / 255)
WARN_COLOR = (255 / 255, 196 / 255, 57 / 255)
DANGER_COLOR = (255 / 255, 69 / 255, 58 / 255)

logger = logging.getLogger(__name__)


def _bar_color(pct: float, brand: tuple[float, float, float]) -> tuple[float, float, float]:
    if pct >= 80:
        return DANGER_COLOR
    if pct >= 50:
        return WARN_COLOR
    return brand


def _resolve_resource(name: str) -> str:
    bundle = NSBundle.mainBundle()
    if bundle is not None:
        stem, _, ext = name.rpartition(".")
        path = bundle.pathForResource_ofType_(stem, ext)
        if path:
            return str(path)
    return str(Path(__file__).parent / "assets" / name)


CLAUDE_ICON_PATH = _resolve_resource("claude.webp")
CODEX_ICON_PATH = _resolve_resource("codex.webp")

_APP_DELEGATE: AppDelegate | None = None


@dataclass(slots=True)
class QuotaRowState:
    title: str
    percent: float | None
    percent_text: str
    reset_text: str
    color: tuple[float, float, float]
    available: bool = True


@dataclass(slots=True)
class PopoverState:
    claude_session: QuotaRowState
    claude_weekly: QuotaRowState
    codex_session: QuotaRowState
    codex_weekly: QuotaRowState
    rate_text: str
    status_text: str
    today_text: str
    show_install_button: bool = False


def format_human_time(seconds: float) -> str:
    if seconds <= 0:
        return "0m"
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class ProgressBarView(NSView):
    percent = objc.ivar()
    bar_color = objc.ivar()
    available = objc.ivar()

    def initWithFrame_(self, frame: Any) -> ProgressBarView:
        self = objc.super(ProgressBarView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.percent = None
        self.bar_color = NSColor.secondaryLabelColor()
        self.available = False
        return self

    def isFlipped(self) -> bool:
        return True

    def setPercent_color_available_(
        self,
        percent: float | None,
        color: NSColor,
        available: bool,
    ) -> None:
        self.percent = percent
        self.bar_color = color
        self.available = available
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirty_rect: Any) -> None:
        bounds = self.bounds()
        rect = NSMakeRect(
            0,
            (bounds.size.height - TRACK_HEIGHT) / 2,
            bounds.size.width,
            TRACK_HEIGHT,
        )

        if not self.available or self.percent is None:
            NSColor.secondaryLabelColor().colorWithAlphaComponent_(0.3).setFill()
            _fill_rounded_rect(rect, TRACK_HEIGHT / 2)
            return

        _track_color_for_view(self).setFill()
        _fill_rounded_rect(rect, TRACK_HEIGHT / 2)

        pct = max(0.0, min(100.0, float(self.percent)))
        fill_width = min(bounds.size.width, max(2.0, bounds.size.width * pct / 100.0))
        fill_rect = NSMakeRect(rect.origin.x, rect.origin.y, fill_width, rect.size.height)
        _accent_gradient(self.bar_color).drawInBezierPath_angle_(
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                fill_rect,
                TRACK_HEIGHT / 2,
                TRACK_HEIGHT / 2,
            ),
            0.0,
        )


class QuotaRowView(NSView):
    title_label = objc.ivar()
    percent_label = objc.ivar()
    reset_label = objc.ivar()
    progress_bar = objc.ivar()

    def initWithFrame_(self, frame: Any) -> QuotaRowView:
        self = objc.super(QuotaRowView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.title_label = _label("", _medium_font(), NSColor.labelColor())
        self.percent_label = _label(
            "",
            NSFont.systemFontOfSize_weight_(12, 0.31),
            NSColor.labelColor(),
            NSTextAlignmentRight,
        )
        self.reset_label = _label("", _regular_font(11), _muted_label_color(), NSTextAlignmentRight)
        self.progress_bar = ProgressBarView.alloc().initWithFrame_(
            NSMakeRect(0, 20, 1, TRACK_HEIGHT),
        )
        for view in (self.title_label, self.percent_label, self.progress_bar, self.reset_label):
            self.addSubview_(view)
        return self

    def isFlipped(self) -> bool:
        return True

    def layout(self) -> None:
        width = self.bounds().size.width
        self.title_label.setFrame_(NSMakeRect(0, 0, width * 0.42, 18))
        self.percent_label.setFrame_(NSMakeRect(width * 0.42, 0, width * 0.58, 18))
        self.progress_bar.setFrame_(NSMakeRect(0, 24, width, TRACK_HEIGHT))
        self.reset_label.setFrame_(NSMakeRect(0, 38, width, 14))

    def setRowState_(self, row: QuotaRowState) -> None:
        self.title_label.setStringValue_(row.title)
        self.percent_label.setStringValue_(row.percent_text)
        self.reset_label.setStringValue_(row.reset_text)
        color = NSColor.colorWithCalibratedRed_green_blue_alpha_(*row.color, 1.0)
        self.progress_bar.setPercent_color_available_(row.percent, color, row.available)
        self.percent_label.setTextColor_(color if row.available else _muted_label_color())
        self.reset_label.setTextColor_(_muted_label_color())
        self.setNeedsLayout_(True)


class HeaderIconView(NSView):
    accent_color = objc.ivar()
    image = objc.ivar()

    def initWithFrame_color_path_(self, frame: Any, color: NSColor, path: str) -> HeaderIconView:
        self = objc.super(HeaderIconView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.accent_color = color
        self.image = NSImage.alloc().initWithContentsOfFile_(path)
        return self

    def isFlipped(self) -> bool:
        return True

    def drawRect_(self, dirty_rect: Any) -> None:
        bounds = self.bounds()
        if self.image is not None:
            self.image.drawInRect_(bounds)


class ActionButton(NSButton):
    accent_color = objc.ivar()
    is_primary = objc.ivar()

    def initWithFrame_title_primary_color_target_action_(
        self,
        frame: Any,
        title: str,
        primary: bool,
        color: NSColor | None,
        target: Any,
        action: str,
    ) -> ActionButton:
        self = objc.super(ActionButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.accent_color = color
        self.is_primary = primary
        self.setTitle_(title)
        self.setFont_(NSFont.systemFontOfSize_weight_(14, 0.28))
        self.setBordered_(False)
        self.setTarget_(target)
        self.setAction_(action)
        return self

    def drawRect_(self, dirty_rect: Any) -> None:
        bounds = self.bounds()
        radius = 10.0
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, radius, radius)
        border = _button_border_color(self, self.is_primary)
        border.setStroke()

        if self.is_primary and self.accent_color is not None:
            _button_gradient(self.accent_color).drawInBezierPath_angle_(path, 90.0)
        else:
            _secondary_button_fill_color(self).setFill()
            path.fill()

        path.setLineWidth_(1.0)
        path.stroke()
        _draw_button_title(self, bounds)


class PopoverContentView(NSView):
    delegate = objc.ivar()
    claude_icon = objc.ivar()
    codex_icon = objc.ivar()
    claude_header = objc.ivar()
    codex_header = objc.ivar()
    claude_session = objc.ivar()
    claude_weekly = objc.ivar()
    codex_session = objc.ivar()
    codex_weekly = objc.ivar()
    rate_label = objc.ivar()
    status_label = objc.ivar()
    today_label = objc.ivar()
    install_hook_button = objc.ivar()
    refresh_button = objc.ivar()
    quit_button = objc.ivar()
    show_install_button = objc.ivar()

    def initWithFrame_delegate_(self, frame: Any, delegate: Any) -> PopoverContentView:
        self = objc.super(PopoverContentView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.delegate = delegate
        self.show_install_button = False
        claude_accent = NSColor.colorWithCalibratedRed_green_blue_alpha_(*CLAUDE_COLOR, 1.0)
        codex_accent = NSColor.colorWithCalibratedRed_green_blue_alpha_(*CODEX_COLOR, 1.0)
        self.claude_icon = HeaderIconView.alloc().initWithFrame_color_path_(
            NSMakeRect(0, 0, 42, 42),
            claude_accent,
            str(CLAUDE_ICON_PATH),
        )
        self.codex_icon = HeaderIconView.alloc().initWithFrame_color_path_(
            NSMakeRect(0, 0, 42, 42),
            codex_accent,
            str(CODEX_ICON_PATH),
        )
        self.claude_header = _label("Claude Code", _semibold_font(), NSColor.labelColor())
        self.codex_header = _label("Codex", _semibold_font(), NSColor.labelColor())
        self.claude_session = QuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.claude_weekly = QuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.codex_session = QuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.codex_weekly = QuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.rate_label = _label("速率：--", _regular_font(13.5), _muted_label_color())
        self.status_label = _label("狀態：載入中", _regular_font(13.5), _muted_label_color())
        self.today_label = _label(
            "今日：$0.00 (0 tokens)",
            NSFont.systemFontOfSize_weight_(15, 0.34),
            NSColor.labelColor(),
        )
        self.today_label.setAllowsDefaultTighteningForTruncation_(True)
        self.install_hook_button = (
            ActionButton.alloc().initWithFrame_title_primary_color_target_action_(
                NSMakeRect(0, 0, 1, BUTTON_HEIGHT),
                "立即安裝 hook",
                True,
                claude_accent,
                delegate,
                "installHook:",
            )
        )
        self.install_hook_button.setHidden_(True)
        accent = NSColor.colorWithCalibratedRed_green_blue_alpha_(*CODEX_COLOR, 1.0)
        self.refresh_button = ActionButton.alloc().initWithFrame_title_primary_color_target_action_(
            NSMakeRect(0, 0, 1, BUTTON_HEIGHT),
            "立即更新",
            True,
            accent,
            delegate,
            "refreshNow:",
        )
        self.quit_button = ActionButton.alloc().initWithFrame_title_primary_color_target_action_(
            NSMakeRect(0, 0, 1, BUTTON_HEIGHT),
            "結束",
            False,
            None,
            delegate,
            "quitApp:",
        )

        for view in (
            self.claude_icon,
            self.codex_icon,
            self.claude_header,
            self.claude_session,
            self.claude_weekly,
            self.codex_header,
            self.codex_session,
            self.codex_weekly,
            self.rate_label,
            self.status_label,
            self.today_label,
            self.install_hook_button,
            self.refresh_button,
            self.quit_button,
        ):
            self.addSubview_(view)
        return self

    def isFlipped(self) -> bool:
        return True

    def layout(self) -> None:
        width = self.bounds().size.width
        content_width = width - (PADDING * 2)
        card_width = content_width
        card_content_width = card_width - (CARD_SIDE_INSET * 2)
        claude_y = PADDING
        codex_y = claude_y + CARD_HEIGHT + SECTION_GAP
        footer_y = codex_y + CARD_HEIGHT + FOOTER_GAP
        icon_x = PADDING + CARD_SIDE_INSET

        self.claude_icon.setFrame_(NSMakeRect(icon_x, claude_y + 18, 36, 36))
        self.claude_header.setFrame_(
            NSMakeRect(
                icon_x + 48,
                claude_y + CARD_HEADER_TOP + 1,
                card_content_width - 48,
                22,
            ),
        )
        self.claude_session.setFrame_(
            NSMakeRect(PADDING + CARD_SIDE_INSET, claude_y + CARD_ROW_TOP, card_content_width, 52),
        )
        self.claude_weekly.setFrame_(
            NSMakeRect(
                PADDING + CARD_SIDE_INSET,
                claude_y + CARD_ROW_TOP + CARD_ROW_GAP,
                card_content_width,
                52,
            ),
        )

        self.codex_icon.setFrame_(NSMakeRect(icon_x, codex_y + 18, 36, 36))
        self.codex_header.setFrame_(
            NSMakeRect(
                icon_x + 48,
                codex_y + CARD_HEADER_TOP + 1,
                card_content_width - 48,
                22,
            ),
        )
        self.codex_session.setFrame_(
            NSMakeRect(PADDING + CARD_SIDE_INSET, codex_y + CARD_ROW_TOP, card_content_width, 52),
        )
        self.codex_weekly.setFrame_(
            NSMakeRect(
                PADDING + CARD_SIDE_INSET,
                codex_y + CARD_ROW_TOP + CARD_ROW_GAP,
                card_content_width,
                52,
            ),
        )

        self.rate_label.setFrame_(NSMakeRect(PADDING + 18, footer_y + 16, content_width - 36, 18))
        self.status_label.setFrame_(
            NSMakeRect(PADDING + 18, footer_y + 16 + FOOTER_LINE_GAP, content_width - 36, 18),
        )
        self.today_label.setFrame_(
            NSMakeRect(PADDING + 18, footer_y + 16 + FOOTER_LINE_GAP + 26, content_width - 36, 22),
        )
        y = footer_y + 16 + FOOTER_LINE_GAP + 26 + 24 + BUTTON_TOP_GAP

        button_gap = 10.0
        button_width = (content_width - 24 - button_gap) / 2
        if self.show_install_button:
            self.install_hook_button.setFrame_(
                NSMakeRect(PADDING + 12, y, content_width - 24, BUTTON_HEIGHT),
            )
            y += INSTALL_BUTTON_EXTRA_HEIGHT
        self.refresh_button.setFrame_(NSMakeRect(PADDING + 12, y, button_width, BUTTON_HEIGHT))
        self.quit_button.setFrame_(
            NSMakeRect(PADDING + 12 + button_width + button_gap, y, button_width, BUTTON_HEIGHT),
        )

    def drawRect_(self, dirty_rect: Any) -> None:
        _background_gradient_for_view(self).drawInRect_angle_(self.bounds(), 90.0)
        content_width = self.bounds().size.width - (PADDING * 2)
        claude_rect = NSMakeRect(PADDING, PADDING, content_width, CARD_HEIGHT)
        codex_rect = NSMakeRect(
            PADDING,
            PADDING + CARD_HEIGHT + SECTION_GAP,
            content_width,
            CARD_HEIGHT,
        )
        footer_rect = NSMakeRect(
            PADDING,
            PADDING + (CARD_HEIGHT * 2) + SECTION_GAP + FOOTER_GAP,
            content_width,
            FOOTER_HEIGHT + (INSTALL_BUTTON_EXTRA_HEIGHT if self.show_install_button else 0.0),
        )

        for card_rect in (claude_rect, codex_rect, footer_rect):
            _card_fill_color_for_view(self).setFill()
            _fill_rounded_rect(card_rect, CARD_RADIUS)
            _card_border_color_for_view(self).setStroke()
            _stroke_rounded_rect(card_rect, CARD_RADIUS, 1.0)

        _card_separator_color_for_view(self).setFill()
        for card_rect in (claude_rect, codex_rect):
            separator_y = card_rect.origin.y + CARD_ROW_TOP + CARD_ROW_GAP - 12
            NSRectFill(
                NSMakeRect(
                    card_rect.origin.x + CARD_SIDE_INSET,
                    separator_y,
                    card_rect.size.width - (CARD_SIDE_INSET * 2),
                    1,
                ),
            )
        NSRectFill(
            NSMakeRect(
                footer_rect.origin.x + 18,
                footer_rect.origin.y + 54,
                footer_rect.size.width - 36,
                1,
            ),
        )

    def setState_(self, state: PopoverState) -> None:
        self.claude_session.setRowState_(state.claude_session)
        self.claude_weekly.setRowState_(state.claude_weekly)
        self.codex_session.setRowState_(state.codex_session)
        self.codex_weekly.setRowState_(state.codex_weekly)
        self.rate_label.setStringValue_(state.rate_text)
        self.status_label.setStringValue_(state.status_text)
        self.today_label.setStringValue_(state.today_text)
        self.show_install_button = state.show_install_button
        self.install_hook_button.setHidden_(not state.show_install_button)
        self.rate_label.setTextColor_(_muted_label_color())
        self.status_label.setTextColor_(_muted_label_color())
        self.today_label.setTextColor_(NSColor.labelColor())
        self.setNeedsLayout_(True)
        self.setNeedsDisplay_(True)


class PopoverViewController(NSViewController):
    content_view = objc.ivar()

    def initWithDelegate_(self, delegate: Any) -> PopoverViewController:
        self = objc.super(PopoverViewController, self).init()
        if self is None:
            return None
        self.content_view = PopoverContentView.alloc().initWithFrame_delegate_(
            NSMakeRect(0, 0, POPOVER_WIDTH, CONTENT_HEIGHT),
            delegate,
        )
        self.setView_(self.content_view)
        return self

    def setState_(self, state: PopoverState) -> None:
        self.view().setFrameSize_(_popover_size(state))
        self.content_view.setState_(state)


class AppDelegate(NSObject):
    status_item = objc.ivar()
    popover = objc.ivar()
    popover_controller = objc.ivar()
    timer = objc.ivar()
    mock = objc.ivar()
    interval = objc.ivar()
    tracker = objc.ivar()
    latest_state = objc.ivar()
    codex_5h_pct = objc.ivar()
    _refresh_in_flight = objc.ivar()

    def initWithMock_interval_(self, mock: bool, interval: int) -> AppDelegate:
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.mock = mock
        self.interval = max(30, interval)
        self.tracker = UsageRateTracker(mock=mock)
        self.codex_5h_pct = None
        self.latest_state = _empty_state()
        self._refresh_in_flight = False
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

        self.popover_controller = PopoverViewController.alloc().initWithDelegate_(self)
        self.popover = NSPopover.alloc().init()
        self.popover.setBehavior_(NSPopoverBehaviorTransient)
        self.popover.setContentSize_(NSMakeSize(POPOVER_WIDTH, CONTENT_HEIGHT))
        self.popover.setContentViewController_(self.popover_controller)

        self._refresh()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.interval,
            self,
            "timerFired:",
            None,
            True,
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes)

    def timerFired_(self, timer: Any) -> None:
        self._refresh()

    def refreshNow_(self, sender: Any) -> None:
        self._refresh()

    def installHook_(self, sender: Any) -> None:
        thread = threading.Thread(target=self._install_hook_in_background, daemon=True)
        thread.start()

    def quitApp_(self, sender: Any) -> None:
        if self.timer is not None:
            self.timer.invalidate()
        NSApp.terminate_(sender)

    def togglePopover_(self, sender: Any) -> None:
        if self.popover.isShown():
            self.popover.performClose_(sender)
            return
        self.popover_controller.setState_(self.latest_state)
        self.popover.setContentSize_(_popover_size(self.latest_state))
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
            state = self._state_from_outcome(outcome, codex_rows)
        except Exception as exc:
            codex_5h_pct = None
            state = _error_state(type(exc).__name__, self.mock)

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
        self.popover_controller.setState_(state)
        self.popover.setContentSize_(_popover_size(state))
        self.status_item.button().setTitle_(self._compose_title(state))
        self._refresh_in_flight = False

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
            alert.setMessageText_("已安裝完成，請重開 Claude Code 一次")
        else:
            alert.setMessageText_("安裝 hook 失敗")
            alert.setInformativeText_(result["message"] or "setup_hook.setup() 回傳失敗")
        alert.runModal()
        self._refresh()

    async def _fetch(self) -> PollOutcome:
        client = ClaudeUsageClient(mock=self.mock)
        try:
            return await client.fetch_once()
        finally:
            await client.aclose()

    def _state_from_outcome(
        self,
        outcome: PollOutcome,
        codex_rows: tuple[QuotaRowState, QuotaRowState],
    ) -> PopoverState:
        now = time.time()
        today_text = _today_title(self.mock)
        group_name = GROUP_NAMES[self.tracker.group()]
        status_text = f"狀態：{outcome.message or '載入中'}"

        if outcome.state == PollState.SUCCESS and outcome.snapshot is not None:
            snapshot = outcome.snapshot
            group_name = GROUP_NAMES[self.tracker.group()]
            claude_session = _quota_row(
                "Session",
                float(snapshot.current_percent)
                if snapshot.current_percent is not None
                else None,
                snapshot.current_reset_at,
                now,
                CLAUDE_COLOR,
            )
            claude_weekly = _quota_row(
                "Weekly",
                float(snapshot.weekly_percent) if snapshot.weekly_percent is not None else None,
                snapshot.weekly_reset_at,
                now,
                CLAUDE_COLOR,
            )
            status_text = f"狀態：{outcome.message or '✓ 已同步'}"
        else:
            claude_session = _missing_row("Session", CLAUDE_COLOR)
            claude_weekly = _missing_row("Weekly", CLAUDE_COLOR)
            status_text = f"狀態：{outcome.message or '無資料'}"

        return PopoverState(
            claude_session=claude_session,
            claude_weekly=claude_weekly,
            codex_session=codex_rows[0],
            codex_weekly=codex_rows[1],
            rate_text=f"速率：{group_name}",
            status_text=status_text,
            today_text=today_text,
            show_install_button=outcome.state == PollState.TOKEN_ERROR,
        )

    def _codex_rows(self) -> tuple[tuple[QuotaRowState, QuotaRowState], int | None]:
        if self.mock:
            now = time.time()
            rows = (
                _quota_row("Session", 12.0, now + (4 * 3600) + (15 * 60), now, CODEX_COLOR),
                _quota_row("Weekly", 28.0, now + (4 * 86400), now, CODEX_COLOR),
            )
            return rows, 12

        try:
            rate_limits = codex_loader.load_rate_limits()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("codex rate limits load failed", exc_info=True)
            rate_limits = None

        if rate_limits is None:
            rows = _missing_row("Session", CODEX_COLOR), _missing_row("Weekly", CODEX_COLOR)
            return rows, None

        now = time.time()
        codex_5h_pct = (
            round(rate_limits.five_hour_pct) if rate_limits.five_hour_pct is not None else None
        )
        rows = (
            _quota_row(
                "Session",
                rate_limits.five_hour_pct,
                rate_limits.five_hour_resets_at,
                now,
                CODEX_COLOR,
            ),
            _quota_row(
                "Weekly",
                rate_limits.seven_day_pct,
                rate_limits.seven_day_resets_at,
                now,
                CODEX_COLOR,
            ),
        )
        return rows, codex_5h_pct

    def _compose_title(self, state: PopoverState) -> str:
        claude_text = state.claude_session.percent_text.replace(" 已用", "")
        base = "🐾 --" if claude_text == "--" else f"🐾 {claude_text}"
        if self.codex_5h_pct is None:
            return base
        return f"{base} · 📜 {self.codex_5h_pct}%"


def run_app(mock: bool = False, interval: int = 60) -> None:
    global _APP_DELEGATE
    app = NSApplication.sharedApplication()
    _APP_DELEGATE = AppDelegate.alloc().initWithMock_interval_(mock, interval)
    app.setDelegate_(_APP_DELEGATE)
    app.run()


def _popover_size(state: PopoverState) -> Any:
    height = CONTENT_HEIGHT + (INSTALL_BUTTON_EXTRA_HEIGHT if state.show_install_button else 0.0)
    return NSMakeSize(POPOVER_WIDTH, height)


def _empty_state() -> PopoverState:
    return PopoverState(
        claude_session=_missing_row("Session", CLAUDE_COLOR),
        claude_weekly=_missing_row("Weekly", CLAUDE_COLOR),
        codex_session=_missing_row("Session", CODEX_COLOR),
        codex_weekly=_missing_row("Weekly", CODEX_COLOR),
        rate_text="速率：--",
        status_text="狀態：載入中",
        today_text="今日：$0.00 (0 tokens)",
        show_install_button=False,
    )


def _error_state(message: str, mock: bool) -> PopoverState:
    state = _empty_state()
    state.status_text = f"狀態：錯誤 ({message})"
    state.today_text = _today_title(mock)
    state.show_install_button = False
    return state


def _quota_row(
    title: str,
    pct: float | None,
    resets_at: float | None,
    now: float,
    color: tuple[float, float, float],
) -> QuotaRowState:
    if pct is None or resets_at is None:
        return _missing_row(title, color)
    pct = max(0.0, min(100.0, float(pct)))
    return QuotaRowState(
        title=title,
        percent=pct,
        percent_text=f"{_format_percent(pct)}% 已用",
        reset_text=f"重置 {format_human_time(resets_at - now)}",
        color=_bar_color(pct, color),
        available=True,
    )


def _missing_row(title: str, color: tuple[float, float, float]) -> QuotaRowState:
    return QuotaRowState(
        title=title,
        percent=None,
        percent_text="--",
        reset_text="重置 --",
        color=color,
        available=False,
    )


def _today_title(mock: bool = False) -> str:
    if mock:
        return "今日：$45.20 (50,193,442 tokens)"

    today = datetime.now().astimezone().date()
    total_tokens = 0
    total_cost = 0.0

    entries = load_entries(hours_back=24) + codex_loader.load_entries(hours_back=24)
    for entry in entries:
        if entry.timestamp.astimezone().date() != today:
            continue
        total_tokens += entry.total_tokens
        total_cost += calculate_cost(entry)

    return f"今日：${total_cost:.2f} ({total_tokens:,} tokens)"


def _format_percent(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _label(
    text: str,
    font: NSFont,
    color: NSColor,
    alignment: int | None = None,
) -> NSTextField:
    label = NSTextField.labelWithString_(text)
    label.setFont_(font)
    label.setTextColor_(color)
    label.setDrawsBackground_(False)
    label.setBordered_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    if alignment is not None:
        label.setAlignment_(alignment)
    return label


def _semibold_font() -> NSFont:
    return NSFont.systemFontOfSize_weight_(16, 0.33)


def _medium_font() -> NSFont:
    return NSFont.systemFontOfSize_weight_(12.5, 0.28)


def _regular_font(size: float) -> NSFont:
    return NSFont.systemFontOfSize_weight_(size, -0.4)


def _muted_label_color() -> NSColor:
    return NSColor.labelColor().colorWithAlphaComponent_(0.74)


def _is_dark_appearance(view: NSView) -> bool:
    name = view.effectiveAppearance().name() or ""
    return "Dark" in name


def _card_fill_color_for_view(view: NSView) -> NSColor:
    if _is_dark_appearance(view):
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.115, 0.126, 0.15, 0.92)
    return NSColor.whiteColor().colorWithAlphaComponent_(0.9)


def _card_border_color_for_view(view: NSView) -> NSColor:
    if _is_dark_appearance(view):
        return NSColor.whiteColor().colorWithAlphaComponent_(0.08)
    return NSColor.blackColor().colorWithAlphaComponent_(0.08)


def _card_separator_color_for_view(view: NSView) -> NSColor:
    if _is_dark_appearance(view):
        return NSColor.whiteColor().colorWithAlphaComponent_(0.09)
    return NSColor.blackColor().colorWithAlphaComponent_(0.08)


def _track_color_for_view(view: NSView) -> NSColor:
    if _is_dark_appearance(view):
        return NSColor.whiteColor().colorWithAlphaComponent_(0.07)
    return NSColor.blackColor().colorWithAlphaComponent_(0.057)


def _background_gradient_for_view(view: NSView) -> NSGradient:
    if _is_dark_appearance(view):
        colors = [
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.11, 0.135, 1.0),
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.065, 0.072, 0.09, 1.0),
        ]
    else:
        colors = [
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.96, 0.965, 0.975, 1.0),
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.93, 0.945, 1.0),
        ]
    return NSGradient.alloc().initWithColors_(colors)


def _accent_gradient(color: NSColor) -> NSGradient:
    return NSGradient.alloc().initWithColors_(
        [
            color.highlightWithLevel_(0.22),
            color,
        ],
    )


def _secondary_button_fill_color(view: NSView) -> NSColor:
    if _is_dark_appearance(view):
        return NSColor.whiteColor().colorWithAlphaComponent_(0.045)
    return NSColor.blackColor().colorWithAlphaComponent_(0.035)


def _button_gradient(color: NSColor) -> NSGradient:
    return NSGradient.alloc().initWithColors_(
        [
            color.highlightWithLevel_(0.08),
            color.shadowWithLevel_(0.12),
        ],
    )


def _button_border_color(view: NSView, primary: bool) -> NSColor:
    if primary:
        return NSColor.whiteColor().colorWithAlphaComponent_(0.14)
    if _is_dark_appearance(view):
        return NSColor.whiteColor().colorWithAlphaComponent_(0.12)
    return NSColor.blackColor().colorWithAlphaComponent_(0.1)


def _icon_badge_fill(view: NSView) -> NSColor:
    if _is_dark_appearance(view):
        return NSColor.whiteColor().colorWithAlphaComponent_(0.04)
    return NSColor.blackColor().colorWithAlphaComponent_(0.03)


def _draw_button_title(button: ActionButton, bounds: Any) -> None:
    style = NSMutableParagraphStyle.alloc().init()
    style.setAlignment_(1)
    text_color = (
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.18, 0.2, 0.96)
        if button.is_primary
        else NSColor.labelColor()
    )
    attrs = {
        NSForegroundColorAttributeName: text_color,
        NSParagraphStyleAttributeName: style,
        NSStrokeColorAttributeName: NSColor.clearColor(),
        NSFontAttributeName: NSFont.systemFontOfSize_weight_(14, 0.32),
    }
    title_rect = NSMakeRect(0, 8, bounds.size.width, 18)
    button.title().drawInRect_withAttributes_(title_rect, attrs)


def _fill_rounded_rect(rect: Any, radius: float) -> None:
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius).fill()


def _stroke_rounded_rect(rect: Any, radius: float, width: float) -> None:
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
    path.setLineWidth_(width)
    path.stroke()
