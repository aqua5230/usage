# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import asyncio
import ctypes
import importlib
import json
import logging
import os
import threading
import time
import tomllib
import webbrowser
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import IntEnum
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import quota.agy_window_keeper as agy_window_keeper
import quota.codex_window_keeper as codex_window_keeper
import quota.window_keeper as window_keeper
import service_status
import usage_diagnosis_snapshot
from i18n import _t
from installer.statusline_settings import _statusline_enabled, _toggle_statusline_settings
from loaders import codex_loader
from loaders.history_loader import UsageEntry, load_entries
from menubar import agy as menubar_agy
from menubar import grok as menubar_grok
from menubar import state as menubar_state
from menubar.prefs import (
    _auto_update_check_enabled,
    _hide_agy_enabled,
    _hide_claude_enabled,
    _hide_codex_enabled,
    _hide_grok_enabled,
    _panel_flavor,
    _quota_card_order,
    _quota_notification_thresholds,
    _quota_notifications_enabled,
    _save_panel_flavor,
    _window_keeper_enabled,
)
from panels.dynamic_height import clamp_content_height, inject_content_height_script
from panels.payload import _load_panel_html, _state_payload
from prefs import _load_preferences, _save_preferences
from pricing import calculate_cost
from quota.burn_rate import BurnRateTracker
from quota.usage_rate import UsageRateTracker
from updates import checker as update_checker
from updates import gate as update_gate
from updates.release_notes import format_release_notes
from usage_client import ClaudeUsageClient, PollState
from usage_common.usage_lang import detect_lang
from usage_notifications import NotificationEvent, QuotaNotifier
from wintray import login_item as win_login_item
from wintray import menu as wintray_menu
from wintray.watch import (
    WindowsFileEventChanges,
    WindowsUsageWatcher,
    setup_windows_watcher,
)

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)

SLOW_POLL_INTERVAL_S = 300
HISTORY_SCAN_CACHE_SECONDS = 30.0
UPDATE_ALERT_BODY_LIMIT = 2000
PANEL_WIDTH = 380
_TOAST_AUMID = "com.lollapalooza.usage"
_TOAST_OPEN_PANEL_ACTION = "open_panel"
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
    ("stained_glass", "panel_stained_glass", "stained_glass.html"),
    ("migration", "panel_migration", "migration.html"),
    ("origami", "panel_origami", "origami.html"),
    ("catppuccin", "panel_catppuccin", "catppuccin.html"),
)
# These are only the initial-placeholder fallback used before the WebView
# reports its real content height (see panel_height()); kept in sync with
# panels/__init__.py's Mac heights from 64a7c0b (Recalibrate HTML panel
# heights and status-wrap growth) so the brief pre-measurement window isn't
# ~17-24pt too tall.
PANEL_HEIGHTS = {
    "classic": 1132,
    "matrix": 1174,
    "win95": 1183,
    "newspaper": 1179,
    "cloud_observation": 1134,
    "aquarium": 1134,
    "prism_arcade": 1134,
    "black_hole": 1134,
    "lepidoptera": 1174,
    "world_cup": 812,
    "stained_glass": 1132,
    "migration": 1132,
    "origami": 1132,
    "catppuccin": 1166,
}

TRAY_UNKNOWN_COLOR = (110, 118, 129, 255)
TRAY_NORMAL_COLOR = (244, 145, 100, 255)
TRAY_PAUSED_COLOR = (255, 196, 57, 255)
TRAY_ERROR_COLOR = (255, 69, 58, 255)


class TaskbarProgressState(IntEnum):
    """TBPFLAG values used by ITaskbarList3::SetProgressState."""

    NO_PROGRESS = 0x0
    NORMAL = 0x2
    ERROR = 0x4
    PAUSED = 0x8


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_ushort),
        ("data3", ctypes.c_ushort),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> _GUID:
        parsed = UUID(value)
        return cls(
            parsed.time_low,
            parsed.time_mid,
            parsed.time_hi_version,
            (ctypes.c_ubyte * 8)(*parsed.bytes[8:]),
        )


_CLSID_TASKBAR_LIST = _GUID.from_string("56FDF344-FD6D-11D0-958A-006097C9A090")
_IID_ITASKBAR_LIST3 = _GUID.from_string("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF")
_RPC_E_CHANGED_MODE = -2147417850

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
    '[data-card="claude"], [data-card="codex"], [data-card="agy"], '
    + '[data-card="grok"]'
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


def _register_toast_aumid(aumid: str = _TOAST_AUMID) -> None:
    """Register the unpackaged tray app as a Windows toast sender."""
    winreg = _winreg()
    key_path = rf"Software\Classes\AppUserModelId\{aumid}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "usage")


def _create_toast_backend(aumid: str = _TOAST_AUMID) -> Any:
    _register_toast_aumid(aumid)
    from windows_toasts import InteractableWindowsToaster

    return InteractableWindowsToaster("usage", notifierAUMID=aumid)


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


def _system_accent_color() -> str | None:
    try:
        winreg = _winreg()
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\DWM",
        ) as key:
            value, value_type = winreg.QueryValueEx(key, "AccentColor")
        if (
            value_type != winreg.REG_DWORD
            or isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 0xFFFFFFFF
        ):
            return None
    except Exception:
        return None
    return f"#{value & 0xFF:02x}{value >> 8 & 0xFF:02x}{value >> 16 & 0xFF:02x}"


