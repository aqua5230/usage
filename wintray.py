# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import tomllib
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import codex_loader
import menubar_agy
import menubar_state
import update_checker
import win_login_item
from burn_rate import BurnRateTracker
from history_loader import UsageEntry, load_entries
from i18n import _t
from menubar_prefs import (
    _hide_agy_enabled,
    _hide_claude_enabled,
    _hide_codex_enabled,
    _quota_card_order,
    _quota_notification_thresholds,
    _quota_notifications_enabled,
)
from panels.payload import _load_panel_html, _state_payload
from prefs import _load_preferences, _save_preferences
from pricing import calculate_cost
from statusline_settings import _statusline_enabled, _toggle_statusline_settings
from usage_client import ClaudeUsageClient, PollState
from usage_lang import detect_lang
from usage_notifications import NotificationEvent, QuotaNotifier
from usage_rate import UsageRateTracker

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)

SLOW_POLL_INTERVAL_S = 300
HISTORY_SCAN_CACHE_SECONDS = 30.0
PANEL_WIDTH = 380
WINDOWS_PANELS = (
    ("classic", "panel_default_name", "classic.html"),
    ("matrix", "panel_matrix", "matrix.html"),
    ("win95", "panel_win95", "win95.html"),
    ("newspaper", "panel_newspaper", "newspaper.html"),
    ("cloud_observation", "panel_cloud_observation", "cloud_observation.html"),
    ("aquarium", "panel_aquarium", "aquarium.html"),
    ("prism_arcade", "panel_prism_arcade", "prism_arcade.html"),
    ("black_hole", "panel_black_hole", "black_hole.html"),
    ("lepidoptera", "panel_lepidoptera", "lepidoptera.html"),
    ("world_cup", "panel_world_cup", "world_cup.html"),
)
PANEL_HEIGHTS = {
    "classic": 1004,
    "matrix": 1070,
    "win95": 1079,
    "newspaper": 1073,
    "cloud_observation": 1023,
    "aquarium": 1023,
    "prism_arcade": 1023,
    "black_hole": 1023,
    "lepidoptera": 1070,
    "world_cup": 812,
}

