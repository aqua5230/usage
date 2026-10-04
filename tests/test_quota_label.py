from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

import prefs
from tests.test_wintray import _state
from wintray import app, quota_label
from wintray.quota_label import TaskbarQuotaLabel, draw_label, taskbar_text_color
from wintray.taskbar_overlay import TaskbarLayout, covers_monitor, label_position


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
            (1436, 1004),
        ),
        (
            (0, 0, 1920, 40),
            (1600, 0, 1920, 40),
            (0, 40, 1920, 1080),
            ((1400, 0, 1500, 40),),
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
    shown: list[object] = []
    hidden: list[int] = []
    paints: list[object] = []
    label = object.__new__(TaskbarQuotaLabel)
    label.hwnd = 25
    label.native = SimpleNamespace(  # type: ignore[assignment]
        layout=lambda: layout,
        fullscreen=lambda _: fullscreen,
        show=lambda *args: shown.append(args),
        hide=hidden.append,
        configure=lambda *args: None,
        paint=lambda *args: paints.append(args),
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
    assert str(updates[-1][0]) == "Claude: 75%"
    controller.toggle_quota_label()
    assert closes == [True]
    assert controller.quota_label is None
    assert prefs._load_preferences()["quota_label_enabled"] is False
    assert prefs._load_preferences()["tray_provider"] == "claude"
    controller.toggle_quota_label()
    assert str(updates[-1][0]) == "Claude: 75%"
    assert prefs._load_preferences()["quota_label_enabled"] is True


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
