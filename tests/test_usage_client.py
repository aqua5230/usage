# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import asyncio
import builtins
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import usage_client
from i18n import _t
from usage_lang import detect_lang

LEGACY_NAME = "usag"


@pytest.fixture(autouse=True)
def isolate_claude_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(usage_client, "_recent_activity_cache", None)
    monkeypatch.setattr(usage_client, "CLAUDE_JSON_FILE", str(tmp_path / ".claude.json"))


def _write_claude_json(path: Path, fetched_at: float) -> None:
    path.write_text(
        json.dumps(
            {
                "cachedUsageUtilization": {
                    "fetchedAtMs": fetched_at * 1000,
                    "utilization": {
                        "five_hour": {
                            "utilization": 3,
                            "resets_at": "2026-07-16T08:29:59.915566+08:00",
                        },
                        "seven_day": {
                            "utilization": 99,
                            "resets_at": "2026-07-17T04:59:59.915591+08:00",
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def test_read_status_file_returns_none_when_both_paths_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(tmp_path / "usage-status.json"))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))

    assert usage_client._read_status_file() is None


def test_read_status_file_skips_bad_json_and_prefers_usage_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    usage_path = tmp_path / "usage-status.json"
    tt_path = tmp_path / "tt-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(usage_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tt_path))

    usage_path.write_text(
        json.dumps({"rate_limits": {"five_hour": {"used_percentage": 12}}}),
        encoding="utf-8",
    )
    tt_path.write_text("{bad json", encoding="utf-8")

    result = usage_client._read_status_file()

    assert result is not None
    data, path, mtime = result
    assert path == str(usage_path)
    assert mtime == pytest.approx(usage_path.stat().st_mtime)
    assert data["rate_limits"]["five_hour"]["used_percentage"] == 12


def test_read_status_file_skips_bad_encoding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A half-written or non-UTF-8 status file must be skipped, not crash the poll loop.
    usage_path = tmp_path / "usage-status.json"
    tt_path = tmp_path / "tt-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(usage_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tt_path))

    usage_path.write_bytes(b"\xff\xfe garbage")
    tt_path.write_text(
        json.dumps({"rate_limits": {"five_hour": {"used_percentage": 7}}}),
        encoding="utf-8",
    )

    result = usage_client._read_status_file()

    assert result is not None
    data, path, _mtime = result
    assert path == str(tt_path)
    assert data["rate_limits"]["five_hour"]["used_percentage"] == 7


def test_read_status_file_prefers_legacy_over_tt_compat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legacy_path = tmp_path / f"{LEGACY_NAME}-status.json"
    tt_path = tmp_path / "tt-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(tmp_path / "usage-status.json"))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(legacy_path))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tt_path))

    legacy_path.write_text(
        json.dumps({"rate_limits": {"five_hour": {"used_percentage": 18}}}),
        encoding="utf-8",
    )
    tt_path.write_text(
        json.dumps({"rate_limits": {"five_hour": {"used_percentage": 7}}}),
        encoding="utf-8",
    )

    result = usage_client._read_status_file()

    assert result is not None
    data, path, mtime = result
    assert path == str(legacy_path)
    assert mtime == pytest.approx(legacy_path.stat().st_mtime)
    assert data["rate_limits"]["five_hour"]["used_percentage"] == 18


def test_read_status_file_returns_none_for_bad_usage_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    usage_path = tmp_path / "usage-status.json"
    tt_path = tmp_path / "tt-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(usage_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tt_path))

    usage_path.write_text("{bad json", encoding="utf-8")

    assert usage_client._read_status_file() is None


def test_read_status_file_logs_bad_json_in_debug_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    usage_path = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(usage_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    monkeypatch.setenv("USAGE_DEBUG", "1")
    usage_path.write_text("{bad json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert usage_client._read_status_file() is None

    assert f"failed to read status file {usage_path}" in caplog.text


def test_build_snapshot_handles_missing_rate_limits_and_clamps_percentages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_700_000_000.0
    monkeypatch.setattr("usage_client.time.time", lambda: now)

    assert usage_client._build_snapshot({}) is None

    snapshot = usage_client._build_snapshot(
        {
            "_received_at_ts": now - 10,
            "rate_limits": {
                "status": "ok",
                "five_hour": {"used_percentage": 180, "resets_at": now + 60},
                "seven_day": {"used_percentage": -3, "resets_at": now + 120},
            },
        }
    )

    assert snapshot is not None
    assert snapshot.current_percent == 100
    assert snapshot.weekly_percent == 0
    assert snapshot.current_status == "ok"
    assert snapshot.polled_at == now - 10


def test_build_snapshot_keeps_missing_weekly_percent_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_700_000_000.0
    monkeypatch.setattr("usage_client.time.time", lambda: now)

    snapshot = usage_client._build_snapshot(
        {
            "rate_limits": {
                "five_hour": {"used_percentage": 42, "resets_at": now + 60},
                "seven_day": {"resets_at": now + 120},
            },
        }
    )

    assert snapshot is not None
    assert snapshot.current_percent == 42
    assert snapshot.weekly_percent is None


def test_build_snapshot_keeps_missing_current_percent_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_700_000_000.0
    monkeypatch.setattr("usage_client.time.time", lambda: now)

    snapshot = usage_client._build_snapshot(
        {
            "rate_limits": {
                "five_hour": {"resets_at": now + 60},
                "seven_day": {"used_percentage": 24, "resets_at": now + 120},
            },
        }
    )

    assert snapshot is not None
    assert snapshot.current_percent is None
    assert snapshot.weekly_percent == 24


def test_build_snapshot_keeps_both_percentages_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_700_000_000.0
    monkeypatch.setattr("usage_client.time.time", lambda: now)

    snapshot = usage_client._build_snapshot(
        {
            "rate_limits": {
                "five_hour": {"used_percentage": 12, "resets_at": now + 60},
                "seven_day": {"used_percentage": 34, "resets_at": now + 120},
            },
        }
    )

    assert snapshot is not None
    assert snapshot.current_percent == 12
    assert snapshot.weekly_percent == 34


def test_build_snapshot_treats_invalid_percentage_values_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_700_000_000.0
    monkeypatch.setattr("usage_client.time.time", lambda: now)

    snapshot = usage_client._build_snapshot(
        {
            "rate_limits": {
                "five_hour": {"used_percentage": "bad", "resets_at": now + 60},
                "seven_day": {"used_percentage": "oops", "resets_at": now + 120},
            },
        }
    )

    assert snapshot is not None
    assert snapshot.current_percent is None
    assert snapshot.weekly_percent is None


def test_fetch_once_mock_returns_success_with_expected_snapshot() -> None:
    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=True).fetch_once())

    assert outcome.state is usage_client.PollState.SUCCESS
    assert outcome.snapshot is not None
    assert outcome.snapshot.current_percent == 50


def test_fetch_once_without_status_file_returns_non_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(tmp_path / "usage-status.json"))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is not usage_client.PollState.SUCCESS
    assert outcome.state is usage_client.PollState.TOKEN_ERROR


def test_fetch_once_uses_claude_json_when_status_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fetched_at = 1_784_144_611.575
    claude_json_path = tmp_path / ".claude.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(tmp_path / "usage-status.json"))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    monkeypatch.setattr(usage_client, "CLAUDE_JSON_FILE", str(claude_json_path))
    monkeypatch.setattr("usage_client.time.time", lambda: fetched_at + 1)
    _write_claude_json(claude_json_path, fetched_at)

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.SUCCESS
    assert outcome.snapshot is not None
    assert outcome.snapshot.data_source == "claude-json"
    assert outcome.snapshot.current_percent == 3
    assert outcome.snapshot.weekly_percent == 99
    assert outcome.snapshot.current_reset_at == pytest.approx(
        datetime.fromisoformat("2026-07-16T08:29:59.915566+08:00").timestamp()
    )
    assert outcome.snapshot.weekly_reset_at == pytest.approx(
        datetime.fromisoformat("2026-07-17T04:59:59.915591+08:00").timestamp()
    )


@pytest.mark.parametrize("status_age", [-1.0, 1.0])
def test_fetch_once_chooses_newest_complete_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status_age: float
) -> None:
    fetched_at = 1_784_144_611.575
    status_path = tmp_path / "usage-status.json"
    claude_json_path = tmp_path / ".claude.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    monkeypatch.setattr(usage_client, "CLAUDE_JSON_FILE", str(claude_json_path))
    monkeypatch.setattr("usage_client.time.time", lambda: fetched_at + 2)
    _write_complete_status(status_path, fetched_at + status_age)
    _write_claude_json(claude_json_path, fetched_at)

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.snapshot is not None
    if status_age >= 0:
        assert outcome.snapshot.data_source == "hook"
        assert outcome.snapshot.current_percent == 12
    else:
        assert outcome.snapshot.data_source == "claude-json"
        assert outcome.snapshot.current_percent == 3


@pytest.mark.parametrize(
    "contents",
    ["{bad json", "{}", '{"cachedUsageUtilization": {}}'],
)
def test_invalid_claude_json_preserves_missing_status_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, contents: str
) -> None:
    claude_json_path = tmp_path / ".claude.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(tmp_path / "usage-status.json"))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    monkeypatch.setattr(usage_client, "CLAUDE_JSON_FILE", str(claude_json_path))
    claude_json_path.write_text(contents, encoding="utf-8")

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.TOKEN_ERROR


