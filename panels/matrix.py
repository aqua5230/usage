# mypy: disable-error-code="import-untyped,misc"
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import objc
from AppKit import (
    NSBezierPath,
    NSButton,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMakePoint,
    NSMakeRect,
    NSMutableParagraphStyle,
    NSParagraphStyleAttributeName,
    NSRectFill,
    NSTextAlignmentCenter,
    NSView,
)
from Foundation import NSMutableDictionary, NSString, NSTimer

from panels.base import (
    BUTTON_HEIGHT,
    BUTTON_TOP_GAP,
    CARD_HEADER_TOP,
    CARD_HEIGHT,
    CARD_RADIUS,
    CARD_ROW_GAP,
    CARD_ROW_TOP,
    CARD_SIDE_INSET,
    CONTENT_HEIGHT,
    FOOTER_GAP,
    FOOTER_HEIGHT,
    FOOTER_LINE_GAP,
    INSTALL_BUTTON_EXTRA_HEIGHT,
    PADDING,
    POPOVER_WIDTH,
    SECTION_GAP,
    PanelQuotaRowView,
    fill_rounded_rect,
    label,
    stroke_rounded_rect,
)

if TYPE_CHECKING:
    from menubar import PopoverState

SWITCH_BUTTON_WIDTH = 106.0
SWITCH_BUTTON_HEIGHT = 28.0
SWITCH_BUTTON_GAP = 16.0
COLUMN_COUNT = 26
COLUMN_WIDTH = 14.0
TRAIL_LENGTH = 10
CHARACTER_POOL = "ｦｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃ0123456789"

MATRIX_GREEN = (0.18, 0.95, 0.45, 1.0)
MUTED_GREEN = (0.05, 0.60, 0.18, 0.85)
CARD_FILL = (0.0, 0.08, 0.03, 0.90)
CARD_BORDER = (0.0, 0.85, 0.35, 0.4)
TRACK_COLOR = (0.0, 0.35, 0.12, 0.4)
FADE_BLACK = (0.0, 0.0, 0.0, 0.18)
OPAQUE_BLACK = (0.0, 0.0, 0.0, 1.0)


def _rgba(color: tuple[float, float, float, float]) -> NSColor:
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(*color)


def _font(size: float, weight: float) -> NSFont:
    try:
        return NSFont.monospacedSystemFontOfSize_weight_(size, weight)
    except Exception:
        fallback = NSFont.fontWithName_size_("Menlo", size)
        if fallback is not None:
            return fallback
        return NSFont.systemFontOfSize_weight_(size, weight)


def _matrix_label(text: str, size: float, color: NSColor) -> Any:
    return label(text, _font(size, 0.26), color)


def _suffix(text: str) -> str:
    if "：" in text:
        return text.split("：", 1)[1].strip()
    if ":" in text:
        return text.split(":", 1)[1].strip()
    return text.strip()


class MatrixTerminalButton(NSButton):
    fill_color = objc.ivar()
    border_color = objc.ivar()
    text_color = objc.ivar()

    def initWithFrame_title_target_action_(
        self,
        frame: Any,
        title: str,
        target: Any,
        action: str,
    ) -> MatrixTerminalButton:
        self = objc.super(MatrixTerminalButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.fill_color = _rgba((0.0, 0.0, 0.0, 0.92))
        self.border_color = _rgba(CARD_BORDER)
        self.text_color = _rgba(MATRIX_GREEN)
        self.setTitle_(title)
        self.setBordered_(False)
        self.setTarget_(target)
        self.setAction_(action)
        return self

    def drawRect_(self, dirty_rect: Any) -> None:
        bounds = self.bounds()
        radius = 9.0
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, radius, radius)
        self.fill_color.setFill()
        path.fill()
        self.border_color.setStroke()
        path.setLineWidth_(1.0)
        path.stroke()

        style = NSMutableParagraphStyle.alloc().init()
        style.setAlignment_(NSTextAlignmentCenter)
        attrs = NSMutableDictionary.dictionaryWithDictionary_(
            {
                NSForegroundColorAttributeName: self.text_color,
                NSParagraphStyleAttributeName: style,
                NSFontAttributeName: _font(13.0, 0.3),
            },
        )
        self.title().drawInRect_withAttributes_(
            NSMakeRect(0, (bounds.size.height - 16.0) / 2, bounds.size.width, 16.0),
            attrs,
        )


