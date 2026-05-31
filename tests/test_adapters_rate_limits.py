from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters import rate_limits


def _write_status(path: Path, body: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_load_rate_limits_skips_bad_utf8_status_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "usage-status.json"
    status_path.write_bytes(b"\xff\xfe not utf-8\n")
    monkeypatch.setattr(rate_limits, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(rate_limits, "LEGACY_STATUS_FILE", str(tmp_path / "missing-legacy.json"))
    monkeypatch.setattr(rate_limits, "TT_STATUS_FILE", str(tmp_path / "missing-tt.json"))

    assert rate_limits.load_rate_limits() is None


def test_load_rate_limits_accepts_numeric_string_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "usage-status.json"
    _write_status(
        status_path,
        {
            "rate_limits": {
                "five_hour": {"used_percentage": "25", "resets_at": "9999999999"},
                "seven_day": {"used_percentage": "70.0", "resets_at": "9999999998"},
            },
            "model": {"display_name": "Claude Test"},
            "_received_at": "2026-05-31T00:00:00Z",
        },
    )
    monkeypatch.setattr(rate_limits, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(rate_limits, "LEGACY_STATUS_FILE", str(tmp_path / "missing-legacy.json"))
    monkeypatch.setattr(rate_limits, "TT_STATUS_FILE", str(tmp_path / "missing-tt.json"))

    result = rate_limits.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 25.0
    assert result.five_hour_resets_at == 9999999999
    assert result.seven_day_pct == 70.0
    assert result.seven_day_resets_at == 9999999998
    assert result.model == "Claude Test"
    assert result.updated_at == "2026-05-31T00:00:00Z"


def test_load_rate_limits_clears_expired_percentage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "usage-status.json"
    now_ts = datetime.now(UTC).timestamp()
    _write_status(
        status_path,
        {
            "rate_limits": {
                "five_hour": {"used_percentage": "25", "resets_at": str(now_ts - 60)},
                "seven_day": {"used_percentage": "70", "resets_at": str(now_ts + 60)},
            }
        },
    )
    monkeypatch.setattr(rate_limits, "STATUS_FILE", str(status_path))
    monkeypatch.setattr(rate_limits, "LEGACY_STATUS_FILE", str(tmp_path / "missing-legacy.json"))
    monkeypatch.setattr(rate_limits, "TT_STATUS_FILE", str(tmp_path / "missing-tt.json"))

    result = rate_limits.load_rate_limits()

    assert result is not None
    assert result.five_hour_pct == 0.0
    assert result.five_hour_resets_at == int(now_ts - 60)
    assert result.seven_day_pct == 70.0