def test_invalid_claude_json_preserves_incomplete_status_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status_path = tmp_path / "usage-status.json"
    claude_json_path = tmp_path / ".claude.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    monkeypatch.setattr(usage_client, "CLAUDE_JSON_FILE", str(claude_json_path))
    status_path.write_text('{"foo": "bar"}', encoding="utf-8")
    claude_json_path.write_text("{}", encoding="utf-8")

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.LOADING
    assert outcome.message == "awaiting_rate_limits"


def test_fetch_once_returns_awaiting_rate_limits_when_status_has_no_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status_path = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    status_path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.LOADING
    assert outcome.message == "awaiting_rate_limits"


def test_fetch_once_reuses_parsed_data_and_rebuilds_when_status_mtime_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status_path = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    status_path.write_text(
        json.dumps(
            {
                "_received_at_ts": 1_700_000_000.0,
                "rate_limits": {
                    "five_hour": {"used_percentage": 12, "resets_at": 1_700_000_060.0},
                    "seven_day": {"used_percentage": 34, "resets_at": 1_700_000_120.0},
                },
            }
        ),
        encoding="utf-8",
    )

    calls = 0
    original = usage_client._build_snapshot
    original_open = builtins.open
    open_calls = 0

    def counting_build_snapshot(
        data: dict[str, object],
        *,
        data_source: str = "hook",
    ) -> usage_client.UsageSnapshot | None:
        nonlocal calls
        calls += 1
        return original(data, data_source=data_source)

    def counting_open(*args: Any, **kwargs: Any) -> Any:
        nonlocal open_calls
        open_calls += 1
        return original_open(*args, **kwargs)

    monkeypatch.setattr(usage_client, "_build_snapshot", counting_build_snapshot)
    monkeypatch.setattr(builtins, "open", counting_open)

    client = usage_client.ClaudeUsageClient(mock=False)
    first = asyncio.run(client.fetch_once())
    second = asyncio.run(client.fetch_once())

    assert first.state is usage_client.PollState.SUCCESS
    assert second.state is usage_client.PollState.SUCCESS
    assert second is not first
    assert calls == 2
    assert open_calls == 1