class MatrixRainView(NSView):
    timer = objc.ivar()
    columns = objc.ivar()
    glyph_font = objc.ivar()

    def initWithFrame_(self, frame: Any) -> MatrixRainView:
        self = objc.super(MatrixRainView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.glyph_font = _font(14.0, 0.24)
        self.columns = []
        self._reset_columns(frame.size.height)
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.08,
            self,
            "tick:",
            None,
            True,
        )
        return self

    def isFlipped(self) -> bool:
        return True

    def viewWillMoveToWindow_(self, window: Any) -> None:
        if window is None and self.timer is not None:
            self.timer.invalidate()
            self.timer = None

    def tick_(self, sender: Any) -> None:
        self.setNeedsDisplay_(True)

    def _reset_columns(self, height: float) -> None:
        self.columns = [
            {
                "x": float(index) * COLUMN_WIDTH + 8.0,
                "y": random.uniform(-height, 0.0),
                "speed": random.uniform(2.0, 4.0),
            }
            for index in range(COLUMN_COUNT)
        ]

    def drawRect_(self, dirty_rect: Any) -> None:
        bounds = self.bounds()
        _rgba(FADE_BLACK).setFill()
        NSRectFill(bounds)

        height = bounds.size.height
        for column in self.columns:
            column["y"] = float(column["y"]) + float(column["speed"])
            if float(column["y"]) > height + (TRAIL_LENGTH * 14.0):
                column["y"] = random.uniform(-120.0, 0.0)
                column["speed"] = random.uniform(2.0, 4.0)

            head_y = float(column["y"])
            for trail_index in range(TRAIL_LENGTH + 1):
                alpha = 1.0 if trail_index == 0 else max(0.05, 0.8 - (trail_index * 0.075))
                color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    MATRIX_GREEN[0],
                    MATRIX_GREEN[1],
                    MATRIX_GREEN[2],
                    alpha,
                )
                attrs = {
                    NSFontAttributeName: self.glyph_font,
                    NSForegroundColorAttributeName: color,
                }
                char_y = head_y - (trail_index * 14.0)
                NSString.stringWithString_(random.choice(CHARACTER_POOL)).drawAtPoint_withAttributes_(
                    NSMakePoint(float(column["x"]), char_y),
                    attrs,
                )


class MatrixOverlayView(NSView):
    def isFlipped(self) -> bool:
        return True