JS_SHIM = """
<script>
window.webkit = window.webkit || {};
window.webkit.messageHandlers = window.webkit.messageHandlers || {};
window.webkit.messageHandlers.usage = {
  postMessage: function(message) { return window.pywebview.api.postMessage(message); }
};

// The panel assets are shared with macOS.  On Windows, intercept their
// built-in switch button and provide the equivalent of the native menu here.
(function() {
  var menuRoot;

  function closeMenu() {
    if (menuRoot) {
      menuRoot.remove();
      menuRoot = null;
    }
  }

  function post(action, extra) {
    var message = Object.assign({ action: action }, extra || {});
    return Promise.resolve(
      window.webkit.messageHandlers.usage.postMessage(JSON.stringify(message))
    );
  }

  function menuItem(item) {
    if (item.type === 'separator') {
      var separator = document.createElement('div');
      separator.className = 'usage-panel-menu-separator';
      separator.setAttribute('role', 'separator');
      return separator;
    }
    if (item.children) {
      var group = document.createElement('div');
      group.className = 'usage-panel-menu-accordion';
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'usage-panel-menu-item usage-panel-menu-parent';
      row.setAttribute('role', 'menuitem');
      row.setAttribute('aria-expanded', 'false');
      row.textContent = item.label + '  ›';
      var submenu = document.createElement('div');
      submenu.className = 'usage-panel-menu-submenu';
      submenu.setAttribute('role', 'menu');
      item.children.forEach(function(child) { submenu.appendChild(menuItem(child)); });
      row.addEventListener('click', function() {
        var expanded = row.getAttribute('aria-expanded') === 'true';
        row.setAttribute('aria-expanded', String(!expanded));
        row.textContent = item.label + (!expanded ? '  ˅' : '  ›');
        submenu.hidden = expanded;
      });
      submenu.hidden = true;
      group.appendChild(row);
      group.appendChild(submenu);
      return group;
    }
    var row = document.createElement('button');
    row.type = 'button';
    row.className = 'usage-panel-menu-item';
    row.setAttribute('role', 'menuitemcheckbox');
    row.textContent = (item.checked ? '✓  ' : '    ') + item.label;
    row.addEventListener('click', function() {
      var extra = item.panelId ? { panel_id: item.panelId } :
        item.preferenceKey ? { preference_key: item.preferenceKey } : undefined;
      post(item.action, extra);
      closeMenu();
    });
    return row;
  }

  function showMenu(items) {
    closeMenu();
    menuRoot = document.createElement('div');
    menuRoot.className = 'usage-panel-menu-backdrop';
    menuRoot.setAttribute('aria-hidden', 'false');
    var menu = document.createElement('div');
    menu.className = 'usage-panel-menu';
    menu.setAttribute('role', 'menu');
    items.forEach(function(item) { menu.appendChild(menuItem(item)); });
    menuRoot.appendChild(menu);
    menuRoot.addEventListener('click', function(event) {
      if (event.target === menuRoot) closeMenu();
    });
    document.body.appendChild(menuRoot);
  }

  document.addEventListener('click', function(event) {
    var button = event.target.closest && event.target.closest('[data-action="switch"]');
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    post('open_menu').then(function(items) {
      if (Array.isArray(items)) showMenu(items);
    });
  }, true);
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') closeMenu();
  });
})();

// Panel assets register their card reorder handler in the bubbling phase. This
// earlier capture listener turns their empty card area into a native drag
// region without changing the shared macOS HTML.  Add the class only after
// excluding controls, so pywebview never treats a button click as a window drag.
document.addEventListener('pointerdown', function(event) {
  var target = event.target;
  var card = target && target.closest && target.closest(
    '[data-card="claude"], [data-card="codex"], [data-card="agy"]'
  );
  var interactive = target && target.closest && target.closest(
    'button, a, input, select, textarea, label, summary, [contenteditable], '
    + '[role="button"], .codex-stale-info, .stale-info'
  );
  if (!card || event.button !== 0 || interactive) return;
  card.classList.add('pywebview-drag-region', 'usage-card-window-dragging');
  var clearDragRegion = function() {
    card.classList.remove('pywebview-drag-region', 'usage-card-window-dragging');
    document.removeEventListener('pointerup', clearDragRegion, true);
    document.removeEventListener('pointercancel', clearDragRegion, true);
  };
  document.addEventListener('pointerup', clearDragRegion, true);
  document.addEventListener('pointercancel', clearDragRegion, true);
  event.stopImmediatePropagation();
}, true);

// Keep the native drag target deliberately small so it remains distinct from
// normal panel interaction.
document.addEventListener('DOMContentLoaded', function() {
  var handle = document.createElement('div');
  handle.className = 'usage-window-drag-handle pywebview-drag-region';
  handle.setAttribute('aria-hidden', 'true');
  document.body.appendChild(handle);
});
</script>
<style>
.usage-window-drag-handle {
  position: fixed;
  top: 4px;
  left: 50%;
  z-index: 2147483647;
  width: 56px;
  height: 7px;
  margin-left: -28px;
  border-radius: 99px;
  background: rgba(127, 127, 127, .28);
  cursor: grab;
  opacity: .35;
  transition: opacity .15s ease, background .15s ease;
}
.usage-window-drag-handle:hover {
  background: rgba(127, 127, 127, .65);
  opacity: 1;
}
.usage-window-drag-handle:active,
.usage-card-window-dragging {
  cursor: grabbing;
}
.usage-panel-menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 2147483646;
  background: rgba(0, 0, 0, .12);
}
.usage-panel-menu {
  position: absolute;
  top: 36px;
  right: 12px;
  min-width: 220px;
  max-height: 80vh;
  overflow-y: auto;
  padding: 6px;
  border: 1px solid rgba(127, 127, 127, .55);
  border-radius: 9px;
  background: rgba(30, 32, 36, .96);
  color: #f5f5f5;
  box-shadow: 0 12px 32px rgba(0, 0, 0, .32);
  font: 13px/1.3 system-ui, sans-serif;
}
.usage-panel-menu-item {
  position: relative;
  display: block;
  width: 100%;
  padding: 7px 10px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: inherit;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
}
.usage-panel-menu-item:hover, .usage-panel-menu-item:focus {
  background: rgba(120, 160, 255, .32);
  outline: none;
}
.usage-panel-menu-accordion { display: block; }
.usage-panel-menu-submenu {
  padding-left: 16px;
}
.usage-panel-menu-submenu[hidden] {
  display: none;
}
.usage-panel-menu-separator { height: 1px; margin: 5px 4px; background: rgba(180, 180, 180, .35); }
</style>
""".strip()


def _winreg() -> Any:
    import winreg

    return winreg


def _system_background_color() -> str:
    try:
        winreg = _winreg()
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _value_type = winreg.QueryValueEx(key, "AppsUseLightTheme")
        if value == 0:
            return "#080d12"
    except Exception:
        pass
    return "#eef2f7"


def available_panels() -> tuple[tuple[str, str, str], ...]:
    """Windows excludes talent_market because its vendored CLI is macOS-only."""
    return tuple(panel for panel in WINDOWS_PANELS if panel[0] != "talent_market")


def tray_icon_style(used_percent: float | None) -> tuple[str, tuple[int, int, int, int]]:
    if used_percent is None:
        return ("--", (110, 118, 129, 255))
    remaining = max(0, min(100, round(100.0 - used_percent)))
    if remaining <= 20:
        color = (255, 69, 58, 255)
    elif remaining <= 50:
        color = (255, 196, 57, 255)
    else:
        color = (244, 145, 100, 255)
    return (str(remaining), color)


def build_tooltip(state: menubar_state.PopoverState) -> str:
    def line(name: str, row: menubar_state.QuotaRowState) -> str:
        remaining = "--" if row.percent is None else str(max(0, round(100 - row.percent)))
        return f"{name} {row.title}: {remaining}%"

    return "\n".join(
        (
            line("Claude", state.claude_session),
            line("Claude", state.claude_weekly),
            f"{line('Codex', state.codex_session)} · "
            f"{line('Codex', state.codex_weekly).removeprefix('Codex ')}",
        )
    )


def draw_tray_icon(used_percent: float | None) -> Image:
    from PIL import Image, ImageDraw, ImageFont

    text, color = tray_icon_style(used_percent)
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill=color)
    font = ImageFont.load_default(size=24)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((64 - (box[2] - box[0])) / 2, (64 - (box[3] - box[1])) / 2 - box[1]),
        text,
        font=font,
        fill=(10, 15, 20, 255),
    )
    return image


