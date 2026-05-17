# mypy: ignore-errors
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBezelStyleRounded,
    NSBezierPath,
    NSButton,
    NSColor,
    NSFont,
    NSMakeRect,
    NSMakeSize,
    NSMinYEdge,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSRectFill,
    NSStatusBar,
    NSTextAlignmentRight,
    NSTextField,
    NSVariableStatusItemLength,
    NSView,
    NSViewController,
)
from Foundation import NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer

import codex_loader
from history_loader import load_entries
from pricing import calculate_cost
from usage_client import ClaudeUsageClient, PollOutcome, PollState
from usage_rate import GROUP_NAMES, UsageRateTracker

POPOVER_WIDTH = 360.0
CONTENT_HEIGHT = 488.0
PADDING = 16.0
TRACK_HEIGHT = 6.0
CLAUDE_COLOR = (217 / 255, 119 / 255, 87 / 255)
CODEX_COLOR = (73 / 255, 163 / 255, 176 / 255)

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
        self.bar_color.setFill()
        _fill_rounded_rect(fill_rect, TRACK_HEIGHT / 2)


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
            NSFont.systemFontOfSize_weight_(12, 0.23),
            _muted_label_color(),
            NSTextAlignmentRight,
        )
        self.reset_label = _label("", _regular_font(10), _muted_label_color(), NSTextAlignmentRight)
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
        self.title_label.setFrame_(NSMakeRect(0, 0, width * 0.48, 18))
        self.percent_label.setFrame_(NSMakeRect(width * 0.48, 0, width * 0.52, 18))
        self.progress_bar.setFrame_(NSMakeRect(0, 24, width, TRACK_HEIGHT))
        self.reset_label.setFrame_(NSMakeRect(0, 38, width, 14))

    def setRowState_(self, row: QuotaRowState) -> None:
        self.title_label.setStringValue_(row.title)
        self.percent_label.setStringValue_(row.percent_text)
        self.reset_label.setStringValue_(row.reset_text)
        color = NSColor.colorWithCalibratedRed_green_blue_alpha_(*row.color, 1.0)
        self.progress_bar.setPercent_color_available_(row.percent, color, row.available)
        for label in (self.percent_label, self.reset_label):
            label.setTextColor_(_muted_label_color())
        self.setNeedsLayout_(True)


