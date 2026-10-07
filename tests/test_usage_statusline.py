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
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from usage_hooks import usage_statusline


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (999, "999"),
        (1_000, "1k"),
        (999_499, "999k"),
        (999_500, "1.0M"),
        (999_999, "1.0M"),
        (1_000_000, "1.0M"),
        (1_500_000, "1.5M"),
        (999_949_999, "999.9M"),
        (999_950_000, "1.0B"),
        (1_500_000_000, "1.5B"),
        (0, "0"),
        (-5, "-5"),
    ],
)
def test_fmt_tokens_handles_unit_rounding_boundaries(value: int, expected: str) -> None:
    assert usage_statusline.fmt_tokens(value) == expected


def test_get_width_uses_conout_width_after_windows_pipe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_oserror(fd: int) -> os.terminal_size:
        _ = fd
        raise OSError("not a terminal")

    monkeypatch.setattr(
        usage_statusline,
        "os",
        SimpleNamespace(name="nt", get_terminal_size=raise_oserror),
    )
    monkeypatch.setattr(usage_statusline, "_conout_columns", lambda: 220)

    assert usage_statusline.get_width() == 216


@pytest.mark.parametrize("columns", (None, 0))
def test_get_width_keeps_default_when_conout_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    columns: int | None,
) -> None:
    def raise_oserror(fd: int) -> os.terminal_size:
        _ = fd
        raise OSError("not a terminal")

    monkeypatch.setattr(
        usage_statusline,
        "os",
        SimpleNamespace(name="nt", get_terminal_size=raise_oserror),
    )
    monkeypatch.setattr(usage_statusline, "_conout_columns", lambda: columns)

    assert usage_statusline.get_width() == 116


def test_get_width_does_not_probe_conout_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_oserror(fd: int) -> os.terminal_size:
        _ = fd
        raise OSError("not a terminal")

    def fail_probe() -> int:
        raise AssertionError("CONOUT$ probe should not run off Windows")

    monkeypatch.setattr(
        usage_statusline,
        "os",
        SimpleNamespace(name="posix", get_terminal_size=raise_oserror),
    )
    monkeypatch.setattr(usage_statusline, "_conout_columns", fail_probe)

    assert usage_statusline.get_width() == 116


