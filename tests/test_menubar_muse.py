# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import json
from typing import Any

import pytest

from loaders import muse_quota_probe as probe
from menubar import muse, prefs, state
from panels.payload import _state_payload
from tests.test_muse_quota_probe import quota


@pytest.mark.parametrize(
    "now,latest,stale",
    [
        (2800, 1001, None),
        (2801, 1001, "about 30 minutes ago"),
        (8200, 1001, "about 2 hours ago"),
        (8200, 1000, None),
        (8200, None, None),
    ],
)
def test_stale_requires_newer_session_and_old_cache(
    now: int, latest: int | None, stale: str | None
) -> None:
    result = muse.project_quota(quota(), "en", now, latest_session=latest)
    assert result is not None
    assert result.stale == ({"ageText": stale} if stale else None)
    assert result.session.title == "Session"
    assert result.weekly.title == "Weekly"


@pytest.mark.parametrize("now,expected", [(9999, 25), (10000, 0), (10001, 0), (20000, 0)])
def test_reset_boundary_uses_reset_done(now: int, expected: int) -> None:
    result = muse.project_quota(quota(), "en", now)
    assert result is not None
    assert result.session.display_percent == expected
    assert result.session.percent == 25
    assert result.session.reset_done is (now >= 10000)
    assert result.weekly.display_percent == (0 if now >= 20000 else 75)


def test_unavailable_projection_hides_card(monkeypatch: pytest.MonkeyPatch) -> None:
    assert muse.project_quota(None, "en") is None
    assert muse.load_refresh_result("en") == muse.MuseRefreshResult(None, True)
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse")
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: None)
    assert muse.load_refresh_result("en") == muse.MuseRefreshResult(None, True)


def test_payload_includes_muse_rows_stale_and_visibility() -> None:
    panel = state._empty_state("en")
    payload: dict[str, Any] = json.loads(json.dumps(_state_payload(panel)))
    assert payload["hideMuse"] is True
    assert payload["muse"]["session"]["available"] is False
    projection = muse.project_quota(quota(), "en", 2801, latest_session=1001)
    assert projection is not None
    panel.muse_session, panel.muse_weekly = projection.session, projection.weekly
    panel.muse_stale, panel.hide_muse = projection.stale, False
    payload = json.loads(json.dumps(_state_payload(panel)))
    assert payload["hideMuse"] is False
    assert payload["muse"]["session"]["percent"] == 25
    assert payload["muse"]["weekly"]["percent"] == 75
    assert payload["muse"]["stale"] == {"ageText": "about 30 minutes ago"}


def test_saved_card_order_appends_muse_and_keeps_old_order() -> None:
    assert prefs._quota_card_order({"quota_card_order": ["grok", "codex", "claude", "agy"]}) == (
        "grok",
        "codex",
        "claude",
        "agy",
        "muse",
    )
    assert prefs._hide_muse_enabled({"hide_muse_section": True})
    assert not prefs._hide_muse_enabled({})


def test_shared_cache_visibility_depends_on_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    probe.CACHE_PATH.write_text(json.dumps(quota()))
    assert muse.load_refresh_result("en").projection is None
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse")
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: None)
    result = muse.load_refresh_result("en")
    assert not result.hide_muse
    assert result.projection is not None
