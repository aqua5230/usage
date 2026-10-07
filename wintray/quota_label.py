# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""A transparent quota label anchored inside the Windows taskbar."""

from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from usage_common.prefs import _load_preferences
from wintray.taskbar_menu import request_tray_menu as request_tray_menu
from wintray.taskbar_obstacles import TaskbarObstacles
from wintray.taskbar_overlay import TaskbarOverlay, label_position

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)


def label_enabled() -> bool:
    return _load_preferences().get("quota_label_enabled") is True


def taskbar_text_color(used_percent: float | None, light: bool) -> tuple[int, int, int, int]:
    remaining = 100 - used_percent if used_percent is not None else 100
    if remaining <= 20:
        return (180, 25, 25, 255) if light else (255, 105, 97, 255)
    if remaining <= 50:
        return (133, 82, 0, 255) if light else (255, 196, 57, 255)
    return (32, 33, 36, 255) if light else (242, 242, 242, 255)


def _light_taskbar() -> bool:
    try:
        winreg = importlib.import_module("winreg")
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return bool(winreg.QueryValueEx(key, "SystemUsesLightTheme")[0])
    except OSError:
        return False


def draw_label(text: str, color: tuple[int, int, int, int], scale: float = 1.0) -> Image:
    from PIL import Image, ImageDraw, ImageFont

    font_size = max(1, round(10 * 96 / 72 * scale))  # 10 pt, scaled to physical pixels.
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype(
            str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"), font_size
        )
    except OSError:
        font = ImageFont.load_default(size=font_size)
    bounds = font.getbbox(text)
    padding = round(6 * scale)
    height = max(round(32 * scale), round(bounds[3] - bounds[1]) + padding * 2)
    width = round(bounds[2] - bounds[0]) + padding * 2
    # Alpha 1 makes the whole label clickable, like the reference WPF surface.
    image = Image.new("RGBA", (width, height), (0, 0, 0, 1))
    ImageDraw.Draw(image).text(
        (padding - bounds[0], (height - bounds[3] + bounds[1]) // 2 - bounds[1]),
        text,
        font=font,
        fill=color,
    )
    return image


class TaskbarQuotaLabel:
    """Construct/update on the UI thread; close may be called from the tray thread."""

    def __init__(self, open_panel: Callable[[], None], open_menu: Callable[[], None]) -> None:
        self.forms = importlib.import_module("System.Windows.Forms")
        self.system = importlib.import_module("System")
        self.form = self.forms.Form()
        self.form.Text = "usage"
        self.form.FormBorderStyle = getattr(self.forms.FormBorderStyle, "None")
        self.form.ShowInTaskbar = False
        self.form.TopMost = True
        self.form.StartPosition = self.forms.FormStartPosition.Manual
        self.form.Cursor = self.forms.Cursors.Hand
        self._open_panel = open_panel
        self._open_menu = open_menu
        self._action_lock = threading.Lock()
        self._closed = threading.Event()
        self.form.MouseClick += self._on_click
        self.tooltip = self.forms.ToolTip()
        self.native = TaskbarOverlay()
        self.hwnd = int(self.form.Handle.ToInt64())
        self.obstacles = TaskbarObstacles()
        self._last: tuple[str, tuple[int, int, int, int], float] | None = None
        self._image: Image | None = None
        self._text = ""
        self._used: float | None = None
        self.timer = self.forms.Timer()
        self.timer.Interval = 500
        self.timer.Tick += self._tick
        self.timer.Start()

    def _on_click(self, _sender: Any, event: Any) -> None:
        if self._closed.is_set():
            return
        if event.Button == self.forms.MouseButtons.Right:
            try:
                self._open_menu()
            except Exception:
                logger.exception("Unable to open the menu from the taskbar label")
            return
        if event.Button != self.forms.MouseButtons.Left:
            return
        if not self._action_lock.acquire(blocking=False):
            return
        # show_panel evaluates WebView JavaScript synchronously. Its completion
        # runs on this UI thread, so waiting here would deadlock the message loop.
        threading.Thread(
            target=self._run_panel_action, name="usage-label-click", daemon=True
        ).start()

    def _run_panel_action(self) -> None:
        try:
            if not self._closed.is_set():
                self._open_panel()
        except Exception:
            logger.exception("Unable to open the panel from the taskbar label")
        finally:
            self._action_lock.release()

    def update(self, text: str, used_percent: float | None, tooltip: str) -> None:
        self._text, self._used = text, used_percent
        self.tooltip.SetToolTip(self.form, tooltip)
        self.form.Text = "usage — " + text
        self._tick()

    def _tick(self, _sender: Any = None, _event: Any = None) -> None:
        if self.form.IsDisposed or not self._text:
            return
        try:
            self._refresh()
        except Exception:
            self.native.hide(self.hwnd)
            logger.exception("Taskbar quota label refresh failed")

    def _refresh(self) -> None:
        layout = self.native.layout()
        if layout is None or not layout.visible or self.native.fullscreen(layout):
            self.native.hide(self.hwnd)
            return
        self.obstacles.hwnd = layout.hwnd
        owner, occupied = self.obstacles.snapshot
        # Wait for a current taskbar snapshot before covering any shell surface.
        if owner != layout.hwnd:
            occupied = (layout.rect,)
        # Read shell widgets on every tick, including after Explorer recreates
        # the taskbar or the user toggles News and interests.
        occupied += self.native.widget_rects(layout.hwnd)
        signature = (self._text, taskbar_text_color(self._used, _light_taskbar()), layout.scale)
        changed = signature != self._last
        if changed:
            self._image = draw_label(*signature)
        assert self._image is not None
        position = label_position(
            layout.rect,
            layout.tray,
            layout.work,
            self._image.size,
            occupied,
            round(4 * layout.scale),
        )
        self.native.configure(self.hwnd, layout.hwnd)
        if changed:
            self.native.paint(self.hwnd, self._image, position)
            self._last = signature
        self.native.show(self.hwnd, position, self._image.size)

    def close(self) -> None:
        self._closed.set()
        if self.form.InvokeRequired:
            self.form.Invoke(self.system.Action(self.close))
            return
        self.timer.Stop()
        self.timer.Dispose()
        self.obstacles.close()
        self.tooltip.Dispose()
        if not self.form.IsDisposed:
            self.form.Close()
