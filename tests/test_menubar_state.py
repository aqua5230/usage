# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import codex_loader
import menubar_state
from burn_rate import BurnRateTracker
from history_loader import UsageEntry


def _patch_history_sources(
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
) -> tuple[Path, Path, Path]:
    claude = home / ".claude" / "projects"
    sessions = home / ".codex" / "sessions"
    archived = home / ".codex" / "archived_sessions"
    for root in (claude, sessions, archived):
        root.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(menubar_state, "CLAUDE_PROJECTS_DIR", claude)
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(codex_loader, "ARCHIVED_SESSIONS_DIR", archived)
    monkeypatch.setattr(codex_loader, "LOGS_DB", home / ".codex" / "logs_2.sqlite")
    monkeypatch.setattr(codex_loader, "STATE_DB", home / ".codex" / "state_5.sqlite")
    return claude, sessions, archived


def test_history_sources_fingerprint_uses_claude_projects_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    projects_dir = home / ".claude" / "projects"
    projects_dir.mkdir(parents=True)
    (projects_dir / "project.jsonl").write_text("{}", encoding="utf-8")
    archived_dir = home / ".codex" / "archived_sessions"
    archived_dir.mkdir(parents=True)
    (archived_dir / "archived.jsonl").write_text("{}", encoding="utf-8")
    noise_dir = home / ".claude" / "sessions"
    noise_dir.mkdir(parents=True)
    (noise_dir / "noise.jsonl").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(menubar_state, "CLAUDE_PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", home / ".codex" / "sessions")
    monkeypatch.setattr(codex_loader, "ARCHIVED_SESSIONS_DIR", archived_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", home / ".codex" / "logs_2.sqlite")
    monkeypatch.setattr(codex_loader, "STATE_DB", home / ".codex" / "state_5.sqlite")

    fingerprint = menubar_state.history_sources_fingerprint()

    assert fingerprint[0][0] == str(projects_dir)
    assert fingerprint[0][1] == 1
    assert fingerprint[2][0] == str(archived_dir)
    assert fingerprint[2][1] == 1


def test_history_source_tracker_skips_directory_io_when_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude, _, _ = _patch_history_sources(monkeypatch, tmp_path)
    (claude / "one.jsonl").write_text("{}", encoding="utf-8")
    tracker = menubar_state.HistorySourceTracker(incremental_enabled=True)
    tracker.scan(now=0.0)
    jsonl_calls = 0
    stat_calls = 0

    def count_jsonl(_root: Path) -> tuple[Path, ...]:
        nonlocal jsonl_calls
        jsonl_calls += 1
        return ()

    def count_stat(_path: Path) -> tuple[int, int] | None:
        nonlocal stat_calls
        stat_calls += 1
        return None

    monkeypatch.setattr(menubar_state, "_jsonl_paths", count_jsonl)
    monkeypatch.setattr(menubar_state, "_stat_index_entry", count_stat)

    scan = tracker.scan(now=1.0)

    assert scan.claude_paths == (claude / "one.jsonl",)
    assert jsonl_calls == 0
    # Only the sqlite file sources get re-stat'ed; no per-jsonl stats.
    assert stat_calls == len(menubar_state._history_file_sources())


def test_history_source_tracker_only_stats_dirty_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude, _, _ = _patch_history_sources(monkeypatch, tmp_path)
    dirty = claude / "dirty.jsonl"
    unchanged = claude / "unchanged.jsonl"
    dirty.write_text("old", encoding="utf-8")
    unchanged.write_text("same", encoding="utf-8")
    tracker = menubar_state.HistorySourceTracker(incremental_enabled=True)
    first = tracker.scan(now=0.0)
    dirty.write_text("new content", encoding="utf-8")
    calls: list[Path] = []
    original_stat = menubar_state._stat_index_entry

    def record_stat(path: Path) -> tuple[int, int] | None:
        calls.append(path)
        return original_stat(path)

    monkeypatch.setattr(menubar_state, "_stat_index_entry", record_stat)
    tracker.record_changes({dirty})
    second = tracker.scan(now=1.0)

    assert [path for path in calls if path.suffix == ".jsonl"] == [dirty]
    assert first.fingerprint != second.fingerprint
    assert set(second.claude_paths) == {dirty, unchanged}


def test_history_source_tracker_handles_added_and_deleted_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude, _, _ = _patch_history_sources(monkeypatch, tmp_path)
    removed = claude / "removed.jsonl"
    added = claude / "added.jsonl"
    removed.write_text("old", encoding="utf-8")
    tracker = menubar_state.HistorySourceTracker(incremental_enabled=True)
    tracker.scan(now=0.0)
    removed.unlink()
    added.write_text("new", encoding="utf-8")

    tracker.record_changes({removed, added})
    scan = tracker.scan(now=1.0)

    assert scan.claude_paths == (added,)


def test_history_source_tracker_full_scan_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_history_sources(monkeypatch, tmp_path)
    tracker = menubar_state.HistorySourceTracker(incremental_enabled=True)
    calls: list[float] = []
    original_build = menubar_state._build_history_source_index

    def record_build(now: float) -> menubar_state.HistorySourceIndex:
        calls.append(now)
        return original_build(now)

    monkeypatch.setattr(menubar_state, "_build_history_source_index", record_build)

    tracker.scan(now=0.0)
    tracker.scan(now=1.0)
    tracker.record_changes(set(), needs_full_scan=True)
    tracker.scan(now=2.0)
    tracker.scan(now=2.0 + menubar_state.HISTORY_FULL_SCAN_INTERVAL_S)

    assert calls == [0.0, 2.0, 2.0 + menubar_state.HISTORY_FULL_SCAN_INTERVAL_S]


def test_history_source_tracker_scans_every_time_without_fsevents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_history_sources(monkeypatch, tmp_path)
    tracker = menubar_state.HistorySourceTracker(incremental_enabled=False)
    calls = 0
    original_build = menubar_state._build_history_source_index

    def record_build(now: float) -> menubar_state.HistorySourceIndex:
        nonlocal calls
        calls += 1
        return original_build(now)

    monkeypatch.setattr(menubar_state, "_build_history_source_index", record_build)

    tracker.scan(now=0.0)
    tracker.scan(now=1.0)

    assert calls == 2


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


def test_codex_rows_hides_missing_session_and_uses_weekly_for_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_loader,
        "load_rate_limits",
        lambda: codex_loader.CodexRateLimits(
            five_hour_pct=None,
            five_hour_resets_at=None,
            seven_day_pct=7.0,
            seven_day_resets_at=9_999_999_999.0,
            five_hour_window_minutes=None,
            seven_day_window_minutes=10080.0,
            model="gpt-test",
            updated_at="",
        ),
    )
    trackers = {
        "codex_session": BurnRateTracker(),
        "codex_weekly": BurnRateTracker(),
    }

    rows, menu_pct, _model, _stale = menubar_state.codex_rows(
        mock=False, language="en", burn_rate_trackers=trackers
    )

    assert rows[0].title == ""
    assert rows[1].title == "Weekly"
    assert menu_pct == 7.0
    assert not trackers["codex_session"]._samples