def available_panels() -> tuple[tuple[str, str, str], ...]:
    """Windows excludes talent_market because its vendored CLI is macOS-only."""
    return tuple(panel for panel in WINDOWS_PANELS if panel[0] != "talent_market")


def tray_icon_style(used_percent: float | None) -> tuple[str, tuple[int, int, int, int]]:
    if used_percent is None:
        return ("--", TRAY_UNKNOWN_COLOR)
    remaining = max(0, min(100, round(100.0 - used_percent)))
    if remaining <= 20:
        color = TRAY_ERROR_COLOR
    elif remaining <= 50:
        color = TRAY_PAUSED_COLOR
    else:
        color = TRAY_NORMAL_COLOR
    return (str(remaining), color)


def taskbar_progress_state(used_percent: float | None) -> TaskbarProgressState:
    """Map the tray icon's existing quota color tier to a taskbar progress state."""
    if used_percent is None:
        return TaskbarProgressState.NO_PROGRESS
    _text, color = tray_icon_style(used_percent)
    if color == TRAY_ERROR_COLOR:
        return TaskbarProgressState.ERROR
    if color == TRAY_PAUSED_COLOR:
        return TaskbarProgressState.PAUSED
    return TaskbarProgressState.NORMAL


def _taskbar_window_handle(window: Any) -> int | None:
    """Return the pywebview WinForms HWND only when it owns a taskbar button."""
    try:
        native = window.native
        if not native.ShowInTaskbar:
            return None
        handle = native.Handle
        to_int64 = getattr(handle, "ToInt64", None)
        value = to_int64() if callable(to_int64) else handle
        hwnd = int(value)
        return hwnd or None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _raise_for_hresult(result: int, operation: str) -> None:
    if result < 0:
        code = result & 0xFFFFFFFF
        raise OSError(f"{operation} failed with HRESULT 0x{code:08X}")