class MatrixContentView(NSView):
    delegate = objc.ivar()
    rain_view = objc.ivar()
    content_layer = objc.ivar()
    claude_header = objc.ivar()
    codex_header = objc.ivar()
    claude_session = objc.ivar()
    claude_weekly = objc.ivar()
    codex_session = objc.ivar()
    codex_weekly = objc.ivar()
    rate_label = objc.ivar()
    status_label = objc.ivar()
    today_label = objc.ivar()
    switch_button = objc.ivar()
    install_hook_button = objc.ivar()
    refresh_button = objc.ivar()
    quit_button = objc.ivar()
    show_install_button = objc.ivar()

    def initWithFrame_delegate_(self, frame: Any, delegate: Any) -> MatrixContentView:
        self = objc.super(MatrixContentView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.delegate = delegate
        self.show_install_button = False
        text = _rgba(MATRIX_GREEN)
        muted = _rgba(MUTED_GREEN)
        track = _rgba(TRACK_COLOR)

        self.rain_view = MatrixRainView.alloc().initWithFrame_(self.bounds())
        self.content_layer = MatrixOverlayView.alloc().initWithFrame_(self.bounds())
        self.content_layer.setAutoresizingMask_(18)

        self.claude_header = _matrix_label("[ CLAUDE_CODE ]", 15.0, text)
        self.codex_header = _matrix_label("[ CODEX ]", 15.0, text)
        self.claude_session = PanelQuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.claude_weekly = PanelQuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.codex_session = PanelQuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        self.codex_weekly = PanelQuotaRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 56))
        for row in (
            self.claude_session,
            self.claude_weekly,
            self.codex_session,
            self.codex_weekly,
        ):
            row.setTextColor_mutedTextColor_trackColor_(text, muted, track)

        self.rate_label = _matrix_label("RATE: --", 13.0, muted)
        self.status_label = _matrix_label("STATUS: LOADING", 13.0, muted)
        self.today_label = _matrix_label("TODAY: $0.00 (0 tokens)", 15.0, text)
        self.today_label.setAllowsDefaultTighteningForTruncation_(True)

        self.switch_button = MatrixTerminalButton.alloc().initWithFrame_title_target_action_(
            NSMakeRect(0, 0, SWITCH_BUTTON_WIDTH, SWITCH_BUTTON_HEIGHT),
            "[ SWITCH ]",
            delegate,
            "switchPanel:",
        )
        self.install_hook_button = MatrixTerminalButton.alloc().initWithFrame_title_target_action_(
            NSMakeRect(0, 0, 1, BUTTON_HEIGHT),
            "[ INSTALL HOOK ]",
            delegate,
            "installHook:",
        )
        self.install_hook_button.setHidden_(True)
        self.refresh_button = MatrixTerminalButton.alloc().initWithFrame_title_target_action_(
            NSMakeRect(0, 0, 1, BUTTON_HEIGHT),
            "[ REFRESH ]",
            delegate,
            "refreshNow:",
        )
        self.quit_button = MatrixTerminalButton.alloc().initWithFrame_title_target_action_(
            NSMakeRect(0, 0, 1, BUTTON_HEIGHT),
            "[ EXIT ]",
            delegate,
            "quitApp:",
        )

        self.addSubview_(self.rain_view)
        self.addSubview_(self.content_layer)
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
            self.switch_button,
            self.install_hook_button,
            self.refresh_button,
            self.quit_button,
        ):
            self.content_layer.addSubview_(view)
        return self

    def isFlipped(self) -> bool:
        return True

    def layout(self) -> None:
        width = self.bounds().size.width
        self.rain_view.setFrame_(self.bounds())
        self.content_layer.setFrame_(self.bounds())
        content_width = width - (PADDING * 2)
        card_content_width = content_width - (CARD_SIDE_INSET * 2)
        claude_y = PADDING
        codex_y = claude_y + CARD_HEIGHT + SECTION_GAP
        footer_y = codex_y + CARD_HEIGHT + FOOTER_GAP
        text_x = PADDING + CARD_SIDE_INSET

        switch_x = PADDING + content_width - CARD_SIDE_INSET - SWITCH_BUTTON_WIDTH
        switch_y = claude_y + 18 + (36 - SWITCH_BUTTON_HEIGHT) / 2
        self.switch_button.setFrame_(
            NSMakeRect(switch_x, switch_y, SWITCH_BUTTON_WIDTH, SWITCH_BUTTON_HEIGHT),
        )
        header_text_width = switch_x - text_x - SWITCH_BUTTON_GAP
        self.claude_header.setFrame_(
            NSMakeRect(text_x, claude_y + CARD_HEADER_TOP + 1, header_text_width, 22),
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

        self.codex_header.setFrame_(
            NSMakeRect(text_x, codex_y + CARD_HEADER_TOP + 1, card_content_width, 22),
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
        _rgba(OPAQUE_BLACK).setFill()
        NSRectFill(self.bounds())

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
            _rgba(CARD_FILL).setFill()
            fill_rounded_rect(card_rect, CARD_RADIUS)
            _rgba(CARD_BORDER).setStroke()
            stroke_rounded_rect(card_rect, CARD_RADIUS, 1.0)

        _rgba((0.0, 0.85, 0.35, 0.22)).setFill()
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
        text = _rgba(MATRIX_GREEN)
        muted = _rgba(MUTED_GREEN)
        track = _rgba(TRACK_COLOR)
        for row_view, row_state in (
            (self.claude_session, state.claude_session),
            (self.claude_weekly, state.claude_weekly),
            (self.codex_session, state.codex_session),
            (self.codex_weekly, state.codex_weekly),
        ):
            row_view.setTextColor_mutedTextColor_trackColor_(text, muted, track)
            row_view.setRowState_(row_state)

        self.rate_label.setStringValue_(f"RATE: {_suffix(state.rate_text)}")
        self.status_label.setStringValue_(f"STATUS: {_suffix(state.status_text)}")
        self.today_label.setStringValue_(f"TODAY: {_suffix(state.today_text)}")
        self.show_install_button = state.show_install_button
        self.install_hook_button.setHidden_(not state.show_install_button)
        self.rate_label.setTextColor_(muted)
        self.status_label.setTextColor_(muted)
        self.today_label.setTextColor_(text)
        self.setNeedsLayout_(True)
        self.setNeedsDisplay_(True)


class MatrixPanel:
    id = "matrix"
    display_name = "駭客任務"

    def build_view(self, delegate: Any) -> NSView:
        width, height = self.preferred_size()
        return MatrixContentView.alloc().initWithFrame_delegate_(
            NSMakeRect(0, 0, width, height),
            delegate,
        )

    def apply_state(self, view: NSView, state: PopoverState) -> None:
        view.setState_(state)

    def preferred_size(self) -> tuple[float, float]:
        return (POPOVER_WIDTH, CONTENT_HEIGHT)