class PopoverContentView(NSView):
    delegate = objc.ivar()
    claude_header = objc.ivar()
    codex_header = objc.ivar()
    claude_session = objc.ivar()
    claude_weekly = objc.ivar()
    codex_session = objc.ivar()
    codex_weekly = objc.ivar()
    rate_label = objc.ivar()
    status_label = objc.ivar()
    today_label = objc.ivar()
    refresh_button = objc.ivar()
    quit_button = objc.ivar()

    def initWithFrame_delegate_(self, frame: Any, delegate: Any) -> PopoverContentView:
        self = objc.super(PopoverContentView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.delegate = delegate
        self.claude_header = _label("Claude Code", _semibold_font(), NSColor.labelColor())
        self.codex_header = _label("Codex", _semibold_font(), NSColor.labelColor())
        self.claude_session = QuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.claude_weekly = QuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.codex_session = QuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.codex_weekly = QuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.rate_label = _label("速率：--", _regular_font(12), NSColor.labelColor())
        self.status_label = _label("狀態：載入中", _regular_font(12), NSColor.labelColor())
        self.today_label = _label(
            "今日：$0.00（0 tokens）",
            _regular_font(12),
            NSColor.labelColor(),
        )
        self.refresh_button = _button("立即重新整理", delegate, "refreshNow:")
        self.quit_button = _button("結束", delegate, "quitApp:")

        for view in (
            self.claude_header,
            self.claude_session,
            self.claude_weekly,
            self.codex_header,
            self.codex_session,
            self.codex_weekly,
            self.rate_label,
            self.status_label,
            self.today_label,
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
        y = PADDING

        self.claude_header.setFrame_(NSMakeRect(PADDING, y, content_width, 16))
        y += 28
        self.claude_session.setFrame_(NSMakeRect(PADDING, y, content_width, 56))
        y += 64
        self.claude_weekly.setFrame_(NSMakeRect(PADDING, y, content_width, 56))
        y += 64
        y += 20

        self.codex_header.setFrame_(NSMakeRect(PADDING, y, content_width, 16))
        y += 28
        self.codex_session.setFrame_(NSMakeRect(PADDING, y, content_width, 56))
        y += 64
        self.codex_weekly.setFrame_(NSMakeRect(PADDING, y, content_width, 56))
        y += 64
        y += 16

        self.rate_label.setFrame_(NSMakeRect(PADDING, y, content_width, 17))
        y += 20
        self.status_label.setFrame_(NSMakeRect(PADDING, y, content_width, 17))
        y += 20
        self.today_label.setFrame_(NSMakeRect(PADDING, y, content_width, 17))
        y += 34

        button_width = (content_width - 8) / 2
        self.refresh_button.setFrame_(NSMakeRect(PADDING, y, button_width, 28))
        self.quit_button.setFrame_(NSMakeRect(PADDING + button_width + 8, y, button_width, 28))

    def drawRect_(self, dirty_rect: Any) -> None:
        NSColor.controlBackgroundColor().setFill()
        NSRectFill(self.bounds())

        width = self.bounds().size.width - (PADDING * 2)
        # Claude 區結束 y=164、Codex header 起點 y=192 → 中間 178
        first_y = 178
        # Codex 區結束 y=340、rate_label 起點 y=364 → 中間 352
        second_y = 352
        NSColor.separatorColor().setFill()
        for y in (first_y, second_y):
            NSRectFill(NSMakeRect(PADDING, y, width, 1))

    def setState_(self, state: PopoverState) -> None:
        self.claude_session.setRowState_(state.claude_session)
        self.claude_weekly.setRowState_(state.claude_weekly)
        self.codex_session.setRowState_(state.codex_session)
        self.codex_weekly.setRowState_(state.codex_weekly)
        self.rate_label.setStringValue_(state.rate_text)
        self.status_label.setStringValue_(state.status_text)
        self.today_label.setStringValue_(state.today_text)
        for label in (self.rate_label, self.status_label, self.today_label):
            label.setTextColor_(NSColor.labelColor())
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

    def quitApp_(self, sender: Any) -> None:
        if self.timer is not None:
            self.timer.invalidate()
        NSApp.terminate_(sender)

    def togglePopover_(self, sender: Any) -> None:
        if self.popover.isShown():
            self.popover.performClose_(sender)
            return
        self.popover_controller.setState_(self.latest_state)
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
        self.status_item.button().setTitle_(self._compose_title(state))
        self._refresh_in_flight = False

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
            self.tracker.sample(float(snapshot.current_percent))
            group_name = GROUP_NAMES[self.tracker.group()]
            claude_session = _quota_row(
                "Session",
                float(snapshot.current_percent),
                snapshot.current_reset_at,
                now,
                CLAUDE_COLOR,
            )
            claude_weekly = _quota_row(
                "Weekly",
                float(snapshot.weekly_percent),
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


def _empty_state() -> PopoverState:
    return PopoverState(
        claude_session=_missing_row("Session", CLAUDE_COLOR),
        claude_weekly=_missing_row("Weekly", CLAUDE_COLOR),
        codex_session=_missing_row("Session", CODEX_COLOR),
        codex_weekly=_missing_row("Weekly", CODEX_COLOR),
        rate_text="速率：--",
        status_text="狀態：載入中",
        today_text="今日：$0.00（0 tokens）",
    )


def _error_state(message: str, mock: bool) -> PopoverState:
    state = _empty_state()
    state.status_text = f"狀態：錯誤 ({message})"
    state.today_text = _today_title(mock)
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
        color=color,
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
        return "今日：$45.20（50,193,442 tokens）"

    today = datetime.now().astimezone().date()
    total_tokens = 0
    total_cost = 0.0

    entries = load_entries(hours_back=24) + codex_loader.load_entries(hours_back=24)
    for entry in entries:
        if entry.timestamp.astimezone().date() != today:
            continue
        total_tokens += entry.total_tokens
        total_cost += calculate_cost(entry)

    return f"今日：${total_cost:.2f}（{total_tokens:,} tokens）"


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


def _button(title: str, target: Any, action: str) -> NSButton:
    button = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 28))
    button.setTitle_(title)
    button.setFont_(_regular_font(13))
    button.setBezelStyle_(NSBezelStyleRounded)
    button.setTarget_(target)
    button.setAction_(action)
    return button


def _semibold_font() -> NSFont:
    return NSFont.systemFontOfSize_weight_(15, 0.3)


def _medium_font() -> NSFont:
    return NSFont.systemFontOfSize_weight_(14, 0.23)


def _regular_font(size: float) -> NSFont:
    return NSFont.systemFontOfSize_weight_(size, -0.4)


def _muted_label_color() -> NSColor:
    return NSColor.labelColor().colorWithAlphaComponent_(0.6)


def _track_color_for_view(view: NSView) -> NSColor:
    name = view.effectiveAppearance().name() or ""
    if "Dark" in name:
        return NSColor.whiteColor().colorWithAlphaComponent_(0.055)
    return NSColor.blackColor().colorWithAlphaComponent_(0.057)


def _fill_rounded_rect(rect: Any, radius: float) -> None:
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius).fill()