def test_statusline_detect_lang_uses_windows_system_lang_when_env_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("USAGE_LANG", "TT_LANG", "LANG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(usage_statusline, "_windows_system_lang", lambda: "zh_TW")

    assert usage_statusline._statusline_detect_lang({}) == "en"
    assert usage_statusline._statusline_detect_lang() == "zh-TW"


def test_statusline_detect_lang_prefers_usage_lang_over_windows_system_lang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(usage_statusline, "_windows_system_lang", lambda: "zh_TW")

    assert usage_statusline._statusline_detect_lang({"USAGE_LANG": "ja"}) == "ja"


def test_statusline_detect_lang_ignores_lang_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert usage_statusline._statusline_detect_lang({"LANG": "zh_TW.UTF-8"}) == "en"
    assert (
        usage_statusline._statusline_detect_lang({"USAGE_LANG": "ja", "LANG": "zh_TW.UTF-8"})
        == "ja"
    )


def test_statusline_windows_system_lang_is_empty_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(usage_statusline, "os", SimpleNamespace(name="posix"))

    assert usage_statusline._windows_system_lang() == ""


def test_windows_output_reconfigures_both_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stream:
        def __init__(self) -> None:
            self.encodings: list[str] = []

        def reconfigure(self, *, encoding: str) -> None:
            self.encodings.append(encoding)

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr(usage_statusline, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    usage_statusline._configure_windows_utf8_output()

    assert stdout.encodings == ["utf-8"]
    assert stderr.encodings == ["utf-8"]


def test_windows_output_tolerates_replaced_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(usage_statusline, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sys, "stdout", object())
    monkeypatch.setattr(sys, "stderr", object())

    usage_statusline._configure_windows_utf8_output()


@pytest.fixture(autouse=True)
def _isolate_context_burn_and_preferences_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Isolate the context-burn, mix and preferences files for each test."""
    monkeypatch.setattr(usage_statusline, "MIX_DIR", str(tmp_path / "mix"))
    monkeypatch.setattr(
        usage_statusline,
        "CONTEXT_BURN_FILE",
        str(tmp_path / "usage-context-burn.json"),
    )
    monkeypatch.setattr(
        usage_statusline,
        "PREFERENCES_FILE",
        str(tmp_path / "usage-preferences.json"),
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


@pytest.mark.skipif(
    vars(usage_statusline).get("fcntl") is None,
    reason="requires POSIX fcntl",
)
def test_exclusive_lock_times_out_when_another_process_holds_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "usage-status.lock"
    fcntl = vars(usage_statusline).get("fcntl")
    assert fcntl is not None
    ready_read, ready_write = os.pipe()
    # os.fork is POSIX-only; this test is skipped on Windows, but mypy still
    # type-checks the line there.
    child_pid = os.fork()  # type: ignore[attr-defined]
    if child_pid == 0:
        os.close(ready_read)
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        os.write(ready_write, b"1")
        time.sleep(0.3)
        os._exit(0)

    os.close(ready_write)
    try:
        assert os.read(ready_read, 1) == b"1"
        monkeypatch.setattr(usage_statusline, "_LOCK_TIMEOUT_S", 0.01)
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            started = time.monotonic()
            with usage_statusline._exclusive_lock(lock_fd):
                pass
            assert time.monotonic() - started < 0.15
        finally:
            os.close(lock_fd)
    finally:
        os.close(ready_read)
        os.waitpid(child_pid, 0)


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
    status_file.write_text(
        json.dumps(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 11},
                    "seven_day": {"used_percentage": 22},
                },
                "_received_at": "old",
                "_received_at_ts": 1,
                "model": {"display_name": "old"},
            }
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))

    usage_statusline.save(
        {
            "model": {"display_name": "new"},
            "rate_limits": {
                "five_hour": {"used_percentage": None},
                "seven_day": {"used_percentage": None},
            },
        },
        now,
    )

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
    status_file.write_text(
        json.dumps(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 11},
                    "seven_day": {"used_percentage": 22},
                },
            }
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))

    usage_statusline.save(
        {
            "rate_limits": {
                "five_hour": {"used_percentage": 88},
                "seven_day": {"used_percentage": 99},
            },
        },
        now,
    )

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
    _write_prefs(
        prefs_file,
        {
            "last_update_check": {
                "checked_at": 1000.0,
                "current_version": "0.11.3",
                "latest_version": "0.12.0",
                "release_url": "https://x",
            },
        },
    )
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    assert usage_statusline._read_update_hint(1000.0) == "0.12.0"


def test_read_update_hint_returns_none_when_same_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    _write_prefs(
        prefs_file,
        {
            "last_update_check": {
                "checked_at": 1000.0,
                "current_version": "0.11.3",
                "latest_version": "0.11.3",
                "release_url": None,
            },
        },
    )
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    assert usage_statusline._read_update_hint(1000.0) is None


def test_read_update_hint_respects_skipped_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    _write_prefs(
        prefs_file,
        {
            "update_skipped_version": "0.12.0",
            "last_update_check": {
                "checked_at": 1000.0,
                "current_version": "0.11.3",
                "latest_version": "0.12.0",
                "release_url": "https://x",
            },
        },
    )
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    assert usage_statusline._read_update_hint(1000.0) is None


def test_read_update_hint_returns_none_when_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    _write_prefs(
        prefs_file,
        {
            "last_update_check": {
                "checked_at": 1000.0,
                "current_version": "0.11.3",
                "latest_version": "0.12.0",
                "release_url": "https://x",
            },
        },
    )
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(prefs_file))

    stale = 1000.0 + usage_statusline.UPDATE_HINT_STALE_SECONDS + 1
    assert usage_statusline._read_update_hint(stale) is None


def test_read_update_hint_handles_missing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(usage_statusline, "PREFERENCES_FILE", str(tmp_path / "does-not-exist.json"))
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


def test_main_reads_utf8_bytes_when_stdin_uses_cp950(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status_file = tmp_path / "usage-status.json"
    payload = {"cwd": r"C:\\Users\\USER\\Desktop\\GitHub專案\\usage"}
    stdin = io.TextIOWrapper(
        io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), encoding="cp950"
    )
    monkeypatch.setattr(usage_statusline, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(usage_statusline, "LOCK_FILE", str(tmp_path / "usage-status.lock"))
    monkeypatch.setattr(sys, "stdin", stdin)

    usage_statusline.main()

    assert json.loads(status_file.read_text(encoding="utf-8"))["cwd"] == payload["cwd"]
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


def test_render_shows_prompt_cache_hit_without_countdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "zh_TW")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    payload = {
        "model": {"display_name": "Opus 5"},
        "cost": {"total_duration_ms": 720000},
        "prompt_cache": {
            "caching_observed": True,
            "hit_ratio": 0.9072975151245158,
            "expires_at": now.timestamp() + 43 * 60,
        },
    }

    output = usage_statusline.render(payload, now)

    line3 = output.splitlines()[0]
    assert "快取:" in line3
    assert "91%" in line3
    assert "43min" not in line3
    assert "\033[2m\033[38;5;111m" in line3


@pytest.mark.parametrize(
    "prompt_cache",
    (None, {"caching_observed": False, "hit_ratio": 0.91}),
)
def test_render_omits_prompt_cache_when_not_observed(
    monkeypatch: pytest.MonkeyPatch,
    prompt_cache: dict[str, object] | None,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    payload: dict[str, object] = {
        "model": {"display_name": "Opus 5"},
        "cost": {"total_duration_ms": 720000},
    }
    if prompt_cache is not None:
        payload["prompt_cache"] = prompt_cache

    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))

    assert output == (
        "\033[2m\033[38;5;111mSession: 12min\033[0m \033[38;5;240m|\033[0m "
        "\033[2m\033[38;5;111mOpus 5\033[0m"
    )


def test_render_keeps_prompt_cache_bar_when_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    output = usage_statusline.render(
        {
            "prompt_cache": {
                "caching_observed": True,
                "hit_ratio": 0.91,
                "expires_at": now.timestamp() - 1,
            },
        },
        now,
    )

    assert "Cache:" in output
    assert "91%" in output
    assert "left" not in output
    assert "(" not in output


@pytest.mark.parametrize(
    ("hit_ratio", "color"),
    ((0.91, "\033[2m\033[38;5;111m"), (0.3, "\033[38;5;160m")),
)
def test_render_prompt_cache_uses_inverted_colors(
    monkeypatch: pytest.MonkeyPatch,
    hit_ratio: float,
    color: str,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)

    output = usage_statusline.render(
        {
            "prompt_cache": {"caching_observed": True, "hit_ratio": hit_ratio},
        },
        datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert color in output
    if hit_ratio == 0.91:
        assert "\033[38;5;160m" not in output


def test_render_prompt_cache_degrades_for_narrow_widths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "en")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    payload = {
        "model": {"display_name": "Opus 5"},
        "cost": {"total_duration_ms": 720000},
        "prompt_cache": {
            "caching_observed": True,
            "hit_ratio": 0.91,
            "expires_at": now.timestamp() + 43 * 60,
        },
    }

    monkeypatch.setattr(usage_statusline, "get_width", lambda: 29)
    pct_only = usage_statusline.render(payload, now)
    assert "Session:" not in pct_only
    assert "Cache:" in pct_only
    assert "43min" not in pct_only

    monkeypatch.setattr(usage_statusline, "get_width", lambda: 17)
    without_cache = usage_statusline.render(payload, now)
    assert "Session:" not in without_cache
    assert "Cache:" not in without_cache


@pytest.mark.parametrize("age", (0, 30, 600))
def test_render_shows_recent_cache_miss(monkeypatch: pytest.MonkeyPatch, age: int) -> None:
    monkeypatch.setenv("TT_LANG", "zh_TW")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    output = usage_statusline.render(
        {
            "prompt_cache": {
                "caching_observed": True,
                "hit_ratio": 0.62,
                "last_miss_at": now.timestamp() - age,
                "last_miss_cause": {"causes": ["tools_changed"]},
            }
        },
        now,
    )

    assert "62%" in output
    assert "\033[2m\033[38;5;111m剛失效:工具換了\033[0m" in output


@pytest.mark.parametrize("last_miss_at", (1767224999, 1767225601, None, "1767225600", True))
def test_render_omits_cache_miss_with_invalid_or_old_time(
    monkeypatch: pytest.MonkeyPatch, last_miss_at: object
) -> None:
    monkeypatch.setenv("TT_LANG", "zh_TW")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)

    output = usage_statusline.render(
        {
            "prompt_cache": {
                "caching_observed": True,
                "hit_ratio": 0.62,
                "last_miss_at": last_miss_at,
                "last_miss_cause": {"causes": ["tools_changed"]},
            }
        },
        datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert "快取:" in output
    assert "62%" in output
    assert "剛失效:" not in output


@pytest.mark.parametrize(
    "last_miss_cause",
    (
        None,
        "tools_changed",
        {"causes": "tools_changed"},
        {"causes": ["unknown"]},
        {"causes": ["unrecognized"]},
        {"causes": [None, {}]},
    ),
)
def test_render_omits_unrecognized_cache_miss(
    monkeypatch: pytest.MonkeyPatch, last_miss_cause: object
) -> None:
    monkeypatch.setenv("TT_LANG", "zh_TW")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    output = usage_statusline.render(
        {
            "prompt_cache": {
                "caching_observed": True,
                "hit_ratio": 0.62,
                "last_miss_at": now.timestamp(),
                "last_miss_cause": last_miss_cause,
            }
        },
        now,
    )

    assert "快取:" in output
    assert "62%" in output
    assert "剛失效:" not in output


def test_render_cache_miss_uses_first_recognized_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "zh_TW")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    output = usage_statusline.render(
        {
            "prompt_cache": {
                "caching_observed": True,
                "hit_ratio": 0.62,
                "last_miss_at": now.timestamp(),
                "last_miss_cause": {"causes": ["unknown", "effort_changed", "tools_changed"]},
            }
        },
        now,
    )

    assert "剛失效:換了思考強度" in output
    assert "工具換了" not in output


def test_render_drops_cache_miss_before_duration_or_percentage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TT_LANG", "zh_TW")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    payload = {
        "cost": {"total_duration_ms": 720000},
        "prompt_cache": {
            "caching_observed": True,
            "hit_ratio": 0.62,
            "last_miss_at": now.timestamp(),
            "last_miss_cause": {"causes": ["tools_changed"]},
        },
    }
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    full = usage_statusline.render(payload, now)
    width = usage_statusline.vlen(full) - usage_statusline.vlen(" 剛失效:工具換了")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: width)

    output = usage_statusline.render(payload, now)

    assert "剛失效:" not in output
    assert "快取:" in output
    assert "62%" in output
    assert "會話時長:" in output
    assert usage_statusline.vlen(output) == width


@pytest.mark.parametrize("lang", ("zh-TW", "zh-CN", "en", "ja", "ko"))
def test_cache_miss_translation_keys(lang: str) -> None:
    causes = (
        "system_prompt_changed",
        "tools_changed",
        "model_changed",
        "fast_mode_changed",
        "cache_scope_or_ttl_changed",
        "betas_changed",
        "effort_changed",
        "thinking_mode_changed",
        "thinking_display_changed",
        "auto_mode_changed",
        "overage_changed",
        "extra_body_changed",
        "defer_loading_changed",
        "messages_rewritten",
        "ttl_expired_5m",
        "ttl_expired_1h",
        "likely_server_side",
    )
    translations = usage_statusline.STATUSLINE_TRANSLATIONS[lang]

    assert translations["cache_miss"]
    assert {key for key in translations if key.startswith("miss_")} == {
        f"miss_{cause}" for cause in causes
    }
    assert all(translations[f"miss_{cause}"] for cause in causes)


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


@pytest.mark.parametrize(
    ("percent", "size", "tokens", "color"),
    [
        (25, 1_000_000, None, 214),
        (45, 1_000_000, None, 160),
        (40, 200_000, None, 42),
        (19, 1_000_000, None, 42),
        (20, 1_000_000, None, 214),
        (39, 1_000_000, None, 214),
        (40, 1_000_000, None, 160),
        (50, 200_000, None, 214),
        (80, 200_000, None, 160),
        (40, None, None, 42),
        (50, None, None, 214),
        (80, None, None, 160),
        (10, 1_000_000, 900_000, 42),
    ],
)
def test_context_color_uses_worse_threshold_without_changing_quota(
    monkeypatch: pytest.MonkeyPatch,
    percent: int,
    size: int | None,
    tokens: object,
    color: int,
) -> None:
    monkeypatch.setenv("USAGE_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 116)
    context: dict[str, Any] = {"used_percentage": percent}
    if size is not None:
        context["context_window_size"] = size
    if tokens is not None:
        context["total_input_tokens"] = tokens
    payload = {
        "context_window": context,
        "rate_limits": {"five_hour": {"used_percentage": 25}},
    }
    output = usage_statusline.render(payload, datetime(2026, 1, 1, tzinfo=UTC))
    assert f"Context:{usage_statusline.C['reset']}\033[38;5;{color}m" in output
    assert f"5h:{usage_statusline.C['reset']}\033[38;5;42m" in output


def _mix_record(*blocks: dict[str, Any], **fields: Any) -> bytes:
    return (
        json.dumps({"type": "user", "message": {"content": list(blocks)}, **fields}) + "\n"
    ).encode()


def test_mix_counts_images_text_sidechains_and_compaction(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    image = {"type": "image", "source": {"data": "not-measured"}}
    tool = {"type": "tool_result", "content": [{"type": "text", "text": "中文abcd"}, image]}
    transcript.write_bytes(
        _mix_record(image, image, tool)
        + _mix_record(image, tool, isSidechain=True)
        + _mix_record(image, type="assistant")
    )
    data = {"session_id": "one", "transcript_path": str(transcript)}
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["images"], mix["toolTokens"]) == (3, 3)
    assert mix["offset"] == transcript.stat().st_size
    assert json.loads((Path(usage_statusline.MIX_DIR) / "one.json").read_text()) == mix
    with transcript.open("ab") as target:
        target.write(b'{"type":"system","subtype":"compact_boundary"}\n')
        target.write(_mix_record(tool))
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["images"], mix["toolTokens"]) == (1, 3)
    with transcript.open("ab") as target:
        target.write(_mix_record(image, isCompactSummary=True))
        target.write(_mix_record({"type": "tool_result", "content": "abcdefgh"}))
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["images"], mix["toolTokens"]) == (0, 2)


def test_mix_incremental_reads_only_new_complete_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = tmp_path / "session.jsonl"
    image = _mix_record({"type": "image"})
    transcript.write_bytes(image)
    data = {"session_id": "one", "transcript_path": str(transcript)}
    assert usage_statusline.read_mix(data)["images"] == 1  # type: ignore[index]
    original_open = open
    reads: list[int] = []

    class Tracked:
        def __enter__(self) -> Any:
            self.source = original_open(transcript, "rb")
            return self

        def __exit__(self, *args: Any) -> None:
            self.source.close()

        def fileno(self) -> int:
            return self.source.fileno()

        def seek(self, offset: int) -> None:
            self.source.seek(offset)

        def read(self, size: int) -> bytes:
            reads.append(size)
            return self.source.read(size)

    def tracked_open(path: Any, mode: str = "r", **kwargs: Any) -> Any:
        return (
            Tracked()
            if str(path) == str(transcript) and mode == "rb"
            else original_open(path, mode, **kwargs)
        )

    monkeypatch.setattr(usage_statusline, "open", tracked_open, raising=False)
    assert usage_statusline.read_mix(data)["images"] == 1  # type: ignore[index]
    assert reads == [0]
    with transcript.open("ab") as target:
        target.write(image + image[:-1])
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["offset"], mix["images"]) == (len(image) * 2, 2)
    with transcript.open("ab") as target:
        target.write(b"\n")
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["offset"], mix["images"]) == (len(image) * 3, 3)


def test_mix_restarts_on_replaced_or_truncated_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / "first.jsonl"
    image = _mix_record({"type": "image"})
    transcript.write_bytes(image * 2)
    data = {"session_id": "one", "transcript_path": str(transcript)}
    assert usage_statusline.read_mix(data)["images"] == 2  # type: ignore[index]
    transcript.write_bytes(image)
    assert usage_statusline.read_mix(data)["images"] == 1  # type: ignore[index]
    other = tmp_path / "second.jsonl"
    other.write_bytes(image * 3)
    data["transcript_path"] = str(other)
    assert usage_statusline.read_mix(data)["images"] == 3  # type: ignore[index]


def test_mix_catches_up_within_the_read_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = tmp_path / "session.jsonl"
    image = _mix_record({"type": "image"})
    long_tool = _mix_record({"type": "tool_result", "content": "x" * 400})
    transcript.write_bytes(image * 3 + long_tool)
    monkeypatch.setattr(usage_statusline, "MIX_READ_BUDGET", len(image) * 2)
    data = {"session_id": "one", "transcript_path": str(transcript)}
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["images"], mix["offset"], mix["complete"]) == (2, len(image) * 2, False)
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["images"], mix["offset"], mix["complete"]) == (3, len(image) * 3, False)
    # The record longer than the budget is read whole in one run.
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["toolTokens"], mix["complete"]) == (100, True)
    assert mix["offset"] == transcript.stat().st_size


def test_render_mix_label_waits_until_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USAGE_LANG", "en")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 200)
    transcript = tmp_path / "session.jsonl"
    image = _mix_record({"type": "image"})
    transcript.write_bytes(image * 2)
    monkeypatch.setattr(usage_statusline, "MIX_READ_BUDGET", len(image))
    payload = {
        "session_id": "one",
        "transcript_path": str(transcript),
        "context_window": {"used_percentage": 30, "context_window_size": 1_000_000},
    }
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert "Images" not in usage_statusline.render(payload, now)
    assert "Images 2" in usage_statusline.render(payload, now)


@pytest.mark.parametrize("session_id", ("../escape", "", "a/b", "a.json"))
def test_mix_rejects_invalid_ids(session_id: str, tmp_path: Path) -> None:
    assert (
        usage_statusline.read_mix(
            {"session_id": session_id, "transcript_path": str(tmp_path / "missing")}
        )
        is None
    )
    assert not Path(usage_statusline.MIX_DIR).exists()


@pytest.mark.parametrize("bad", (b"broken\n", b"null\n", b"\xff\n", b"[1]\n"))
def test_mix_skips_torn_lines(bad: bytes, tmp_path: Path) -> None:
    transcript = tmp_path / "one.jsonl"
    image = _mix_record({"type": "image"})
    transcript.write_bytes(image + bad + image)
    data = {"session_id": "one", "transcript_path": str(transcript)}
    mix = usage_statusline.read_mix(data)
    assert mix is not None
    assert (mix["images"], mix["offset"], mix["complete"]) == (2, transcript.stat().st_size, True)


@pytest.mark.parametrize("cache_text", ("broken", "null", '{"sessionId": "one"}'))
def test_mix_restarts_from_a_corrupt_cache(cache_text: str, tmp_path: Path) -> None:
    transcript = tmp_path / "one.jsonl"
    transcript.write_bytes(_mix_record({"type": "image"}))
    cache = Path(usage_statusline.MIX_DIR) / "one.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(cache_text)
    mix = usage_statusline.read_mix({"session_id": "one", "transcript_path": str(transcript)})
    assert mix is not None
    assert (mix["images"], mix["complete"]) == (1, True)
    assert json.loads(cache.read_text()) == mix


@pytest.mark.parametrize("percent,images,visible", ((30, 3, True), (50, 0, True), (19, 3, False)))
def test_render_mix_label(
    percent: int, images: int, visible: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TT_LANG", "zh-TW")
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 300)
    transcript = tmp_path / "one.jsonl"
    transcript.write_bytes(
        _mix_record(
            *([{"type": "image"}] * images), {"type": "tool_result", "content": "a" * 480000}
        )
    )
    data = {
        "session_id": "one",
        "transcript_path": str(transcript),
        "context_window": {"used_percentage": percent, "context_window_size": 1000000},
    }
    now = datetime(2026, 1, 1, tzinfo=UTC)
    output = usage_statusline.render(data, now)
    assert ("讀檔與指令輸出" in output) is visible
    assert ("圖片 3 張" in output) is (visible and images > 0)
    if percent == 30:
        assert "讀檔與指令輸出 40%" in output
    if not visible:
        assert output == usage_statusline.render({"context_window": data["context_window"]}, now)
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 20)
    assert "讀檔與指令輸出" not in usage_statusline.render(data, now)


def test_render_drops_mix_label_before_the_context_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USAGE_LANG", "zh-TW")
    transcript = tmp_path / "session.jsonl"
    transcript.write_bytes(_mix_record({"type": "image"}, {"type": "image"}))
    payload = {
        "session_id": "one",
        "transcript_path": str(transcript),
        "context_window": {"used_percentage": 30, "context_window_size": 1_000_000},
        "cost": {"total_duration_ms": 3_600_000},
        "model": {"display_name": "Opus 5.5"},
    }
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 90)
    assert "/ 1.0M" in usage_statusline.render(payload, now)
    assert "圖片 2 張" in usage_statusline.render(payload, now)
    monkeypatch.setattr(usage_statusline, "get_width", lambda: 60)
    narrow = usage_statusline.render(payload, now)
    assert "/ 1.0M" in narrow
    assert "圖片 2 張" not in narrow


def test_mix_sweeps_stale_files_when_a_new_session_starts(tmp_path: Path) -> None:
    mix_dir = Path(usage_statusline.MIX_DIR)
    mix_dir.mkdir(parents=True)
    old, fresh = mix_dir / "old.json", mix_dir / "fresh.json"
    old.write_text("{}")
    fresh.write_text("{}")
    week_ago = time.time() - usage_statusline.MIX_STALE_SECONDS - 60
    os.utime(old, (week_ago, week_ago))
    transcript = tmp_path / "one.jsonl"
    transcript.write_bytes(_mix_record({"type": "image"}))
    assert usage_statusline.read_mix({"session_id": "one", "transcript_path": str(transcript)})
    assert sorted(p.name for p in mix_dir.iterdir()) == ["fresh.json", "one.json"]
