# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import errno
import io
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import usage_statusline


@pytest.fixture(autouse=True)
def _isolate_context_burn_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        usage_statusline,
        "CONTEXT_BURN_FILE",
        str(tmp_path / "usage-context-burn.json"),
    )


def test_save_writes_status_json_with_received_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "usage-status.json"
    now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))

    usage_statusline.save({"rate_limits": {"status": "ok"}}, now)

    data = json.loads(status_file.read_text(encoding="utf-8"))
    assert data["rate_limits"] == {"status": "ok"}
    assert data["_received_at"] == now.isoformat()
    assert data["_received_at_ts"] == now.timestamp()


def test_save_works_without_fcntl_or_msvcrt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(usage_statusline, "LOCK_FILE", str(tmp_path / "usage-status.lock"))
    monkeypatch.setattr(usage_statusline, "fcntl", None)
    monkeypatch.setattr(usage_statusline, "msvcrt", None)

    usage_statusline.save({"rate_limits": {"status": "ok"}}, datetime.now(UTC))

    assert status_file.exists()


def test_acquire_msvcrt_lock_waits_out_a_contended_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: LK_NBLCK gives up instantly, and the caller used to swallow
    # that and run save()'s read-modify-write unlocked — unlike the blocking
    # fcntl.flock on POSIX.
    attempts = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        def locking(self, fd: int, mode: int, nbytes: int) -> None:
            attempts.append(mode)
            if len(attempts) < 3:
                raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(usage_statusline, "msvcrt", FakeMsvcrt())
    monkeypatch.setattr(usage_statusline, "_LOCK_POLL_INTERVAL_S", 0)

    with tempfile.TemporaryFile() as handle:
        assert usage_statusline._acquire_msvcrt_lock(handle.fileno()) is True

    assert len(attempts) == 3


def test_acquire_msvcrt_lock_gives_up_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        def locking(self, fd: int, mode: int, nbytes: int) -> None:
            raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(usage_statusline, "msvcrt", FakeMsvcrt())
    monkeypatch.setattr(usage_statusline, "_LOCK_POLL_INTERVAL_S", 0)
    monkeypatch.setattr(usage_statusline, "_LOCK_TIMEOUT_S", 0.01)

    with tempfile.TemporaryFile() as handle:
        assert usage_statusline._acquire_msvcrt_lock(handle.fileno()) is False


def test_acquire_msvcrt_lock_does_not_spin_when_locking_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        def locking(self, fd: int, mode: int, nbytes: int) -> None:
            attempts.append(mode)
            raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(usage_statusline, "msvcrt", FakeMsvcrt())
    monkeypatch.setattr(usage_statusline, "_LOCK_POLL_INTERVAL_S", 0)

    with tempfile.TemporaryFile() as handle:
        assert usage_statusline._acquire_msvcrt_lock(handle.fileno()) is False

    assert len(attempts) == 1


def test_save_preserves_existing_complete_rate_limits_when_new_data_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "usage-status.json"
    status_file.write_text(json.dumps({
        "rate_limits": {
            "five_hour": {"used_percentage": 11},
            "seven_day": {"used_percentage": 22},
        },
        "_received_at": "old",
        "_received_at_ts": 1,
        "model": {"display_name": "old"},
    }), encoding="utf-8")
    now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))

    usage_statusline.save({
        "model": {"display_name": "new"},
        "rate_limits": {
            "five_hour": {"used_percentage": None},
            "seven_day": {"used_percentage": None},
        },
    }, now)

    data = json.loads(status_file.read_text(encoding="utf-8"))
    assert data["model"] == {"display_name": "new"}
    assert data["rate_limits"] == {
        "five_hour": {"used_percentage": 11},
        "seven_day": {"used_percentage": 22},
    }
    assert data["_received_at"] == now.isoformat()
    assert data["_received_at_ts"] == now.timestamp()