def _set_taskbar_progress(
    hwnd: int,
    completed: int,
    total: int,
    state: TaskbarProgressState,
) -> None:
    """Apply taskbar progress with a thread-local, short-lived ITaskbarList3."""
    if os.name != "nt":
        return

    # WinDLL leaves HRESULT handling to us, including RPC_E_CHANGED_MODE;
    # OleDLL would raise before we could safely reuse an existing apartment.
    library_name = "WinDLL"
    win_dll: Any = getattr(ctypes, library_name)
    ole32: Any = win_dll("ole32", use_last_error=True)
    function_type_name = "WINFUNCTYPE"
    win_function_type: Any = getattr(ctypes, function_type_name)
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    initialize_result = int(ole32.CoInitializeEx(None, 0x2))  # COINIT_APARTMENTTHREADED
    initialized_here = initialize_result in {0, 1}  # S_OK or S_FALSE
    if initialize_result < 0 and initialize_result != _RPC_E_CHANGED_MODE:
        _raise_for_hresult(initialize_result, "CoInitializeEx")

    taskbar = ctypes.c_void_p()
    try:
        result = int(
            ole32.CoCreateInstance(
                ctypes.byref(_CLSID_TASKBAR_LIST),
                None,
                0x1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(_IID_ITASKBAR_LIST3),
                ctypes.byref(taskbar),
            )
        )
        _raise_for_hresult(result, "CoCreateInstance(CLSID_TaskbarList)")

        vtable = ctypes.cast(
            taskbar, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        hresult_method = win_function_type(ctypes.c_long, ctypes.c_void_p)
        set_progress_value_method = win_function_type(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulonglong,
            ctypes.c_ulonglong,
        )
        set_progress_state_method = win_function_type(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int
        )
        release_method = win_function_type(ctypes.c_ulong, ctypes.c_void_p)

        _raise_for_hresult(int(hresult_method(vtable[3])(taskbar)), "ITaskbarList3.HrInit")
        if state != TaskbarProgressState.NO_PROGRESS:
            _raise_for_hresult(
                int(
                    set_progress_value_method(vtable[9])(
                        taskbar,
                        ctypes.c_void_p(hwnd),
                        completed,
                        total,
                    )
                ),
                "ITaskbarList3.SetProgressValue",
            )
        _raise_for_hresult(
            int(
                set_progress_state_method(vtable[10])(
                    taskbar, ctypes.c_void_p(hwnd), int(state)
                )
            ),
            "ITaskbarList3.SetProgressState",
        )
    finally:
        if taskbar.value:
            vtable = ctypes.cast(
                taskbar, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            ).contents
            release_method = win_function_type(ctypes.c_ulong, ctypes.c_void_p)
            release_method(vtable[2])(taskbar)
        if initialized_here:
            ole32.CoUninitialize()


def build_tooltip(state: menubar_state.PopoverState) -> str:
    def line(name: str, row: menubar_state.QuotaRowState) -> str:
        used = (
            "--"
            if row.percent is None
            else str(min(100, max(0, round(row.percent))))
        )
        return f"{name} {row.title}: {used}%"

    lines = [
        f"{line('Claude', state.claude_session)} · "
        f"{line('Claude', state.claude_weekly).removeprefix('Claude ')}",
        f"{line('Codex', state.codex_session)} · "
        f"{line('Codex', state.codex_weekly).removeprefix('Codex ')}",
    ]
    if not state.hide_agy:
        lines.append(
            f"{line('Antigravity', state.agy_session)} · "
            f"{line('Antigravity', state.agy_weekly).removeprefix('Antigravity ')}"
        )
    if not state.hide_grok:
        lines.append(line("Grok", state.grok_weekly))
    return "\n".join(lines)


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
    html = html.replace("{{PANEL_FLAVOR}}", _panel_flavor())
    html = inject_content_height_script(html)
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
        return metadata.version("usage-cli")
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


def _yesterday_text(entries: list[UsageEntry], language: str) -> str:
    yesterday = datetime.now().astimezone().date() - timedelta(days=1)
    selected = [entry for entry in entries if entry.timestamp.astimezone().date() == yesterday]
    return _t(
        language,
        "yesterday_text",
        cost=f"{sum(calculate_cost(entry) for entry in selected):.2f}",
        tokens=f"{sum(entry.total_tokens for entry in selected):,}",
    )


def _mock_projects() -> tuple[
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
    list[tuple[str, int, float | None]],
]:
    return (
        [("usage", 11_200_000, 6.47), ("FinMind", 3_100_000, 1.82), ("AI客服", 800_000, 0.48)],
        [("usage", 10_800_000, 6.21), ("FinMind", 2_900_000, 1.70)],
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
            "agy_session": BurnRateTracker(),
            "agy_weekly": BurnRateTracker(),
        }
        self.icon: Any = None
        self.window: Any = None
        self.visible = False
        self._positioned_this_show = False
        self.stopping = threading.Event()
        self.refresh_lock = threading.Lock()
        self._refresh_in_flight = False
        self._refresh_queued = False
        self._refresh_thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._watcher_lock = threading.Lock()
        self._windows_watcher: WindowsUsageWatcher | None = None
        self._file_event_lock = threading.Lock()
        self._file_event_refresh_timer: threading.Timer | None = None
        self._last_file_event_refresh_started_at: float | None = None
        self._history_source_tracker = menubar_state.HistorySourceTracker()
        self._quota_notifier = QuotaNotifier(_quota_notification_thresholds())
        self.usage_client = ClaudeUsageClient(mock=mock)
        self._last_tray_percent: float | None = None
        self._last_tray_tooltip: str | None = None
        self._last_injected_state: str | None = None
        self._toast_backend: Any = None
        self._toast_backend_attempted = False
        self._history_fingerprint: tuple[tuple[str, int, float], ...] | None = None
        self._history_cache_date: date | None = None
        self._cached_history: _RefreshData | None = None
        self._cached_projects: tuple[list[tuple[str, int, float | None]], ...] | None = None
        self._history_scan: menubar_state.HistorySourceScan | None = None
        self._history_scan_at: float | None = None
        self._content_height: int | None = None
        self._window_mutations: deque[Callable[[], None]] = deque()
        self._window_mutation_lock = threading.Lock()
        self._window_mutation_scheduled = False

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
            grok_weekly=missing(
                _t(self.language, "weekly_label"), menubar_state.GROK_COLOR, self.language
            ),
            projects=[],
            projects_yesterday=[],
            projects_7d=[],
            projects_30d=[],
            projects_all=[],
            rate_text=_t(self.language, "rate_text", value="--"),
            status_text=_t(self.language, "status_text", value=_t(self.language, "status_loading")),
            today_text=_t(self.language, "today_text", cost="0.00", tokens="0"),
            yesterday_text=_t(self.language, "yesterday_text", cost="0.00", tokens="0"),
            statusline=_statusline_payload(self.language),
            hide_claude=_hide_claude_enabled(),
            hide_codex=_hide_codex_enabled(),
            hide_agy=_hide_agy_enabled(),
            hide_grok=True,
            card_order=_quota_card_order(),
        )

    def panel_filename(self) -> str:
        return next(item[2] for item in available_panels() if item[0] == self.active_panel_id)

    def panel_height(self) -> int:
        return self._content_height or PANEL_HEIGHTS[self.active_panel_id]

    def _apply_content_height(self, value: object) -> None:
        self._dispatch_window_mutation(lambda: self._apply_content_height_on_ui_thread(value))

    def _apply_content_height_on_ui_thread(self, value: object) -> None:
        if self.stopping.is_set():
            return
        current_position = self._current_window_position()
        work_area = self._work_area_for_point(current_position) or self._working_area()
        maximum = (
            float(work_area[3] - work_area[1] - 24)
            if work_area is not None
            else float(PANEL_HEIGHTS[self.active_panel_id])
        )
        height = clamp_content_height(value, maximum)
        if height is None:
            return
        rounded = int(round(height))
        if rounded == self._content_height:
            return
        self._content_height = rounded
        if self.visible:
            self._place_window_on_ui_thread()

    def attach(self, icon: Any, window: Any) -> None:
        self.icon = icon
        self.window = window
        self._update_tray()
        threading.Thread(target=self._startup_maintenance, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.refresh()

    def _startup_maintenance(self) -> None:
        usage_diagnosis_snapshot.maybe_schedule_refresh()
        self._clear_stale_update_cache()
        self._check_update_in_background(
            manual=False,
            ignore_cooldown=False,
            ignore_skipped=False,
        )

    def on_loaded(self) -> None:
        # pywebview's resize()/move() call SetWindowPos with SWP_SHOWWINDOW,
        # so placing the window while it is hidden would drag the bare panel
        # onto the screen. Placement happens in show_panel() instead; here it
        # only re-applies after a visible panel switch reloads the document.
        if self.visible and not self.stopping.is_set():
            self._place_window()
            self.inject_state(force=True)
            # A panel reload can recreate its taskbar button. Reapply the
            # latest value once the visible native window has loaded.
            self._update_taskbar_progress(self.latest_state.claude_session.percent)

    @staticmethod
    def _screen_rectangle(value: object) -> tuple[int, int, int, int] | None:
        """Return a pywebview/WinForms rectangle as logical left/top/right/bottom."""
        left = getattr(value, "Left", getattr(value, "x", None))
        top = getattr(value, "Top", getattr(value, "y", None))
        right = getattr(value, "Right", None)
        bottom = getattr(value, "Bottom", None)
        if right is None:
            width = getattr(value, "Width", getattr(value, "width", None))
            right = (
                left + width
                if isinstance(left, int | float) and isinstance(width, int | float)
                else None
            )
        if bottom is None:
            height = getattr(value, "Height", getattr(value, "height", None))
            bottom = (
                top + height
                if isinstance(top, int | float) and isinstance(height, int | float)
                else None
            )
        coordinates = (left, top, right, bottom)
        if any(isinstance(item, bool) or not isinstance(item, int | float) for item in coordinates):
            return None
        assert isinstance(left, int | float)
        assert isinstance(top, int | float)
        assert isinstance(right, int | float)
        assert isinstance(bottom, int | float)
        return (int(left), int(top), int(right), int(bottom))

    def _logical_screens(
        self,
    ) -> list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
        """Return pywebview screen bounds and work areas, all in logical pixels."""
        try:
            webview = importlib.import_module("webview")
            screens = webview.screens
        except Exception:
            return []

        result = []
        for screen in screens:
            bounds = self._screen_rectangle(screen)
            work_area = self._screen_rectangle(getattr(screen, "frame", None)) or bounds
            if bounds is not None and work_area is not None:
                result.append((bounds, work_area))
        return result

    def _working_area(self) -> tuple[int, int, int, int] | None:
        """Return the primary monitor work area in pywebview logical pixels."""
        screens = self._logical_screens()
        for bounds, work_area in screens:
            left, top, right, bottom = bounds
            if left <= 0 < right and top <= 0 < bottom:
                return work_area
        return screens[0][1] if screens else None

    def _work_area_for_point(
        self, point: tuple[int, int] | None
    ) -> tuple[int, int, int, int] | None:
        """Logical work area of the pywebview monitor nearest ``point``."""
        if point is None:
            return self._working_area()
        screens = self._logical_screens()
        if not screens:
            return None
        for bounds, work_area in screens:
            left, top, right, bottom = bounds
            if left <= point[0] < right and top <= point[1] < bottom:
                return work_area

        def distance(bounds: tuple[int, int, int, int]) -> int:
            left, top, right, bottom = bounds
            dx = max(left - point[0], 0, point[0] - (right - 1))
            dy = max(top - point[1], 0, point[1] - (bottom - 1))
            return dx * dx + dy * dy

        return min(screens, key=lambda screen: distance(screen[0]))[1]

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
        self._dispatch_window_mutation(
            lambda: self._place_window_on_ui_thread(force_default=force_default)
        )

    def _place_window_on_ui_thread(self, *, force_default: bool = False) -> None:
        if self.window is None or self.stopping.is_set():
            return
        primary_work_area = self._working_area()
        if primary_work_area is None:
            return

        # Resolve the *target* anchor point before picking a work area, then
        # look up the work area of whichever monitor that point is on. The
        # primary monitor's work area is only a fallback for the "no anchor
        # yet" (first-ever launch) case — using it unconditionally would
        # clamp a window the user dragged onto a secondary display back onto
        # the primary one every time the panel is switched.
        if force_default:
            anchor = None
        elif self._positioned_this_show:
            anchor = self._current_window_position() or self._saved_window_position()
        else:
            anchor = self._saved_window_position()

        work_area = self._work_area_for_point(anchor) or primary_work_area
        left, top, right, bottom = work_area
        height = min(self.panel_height(), max(240, bottom - top - 24))
        self.window.resize(PANEL_WIDTH, height)
        position = anchor if anchor is not None else self._default_window_position(
            work_area, height
        )
        self.window.move(*self._clamp_window_position(position, work_area, height))
        self._positioned_this_show = True

    def _dispatch_window_mutation(self, mutation: Callable[[], None]) -> None:
        """Serialize geometry mutations onto the native WinForms UI thread."""
        if self.stopping.is_set():
            return
        with self._window_mutation_lock:
            self._window_mutations.append(mutation)
            if self._window_mutation_scheduled:
                return
            self._window_mutation_scheduled = True

        if self._schedule_window_mutation_drain():
            return
        with self._window_mutation_lock:
            self._window_mutation_scheduled = False

    def _schedule_window_mutation_drain(self) -> bool:
        window = self.window
        if window is None:
            return False
        if not hasattr(window, "native"):
            # Lightweight test doubles have no native control and execute synchronously.
            self._drain_window_mutations()
            return True
        native = window.native
        if native is None:
            # The tray can receive a click before pywebview has created its Form.
            # Leave the work queued; on_loaded() will schedule another drain.
            return False
        try:
            if native.InvokeRequired:
                system = importlib.import_module("System")
                native.BeginInvoke(system.Action(self._drain_window_mutations))
            else:
                self._drain_window_mutations()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Failed to dispatch window mutation", exc_info=True)
            return False
        return True

    def _drain_window_mutations(self) -> None:
        while True:
            with self._window_mutation_lock:
                if self.stopping.is_set():
                    self._window_mutations.clear()
                    self._window_mutation_scheduled = False
                    return
                if not self._window_mutations:
                    self._window_mutation_scheduled = False
                    return
                mutation = self._window_mutations.popleft()
            try:
                mutation()
            except Exception:
                if os.environ.get("USAGE_DEBUG") == "1":
                    logger.warning("Window mutation failed", exc_info=True)

    def _save_window_position(self) -> None:
        position = self._current_window_position()
        if position is None:
            return
        preferences = _load_preferences()
        preferences["usage.windowPosition"] = {"x": position[0], "y": position[1]}
        _save_preferences(preferences)

    def reset_panel_position(self, _icon: Any = None, _item: Any = None) -> None:
        if self.stopping.is_set():
            return
        preferences = _load_preferences()
        preferences.pop("usage.windowPosition", None)
        _save_preferences(preferences)
        if self.visible:
            self._place_window(force_default=True)

    def _poll_loop(self) -> None:
        current_thread = threading.current_thread()
        self._poll_thread = current_thread
        try:
            while not self.stopping.wait(
                self.interval if self.visible else max(self.interval, SLOW_POLL_INTERVAL_S)
            ):
                self.refresh()
        finally:
            if self._poll_thread is current_thread:
                self._poll_thread = None

    def _ensure_windows_watcher(self) -> None:
        if self.mock or self.stopping.is_set():
            return
        with self._watcher_lock:
            if self._windows_watcher is not None or self.stopping.is_set():
                return
            watcher = setup_windows_watcher(self._refresh_from_file_event)
            if watcher is not None:
                self._windows_watcher = watcher
                self._history_source_tracker.set_incremental_enabled(True)

    def _refresh_from_file_event(self, changes: WindowsFileEventChanges) -> None:
        self._history_source_tracker.record_changes(
            set(changes.paths),
            needs_full_scan=changes.needs_full_scan,
        )
        refresh_now = False
        timer_to_start: threading.Timer | None = None
        with self._file_event_lock:
            if self.stopping.is_set():
                return
            now = time.monotonic()
            decision = menubar_state.file_event_refresh_decision(
                now,
                self._last_file_event_refresh_started_at,
                self._file_event_refresh_timer is not None,
            )
            if decision.refresh_now:
                self._last_file_event_refresh_started_at = now
                refresh_now = True
            elif decision.trailing_delay is not None:
                timer_to_start = threading.Timer(
                    decision.trailing_delay,
                    self._refresh_from_trailing_file_event,
                )
                timer_to_start.daemon = True
                self._file_event_refresh_timer = timer_to_start
        if timer_to_start is not None:
            timer_to_start.start()
        if refresh_now:
            self.refresh()

    def _refresh_from_trailing_file_event(self) -> None:
        with self._file_event_lock:
            self._file_event_refresh_timer = None
            if self.stopping.is_set():
                return
            self._last_file_event_refresh_started_at = time.monotonic()
        self.refresh()

    def refresh(self) -> None:
        with self.refresh_lock:
            if self.stopping.is_set():
                return
            if self._refresh_in_flight:
                self._refresh_queued = True
                return
            self._refresh_in_flight = True
            self._refresh_thread = threading.Thread(
                target=self._refresh_worker,
                name="usage-refresh",
                daemon=True,
            )
            self._refresh_thread.start()

    def _refresh_worker(self) -> None:
        self._ensure_windows_watcher()
        debug_timing = os.environ.get("USAGE_DEBUG") == "1"

        def measure(stage: str, started_at: float) -> None:
            if debug_timing:
                elapsed_ms = (time.monotonic() - started_at) * 1000
                logger.debug("refresh_timing stage=%s elapsed_ms=%.1f", stage, elapsed_ms)

        while True:
            try:
                self.latest_state = self._build_state(
                    measure=measure,
                    debug_timing=debug_timing,
                )
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

            with self.refresh_lock:
                if self._refresh_queued and not self.stopping.is_set():
                    self._refresh_queued = False
                    continue
                self._refresh_queued = False
                self._refresh_in_flight = False
                self._refresh_thread = None
                return

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
        if self._windows_watcher is not None:
            return self._history_source_tracker.scan()
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
        scan = self._history_source_scan()
        codex_rows, _codex_pct, _model, codex_stale, codex_credits = menubar_state.codex_rows(
            mock=self.mock,
            language=self.language,
            burn_rate_trackers=self.burn_rate_trackers,
            jsonl_candidates=scan.codex_rate_limit_candidates,
        )
        measure("codex_load", started_at)
        started_at = time.monotonic() if debug_timing else 0.0
        agy_result = menubar_agy.load_refresh_result(
            self.language, self.burn_rate_trackers
        )
        agy = agy_result.projection or menubar_agy.fallback_projection(self.language)
        measure("agy_load", started_at)
        started_at = time.monotonic() if debug_timing else 0.0
        grok_result = menubar_grok.load_refresh_result(self.language)
        grok = grok_result.projection or menubar_grok.fallback_projection(self.language)
        measure("grok_load", started_at)
        started_at = time.monotonic() if debug_timing else 0.0
        local_date = datetime.now().astimezone().date()
        if self._history_cache_date != local_date or menubar_state.history_cache_needs_reload(
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
            self._history_cache_date = local_date
        history = self._cached_history
        projects = self._cached_projects
        assert history is not None and projects is not None
        measure("history_load", started_at)
        started_at = time.monotonic() if debug_timing else 0.0
        outcome = asyncio.run(self._fetch())
        measure("fetch", started_at)
        service_statuses = self._service_statuses()
        if outcome.snapshot is not None:
            window_keeper.maybe_ping(
                outcome.snapshot.current_reset_at,
                outcome.snapshot.current_percent,
                outcome.snapshot.data_source,
                self.mock,
            )
        agy_window_keeper.maybe_ping(agy_result, self.mock)
        codex_window_keeper.maybe_ping(self.mock)
        return menubar_state.build_popover_state(
            outcome=outcome,
            codex_rows=codex_rows,
            agy_rows=(agy.session, agy.weekly),
            agy_group_name=agy.group_name,
            grok_row=grok.weekly,
            projects=projects[0],
            projects_yesterday=projects[1],
            projects_7d=projects[2],
            projects_30d=projects[3],
            projects_all=projects[4],
            language=self.language,
            group=self.tracker.group(),
            burn_rate_trackers=self.burn_rate_trackers,
            today_text=(
                _t(self.language, "today_text", cost="45.20", tokens="50,193,442")
                if self.mock
                else _today_text(history.entries, self.language)
            ),
            yesterday_text=(
                _t(self.language, "yesterday_text", cost="41.10", tokens="48,200,000")
                if self.mock
                else _yesterday_text(history.entries, self.language)
            ),
            statusline=_statusline_payload(self.language),
            show_install_button=outcome.state == PollState.TOKEN_ERROR,
            hide_claude=_hide_claude_enabled(),
            hide_codex=_hide_codex_enabled(),
            hide_agy=agy_result.hide_agy or _hide_agy_enabled(),
            hide_grok=grok_result.hide_grok or _hide_grok_enabled(),
            codex_stale=codex_stale,
            codex_credits=codex_credits,
            agy_stale=agy.stale,
            grok_stale=grok.stale,
            card_order=_quota_card_order(),
            history_error=menubar_state.history_load_error_state(
                history.history_error_key, self.language
            ),
            service_statuses=service_statuses,
        )

    def _service_statuses(self) -> tuple[service_status.ServiceStatus, ...]:
        statuses: list[service_status.ServiceStatus] = []
        for config in (service_status.CLAUDE_STATUS, service_status.CODEX_STATUS):
            try:
                statuses.append(service_status.get_service_status(config))
            except Exception:
                if os.environ.get("USAGE_DEBUG") == "1":
                    logger.warning(
                        "Windows %s service status refresh failed",
                        config.service_name,
                        exc_info=True,
                    )
        return tuple(statuses)

    async def _fetch(self) -> Any:
        return await self.usage_client.fetch_once()

    def _update_tray(self) -> None:
        percent = self.latest_state.claude_session.percent
        self._update_taskbar_progress(percent)
        if self.icon is None:
            return
        tooltip = build_tooltip(self.latest_state)
        if percent == self._last_tray_percent and tooltip == self._last_tray_tooltip:
            return
        self.icon.icon = draw_tray_icon(percent)
        self.icon.title = tooltip
        self._last_tray_percent = percent
        self._last_tray_tooltip = tooltip

    def _update_taskbar_progress(self, used_percent: float | None) -> None:
        # ITaskbarList3 targets a window's taskbar button, not the pystray icon.
        # This popover has such a button only while its WinForms Form is visible.
        if not self.visible or self.window is None:
            return
        hwnd = _taskbar_window_handle(self.window)
        if hwnd is None:
            return
        completed = 0 if used_percent is None else max(0, min(100, round(used_percent)))
        try:
            _set_taskbar_progress(
                hwnd,
                completed,
                100,
                taskbar_progress_state(used_percent),
            )
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows taskbar progress update failed", exc_info=True)

    def inject_state(self, *, force: bool = False) -> None:
        if self.window is None:
            return
        encoded = json.dumps(
            _state_payload(
                self.latest_state,
                system_accent_color=_system_accent_color(),
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if not force and encoded == self._last_injected_state:
            return
        self.window.evaluate_js(f"window.usageApplyState({encoded})")
        self._last_injected_state = encoded

    def show_panel(self, _icon: Any = None, _item: Any = None) -> None:
        if self.stopping.is_set():
            return
        if self.visible:
            self._save_window_position()
            self.visible = False
            self._positioned_this_show = False
            self.window.hide()
            return
        self.visible = True
        self._place_window()
        self.window.show()
        self._update_taskbar_progress(self.latest_state.claude_session.percent)
        self.inject_state(force=True)
        self.refresh()

    def _activate_panel(self) -> None:
        """Show or foreground the existing tray panel without toggling it closed."""
        if self.window is None:
            return
        if not self.visible:
            self.show_panel()
            return
        self.window.show()

    def switch_panel(self, panel_id: str) -> None:
        self.active_panel_id = panel_id
        # Deliberately keep the previous panel's measured height instead of
        # resetting to None: on_loaded() clamps the window to fit before the
        # new panel reports its real height, and PANEL_HEIGHTS' fallback
        # values are near-fullscreen placeholders that would clamp a dragged
        # window's Y position back up to the top of the screen every switch.
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
        entries = wintray_menu.entries_for_surface(_menu_model(), wintray_menu.PANEL)
        return [_panel_menu_entry(self, entry) for entry in entries]

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
        self.latest_state.hide_grok = _hide_grok_enabled()
        if self.visible:
            self.inject_state()

    def toggle_quota_notifications(self, _icon: Any = None, _item: Any = None) -> None:
        preferences = _load_preferences()
        preferences["quota_notifications"] = not _quota_notifications_enabled(preferences)
        _save_preferences(preferences)

    def toggle_window_keeper(self, _icon: Any = None, _item: Any = None) -> None:
        preferences = _load_preferences()
        enabled = not _window_keeper_enabled(preferences)
        preferences["window_keeper"] = enabled
        preferences.pop("agy_window_keeper", None)
        _save_preferences(preferences)
        if enabled:
            self._message_box(
                f"{_t(self.language, 'window_keeper_sleep_title')}\n\n"
                f"{_t(self.language, 'window_keeper_sleep_body_windows')}"
            )

    def toggle_session_resume(self, _icon: Any = None, _item: Any = None) -> None:
        threading.Thread(target=self._toggle_session_resume_in_background, daemon=True).start()

    def _toggle_session_resume_in_background(self) -> None:
        from installer import session_hooks

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
        from installer import session_hooks

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
                    "agy_session": (
                        state.agy_session.percent,
                        state.agy_session.available and state.agy_stale is None,
                    ),
                    "agy_weekly": (
                        state.agy_weekly.percent,
                        state.agy_weekly.available and state.agy_stale is None,
                    ),
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
        rows = {
            "claude_session": state.claude_session,
            "claude_weekly": state.claude_weekly,
            "codex_session": state.codex_session,
            "codex_weekly": state.codex_weekly,
            "agy_session": state.agy_session,
            "agy_weekly": state.agy_weekly,
        }
        row = rows[event.channel]
        scope = row.title or _t(
            self.language, "session_label" if event.channel.endswith("_session") else "weekly_label"
        )
        tool = (
            "Claude"
            if event.channel.startswith("claude_")
            else "Antigravity"
            if event.channel.startswith("agy_")
            else "Codex"
        )
        message = _t(
            self.language,
            f"notif_{event.kind}_body",
            tool=tool,
            scope=scope,
            pct=f"{round(row.percent or event.threshold or 0.0):g}",
            reset=row.reset_text,
        )
        title = _t(self.language, f"notif_{event.kind}_title")
        if not self._show_interactive_toast(title, message):
            self._show_balloon_notification(title, message)

    def _toast_toaster(self) -> Any:
        if self._toast_backend_attempted:
            return self._toast_backend
        self._toast_backend_attempted = True
        try:
            self._toast_backend = _create_toast_backend()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows interactive toast backend unavailable", exc_info=True)
        return self._toast_backend

    def _show_interactive_toast(self, title: str, message: str) -> bool:
        toaster = self._toast_toaster()
        if toaster is None:
            return False
        try:
            from windows_toasts import Toast, ToastButton

            toast = Toast(text_fields=[title, message])
            toast.AddAction(
                ToastButton(
                    content=_t(self.language, "usage_title"),
                    arguments=_TOAST_OPEN_PANEL_ACTION,
                )
            )
            toast.on_activated = self._on_toast_activated
            toaster.show_toast(toast)
            return True
        except Exception:
            self._toast_backend = None
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows interactive toast failed", exc_info=True)
            return False

    def _on_toast_activated(self, event_args: Any) -> None:
        if getattr(event_args, "arguments", None) != _TOAST_OPEN_PANEL_ACTION:
            return
        try:
            self._activate_panel()
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows toast panel activation failed", exc_info=True)

    def _show_balloon_notification(self, title: str, message: str) -> None:
        if self.icon is None or not hasattr(self.icon, "notify"):
            return
        try:
            self.icon.notify(message, title)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows balloon notification failed", exc_info=True)

    def check_update(self, _icon: Any = None, _item: Any = None) -> None:
        threading.Thread(
            target=self._check_update_in_background,
            kwargs={
                "manual": True,
                "ignore_cooldown": True,
                "ignore_skipped": True,
            },
            daemon=True,
        ).start()

    def _clear_stale_update_cache(self) -> None:
        try:
            current_version = _current_version()
            preferences = _load_preferences()
            updated_cache = update_gate.stale_cache_reset(preferences, current_version)
            if updated_cache is not None:
                preferences["last_update_check"] = updated_cache
                _save_preferences(preferences)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows stale update cache reset failed", exc_info=True)

    def _check_update_in_background(
        self,
        *,
        manual: bool,
        ignore_cooldown: bool,
        ignore_skipped: bool,
    ) -> None:
        preferences = _load_preferences()
        if not manual and not _auto_update_check_enabled(preferences):
            return
        if not manual and not update_gate.auto_check_is_due(preferences):
            return
        if not ignore_cooldown and update_gate.dismissed_recently(preferences):
            return

        try:
            current_version = _current_version()
            result = update_checker.check_latest_release_result(current_version)
        except Exception:
            if os.environ.get("USAGE_DEBUG") == "1":
                logger.warning("Windows update check failed", exc_info=True)
            if manual:
                self._message_box(_t(self.language, "update_check_failed"))
            return

        if result.failed:
            if manual:
                self._message_box(_t(self.language, "update_check_failed"))
            return

        release = result.release
        preferences["last_update_check"] = update_gate.build_check_cache_entry(
            current_version, release
        )
        _save_preferences(preferences)

        if release is None:
            if manual:
                self._message_box(_t(self.language, "update_no_new_version"))
            return
        if not ignore_skipped and preferences.get("update_skipped_version") == release.version:
            return
        self._show_update_alert(release)

    def _show_update_alert(self, release: update_checker.ReleaseInfo) -> None:
        title = _t(self.language, "update_alert_title", version=release.version)
        body = format_release_notes(release.body, UPDATE_ALERT_BODY_LIMIT)
        result = self._message_box(f"{title}\n\n{body}", style=0x44)
        action, preference_updates = update_gate.resolve_alert_choice(
            1000 if result == 6 else 1001,
            release.version,
        )
        if action == "open":
            webbrowser.open(release.html_url)
            return

        preferences = _load_preferences()
        preferences.update(preference_updates)
        if action == "dismiss":
            preferences["update_dismissed_at"] = time.time()
        _save_preferences(preferences)

    def _message_box(self, text: str, *, style: int = 0x40) -> int:
        import ctypes

        library_name = "windll"
        windll: Any = getattr(ctypes, library_name)
        return int(windll.user32.MessageBoxW(0, text, "usage", style))

    def handle_panel_message(self, message: object) -> list[dict[str, object]] | None:
        if self.stopping.is_set():
            return None
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
            if action == "content_height":
                self._apply_content_height(payload.get("height"))
                return None
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
            elif action == "set_panel_flavor":
                _save_panel_flavor(payload.get("flavor"))
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
                    "hide_grok_section",
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
            elif action == "toggle_window_keeper":
                self.toggle_window_keeper()
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
        from installer import session_hooks, setup_hook

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
        with self._file_event_lock:
            timer = self._file_event_refresh_timer
            self._file_event_refresh_timer = None
        if timer is not None:
            timer.cancel()
        with self._watcher_lock:
            watcher = self._windows_watcher
            self._windows_watcher = None
        if watcher is not None:
            watcher.stop()

        current_thread = threading.current_thread()
        with self.refresh_lock:
            refresh_thread = self._refresh_thread
        for worker in (self._poll_thread, refresh_thread):
            if worker is not None and worker is not current_thread:
                worker.join(3.0)
        if self.icon is not None:
            self.icon.stop()
        if self.window is not None:
            self.window.destroy()


def _menu(controller: _WindowsTrayController) -> Any:
    import pystray

    entries = wintray_menu.entries_for_surface(_menu_model(), wintray_menu.TRAY)
    recovery_items = tuple(
        _tray_menu_entry(pystray, controller, entry) for entry in entries
    )
    return pystray.Menu(
        pystray.MenuItem("Open", controller.show_panel, default=True, visible=False),
        *recovery_items,
    )


def _menu_model() -> tuple[wintray_menu.MenuEntry, ...]:
    return wintray_menu.windows_menu_model(available_panels())


def _menu_checked(controller: _WindowsTrayController, entry: wintray_menu.MenuCommand) -> bool:
    checks = {
        "active_panel": lambda: controller.active_panel_id == entry.argument_value,
        "hide_claude": _hide_claude_enabled,
        "hide_codex": _hide_codex_enabled,
        "hide_agy": _hide_agy_enabled,
        "hide_grok": _hide_grok_enabled,
        "launch_at_login": win_login_item.is_enabled,
        "quota_notifications": _quota_notifications_enabled,
        "window_keeper": _window_keeper_enabled,
        "session_resume": _session_resume_enabled,
        "terse_mode": _terse_mode_enabled,
    }
    return checks[entry.checked_by]() if entry.checked_by is not None else False


def _panel_menu_entry(
    controller: _WindowsTrayController, entry: wintray_menu.MenuEntry
) -> dict[str, object]:
    if isinstance(entry, wintray_menu.MenuSeparator):
        return {"type": "separator"}
    data: dict[str, object] = {
        "i18nKey": entry.i18n_key,
        "label": _t(controller.language, entry.i18n_key),
    }
    if isinstance(entry, wintray_menu.MenuGroup):
        data["action"] = ""
        data["children"] = [_panel_menu_entry(controller, child) for child in entry.children]
        return data
    data["action"] = entry.action
    if entry.checked_by is not None:
        data["checked"] = _menu_checked(controller, entry)
    if entry.argument_name is not None:
        data[entry.argument_name] = entry.argument_value
    return data


def _tray_menu_entry(
    pystray: Any,
    controller: _WindowsTrayController,
    entry: wintray_menu.MenuEntry,
) -> Any:
    if isinstance(entry, wintray_menu.MenuSeparator):
        return pystray.Menu.SEPARATOR
    if isinstance(entry, wintray_menu.MenuGroup):
        children = tuple(_tray_menu_entry(pystray, controller, child) for child in entry.children)
        return pystray.MenuItem(
            _t(controller.language, entry.i18n_key), pystray.Menu(*children)
        )
    action = getattr(controller, entry.action)
    kwargs: dict[str, object] = {"radio": entry.radio}
    if entry.checked_by is not None:
        kwargs["checked"] = lambda _item: _menu_checked(controller, entry)
    if entry.argument_value is not None:
        value = entry.argument_value

        def action(_icon: Any, _item: Any, *, value: str = value) -> Any:
            return getattr(controller, entry.action)(value)

    return pystray.MenuItem(_t(controller.language, entry.i18n_key), action, **kwargs)


def _session_resume_enabled() -> bool:
    try:
        from installer import session_hooks

        return session_hooks.is_resume_enabled()
    except Exception:
        return False


def _terse_mode_enabled() -> bool:
    try:
        from installer import session_hooks

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
    try:
        webview.start(gui="edgechromium", debug=os.environ.get("USAGE_DEBUG") == "1")
    finally:
        controller.stopping.set()
        _release_single_instance_lock()
