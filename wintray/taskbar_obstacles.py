# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Read taskbar button bounds off the UI thread to avoid covering applications."""

from __future__ import annotations

import importlib
import logging
import threading
from pathlib import Path

from wintray.taskbar_overlay import Rect

logger = logging.getLogger(__name__)


class TaskbarObstacles:
    def __init__(self) -> None:
        self.hwnd = 0
        self.snapshot: tuple[int, tuple[Rect, ...]] = (0, ())
        self._stop = threading.Event()
        threading.Thread(target=self._watch, name="usage-taskbar-layout", daemon=True).start()

    def _watch(self) -> None:
        try:
            clr = importlib.import_module("clr")
            runtime = importlib.import_module("System.Runtime.InteropServices")
            framework = Path(runtime.RuntimeEnvironment.GetRuntimeDirectory())
            for assembly in ("UIAutomationTypes", "UIAutomationClient"):
                clr.AddReference(str(framework / "WPF" / (assembly + ".dll")))
            automation = importlib.import_module("System.Windows.Automation")
            system = importlib.import_module("System")
            element = automation.AutomationElement
            condition = automation.OrCondition(
                automation.PropertyCondition(
                    element.ControlTypeProperty, automation.ControlType.Button
                ),
                automation.PropertyCondition(
                    element.ControlTypeProperty, automation.ControlType.ListItem
                ),
            )
            while not self._stop.is_set():
                hwnd = self.hwnd
                if hwnd:
                    try:
                        root = element.FromHandle(system.IntPtr(hwnd))
                        buttons = root.FindAll(automation.TreeScope.Descendants, condition)
                        rects: list[Rect] = []
                        for button in buttons:
                            current = button.Current
                            bounds = current.BoundingRectangle
                            if not current.IsOffscreen and not bounds.IsEmpty:
                                rects.append(
                                    (
                                        round(bounds.Left),
                                        round(bounds.Top),
                                        round(bounds.Right),
                                        round(bounds.Bottom),
                                    )
                                )
                        self.snapshot = (hwnd, tuple(rects))
                    except Exception:
                        # Explorer may be rebuilding its accessibility tree.
                        self.snapshot = (0, ())
                self._stop.wait(2)
        except Exception:
            logger.warning("Taskbar button bounds unavailable", exc_info=True)

    def close(self) -> None:
        self._stop.set()