def test_save_overwrites_existing_rate_limits_when_new_data_is_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "usage-status.json"
    status_file.write_text(json.dumps({
        "rate_limits": {
            "five_hour": {"used_percentage": 11},
            "seven_day": {"used_percentage": 22},
        },
    }), encoding="utf-8")
    now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))

    usage_statusline.save({
        "rate_limits": {
            "five_hour": {"used_percentage": 88},
            "seven_day": {"used_percentage": 99},
        },
    }, now)

    data = json.loads(status_file.read_text(encoding="utf-8"))
    assert data["rate_limits"] == {
        "five_hour": {"used_percentage": 88},
        "seven_day": {"used_percentage": 99},
    }
    assert data["_received_at"] == now.isoformat()
    assert data["_received_at_ts"] == now.timestamp()


def _write_prefs(path: Path, prefs: dict[str, Any]) -> None:
    path.write_text(json.dumps(prefs), encoding="utf-8")


def test_read_update_hint_returns_latest_when_fresh_and_newer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    _write_prefs(prefs_file, {
        "last_update_check": {
            "checked_at": 1000.0,
            "current_version": "0.11.3",
            "latest_version": "0.12.0",
            "release_url": "https://x",
        },
    })
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    assert usage_statusline._read_update_hint(1000.0) == "0.12.0"


def test_read_update_hint_returns_none_when_same_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    _write_prefs(prefs_file, {
        "last_update_check": {
            "checked_at": 1000.0,
            "current_version": "0.11.3",
            "latest_version": "0.11.3",
            "release_url": None,
        },
    })
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    assert usage_statusline._read_update_hint(1000.0) is None


def test_read_update_hint_respects_skipped_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    _write_prefs(prefs_file, {
        "update_skipped_version": "0.12.0",
        "last_update_check": {
            "checked_at": 1000.0,
            "current_version": "0.11.3",
            "latest_version": "0.12.0",
            "release_url": "https://x",
        },
    })
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    assert usage_statusline._read_update_hint(1000.0) is None


def test_read_update_hint_returns_none_when_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    _write_prefs(prefs_file, {
        "last_update_check": {
            "checked_at": 1000.0,
            "current_version": "0.11.3",
            "latest_version": "0.12.0",
            "release_url": "https://x",
        },
    })
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    stale = 1000.0 + usage_statusline.UPDATE_HINT_STALE_SECONDS + 1
    assert usage_statusline._read_update_hint(stale) is None


def test_read_update_hint_handles_missing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        usage_statusline, "PREFERENCES_FILE", str(tmp_path / "does-not-exist.json")
    )
    assert usage_statusline._read_update_hint(1000.0) is None


def test_read_update_hint_handles_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    prefs_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    assert usage_statusline._read_update_hint(1000.0) is None


def test_render_skips_bad_utf8_update_preferences_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    prefs_file.write_bytes(b"\xff\xfe{")
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)

    output = usage_statusline.render(
        {
            "model": {"display_name": "Sonnet 4.6"},
            "rate_limits": {
                "five_hour": {"used_percentage": 85},
                "seven_day": {"used_percentage": 33},
            },
            "context_window": {"used_percentage": 12, "context_window_size": 200000},
        },
        datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert output != "usage"
    assert "5h" in output
    assert "7d" in output
    assert "Context" in output
    assert "available" not in output


def test_save_cleans_temp_file_when_atomic_replace_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))

    def fail_replace(src: str, dst: str) -> None:
        _ = src, dst
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        usage_statusline.save({"ok": True}, datetime(2026, 1, 1, tzinfo=UTC))

    assert not status_file.exists()
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("stdin_text", ["", "   \n", "{bad json", "[1, 2, 3]"])
def test_main_ignores_invalid_or_empty_stdin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdin_text: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status_file = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))

    usage_statusline.main()

    assert not status_file.exists()
    captured = capsys.readouterr()
    if stdin_text.strip():
        assert captured.out == "usage\n"
    else:
        assert captured.out == ""


