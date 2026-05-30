from __future__ import annotations

import asyncio
import builtins
import json
import logging
from pathlib import Path
from typing import Any

import pytest

import usage_client

LEGACY_NAME = "usag"


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


def test_fetch_once_recomputes_stale_state_when_status_mtime_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    status_path = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(usage_client, "LEGACY_STATUS_FILE", str(tmp_path / f"{LEGACY_NAME}.json"))
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(tmp_path / "tt-status.json"))
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
