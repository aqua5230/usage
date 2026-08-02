# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import os
from pathlib import Path

import pytest

import cache_quarantine


def test_quarantine_moves_a_cache_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    quarantine_dir = tmp_path / "quarantine"
    source = tmp_path / "cache.json"
    source.write_text("broken", encoding="utf-8")
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)
    monkeypatch.setattr("cache_quarantine.time.time_ns", lambda: 1_754_132_400_123_000_000)

    cache_quarantine.quarantine(source, "json-error")

    backup = quarantine_dir / "cache.json.1754132400123.bak"
    assert not source.exists()
    assert backup.read_text(encoding="utf-8") == "broken"


def test_quarantine_skips_files_larger_than_five_megabytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    quarantine_dir = tmp_path / "quarantine"
    source = tmp_path / "cache.json"
    with source.open("wb") as file:
        file.truncate(5 * 1024 * 1024 + 1)
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)

    cache_quarantine.quarantine(source, "json-error")

    assert source.exists()
    assert not quarantine_dir.exists()


def test_quarantine_keeps_only_ten_backups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()
    for index in range(10):
        backup = quarantine_dir / f"old-{index}.bak"
        backup.write_text("old", encoding="utf-8")
        os.utime(backup, (index + 1, index + 1))
    source = tmp_path / "cache.json"
    source.write_text("broken", encoding="utf-8")
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)
    monkeypatch.setattr("cache_quarantine.time.time_ns", lambda: 1_754_132_400_123_000_000)

    cache_quarantine.quarantine(source, "json-error")

    assert len(list(quarantine_dir.glob("*.bak"))) == 10
    assert not (quarantine_dir / "old-0.bak").exists()
    assert (quarantine_dir / "cache.json.1754132400123.bak").exists()


def test_quarantine_ignores_a_missing_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", tmp_path / "quarantine")

    cache_quarantine.quarantine(tmp_path / "missing.json", "json-error")


def test_quarantine_ignores_an_uncreatable_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    quarantine_dir = tmp_path / "not-a-directory"
    quarantine_dir.write_text("blocked", encoding="utf-8")
    source = tmp_path / "cache.json"
    source.write_text("broken", encoding="utf-8")
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)

    cache_quarantine.quarantine(source, "json-error")

    assert source.exists()