def panel_html(filename: str) -> str:
    html = _load_panel_html(filename)
    marker = "<head>"
    return html.replace(marker, f"{marker}\n{JS_SHIM}", 1)


def _active_panel_id() -> str:
    panel_ids = {panel[0] for panel in available_panels()}
    value = _load_preferences().get("usage.activePanelId", "classic")
    return str(value) if value in panel_ids else "classic"


def _save_active_panel_id(panel_id: str) -> None:
    preferences = _load_preferences()
    preferences["usage.activePanelId"] = panel_id
    _save_preferences(preferences)


def _current_version() -> str:
    try:
        return metadata.version("usage")
    except metadata.PackageNotFoundError:
        from i18n import packaged_resource_path

        pyproject = packaged_resource_path(
            "pyproject.toml", Path(__file__).with_name("pyproject.toml")
        )
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        value = data["project"]["version"]
        return str(value)


def _statusline_payload(language: str) -> dict[str, object]:
    return {
        "enabled": _statusline_enabled(),
        "enabledText": _t(language, "cli_enabled"),
        "disabledText": _t(language, "cli_disabled"),
    }


def _today_text(entries: list[UsageEntry], language: str) -> str:
    today = datetime.now().astimezone().date()
    selected = [entry for entry in entries if entry.timestamp.astimezone().date() == today]
    return _t(
        language,
        "today_text",
        cost=f"{sum(calculate_cost(entry) for entry in selected):.2f}",
        tokens=f"{sum(entry.total_tokens for entry in selected):,}",
    )


def _mock_projects() -> tuple[
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
]:
    return (
        [("usage", 11_200_000, 6.47), ("FinMind", 3_100_000, 1.82), ("AI客服", 800_000, 0.48)],
        [("usage", 78_400_000, 45.20), ("FinMind", 21_700_000, 12.74), ("AI客服", 5_600_000, 3.36)],
        [
            ("usage", 312_000_000, 180.50),
            ("FinMind", 86_400_000, 50.12),
            ("AI客服", 22_000_000, 13.20),
        ],
        [
            ("usage", 624_000_000, 361.00),
            ("FinMind", 172_800_000, 100.24),
            ("AI客服", 44_000_000, 26.40),
        ],
    )


@dataclass(slots=True)
class _RefreshData:
    entries: list[UsageEntry]
    history_error_key: str | None


class _JSApi:
    def __init__(self, controller: _WindowsTrayController) -> None:
        # Underscore-private: pywebview serializes every public attribute of a
        # js_api object into the JS bridge, and walking the controller (and its
        # WinForms window graph) recurses forever.
        self._controller = controller

    def postMessage(  # noqa: N802 - JavaScript contract
        self, message: object
    ) -> list[dict[str, object]] | None:
        return self._controller.handle_panel_message(message)


