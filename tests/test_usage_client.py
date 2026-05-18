from __future__ import annotations

import asyncio
import json
from pathlib import Path

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
    data, path = result
    assert path == str(usage_path)
    assert data["rate_limits"]["five_hour"]["used_percentage"] == 12


def test_read_status_file_uses_legacy_file_before_token_tracker(
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
    data, path = result
    assert path == str(legacy_path)
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
