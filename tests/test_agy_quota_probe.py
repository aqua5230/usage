# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import agy_quota_probe
from agy_quota_probe import AgyQuotaGroup, AgyQuotaResult, AgyQuotaWindow

SYNTHETIC_TRANSCRIPT = """
Models & Quota

GEMINI MODELS
  Models within this group: Gemini Flash, Gemini Pro

  Weekly Limit
    [===========================>] 83.28%
    83% remaining · Refreshes in 145h 44m

  Five Hour Limit
    [===============================>] 95.27%
    95% remaining · Refreshes in 3h 53m

CLAUDE AND GPT MODELS
  Models within this group: Claude Opus, Claude Sonnet, GPT-OSS

  Weekly Limit
    [================================] 100.00%
    Quota available

  Five Hour Limit
    [================================] 100.00%
    Quota available
"""


def test_find_agy_returns_path_from_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/custom/bin/agy")

    assert agy_quota_probe.find_agy() == "/custom/bin/agy"


def test_find_agy_falls_back_to_user_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agy_path = tmp_path / ".local" / "bin" / "agy"
    agy_path.parent.mkdir(parents=True)
    agy_path.touch()
    agy_path.chmod(0o755)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: str(tmp_path / path.removeprefix("~/")),
    )

    assert agy_quota_probe.find_agy() == str(agy_path)


def test_find_agy_returns_none_when_all_paths_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: str(tmp_path / path.removeprefix("~/")),
    )

    assert agy_quota_probe.find_agy() is None


def test_probe_env_prepends_paths_deduplicates_and_preserves_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(["/usr/local/bin", "/usr/bin", "/custom/bin"]),
    )
    monkeypatch.setenv("AGY_PROBE_TEST", "retained")
    monkeypatch.delenv("TERM", raising=False)

    env = agy_quota_probe._probe_env("/custom/bin/agy")
    path_entries = env["PATH"].split(os.pathsep)

    assert path_entries == [
        "/custom/bin",
        os.path.expanduser("~/.local/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
    ]
    assert env["TERM"] == "xterm-256color"
    assert env["AGY_PROBE_TEST"] == "retained"


def test_probe_env_preserves_existing_term(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "screen-256color")

    assert agy_quota_probe._probe_env("/custom/bin/agy")["TERM"] == "screen-256color"


def test_parse_quota_output_parses_all_groups_and_windows() -> None:
    result = agy_quota_probe._parse_quota_output(SYNTHETIC_TRANSCRIPT)

    assert result is not None
    assert [group.name for group in result.groups] == ["GEMINI MODELS", "CLAUDE AND GPT MODELS"]
    first_group, second_group = result.groups
    assert first_group.models == ["Gemini Flash", "Gemini Pro"]
    assert first_group.weekly == AgyQuotaWindow(83.28, "145h 44m", 8744)
    assert first_group.five_hour == AgyQuotaWindow(95.27, "3h 53m", 233)
    assert second_group.models == ["Claude Opus", "Claude Sonnet", "GPT-OSS"]
    assert second_group.weekly == AgyQuotaWindow(100.0, None, None)
    assert second_group.five_hour == AgyQuotaWindow(100.0, None, None)


def test_parse_quota_output_returns_none_for_malformed_output() -> None:
    malformed = SYNTHETIC_TRANSCRIPT.replace("Refreshes in 3h 53m", "Refreshes later")

    assert agy_quota_probe._parse_quota_output(malformed) is None
    assert agy_quota_probe._parse_quota_output("not a quota screen") is None


def test_parse_quota_output_falls_back_to_summary_percent_without_progress_bar() -> None:
    transcript = re.sub(
        r"^\s*\[=+>\]\s*83\.28%\n",
        "",
        SYNTHETIC_TRANSCRIPT,
        count=1,
        flags=re.MULTILINE,
    )

    result = agy_quota_probe._parse_quota_output(transcript)

    assert result is not None
    assert result.groups[0].weekly.remaining_percent == 83.0


def test_load_quota_returns_fresh_cache_without_probing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "agy_quota_cache.json"
    cached = _result(datetime.now(UTC))
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", cache_path)
    agy_quota_probe._write_cache(cached)
    monkeypatch.setattr(agy_quota_probe, "probe_quota", _unexpected_probe)

    assert agy_quota_probe.load_quota() == cached


def test_load_quota_probes_when_cache_is_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "agy_quota_cache.json"
    stale = _result(datetime.now(UTC) - timedelta(minutes=16))
    fresh = _result(datetime.now(UTC))
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", cache_path)
    agy_quota_probe._write_cache(stale)
    monkeypatch.setattr(agy_quota_probe, "probe_quota", lambda: fresh)

    assert agy_quota_probe.load_quota(max_age_minutes=15) == fresh
    assert agy_quota_probe._read_cache() == fresh


def test_load_quota_returns_stale_cache_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "agy_quota_cache.json"
    stale = _result(datetime.now(UTC) - timedelta(minutes=16))
    monkeypatch.setattr(agy_quota_probe, "CACHE_PATH", cache_path)
    agy_quota_probe._write_cache(stale)
    monkeypatch.setattr(agy_quota_probe, "probe_quota", lambda: None)

    assert agy_quota_probe.load_quota(max_age_minutes=15) == stale


def _result(fetched_at: datetime) -> AgyQuotaResult:
    window = AgyQuotaWindow(83.28, "2h 5m", 125)
    group = AgyQuotaGroup("TEST MODELS", ["Test One"], window, window)
    return AgyQuotaResult([group], fetched_at.isoformat())


def _unexpected_probe() -> AgyQuotaResult | None:
    raise AssertionError("fresh cache must not call probe_quota")
