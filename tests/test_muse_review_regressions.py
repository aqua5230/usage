from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock

import pytest

from loaders import muse_quota_probe as probe
from menubar import muse, notify, state
from panels.catalog import PANEL_SPECS
from quota import window_keeper
from quota.notifications import QuotaNotifier
from tests.test_muse_quota_probe import quota


def test_cache_is_rechecked_after_worker_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    probe.CACHE_PATH.write_text(json.dumps(quota(0)))

    def finish_worker() -> str:
        probe.CACHE_PATH.write_text(json.dumps(quota(4000)))
        return "/fake/muse"

    monkeypatch.setattr(probe, "find_muse", finish_worker)
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: 1)
    monkeypatch.setattr(time, "time", lambda: 4000)
    thread = Mock()
    monkeypatch.setattr(threading, "Thread", thread)
    assert probe.load_quota() == quota(4000)
    thread.assert_not_called()


@pytest.mark.parametrize("channel", ["muse_session", "muse_weekly"])
def test_reset_notifications_use_displayed_usage(channel: str) -> None:
    panel = state._empty_state()
    row = state.QuotaRowState("", 100.0, "", "", (0.0, 0.0, 0.0))
    setattr(panel, channel, row)
    notifier = QuotaNotifier()
    assert [(e.channel, e.kind) for e in notifier.update(notify.notification_channels(panel))] == [
        (channel, "depleted")
    ]
    row.reset_done = True
    assert QuotaNotifier().update(notify.notification_channels(panel)) == []
    assert [(e.channel, e.kind) for e in notifier.update(notify.notification_channels(panel))] == [
        (channel, "restored")
    ]


def test_failed_probe_waits_for_new_session_and_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse")
    latest, clock = [1], [0]
    monkeypatch.setattr(probe, "latest_session_mtime", lambda: latest[0])
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    process = Mock(returncode=0)
    process.communicate.return_value = ("{}", "")
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    thread = Mock()
    monkeypatch.setattr(threading, "Thread", thread)
    probe.load_quota()
    probe._probe_worker("/fake/muse")
    for clock[0] in (1801, 3602):
        probe.load_quota()
    assert thread.call_count == 1
    latest[0] = 2
    clock[0] = 1799
    probe.load_quota()
    assert thread.call_count == 1
    clock[0] = 1800
    probe.load_quota()
    assert thread.call_count == 2


@pytest.mark.parametrize("stubborn", [False, True])
def test_exit_cleanup_terminates_live_probe(
    monkeypatch: pytest.MonkeyPatch, stubborn: bool
) -> None:
    process = Mock()
    process.poll.return_value = None
    if stubborn:
        process.wait.side_effect = [subprocess.TimeoutExpired("fake", 5), 0]
    monkeypatch.setattr(probe, "_probe_process", process, raising=False)
    probe._cleanup_probe()
    process.terminate.assert_called_once()
    assert process.wait.call_args_list[0].kwargs == {"timeout": 5}
    assert process.kill.call_count == int(stubborn)


def test_exit_cleanup_leaves_completed_probe_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock()
    process.poll.return_value = 0
    monkeypatch.setattr(probe, "_probe_process", process, raising=False)
    probe._cleanup_probe()
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


@pytest.mark.parametrize("installed", [False, True])
def test_refresh_scans_sessions_once_or_never(
    monkeypatch: pytest.MonkeyPatch, installed: bool
) -> None:
    probe.CACHE_PATH.write_text(json.dumps(quota(4000)))
    monkeypatch.setattr(probe, "find_muse", lambda: "/fake/muse" if installed else None)
    scan = Mock(return_value=4001)
    monkeypatch.setattr(probe, "latest_session_mtime", scan)
    monkeypatch.setattr(time, "time", lambda: 4001)
    result = muse.load_refresh_result("en")
    assert scan.call_count == int(installed)
    assert result.hide_muse is (not installed)
    if installed:
        assert result.projection is not None
        assert result.projection.stale is None


@pytest.mark.parametrize("missing", [0, 1, 2])
def test_hidden_codex_missing_rows_do_not_change_height(missing: int) -> None:
    spec = PANEL_SPECS[0]
    panel = Mock(**asdict(spec))
    panel.preferred_size.return_value = (364.0, spec.height)
    panel.codex_row_height = 42.0
    value = state._empty_state()
    value.hide_codex = True
    value.hide_agy = value.hide_grok = value.hide_muse = False
    expected = state.popover_dimensions(value, panel)
    for row in (value.codex_session, value.codex_weekly)[:missing]:
        row.title = ""
    assert state.popover_dimensions(value, panel) == expected


def test_global_fixture_isolates_keeper_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert window_keeper.KEEPER_CLAUDE_SETTINGS_PATH.is_relative_to(tmp_path)
    monkeypatch.setattr(subprocess, "run", Mock())
    window_keeper._run_claude_ping("/fake/claude")
    assert json.loads(window_keeper.KEEPER_CLAUDE_SETTINGS_PATH.read_text()) == {
        "disableAllHooks": True
    }


@pytest.mark.parametrize(
    "language,retry,new_usage,menu",
    [
        ("zh-TW", "自動重試", "新用量", "選單"),
        ("en", "automatically", "new usage", "menu"),
        ("zh-CN", "自动重试", "新用量", "菜单"),
        ("ja", "自動", "新しい利用", "メニュー"),
        ("ko", "자동", "새 사용량", "메뉴"),
    ],
)
def test_stale_tooltip_explains_automatic_retry(
    language: str, retry: str, new_usage: str, menu: str
) -> None:
    translations = json.loads((Path(__file__).parents[1] / "i18n.json").read_text())
    text = translations[language]["muse_stale_tooltip"]
    assert retry in text
    assert new_usage in text
    assert menu not in text


def test_process_exit_runs_registered_cleanup() -> None:
    script = """
from unittest.mock import Mock
from loaders import muse_quota_probe as probe
process = Mock()
process.poll.return_value = None
process.terminate.side_effect = lambda: print("terminated")
process.wait.side_effect = lambda **kwargs: print("wait", kwargs["timeout"])
probe._probe_process = process
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        encoding="utf-8",
        timeout=10,
        check=True,
    )
    assert completed.stdout.splitlines() == ["terminated", "wait 5"]


def test_shutdown_prevents_pending_worker_from_launching(monkeypatch: pytest.MonkeyPatch) -> None:
    popen = Mock()
    monkeypatch.setattr(subprocess, "Popen", popen)
    probe._cleanup_probe()
    probe._probe_worker("/fake/muse")
    popen.assert_not_called()


def test_worker_timeout_kills_and_reaps_process(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock(returncode=-9)
    process.poll.return_value = -9
    process.communicate.side_effect = [subprocess.TimeoutExpired("fake", 120), ("", "")]
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    probe._probe_worker("/fake/muse")
    assert process.communicate.call_args_list[0].kwargs == {"timeout": 120}
    process.kill.assert_called_once()
    assert process.communicate.call_count == 2
    assert probe._probe_process is None
    assert not probe._probe_running
