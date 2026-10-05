from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

import i18n
import prefs
from tests.test_wintray import _state
from wintray import app, quota_label, taskbar_overlay
from wintray.quota_label import TaskbarQuotaLabel, draw_label, taskbar_text_color
from wintray.taskbar_overlay import TaskbarLayout, covers_monitor, intersects, label_position


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_overlay_rejects_non_windows_before_loading_native_libraries(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(taskbar_overlay, "sys", SimpleNamespace(platform=platform))
    with pytest.raises(RuntimeError, match="requires Windows"):
        taskbar_overlay.TaskbarOverlay()


def test_click_returns_without_waiting_for_panel_and_coalesces_busy_clicks() -> None:
    label = object.__new__(TaskbarQuotaLabel)
    label.forms = SimpleNamespace(MouseButtons=SimpleNamespace(Left=1))  # type: ignore[assignment]
    label._closed = threading.Event()
    label._action_lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()
    callback_threads: list[int] = []

    def panel_action() -> None:
        callback_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(2)

    label._open_panel = panel_action
    try:
        label._on_click(None, SimpleNamespace(Button=1))
        assert entered.wait(1)
        assert len(callback_threads) == 1
        assert callback_threads[0] != threading.get_ident()
        label._on_click(None, SimpleNamespace(Button=1))
        assert len(callback_threads) == 1
    finally:
        release.set()
    assert label._action_lock.acquire(timeout=1)
    label._action_lock.release()
    # Closing a label also prevents queued/late click events from reopening it.
    label._closed.set()
    label._on_click(None, SimpleNamespace(Button=1))
    assert len(callback_threads) == 1


def test_panel_action_failure_releases_click_guard(caplog: pytest.LogCaptureFixture) -> None:
    label = object.__new__(TaskbarQuotaLabel)
    label._closed = threading.Event()
    label._action_lock = threading.Lock()
    label._action_lock.acquire()

    def fail() -> None:
        raise RuntimeError("WebView is closing")

    label._open_panel = fail
    label._run_panel_action()
    assert not label._action_lock.locked()
    assert "Unable to open the panel" in caplog.text


@pytest.mark.parametrize(
    ("taskbar", "tray", "work", "occupied", "expected"),
    [
        ((0, 1040, 1920, 1080), (1600, 1040, 1920, 1080), (0, 0, 1920, 1040), (), (1436, 1044)),
        ((0, 0, 1920, 40), (1600, 0, 1920, 40), (0, 40, 1920, 1080), (), (1436, 4)),
        ((-1920, 1040, 0, 1080), (-320, 1040, 0, 1080), (-1920, 0, 0, 1040), (), (-484, 1044)),
        (
            (0, 1040, 1920, 1080),
            (1600, 1040, 1920, 1080),
            (0, 0, 1920, 1040),
            ((1400, 1040, 1500, 1080),),
            (1236, 1044),
        ),
        (
            (0, 0, 1920, 40),
            (1600, 0, 1920, 40),
            (0, 40, 1920, 1080),
            ((1400, 0, 1500, 40),),
            (1236, 4),
        ),
        (
            (0, 1040, 1920, 1080),
            (1600, 1040, 1920, 1080),
            (0, 0, 1920, 1040),
            ((0, 1040, 1600, 1080),),
            (1436, 1004),
        ),
        (
            (0, 0, 1920, 40),
            (1600, 0, 1920, 40),
            (0, 40, 1920, 1080),
            ((0, 0, 1600, 40),),
            (1436, 44),
        ),
        ((0, 0, 48, 1080), (0, 800, 48, 1080), (48, 0, 1920, 1080), (), (52, 764)),
        ((1872, 0, 1920, 1080), (1872, 800, 1920, 1080), (0, 0, 1872, 1080), (), (1708, 764)),
    ],
)
def test_label_placement_avoids_buttons_and_handles_taskbar_edges(
    taskbar: tuple[int, int, int, int],
    tray: tuple[int, int, int, int],
    work: tuple[int, int, int, int],
    occupied: tuple[tuple[int, int, int, int], ...],
    expected: tuple[int, int],
) -> None:
    assert label_position(taskbar, tray, work, (160, 32), occupied) == expected


@pytest.mark.parametrize("scale", [1.0, 1.5])
@pytest.mark.parametrize("offset", [0, -1920])
def test_label_moves_left_of_weather_and_buttons(scale: float, offset: int) -> None:
    def rect(left: int, top: int, right: int, bottom: int) -> tuple[int, int, int, int]:
        return (
            round((left + offset) * scale),
            round(top * scale),
            round((right + offset) * scale),
            round(bottom * scale),
        )

    taskbar = rect(0, 1040, 1920, 1080)
    tray = rect(1633, 1040, 1920, 1080)
    work = rect(0, 0, 1920, 1040)
    weather = rect(1515, 1040, 1625, 1080)
    button = rect(1390, 1040, 1500, 1080)
    size = (round(81 * scale), round(32 * scale))
    gap = round(4 * scale)
    for occupied in ((weather,), (weather, button), (button, weather)):
        x, y = label_position(taskbar, tray, work, size, occupied, gap)
        label = (x, y, x + size[0], y + size[1])
        assert taskbar[0] <= x and taskbar[1] <= y
        assert label[3] <= taskbar[3]
        assert label[2] == min(obstacle[0] for obstacle in occupied) - gap
        assert not any(intersects(label, obstacle) for obstacle in occupied)


def test_native_widgets_include_only_visible_nonempty_dynamic_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = object.__new__(taskbar_overlay.TaskbarOverlay)
    taskbar = 1 << 34
    children = [taskbar + i for i in range(1, 7)]
    classes = dict(
        zip(
            children,
            (
                "DynamicContent2",
                "DynamicContent1",
                "DynamicContent3",
                "DynamicContent4",
                "TrayNotifyWnd",
                "DynamicContent",
            ),
            strict=True,
        )
    )
    visible = set(children) - {children[1]}
    bounds = {child: (1515, 1040, 1625, 1080) for child in children}
    bounds[children[2]] = (0, 0, 0, 0)

    def find(parent: int, after: int | None, _cls: object, _title: object) -> int | None:
        assert parent == taskbar
        index = children.index(after) + 1 if after is not None else 0
        return children[index] if index < len(children) else None

    def name(hwnd: int, buffer: Any, _length: int) -> int:
        buffer.value = classes[hwnd]
        return len(buffer.value)

    native.user = SimpleNamespace(  # type: ignore[assignment]
        FindWindowExW=find, GetClassNameW=name, IsWindowVisible=lambda hwnd: hwnd in visible
    )
    monkeypatch.setattr(
        native, "window_rect", lambda hwnd: None if hwnd == children[3] else bounds[hwnd]
    )
    assert native.widget_rects(taskbar) == (bounds[children[0]], bounds[children[5]])
    visible.clear()
    assert native.widget_rects(taskbar) == ()
    children.clear()  # Explorer can remove all its children while rebuilding.
    assert native.widget_rects(taskbar) == ()


def test_label_image_has_transparent_background_without_a_dark_outline() -> None:
    pytest.importorskip("PIL", reason="Pillow is a Windows-only extra")
    image = draw_label("Codex: 92%", (245, 247, 250, 255))
    assert image.mode == "RGBA"
    assert image.getchannel("A").getpixel((0, 0)) == 1
    assert image.getchannel("A").getpixel((image.width - 1, image.height - 1)) == 1
    colors = {color for _count, color in image.getcolors(image.width * image.height) or []}
    assert (245, 247, 250, 255) in colors
    assert (24, 30, 40, 255) not in colors
    assert image.width > image.height * 2
    scaled = draw_label("Codex: 92%", (245, 247, 250, 255), 2)
    assert scaled.height == image.height * 2
    # Font hinting rounds individual glyph widths differently at each size.
    assert scaled.width == pytest.approx(image.width * 2, rel=0.05)


def test_fullscreen_detection_distinguishes_maximized_and_other_monitors() -> None:
    assert covers_monitor((0, 0, 1920, 1080), (0, 0, 1920, 1080))
    assert not covers_monitor((0, 0, 1920, 1040), (0, 0, 1920, 1080))
    assert not covers_monitor((-1920, 0, 0, 1080), (0, 0, 1920, 1080))


def test_text_uses_theme_contrast_and_low_quota_colors() -> None:
    assert taskbar_text_color(8, False) == (242, 242, 242, 255)
    assert taskbar_text_color(8, True) == (32, 33, 36, 255)
    assert taskbar_text_color(None, True) == taskbar_text_color(8, True)
    assert taskbar_text_color(85, False) == (255, 105, 97, 255)
    assert taskbar_text_color(60, True) == (133, 82, 0, 255)


def test_label_hides_for_fullscreen_and_auto_hide_then_restores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("PIL", reason="Pillow is a Windows-only extra")
    layout = TaskbarLayout(
        12,
        (0, 1040, 1920, 1080),
        (1600, 1040, 1920, 1080),
        (0, 0, 1920, 1040),
        (0, 0, 1920, 1080),
        1,
        True,
    )
    fullscreen = False
    shown: list[Any] = []
    hidden: list[int] = []
    paints: list[object] = []
    widgets: tuple[tuple[int, int, int, int], ...] = ()
    label = object.__new__(TaskbarQuotaLabel)
    label.hwnd = 25
    label.native = SimpleNamespace(  # type: ignore[assignment]
        layout=lambda: layout,
        fullscreen=lambda _: fullscreen,
        show=lambda *args: shown.append(args),
        hide=hidden.append,
        configure=lambda *args: None,
        paint=lambda *args: paints.append(args),
        widget_rects=lambda _: widgets,
    )
    label.obstacles = SimpleNamespace(hwnd=0, snapshot=(12, ()))  # type: ignore[assignment]
    label._last = None
    label._image = None
    label._text = "Codex: 92%"
    label._used = 8
    monkeypatch.setattr(quota_label, "_light_taskbar", lambda: False)
    label._refresh()
    assert len(shown) == len(paints) == 1
    fullscreen = True
    label._refresh()
    assert hidden == [25]
    assert len(shown) == 1
    fullscreen = False
    layout = replace(layout, visible=False)
    label._refresh()
    assert hidden == [25, 25]
    layout = replace(layout, visible=True, scale=1.5)
    label._refresh()
    assert len(shown) == len(paints) == 2
    assert label._image is not None and label._image.height == 48
    layout = replace(layout, rect=(0, 1020, 1920, 1080), work=(0, 0, 1920, 1020))
    widgets = ((1450, 1040, 1600, 1080),)
    label._refresh()
    position = shown[-1][1]
    assert position[0] + label._image.width <= widgets[0][0]
    widgets = ()
    label._refresh()
    assert shown[-1][1][0] > position[0]
    layout = replace(layout, hwnd=13)
    label._refresh()
    assert shown[-1][1][1] < layout.rect[1]
    label.obstacles.snapshot = (13, ())
    label._refresh()
    assert shown[-1][1][1] >= layout.rect[1]


def test_label_follows_provider_quota_and_persisted_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    updates: list[tuple[object, ...]] = []
    closes: list[bool] = []
    label = SimpleNamespace(
        update=lambda *args: updates.append(args), close=lambda: closes.append(True)
    )
    monkeypatch.setattr(app, "TaskbarQuotaLabel", lambda callback: label)
    prefs._save_preferences({"quota_label_enabled": True, "tray_provider": "codex"})
    controller = app._WindowsTrayController(mock=True, interval=60)
    controller.window = SimpleNamespace()
    controller.latest_state = replace(
        _state(),
        codex_session=replace(_state().codex_session, title="", percent=None),
        codex_weekly=replace(_state().codex_weekly, percent=8),
    )
    controller.on_loaded()
    assert str(updates[-1][0]) == "Codex: 92%"
    assert updates[-1][1] == 8
    assert str(updates[-1][2]).startswith("Codex Weekly: 8%")
    controller.set_tray_provider("claude")
    assert str(updates[-1][0]) == "Claude Code: 75%"
    controller.toggle_quota_label()
    assert closes == [True]
    assert controller.quota_label is None
    assert prefs._load_preferences()["quota_label_enabled"] is False
    assert prefs._load_preferences()["tray_provider"] == "claude"
    controller.toggle_quota_label()
    assert str(updates[-1][0]) == "Claude Code: 75%"
    assert prefs._load_preferences()["quota_label_enabled"] is True


@pytest.mark.parametrize("language", ["en", "zh-TW", "zh-CN", "ja", "ko"])
@pytest.mark.parametrize(("provider", "name"), [("claude", "Claude Code"), ("codex", "Codex")])
@pytest.mark.parametrize(
    ("used", "available", "expected"),
    [(8, True, "92%"), (None, True, "--"), (8, False, "--"), (0, True, "100%"), (100, True, "0%")],
)
def test_label_formats_remaining_and_unknown_quota_in_every_language(
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    provider: str,
    name: str,
    used: float | None,
    available: bool,
    expected: str,
) -> None:
    updates: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        app,
        "TaskbarQuotaLabel",
        lambda _: SimpleNamespace(update=lambda *args: updates.append(args)),
    )
    prefs._save_preferences({"quota_label_enabled": True, "tray_provider": provider})
    controller = app._WindowsTrayController(mock=True, interval=60)
    controller.language = language
    state = _state()
    row = replace(state.claude_session, percent=used, available=available)
    controller.latest_state = replace(state, claude_session=row, codex_session=row)
    controller._update_quota_label_on_ui_thread()
    assert updates[-1][0] == f"{name}: {expected}"
    assert updates[-1][1] == (used if available else None)


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_label_uses_localized_provider_and_format_templates(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    table = i18n._load_i18n_bundle()["ja"]
    monkeypatch.setitem(table, f"{provider}_name", "翻訳された名前")
    monkeypatch.setitem(table, "quota_label_format", "{value}% · {provider}")
    monkeypatch.setitem(table, "quota_label_unknown", "不明 · {provider}")
    updates: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        app,
        "TaskbarQuotaLabel",
        lambda _: SimpleNamespace(update=lambda *args: updates.append(args)),
    )
    prefs._save_preferences({"quota_label_enabled": True, "tray_provider": provider})
    controller = app._WindowsTrayController(mock=True, interval=60)
    controller.language = "ja"
    controller.latest_state = _state()
    controller._update_quota_label_on_ui_thread()
    assert str(updates[-1][0]) == "75% · 翻訳された名前"
    unknown = replace(_state().claude_session, percent=None)
    controller.latest_state = replace(_state(), claude_session=unknown, codex_session=unknown)
    controller._update_quota_label_on_ui_thread()
    assert str(updates[-1][0]) == "不明 · 翻訳された名前"


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_selected_label_and_tray_show_full_remaining_quota_after_reset(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    updates: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        app,
        "TaskbarQuotaLabel",
        lambda _: SimpleNamespace(update=lambda *args: updates.append(args)),
    )
    prefs._save_preferences({"quota_label_enabled": True, "tray_provider": provider})
    controller = app._WindowsTrayController(mock=True, interval=60)
    row = replace(_state().claude_session, percent=85, reset_done=True)
    controller.latest_state = replace(_state(), claude_session=row, codex_session=row)
    controller._update_quota_label_on_ui_thread()
    assert controller._tray_percent() == 0
    assert str(updates[-1][0]).endswith(": 100%")
    assert row.percent == 85  # Notifications retain the actual observation.


def test_taskbar_label_replaces_numeric_icon_and_toggle_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefs._save_preferences({"quota_label_enabled": True, "tray_provider": "codex"})
    controller = app._WindowsTrayController(mock=True, interval=60)
    controller.latest_state = _state()
    controller.icon = SimpleNamespace(icon=None, title=None, update_menu=lambda: None)
    plain_icon = object()
    monkeypatch.setattr(app, "draw_app_icon", lambda: plain_icon)
    monkeypatch.setattr(app, "draw_tray_icon", lambda percent: "numeric")
    controller._update_tray()
    assert controller.icon.icon is plain_icon
    controller.toggle_quota_label()
    assert controller.icon.icon == "numeric"
    controller.toggle_quota_label()
    assert controller.icon.icon is plain_icon


def test_quit_closes_label(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    controller = app._WindowsTrayController(mock=True, interval=60)
    monkeypatch.setattr(
        controller, "quota_label", SimpleNamespace(close=lambda: closed.append(True))
    )
    controller.quit()
    assert closed == [True]
    assert controller.quota_label is None