def test_fetch_once_reuses_claude_json_snapshot_until_mtime_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claude_json_path = tmp_path / ".claude.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt.json"))
    monkeypatch.setattr(usage_client, "CLAUDE_JSON_FILE", str(claude_json_path))
    claude_json_path.write_text("{}", encoding="utf-8")
    calls = 0
    original = usage_client._read_claude_json_snapshot

    def counting_read() -> usage_client.UsageSnapshot | None:
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(usage_client, "_read_claude_json_snapshot", counting_read)
    client = usage_client.ClaudeUsageClient(mock=False)

    asyncio.run(client.fetch_once())
    asyncio.run(client.fetch_once())
    current = claude_json_path.stat().st_mtime
    os.utime(claude_json_path, (current + 1, current + 1))
    asyncio.run(client.fetch_once())

    assert calls == 2


def test_fetch_once_recomputes_stale_state_when_status_mtime_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status_path = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    monkeypatch.setattr(usage_client, "CLAUDE_PROJECTS_DIR", tmp_path / "projects")
    received_at = 1_700_000_000.0
    reset_at = received_at + 60
    status_path.write_text(
        json.dumps(
            {
                "_received_at_ts": received_at,
                "rate_limits": {
                    "five_hour": {"used_percentage": 12, "resets_at": reset_at},
                    "seven_day": {"used_percentage": 34, "resets_at": received_at + 120},
                },
            }
        ),
        encoding="utf-8",
    )

    now = received_at + 10
    monkeypatch.setattr("usage_client.time.time", lambda: now)
    client = usage_client.ClaudeUsageClient(mock=False)
    first = asyncio.run(client.fetch_once())

    now = received_at + usage_client.STALE_SECONDS + 60
    second = asyncio.run(client.fetch_once())

    assert first.snapshot is not None
    assert second.snapshot is not None
    assert first.snapshot.is_stale is False
    assert second.snapshot.is_stale is True
    assert second.snapshot.current_percent == 0
    assert second.message == "⚠ usage stale 361m"