def test_main_writes_valid_json_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status_file = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"rate_limits": {"status": "ok"}}'))

    usage_statusline.main()

    data = json.loads(status_file.read_text(encoding="utf-8"))
    assert data["rate_limits"] == {"status": "ok"}
    assert isinstance(data["_received_at"], str)
    assert isinstance(data["_received_at_ts"], int | float)
    assert capsys.readouterr().out == "usage\n"


def test_main_returns_when_stdin_read_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class BrokenStdin:
        def read(self) -> str:
            raise RuntimeError("read failed")

    status_file = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(sys, "stdin", BrokenStdin())

    usage_statusline.main()

    assert not status_file.exists()
    assert capsys.readouterr().out == ""


def test_main_logs_invalid_json_in_debug_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status_file = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(sys, "stdin", io.StringIO("{bad json"))
    monkeypatch.setenv("USAGE_DEBUG", "1")

    usage_statusline.main()

    captured = capsys.readouterr()
    assert "usage_statusline: invalid stdin JSON" in captured.err
    assert captured.out == "usage\n"
    assert not status_file.exists()


def test_render_outputs_multiline_colored_statusline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload = {
        "model": {"display_name": "Sonnet 4.6"},
        "effort": {"level": "high"},
        "fast_mode": True,
        "context_window": {
            "used_percentage": 12,
            "context_window_size": 200000,
            "total_input_tokens": 123456,
            "total_output_tokens": 7890,
            "current_usage": {
                "input_tokens": 1200,
                "cache_creation_input_tokens": 300,
                "cache_read_input_tokens": 4567,
                "output_tokens": 890,
            },
        },
        "rate_limits": {
            "five_hour": {"used_percentage": 85},
            "seven_day": {"used_percentage": 33},
        },
        "cost": {"total_cost_usd": 38.73, "total_duration_ms": 3723000},
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    assert "\n" in output
    assert "\033[" in output
    assert "■" in output
    assert "5h" in output
    assert "7d" in output
    assert "Context" in output
    assert "Sonnet 4.6" in output
    assert "$" not in output  # cost line removed in v0.10.0


def test_render_skips_bad_rate_limit_percentage_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload = {
        "rate_limits": {
            "five_hour": {"used_percentage": "bad"},
            "seven_day": {"used_percentage": 33},
        },
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    assert output != "usage"
    assert "7d" in output
    assert "5h" not in output


def test_render_skips_bad_context_percentage_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload = {
        "rate_limits": {"seven_day": {"used_percentage": 33}},
        "context_window": {"used_percentage": "bad", "context_window_size": 200000},
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    assert output != "usage"
    assert "7d" in output
    assert "Context" not in output


def test_render_skips_bad_resets_at_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload = {
        "rate_limits": {
            "five_hour": {"used_percentage": 50, "resets_at": "not-a-number"},
            "seven_day": {"used_percentage": 33},
        },
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    assert output != "usage"  # one bad field must not blank the whole line
    assert "5h" in output  # percentage still shown, just no reset countdown


def test_render_appends_clear_nudge_when_context_is_heavy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload = {
        "rate_limits": {"seven_day": {"used_percentage": 33}},
        "context_window": {"used_percentage": 82, "context_window_size": 200000},
        "cost": {"total_cost_usd": 2.7},
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    last_line = output.splitlines()[-1]
    assert "⚠" in last_line
    assert "/clear" in last_line
    assert "82%" in last_line


def test_render_omits_clear_nudge_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload = {
        "rate_limits": {"seven_day": {"used_percentage": 33}},
        "context_window": {"used_percentage": 65, "context_window_size": 200000},
        "cost": {"total_cost_usd": 2.7},
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    assert "⚠" not in output
    assert "/clear" not in output


def test_render_clear_nudge_triggers_early_when_context_burn_is_fast(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    burn_file = tmp_path / "usage-context-burn.json"
    monkeypatch.setattr(usage_statusline, "CONTEXT_BURN_FILE", str(burn_file))
    now = datetime(2026, 1, 1, 12, 1, tzinfo=UTC)
    burn_file.write_text(
        json.dumps({"percent": 50.0, "ts": now.timestamp() - 60.0}),
        encoding="utf-8",
    )
    payload = {
        "rate_limits": {"seven_day": {"used_percentage": 33}},
        "context_window": {"used_percentage": 58, "context_window_size": 200000},
    }

    output = usage_statusline.render(payload, now)

    last_line = output.splitlines()[-1]
    assert "⚠" in last_line
    assert "/clear" in last_line
    assert "58%" in last_line


def test_render_clear_nudge_keeps_default_threshold_when_context_burn_is_slow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    burn_file = tmp_path / "usage-context-burn.json"
    monkeypatch.setattr(usage_statusline, "CONTEXT_BURN_FILE", str(burn_file))
    now = datetime(2026, 1, 1, 12, 1, tzinfo=UTC)
    burn_file.write_text(
        json.dumps({"percent": 64.0, "ts": now.timestamp() - 60.0}),
        encoding="utf-8",
    )
    payload = {
        "rate_limits": {"seven_day": {"used_percentage": 33}},
        "context_window": {"used_percentage": 65, "context_window_size": 200000},
    }

    output = usage_statusline.render(payload, now)

    assert "⚠" not in output
    assert "/clear" not in output


def test_render_clear_nudge_keeps_default_threshold_without_context_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload = {
        "rate_limits": {"seven_day": {"used_percentage": 33}},
        "context_window": {"used_percentage": 65, "context_window_size": 200000},
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    assert "⚠" not in output
    assert "/clear" not in output


def test_render_clear_nudge_resets_to_default_threshold_after_large_context_drop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    burn_file = tmp_path / "usage-context-burn.json"
    monkeypatch.setattr(usage_statusline, "CONTEXT_BURN_FILE", str(burn_file))
    now = datetime(2026, 1, 1, 12, 1, tzinfo=UTC)
    burn_file.write_text(
        json.dumps({"percent": 80.0, "ts": now.timestamp() - 60.0}),
        encoding="utf-8",
    )
    payload = {
        "rate_limits": {"seven_day": {"used_percentage": 33}},
        "context_window": {"used_percentage": 65, "context_window_size": 200000},
    }

    output = usage_statusline.render(payload, now)

    assert "⚠" not in output
    assert "/clear" not in output
    assert json.loads(burn_file.read_text(encoding="utf-8"))["percent"] == 65


def test_render_clear_nudge_ignores_malformed_context_burn_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    burn_file = tmp_path / "usage-context-burn.json"
    monkeypatch.setattr(usage_statusline, "CONTEXT_BURN_FILE", str(burn_file))
    burn_file.write_text("not json", encoding="utf-8")
    payload = {
        "rate_limits": {"seven_day": {"used_percentage": 33}},
        "context_window": {"used_percentage": 65, "context_window_size": 200000},
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "⚠" not in output
    assert "/clear" not in output


def test_render_clear_nudge_drops_cost_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload = {
        "context_window": {"used_percentage": 90, "context_window_size": 200000},
    }

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    last_line = output.splitlines()[-1]
    assert "/clear" in last_line
    assert "$" not in last_line


def test_main_prints_fallback_when_render_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status_file = tmp_path / "usage-status.json"
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"model": {"display_name": "Sonnet"}}'))

    def fail_render(data: dict[str, object], now: datetime) -> str:
        _ = data, now
        raise RuntimeError("render failed")

    monkeypatch.setattr(usage_statusline, "render", fail_render)

    usage_statusline.main()

    assert status_file.exists()
    assert capsys.readouterr().out == "usage\n"