def test_codex_rows_menu_prefers_session_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_loader,
        "load_rate_limits",
        lambda: codex_loader.CodexRateLimits(
            five_hour_pct=12.0,
            five_hour_resets_at=9_999_999_998.0,
            seven_day_pct=7.0,
            seven_day_resets_at=9_999_999_999.0,
            model="gpt-test",
            updated_at="",
        ),
    )
    trackers = {
        "codex_session": BurnRateTracker(),
        "codex_weekly": BurnRateTracker(),
    }

    _rows, menu_pct, _model, _stale = menubar_state.codex_rows(
        mock=False, language="en", burn_rate_trackers=trackers
    )

    assert menu_pct == 12.0


def test_history_load_error_state_none_when_no_reason() -> None:
    assert menubar_state.history_load_error_state(None, "en") is None


def test_history_load_error_state_localizes_reason() -> None:
    state = menubar_state.history_load_error_state("history_load_error_file", "en")

    assert state is not None
    assert state["reasonText"]


def test_file_event_refresh_decision_passes_through_outside_interval() -> None:
    decision = menubar_state.file_event_refresh_decision(130.0, 100.0, False)

    assert decision.refresh_now is True
    assert decision.trailing_delay is None


def test_file_event_refresh_decision_schedules_trailing_inside_interval() -> None:
    decision = menubar_state.file_event_refresh_decision(110.0, 100.0, False)

    assert decision.refresh_now is False
    assert decision.trailing_delay == 20.0


def test_file_event_refresh_decision_merges_into_existing_trailing() -> None:
    decision = menubar_state.file_event_refresh_decision(129.0, 100.0, True)

    assert decision.refresh_now is False
    assert decision.trailing_delay is None


def test_history_cache_reload_decision() -> None:
    fingerprint = (("history", 1, 10.0),)

    assert menubar_state.history_cache_needs_reload(
        None, fingerprint, has_cached_result=False
    )
    assert not menubar_state.history_cache_needs_reload(
        fingerprint, fingerprint, has_cached_result=True
    )
    assert menubar_state.history_cache_needs_reload(
        fingerprint, (("history", 2, 11.0),), has_cached_result=True
    )


def test_project_rows_for_windows_matches_window_boundaries() -> None:
    now = datetime.now(UTC).replace(microsecond=0)

    def entry(project: str, timestamp: datetime, tokens: int) -> UsageEntry:
        return UsageEntry(
            timestamp=timestamp,
            session_id=project,
            message_id=project,
            request_id=project,
            model="test",
            input_tokens=tokens,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            cost_usd=float(tokens),
            project=project,
        )

    rows_24h, rows_7d, rows_30d, rows_all = menubar_state.project_rows_for_windows(
        [
            entry("today", now, 4),
            entry("week", now - timedelta(days=2), 3),
            entry("month", now - timedelta(days=10), 2),
            entry("old", now - timedelta(days=40), 1),
        ],
        now=now,
    )

    assert rows_24h == [("today", 4, 4.0)]
    assert rows_7d == [("today", 4, 4.0), ("week", 3, 3.0)]
    assert rows_30d == [
        ("today", 4, 4.0),
        ("week", 3, 3.0),
        ("month", 2, 2.0),
    ]
    assert rows_all == [
        ("today", 4, 4.0),
        ("week", 3, 3.0),
        ("month", 2, 2.0),
    ]