class _WindowsTrayController:
    def __init__(self, mock: bool, interval: int) -> None:
        self.mock = mock
        self.interval = max(30, interval)
        self.language = detect_lang()
        self.active_panel_id = _active_panel_id()
        self._switch_pending: bool = False
        self.latest_state = self._empty_state()
        self.tracker = UsageRateTracker(mock=mock)
        self.burn_rate_trackers = {
            "claude_session": BurnRateTracker(),
            "claude_weekly": BurnRateTracker(),
            "codex_session": BurnRateTracker(),
            "codex_weekly": BurnRateTracker(),
        }
        self.icon: Any = None
        self.window: Any = None
        self.visible = False
        self._positioned_this_show = False
        self.stopping = threading.Event()
        self.refresh_lock = threading.Lock()
        self._quota_notifier = QuotaNotifier(_quota_notification_thresholds())
        self.usage_client = ClaudeUsageClient(mock=mock)
        self._last_tray_percent: float | None = None
        self._last_tray_tooltip: str | None = None
        self._last_injected_state: str | None = None
        self._history_fingerprint: tuple[tuple[str, int, float], ...] | None = None
        self._cached_history: _RefreshData | None = None
        self._cached_projects: tuple[list[tuple[str, int, float | None]], ...] | None = None
        self._history_scan: menubar_state.HistorySourceScan | None = None
        self._history_scan_at: float | None = None

    def _empty_state(self) -> menubar_state.PopoverState:
        missing = menubar_state._missing_row
        return menubar_state.PopoverState(
            language=self.language,
            claude_session=missing(
                _t(self.language, "session_label"), menubar_state.CLAUDE_COLOR, self.language
            ),
            claude_weekly=missing(
                _t(self.language, "weekly_label"), menubar_state.CLAUDE_COLOR, self.language
            ),
            codex_session=missing(
                _t(self.language, "session_label"), menubar_state.CODEX_COLOR, self.language
            ),
            codex_weekly=missing(
                _t(self.language, "weekly_label"), menubar_state.CODEX_COLOR, self.language
            ),
            agy_session=missing(
                _t(self.language, "session_label"), menubar_state.AGY_COLOR, self.language
            ),
            agy_weekly=missing(
                _t(self.language, "weekly_label"), menubar_state.AGY_COLOR, self.language
            ),
            agy_group_name="",
            projects=[],
            projects_7d=[],
            projects_30d=[],
            projects_all=[],
            rate_text=_t(self.language, "rate_text", value="--"),
            status_text=_t(self.language, "status_text", value=_t(self.language, "status_loading")),
            today_text=_t(self.language, "today_text", cost="0.00", tokens="0"),
            statusline=_statusline_payload(self.language),
            hide_claude=_hide_claude_enabled(),
            hide_codex=_hide_codex_enabled(),
            hide_agy=_hide_agy_enabled(),
            card_order=_quota_card_order(),
        )

    def panel_filename(self) -> str:
        return next(item[2] for item in available_panels() if item[0] == self.active_panel_id)

    def panel_height(self) -> int:
        return PANEL_HEIGHTS[self.active_panel_id]

    def attach(self, icon: Any, window: Any) -> None:
        self.icon = icon
        self.window = window
        self._update_tray()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.refresh()

    def on_loaded(self) -> None:
        # pywebview's resize()/move() call SetWindowPos with SWP_SHOWWINDOW,
        # so placing the window while it is hidden would drag the bare panel
        # onto the screen. Placement happens in show_panel() instead; here it
        # only re-applies after a visible panel switch reloads the document.
        if self.visible:
            self._place_window()
            self.inject_state(force=True)

    def _working_area(self) -> tuple[int, int, int, int] | None:
        """Return the primary monitor work area (without taskbar)."""
        if os.name != "nt":
            return None
        import ctypes

        class Rect(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = Rect()
        library_name = "windll"
        user32: Any = getattr(ctypes, library_name).user32
        if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return (rect.left, rect.top, rect.right, rect.bottom)
        return None

    def _saved_window_position(self) -> tuple[int, int] | None:
        value = _load_preferences().get("usage.windowPosition")
        if not isinstance(value, dict):
            return None
        x, y = value.get("x"), value.get("y")
        if isinstance(x, bool) or isinstance(y, bool):
            return None
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        return (int(x), int(y))

    def _current_window_position(self) -> tuple[int, int] | None:
        if self.window is None:
            return None
        try:
            x, y = self.window.x, self.window.y
        except (AttributeError, TypeError, ValueError):
            return None
        if isinstance(x, bool) or isinstance(y, bool):
            return None
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        return (int(x), int(y))

    @staticmethod
    def _clamp_window_position(
        position: tuple[int, int], work_area: tuple[int, int, int, int], height: int
    ) -> tuple[int, int]:
        left, top, right, bottom = work_area
        return (
            min(max(position[0], left + 12), max(left + 12, right - PANEL_WIDTH - 12)),
            min(max(position[1], top + 12), max(top + 12, bottom - height - 12)),
        )

    @staticmethod
    def _default_window_position(
        work_area: tuple[int, int, int, int], height: int
    ) -> tuple[int, int]:
        left, top, right, bottom = work_area
        return (max(left + 12, right - PANEL_WIDTH - 12), max(top + 12, bottom - height - 12))

    def _place_window(self, *, force_default: bool = False) -> None:
        if self.window is None:
            return
        work_area = self._working_area()
        if work_area is None:
            return
        left, top, right, bottom = work_area
        height = min(self.panel_height(), max(640, bottom - top - 24))
        self.window.resize(PANEL_WIDTH, height)
        if force_default:
            position = self._default_window_position(work_area, height)
        elif self._positioned_this_show:
            current_position = self._current_window_position()
            position = (
                current_position
                or self._saved_window_position()
                or self._default_window_position(work_area, height)
            )
        else:
            position = self._saved_window_position() or self._default_window_position(
                work_area, height
            )
        self.window.move(*self._clamp_window_position(position, work_area, height))
        self._positioned_this_show = True

    def _save_window_position(self) -> None:
        position = self._current_window_position()
        if position is None:
            return
        preferences = _load_preferences()
        preferences["usage.windowPosition"] = {"x": position[0], "y": position[1]}
        _save_preferences(preferences)

    def reset_panel_position(self, _icon: Any = None, _item: Any = None) -> None:
        preferences = _load_preferences()
        preferences.pop("usage.windowPosition", None)
        _save_preferences(preferences)
        if self.visible:
            self._place_window(force_default=True)

    def _poll_loop(self) -> None:
        while not self.stopping.wait(
            self.interval if self.visible else max(self.interval, SLOW_POLL_INTERVAL_S)
        ):
            self.refresh()

    def refresh(self) -> None:
        if not self.refresh_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        debug_timing = os.environ.get("USAGE_DEBUG") == "1"

        def measure(stage: str, started_at: float) -> None:
            if debug_timing:
                elapsed_ms = (time.monotonic() - started_at) * 1000
                logger.debug("refresh_timing stage=%s elapsed_ms=%.1f", stage, elapsed_ms)

        try:
            self.latest_state = self._build_state(measure=measure, debug_timing=debug_timing)
            self._process_quota_notifications(self.latest_state)
            started_at = time.monotonic() if debug_timing else 0.0
            self._update_tray()
            measure("update_tray", started_at)
            if self.visible:
                started_at = time.monotonic() if debug_timing else 0.0
                self.inject_state()
                measure("inject_state", started_at)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows tray refresh failed", exc_info=True)
        finally:
            self.refresh_lock.release()

    def _load_entries(self, scan: menubar_state.HistorySourceScan) -> _RefreshData:
        if self.mock:
            return _RefreshData([], None)
        entries: list[UsageEntry] = []
        error_key = None
        try:
            entries.extend(load_entries(hours_back=0, jsonl_paths=scan.claude_paths))
        except OSError:
            error_key = "history_load_error_file"
        except (ValueError, KeyError, TypeError):
            error_key = "history_load_error_parse"
        try:
            entries.extend(codex_loader.load_entries(hours_back=0, jsonl_paths=scan.codex_paths))
        except OSError:
            error_key = "history_load_error_file"
        except (ValueError, KeyError, TypeError):
            error_key = "history_load_error_parse"
        return _RefreshData(entries, error_key)

    def _history_source_scan(self) -> menubar_state.HistorySourceScan:
        """Avoid recursively statting every session JSONL on each tray tick."""
        now = time.monotonic()
        if (
            self._history_scan is not None
            and self._history_scan_at is not None
            and now - self._history_scan_at < HISTORY_SCAN_CACHE_SECONDS
        ):
            return self._history_scan
        self._history_scan = menubar_state.history_source_scan()
        self._history_scan_at = now
        return self._history_scan

    def _build_state(
        self,
        *,
        measure: Any = lambda _stage, _started_at: None,
        debug_timing: bool = False,
    ) -> menubar_state.PopoverState:
        started_at = time.monotonic() if debug_timing else 0.0
        codex_rows, _codex_pct, _model, codex_stale, codex_credits = menubar_state.codex_rows(
            mock=self.mock,
            language=self.language,
            burn_rate_trackers=self.burn_rate_trackers,
        )
        measure("codex_load", started_at)
        started_at = time.monotonic() if debug_timing else 0.0
        agy_result = menubar_agy.load_refresh_result(self.language)
        agy = agy_result.projection or menubar_agy.fallback_projection(self.language)
        measure("agy_load", started_at)
        started_at = time.monotonic() if debug_timing else 0.0
        scan = self._history_source_scan()
        if menubar_state.history_cache_needs_reload(
            self._history_fingerprint,
            scan.fingerprint,
            has_cached_result=(
                self._cached_history is not None and self._cached_projects is not None
            ),
        ):
            self._cached_history = self._load_entries(scan)
            self._cached_projects = (
                _mock_projects()
                if self.mock
                else menubar_state.project_rows_for_windows(self._cached_history.entries)
            )
            # A load error may be transient (e.g. a file locked mid-write); keep the
            # fingerprint unset so the next poll retries instead of pinning the error.
            self._history_fingerprint = (
                scan.fingerprint if self._cached_history.history_error_key is None else None
            )
        history = self._cached_history
        projects = self._cached_projects
        assert history is not None and projects is not None
        measure("history_load", started_at)
        started_at = time.monotonic() if debug_timing else 0.0
        outcome = asyncio.run(self._fetch())
        measure("fetch", started_at)
        return menubar_state.build_popover_state(
            outcome=outcome,
            codex_rows=codex_rows,
            agy_rows=(agy.session, agy.weekly),
            agy_group_name=agy.group_name,
            projects=projects[0],
            projects_7d=projects[1],
            projects_30d=projects[2],
            projects_all=projects[3],
            language=self.language,
            group=self.tracker.group(),
            burn_rate_trackers=self.burn_rate_trackers,
            today_text=(
                _t(self.language, "today_text", cost="45.20", tokens="50,193,442")
                if self.mock
                else _today_text(history.entries, self.language)
            ),
            statusline=_statusline_payload(self.language),
            show_install_button=outcome.state == PollState.TOKEN_ERROR,
            hide_claude=_hide_claude_enabled(),
            hide_codex=_hide_codex_enabled(),
            hide_agy=agy_result.hide_agy or _hide_agy_enabled(),
            codex_stale=codex_stale,
            codex_credits=codex_credits,
            agy_stale=agy.stale,
            card_order=_quota_card_order(),
            history_error=menubar_state.history_load_error_state(
                history.history_error_key, self.language
            ),
        )

    async def _fetch(self) -> Any:
        return await self.usage_client.fetch_once()

    def _update_tray(self) -> None:
        if self.icon is None:
            return
        percent = self.latest_state.claude_session.percent
        tooltip = build_tooltip(self.latest_state)
        if percent == self._last_tray_percent and tooltip == self._last_tray_tooltip:
            return
        self.icon.icon = draw_tray_icon(percent)
        self.icon.title = tooltip
        self._last_tray_percent = percent
        self._last_tray_tooltip = tooltip

    def inject_state(self, *, force: bool = False) -> None:
        if self.window is None:
            return
        encoded = json.dumps(
            _state_payload(self.latest_state), ensure_ascii=False, separators=(",", ":")
        )
        if not force and encoded == self._last_injected_state:
            return
        self.window.evaluate_js(f"window.usageApplyState({encoded})")
        self._last_injected_state = encoded

    def show_panel(self, _icon: Any = None, _item: Any = None) -> None:
        if self.visible:
            self._save_window_position()
            self.visible = False
            self._positioned_this_show = False
            self.window.hide()
            return
        self.visible = True
        self._place_window()
        self.window.show()
        self.inject_state(force=True)
        self.refresh()

    def switch_panel(self, panel_id: str) -> None:
        self.active_panel_id = panel_id
        _save_active_panel_id(panel_id)
        # A panel reload is initialized from ``latest_state`` in ``on_loaded``.
        # Card order is changed directly by the JS bridge, outside the refresh
        # worker, so refresh this field from the shared preferences before the
        # next theme receives that state.
        self.latest_state.card_order = _quota_card_order()
        self.window.load_html(panel_html(self.panel_filename()))

    def _deferred_switch_panel(self, panel_id: str) -> None:
        self._switch_pending = False
        self.switch_panel(panel_id)

    def _schedule_panel_switch(self, panel_id: str) -> None:
        if self._switch_pending or panel_id not in {panel[0] for panel in available_panels()}:
            return
        self._switch_pending = True
        # postMessage is a pywebview promise. Reloading the document before
        # that promise resolves destroys its callback and can leave the Edge
        # WebView as a blank white window. Keep the existing short deferral,
        # but now reload the panel explicitly chosen from the HTML menu.
        threading.Timer(0.05, lambda: self._deferred_switch_panel(panel_id)).start()

    def _panel_menu_data(self) -> list[dict[str, object]]:
        """Return fresh, localized data for the HTML panel menu."""

        def item(key: str, action: str, **extra: object) -> dict[str, object]:
            return {
                "i18nKey": key,
                "label": _t(self.language, key),
                "action": action,
                **extra,
            }

        panels = [
            item(
                key,
                "switch_panel",
                panelId=panel_id,
                checked=self.active_panel_id == panel_id,
            )
            for panel_id, key, _filename in available_panels()
        ]
        hidden_sections = [
            item(
                "claude_name",
                "toggle_hide_section",
                preferenceKey="hide_claude_section",
                checked=_hide_claude_enabled(),
            ),
            item(
                "codex_name",
                "toggle_hide_section",
                preferenceKey="hide_codex_section",
                checked=_hide_codex_enabled(),
            ),
            item(
                "agy_name",
                "toggle_hide_section",
                preferenceKey="hide_agy_section",
                checked=_hide_agy_enabled(),
            ),
        ]
        return [
            item("panel_ai_daily", "open_ai_daily"),
            {"type": "separator"},
            item("switch_panel", "", children=panels),
            item("hide_sections_menu", "", children=hidden_sections),
            {"type": "separator"},
            item("launch_at_login", "toggle_login", checked=win_login_item.is_enabled()),
            item(
                "quota_notifications_menu",
                "toggle_quota_notifications",
                checked=_quota_notifications_enabled(),
            ),
            {"type": "separator"},
            item("project_butler", "toggle_session_resume", checked=_session_resume_enabled()),
            item("terse_mode_menu", "toggle_terse_mode", checked=_terse_mode_enabled()),
            {"type": "separator"},
            item("refresh_now", "refresh"),
        ]

    def toggle_login(self, _icon: Any = None, _item: Any = None) -> None:
        win_login_item.disable() if win_login_item.is_enabled() else win_login_item.enable()

    def open_ai_daily(self, _icon: Any = None, _item: Any = None) -> None:
        webbrowser.open("https://aqua5230.github.io/ai-updates/")

    def toggle_hide_section(self, preference_key: str) -> None:
        preferences = _load_preferences()
        preferences[preference_key] = preferences.get(preference_key) is not True
        _save_preferences(preferences)
        self.latest_state.hide_claude = _hide_claude_enabled()
        self.latest_state.hide_codex = _hide_codex_enabled()
        self.latest_state.hide_agy = _hide_agy_enabled()
        if self.visible:
            self.inject_state()

    def toggle_quota_notifications(self, _icon: Any = None, _item: Any = None) -> None:
        preferences = _load_preferences()
        preferences["quota_notifications"] = not _quota_notifications_enabled(preferences)
        _save_preferences(preferences)

    def toggle_session_resume(self, _icon: Any = None, _item: Any = None) -> None:
        threading.Thread(target=self._toggle_session_resume_in_background, daemon=True).start()

    def _toggle_session_resume_in_background(self) -> None:
        import session_hooks

        try:
            if session_hooks.is_resume_enabled():
                session_hooks.disable_session_resume()
            else:
                session_hooks.enable_session_resume()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("toggle session resume failed", exc_info=True)

    def toggle_terse_mode(self, _icon: Any = None, _item: Any = None) -> None:
        threading.Thread(target=self._toggle_terse_mode_in_background, daemon=True).start()

    def _toggle_terse_mode_in_background(self) -> None:
        import session_hooks

        try:
            if session_hooks.is_terse_mode_enabled():
                session_hooks.disable_terse_mode()
            else:
                session_hooks.enable_terse_mode()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("toggle terse mode failed", exc_info=True)

    def _process_quota_notifications(self, state: menubar_state.PopoverState) -> None:
        try:
            events = self._quota_notifier.update(
                {
                    "claude_session": (
                        state.claude_session.percent,
                        state.claude_session.available,
                    ),
                    "claude_weekly": (
                        state.claude_weekly.percent,
                        state.claude_weekly.available,
                    ),
                    "codex_session": (state.codex_session.percent, state.codex_session.available),
                    "codex_weekly": (state.codex_weekly.percent, state.codex_weekly.available),
                }
            )
            if _quota_notifications_enabled() and not self.mock:
                for event in events:
                    self._send_quota_notification(event, state)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows quota notification processing failed", exc_info=True)

    def _send_quota_notification(
        self, event: NotificationEvent, state: menubar_state.PopoverState
    ) -> None:
        if self.icon is None or not hasattr(self.icon, "notify"):
            return
        rows = {
            "claude_session": state.claude_session,
            "claude_weekly": state.claude_weekly,
            "codex_session": state.codex_session,
            "codex_weekly": state.codex_weekly,
        }
        row = rows[event.channel]
        scope = row.title or _t(
            self.language, "session_label" if event.channel.endswith("_session") else "weekly_label"
        )
        message = _t(
            self.language,
            f"notif_{event.kind}_body",
            tool="Claude" if event.channel.startswith("claude_") else "Codex",
            scope=scope,
            pct=f"{round(row.percent or event.threshold or 0.0):g}",
            reset=row.reset_text,
        )
        self.icon.notify(message, _t(self.language, f"notif_{event.kind}_title"))

    def check_update(self, _icon: Any = None, _item: Any = None) -> None:
        def worker() -> None:
            result = update_checker.check_latest_release_result(_current_version())
            if result.release is not None:
                release = result.release
                title = _t(self.language, "update_alert_title", version=release.version)
                if self._message_box(f"{title}\n\n{release.body[:2000]}", style=0x44) == 6:
                    webbrowser.open(release.html_url)
            else:
                self._message_box(
                    _t(
                        self.language,
                        "update_check_failed" if result.failed else "update_no_new_version",
                    )
                )

        threading.Thread(target=worker, daemon=True).start()

    def _message_box(self, text: str, *, style: int = 0x40) -> int:
        import ctypes

        library_name = "windll"
        windll: Any = getattr(ctypes, library_name)
        return int(windll.user32.MessageBoxW(0, text, "usage", style))

    def handle_panel_message(self, message: object) -> list[dict[str, object]] | None:
        payload: object = message
        if isinstance(message, str) and message.startswith("{"):
            try:
                payload = json.loads(message)
            except ValueError:
                return None
        if isinstance(payload, dict):
            action = payload.get("action")
            if action == "open_menu":
                return self._panel_menu_data()
            if action == "set_card_order":
                order = payload.get("order")
                if (
                    isinstance(order, list)
                    and all(isinstance(item, str) for item in order)
                    and len(order) == 3
                    and set(order) == {"agy", "claude", "codex"}
                ):
                    preferences = _load_preferences()
                    preferences["quota_card_order"] = order
                    _save_preferences(preferences)
            elif action == "switch_panel":
                panel_id = payload.get("panel_id")
                if isinstance(panel_id, str):
                    self._schedule_panel_switch(panel_id)
            elif action == "toggle_hide_section":
                preference_key = payload.get("preference_key")
                if preference_key in {
                    "hide_claude_section",
                    "hide_codex_section",
                    "hide_agy_section",
                }:
                    self.toggle_hide_section(preference_key)
            elif action == "open_ai_daily":
                self.open_ai_daily()
            elif action == "reset_panel_position":
                self.reset_panel_position()
            elif action == "refresh":
                self.refresh()
            elif action == "toggle_login":
                self.toggle_login()
            elif action == "toggle_quota_notifications":
                self.toggle_quota_notifications()
            elif action == "toggle_session_resume":
                self.toggle_session_resume()
            elif action == "toggle_terse_mode":
                self.toggle_terse_mode()
            elif action == "check_update":
                self.check_update()
            elif action == "quit":
                self.quit()
            return None
        action = str(payload)
        if action == "refresh":
            self.refresh()
        elif action == "quit":
            self.quit()
        elif action == "switch":
            # Older panel assets post this action directly. Return menu data
            # instead of cycling themes so the bridge remains forwards-safe.
            return self._panel_menu_data()
        elif action in {"toggle_statusline", "toggle-statusline"}:
            threading.Thread(target=self._toggle_statusline, daemon=True).start()
        elif action == "install":
            threading.Thread(target=self._install_hook, daemon=True).start()
        elif action == "analyze":
            project_range = self.window.evaluate_js(
                "typeof projectRange === 'string' ? projectRange : '30d'"
            )
            threading.Thread(
                target=self._analyze_usage,
                args=(str(project_range or "30d"),),
                daemon=True,
            ).start()
        return None

    def _toggle_statusline(self) -> None:
        _toggle_statusline_settings()
        self.refresh()

    def _install_hook(self) -> None:
        import session_hooks
        import setup_hook

        if setup_hook.setup() == 0:
            session_hooks._migrate_bundled_python_commands_if_needed()
        self.refresh()

    def _analyze_usage(self, project_range: str) -> None:
        from adapters.registry import detect_agents
        from analyzer.reporter import build_report_data
        from ui.html_report import save_and_open

        periods = {"1d": "today", "7d": "last7", "30d": "last30", "all": "all"}
        period = periods.get(project_range, "month")
        save_and_open(build_report_data(detect_agents(), period), language=self.language)

    def quit(self, _icon: Any = None, _item: Any = None) -> None:
        self.stopping.set()
        if self.icon is not None:
            self.icon.stop()
        if self.window is not None:
            self.window.destroy()


def _menu(controller: _WindowsTrayController) -> Any:
    import pystray

    panel_items = tuple(
        pystray.MenuItem(
            _t(controller.language, key),
            # pystray rejects actions whose co_argcount isn't 0/1/2, so the
            # panel_id binding must be keyword-only.
            lambda _icon, _item, *, panel_id=panel_id: controller.switch_panel(panel_id),
            checked=lambda _item, panel_id=panel_id: controller.active_panel_id == panel_id,
            radio=True,
        )
        for panel_id, key, _filename in available_panels()
    )
    return pystray.Menu(
        pystray.MenuItem("Open", controller.show_panel, default=True, visible=False),
        pystray.MenuItem(_t(controller.language, "panel_ai_daily"), controller.open_ai_daily),
        pystray.MenuItem(
            _t(controller.language, "reset_panel_position"), controller.reset_panel_position
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_t(controller.language, "switch_panel"), pystray.Menu(*panel_items)),
        pystray.MenuItem(
            _t(controller.language, "hide_sections_menu"),
            pystray.Menu(
                pystray.MenuItem(
                    _t(controller.language, "claude_name"),
                    lambda _icon, _item: controller.toggle_hide_section("hide_claude_section"),
                    checked=lambda _item: _hide_claude_enabled(),
                ),
                pystray.MenuItem(
                    _t(controller.language, "codex_name"),
                    lambda _icon, _item: controller.toggle_hide_section("hide_codex_section"),
                    checked=lambda _item: _hide_codex_enabled(),
                ),
                pystray.MenuItem(
                    _t(controller.language, "agy_name"),
                    lambda _icon, _item: controller.toggle_hide_section("hide_agy_section"),
                    checked=lambda _item: _hide_agy_enabled(),
                ),
            ),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_t(controller.language, "refresh_now"), lambda i, x: controller.refresh()),
        pystray.MenuItem(
            _t(controller.language, "launch_at_login"),
            controller.toggle_login,
            checked=lambda _item: win_login_item.is_enabled(),
        ),
        pystray.MenuItem(
            _t(controller.language, "quota_notifications_menu"),
            controller.toggle_quota_notifications,
            checked=lambda _item: _quota_notifications_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            _t(controller.language, "project_butler"),
            controller.toggle_session_resume,
            checked=lambda _item: _session_resume_enabled(),
        ),
        pystray.MenuItem(
            _t(controller.language, "terse_mode_menu"),
            controller.toggle_terse_mode,
            checked=lambda _item: _terse_mode_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_t(controller.language, "check_update"), controller.check_update),
        pystray.MenuItem(_t(controller.language, "quit"), controller.quit),
    )


def _session_resume_enabled() -> bool:
    try:
        import session_hooks

        return session_hooks.is_resume_enabled()
    except Exception:
        return False


def _terse_mode_enabled() -> bool:
    try:
        import session_hooks

        return session_hooks.is_terse_mode_enabled()
    except Exception:
        return False


_SINGLE_INSTANCE_MUTEX = "usage-windows-tray-single-instance"
_ERROR_ALREADY_EXISTS = 183
_single_instance_handle: int | None = None


def _acquire_single_instance_lock() -> bool:
    """Hold a named mutex for the process lifetime; False if another tray owns it.

    Two tray instances fight over the same WebView2 user-data directory: the
    loser's panel fails to initialize and lingers as a bare white window.
    """
    global _single_instance_handle
    import ctypes

    library_name = "windll"
    windll: Any = getattr(ctypes, library_name)
    handle = windll.kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX)
    if not handle:
        return True
    if windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        windll.kernel32.CloseHandle(handle)
        return False
    _single_instance_handle = handle
    return True


