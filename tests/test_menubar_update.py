from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from menubar import update
from updates import checker as update_checker
from updates import gate as update_gate


def test_due_background_update_checks_and_saves_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise the real update helper without a real GitHub request.
    monkeypatch.setattr(update, "_current_version", lambda: "0.0.0")
    monkeypatch.setattr(update, "_load_preferences", lambda: {})
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
    update.check_update_in_background(cast(Any, app))
    assert calls == ["0.0.0"]
    assert len(saved) == 1