def _write_complete_status(path: Path, received_at: float) -> None:
    path.write_text(
        json.dumps(
            {
                "_received_at_ts": received_at,
                "rate_limits": {
                    "five_hour": {
                        "used_percentage": 12,
                        "resets_at": received_at + 7200,
                    },
                    "seven_day": {
                        "used_percentage": 34,
                        "resets_at": received_at + 86400,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _patch_status_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    projects_dir: Path,
) -> Path:
    status_path = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    monkeypatch.setattr(usage_client, "CLAUDE_PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(usage_client, "_recent_activity_cache", None)
    return status_path


def _touch_project_log(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_fetch_once_warns_reinstall_when_recent_activity_and_hook_not_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = 1_700_000_000.0
    projects_dir = tmp_path / "projects"
    status_path = _patch_status_paths(monkeypatch, tmp_path, projects_dir)
    _write_complete_status(status_path, now - usage_client.RECENT_ACTIVITY_SECONDS - 1)
    _touch_project_log(projects_dir / "demo" / "session.jsonl", now - 60)
    monkeypatch.setattr("usage_client.time.time", lambda: now)
    monkeypatch.setattr(usage_client, "current_hook_state", lambda: "none")

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.SUCCESS
    assert outcome.snapshot is not None
    assert outcome.snapshot.current_percent == 12
    assert outcome.snapshot.weekly_percent == 34
    assert outcome.message == usage_client.HOOK_BROKEN_NOT_INSTALLED


def test_fetch_once_warns_restart_when_recent_activity_and_usage_hook_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = 1_700_000_000.0
    projects_dir = tmp_path / "projects"
    status_path = _patch_status_paths(monkeypatch, tmp_path, projects_dir)
    _write_complete_status(status_path, now - usage_client.RECENT_ACTIVITY_SECONDS - 1)
    _touch_project_log(projects_dir / "demo" / "session.jsonl", now - 60)
    monkeypatch.setattr("usage_client.time.time", lambda: now)
    monkeypatch.setattr(usage_client, "current_hook_state", lambda: "us-forwarder")

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.SUCCESS
    assert outcome.snapshot is not None
    assert outcome.snapshot.current_percent == 12
    assert outcome.snapshot.weekly_percent == 34
    assert outcome.message == usage_client.HOOK_BROKEN_RESTART


def test_fetch_once_does_not_warn_without_recent_project_activity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = 1_700_000_000.0
    projects_dir = tmp_path / "projects"
    status_path = _patch_status_paths(monkeypatch, tmp_path, projects_dir)
    _write_complete_status(status_path, now - usage_client.RECENT_ACTIVITY_SECONDS - 1)
    _touch_project_log(
        projects_dir / "demo" / "session.jsonl",
        now - usage_client.RECENT_ACTIVITY_SECONDS - 1,
    )
    monkeypatch.setattr("usage_client.time.time", lambda: now)
    monkeypatch.setattr(usage_client, "current_hook_state", lambda: "none")

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.SUCCESS
    assert outcome.snapshot is not None
    assert outcome.snapshot.current_percent == 12
    assert outcome.snapshot.weekly_percent == 34
    assert outcome.message is None


def test_fetch_once_hints_active_when_status_missing_hook_installed_and_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = 1_700_000_000.0
    projects_dir = tmp_path / "projects"
    _patch_status_paths(monkeypatch, tmp_path, projects_dir)
    _touch_project_log(projects_dir / "demo" / "session.jsonl", now - 60)
    monkeypatch.setattr("usage_client.time.time", lambda: now)
    monkeypatch.setattr(usage_client, "current_hook_state", lambda: "us-direct")

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.TOKEN_ERROR
    assert outcome.message == _t(detect_lang(), "usage_status_missing_active")


def test_fetch_once_uses_generic_missing_message_without_recent_activity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    now = 1_700_000_000.0
    projects_dir = tmp_path / "projects"
    _patch_status_paths(monkeypatch, tmp_path, projects_dir)
    monkeypatch.setattr("usage_client.time.time", lambda: now)
    monkeypatch.setattr(usage_client, "current_hook_state", lambda: "us-direct")

    outcome = asyncio.run(usage_client.ClaudeUsageClient(mock=False).fetch_once())

    assert outcome.state is usage_client.PollState.TOKEN_ERROR
    assert outcome.message == _t(detect_lang(), "usage_status_missing")


def test_recent_project_activity_uses_ttl_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePath:
        def __init__(self, mtime: float) -> None:
            self._mtime = mtime

        def stat(self) -> os.stat_result:
            return os.stat_result((0, 0, 0, 0, 0, 0, 0, self._mtime, self._mtime, self._mtime))

    class FakeProjectsDir:
        def __init__(self) -> None:
            self.calls = 0

        def rglob(self, _pattern: str) -> list[FakePath]:
            self.calls += 1
            return [FakePath(1_700_000_000.0 - 60)]

    now = 1_700_000_000.0
    projects_dir = FakeProjectsDir()
    monkeypatch.setattr(usage_client, "CLAUDE_PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(usage_client, "_recent_activity_cache", None)

    assert usage_client._has_recent_claude_project_activity(now) is True
    assert usage_client._has_recent_claude_project_activity(
        now + usage_client.RECENT_ACTIVITY_CACHE_TTL_SECONDS - 1
    ) is True
    assert projects_dir.calls == 1


def test_recent_project_activity_rescans_after_ttl_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePath:
        def __init__(self, mtime: float) -> None:
            self._mtime = mtime

        def stat(self) -> os.stat_result:
            return os.stat_result((0, 0, 0, 0, 0, 0, 0, self._mtime, self._mtime, self._mtime))

    class FakeProjectsDir:
        def __init__(self) -> None:
            self.calls = 0

        def rglob(self, _pattern: str) -> list[FakePath]:
            self.calls += 1
            return [FakePath(1_700_000_000.0 - 60)]

    now = 1_700_000_000.0
    projects_dir = FakeProjectsDir()
    monkeypatch.setattr(usage_client, "CLAUDE_PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(usage_client, "_recent_activity_cache", None)

    assert usage_client._has_recent_claude_project_activity(now) is True
    assert usage_client._has_recent_claude_project_activity(
        now + usage_client.RECENT_ACTIVITY_CACHE_TTL_SECONDS
    ) is True
    assert projects_dir.calls == 2


def test_cached_claude_json_rezeroes_after_reset_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fetched_at = 1_784_144_611.575
    five_reset = datetime.fromisoformat("2026-07-16T08:29:59.915566+08:00").timestamp()
    seven_reset = datetime.fromisoformat("2026-07-17T04:59:59.915591+08:00").timestamp()
    claude_json_path = tmp_path / ".claude.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(tmp_path / "usage-status.json"))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
    monkeypatch.setattr(usage_client, "CLAUDE_JSON_FILE", str(claude_json_path))
    fake_now = fetched_at + 1
    monkeypatch.setattr("usage_client.time.time", lambda: fake_now)
    _write_claude_json(claude_json_path, fetched_at)

    client = usage_client.ClaudeUsageClient(mock=False)
    first = asyncio.run(client.fetch_once())
    assert first.snapshot is not None
    assert first.snapshot.current_percent == 3
    assert first.snapshot.weekly_percent == 99

    # File untouched, but the five-hour window resets: the cache hit must re-derive
    # expiry-sensitive fields instead of replaying the stale parse.
    fake_now = five_reset + 10
    assert fake_now < seven_reset
    second = asyncio.run(client.fetch_once())
    assert second.snapshot is not None
    assert second.snapshot.current_percent == 0
    assert second.snapshot.weekly_percent == 99