def _release_single_instance_lock() -> None:
    global _single_instance_handle
    if _single_instance_handle is None:
        return
    import ctypes

    library_name = "windll"
    windll: Any = getattr(ctypes, library_name)
    windll.kernel32.CloseHandle(_single_instance_handle)
    _single_instance_handle = None


def _show_already_running_notice() -> None:
    import ctypes

    library_name = "windll"
    windll: Any = getattr(ctypes, library_name)
    windll.user32.MessageBoxW(0, _t(detect_lang(), "wintray_already_running"), "usage", 0x40)


def run_app(mock: bool = False, interval: int = 60) -> None:
    if not _acquire_single_instance_lock():
        _show_already_running_notice()
        return

    import pystray
    import webview

    controller = _WindowsTrayController(mock, interval)
    window = webview.create_window(
        "usage",
        html=panel_html(controller.panel_filename()),
        js_api=_JSApi(controller),
        width=PANEL_WIDTH,
        height=controller.panel_height(),
        frameless=True,
        easy_drag=False,
        on_top=True,
        hidden=True,
        background_color=_system_background_color(),
    )
    if window is None:
        raise RuntimeError("pywebview did not create a window")
    window.events.loaded += controller.on_loaded
    icon = pystray.Icon("usage", draw_tray_icon(None), "usage", _menu(controller))
    controller.attach(icon, window)
    icon.run_detached()
    webview.start(gui="edgechromium", debug=os.environ.get("USAGE_DEBUG") == "1")
