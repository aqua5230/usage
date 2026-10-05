from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from menubar import update
from updates import checker as update_checker
from updates import gate as update_gate


@pytest.mark.parametrize(
    ("enabled", "manual", "expected_calls"),
    [(False, False, 0), (True, False, 1), (False, True, 1)],
)
def test_background_update_respects_preference_without_network(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, manual: bool, expected_calls: int
) -> None:
    # Only the version supplier needs AppKit. Exercise the real update helper
    # on every platform, with neither PyObjC nor a real GitHub request.
    app_module = ModuleType("menubar.app")
    monkeypatch.setattr(app_module, "_current_version", lambda: "0.0.0", raising=False)
    monkeypatch.setitem(sys.modules, "menubar.app", app_module)
    monkeypatch.setattr(update, "_load_preferences", lambda: {"auto_update_check": enabled})
    saved: list[object] = []
    monkeypatch.setattr(update, "_save_preferences", saved.append)
    monkeypatch.setattr(update_gate, "auto_check_is_due", lambda _: True)
    monkeypatch.setattr(update_gate, "dismissed_recently", lambda _: False)
    calls: list[str] = []

    def check(version: str) -> SimpleNamespace:
        calls.append(version)
        return SimpleNamespace(failed=False, release=None)

    monkeypatch.setattr(update_checker, "check_latest_release_result", check)
    app = SimpleNamespace(performSelectorOnMainThread_withObject_waitUntilDone_=lambda *args: None)
    update.check_update_in_background(
        cast(Any, app), manual=manual, ignore_cooldown=False, ignore_skipped=False
    )
    assert calls == ["0.0.0"] * expected_calls
    assert len(saved) == expected_calls
