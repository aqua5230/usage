from __future__ import annotations

from datetime import UTC, datetime, timedelta

import menubar_state


def test_codex_stale_state_hides_fresh_data() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    updated_at = (now - timedelta(seconds=900)).isoformat()

    assert menubar_state.codex_stale_state(updated_at, now.timestamp(), "en") is None


def test_codex_stale_state_uses_minutes_for_recent_stale_data() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    updated_at = (now - timedelta(minutes=30)).isoformat()

    state = menubar_state.codex_stale_state(updated_at, now.timestamp(), "en")

    assert state is not None
    assert state["ageText"]


def test_codex_stale_state_uses_hours_for_old_stale_data() -> None:
    now = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    updated_at = (now - timedelta(hours=2, minutes=30)).isoformat()

    state = menubar_state.codex_stale_state(updated_at, now.timestamp(), "en")

    assert state is not None
    assert state["ageText"]


def test_codex_stale_state_hides_missing_timestamp() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC).timestamp()

    assert menubar_state.codex_stale_state("", now, "en") is None
