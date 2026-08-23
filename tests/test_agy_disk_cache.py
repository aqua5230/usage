# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from loaders import agy_disk_cache, agy_loader, cache_quarantine


def _agy_entry(session_id: str, project: str = "test-project") -> agy_loader.AgyUsageEntry:
    return agy_loader.AgyUsageEntry(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        model="test-model",
        input_tokens=1,
        output_tokens=2,
        cache_read_tokens=3,
        thinking_tokens=4,
        dedup_key=f"{session_id}:dedup",
        session_id=session_id,
        project=project,
    )


def _file_cache_entry(session_id: str, mtime: float = 1.0) -> agy_loader._FileCacheEntry:
    return agy_loader._FileCacheEntry(
        mtime=mtime,
        size=10,
        entries=[_agy_entry(session_id)],
        skipped_missing_dedup_key=0,
    )


def test_roundtrip_flush_then_seed(tmp_path: Path) -> None:
    cache_path = tmp_path / "agy.json"
    path = Path("/sessions/db-1.db")
    cache = OrderedDict([(path, _file_cache_entry("db-1"))])

    agy_disk_cache.flush_caches(cache_path, 1, cache)
    seeded: OrderedDict[Path, agy_loader._FileCacheEntry] = OrderedDict()
    agy_disk_cache.seed_caches(cache_path, 1, 4096, seeded)

    assert path in seeded
    assert seeded[path] == cache[path]
    assert seeded[path].entries[0].project == "test-project"


def test_schema_version_mismatch_is_miss_not_quarantined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "agy.json"
    path = Path("/sessions/db-1.db")
    cache = OrderedDict([(path, _file_cache_entry("db-1"))])
    agy_disk_cache.flush_caches(cache_path, 1, cache)
    quarantine_dir = tmp_path / "quarantine"
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)

    seeded: OrderedDict[Path, agy_loader._FileCacheEntry] = OrderedDict()
    agy_disk_cache.seed_caches(cache_path, 2, 4096, seeded)

    assert not seeded
    assert cache_path.exists()
    assert not quarantine_dir.exists()


def test_corrupt_json_is_quarantined_and_miss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "agy.json"
    cache_path.write_text("not json{", encoding="utf-8")
    quarantine_dir = tmp_path / "quarantine"
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)

    seeded: OrderedDict[Path, agy_loader._FileCacheEntry] = OrderedDict()
    agy_disk_cache.seed_caches(cache_path, 1, 4096, seeded)

    assert not seeded
    assert not cache_path.exists()
    assert len(list(quarantine_dir.glob("*.bak"))) == 1


def test_invalid_utf8_is_quarantined_as_decode_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "agy.json"
    cache_path.write_bytes(b"\x80\x81\x82")
    quarantine_dir = tmp_path / "quarantine"
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)

    seeded: OrderedDict[Path, agy_loader._FileCacheEntry] = OrderedDict()
    agy_disk_cache.seed_caches(cache_path, 1, 4096, seeded)

    assert not seeded
    assert not cache_path.exists()
    assert len(list(quarantine_dir.glob("*.bak"))) == 1


def test_non_mapping_payload_is_quarantined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "agy.json"
    cache_path.write_text("[]", encoding="utf-8")
    quarantine_dir = tmp_path / "quarantine"
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)

    seeded: OrderedDict[Path, agy_loader._FileCacheEntry] = OrderedDict()
    agy_disk_cache.seed_caches(cache_path, 1, 4096, seeded)

    assert not seeded
    assert not cache_path.exists()
    assert len(list(quarantine_dir.glob("*.bak"))) == 1


def test_missing_cache_file_is_silent_miss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "does-not-exist.json"
    quarantine_dir = tmp_path / "quarantine"
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", quarantine_dir)

    seeded: OrderedDict[Path, agy_loader._FileCacheEntry] = OrderedDict()
    agy_disk_cache.seed_caches(cache_path, 1, 4096, seeded)

    assert not seeded
    assert not quarantine_dir.exists()


def test_flush_creates_missing_parent_directory(tmp_path: Path) -> None:
    cache_path = tmp_path / "nested" / "dir" / "agy.json"
    path = Path("/sessions/db-1.db")
    cache = OrderedDict([(path, _file_cache_entry("db-1"))])

    agy_disk_cache.flush_caches(cache_path, 1, cache)

    assert cache_path.exists()
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert str(path) in payload["files"]
    assert list(cache_path.parent.glob("*.tmp")) == []


def test_flush_to_unwritable_parent_does_not_raise(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("blocked", encoding="utf-8")
    cache_path = blocker / "agy.json"
    cache = OrderedDict([(Path("/sessions/db-1.db"), _file_cache_entry("db-1"))])

    agy_disk_cache.flush_caches(cache_path, 1, cache)

    assert not cache_path.exists()


def test_seed_evicts_oldest_entry_when_exceeding_maxsize(tmp_path: Path) -> None:
    cache_path = tmp_path / "agy.json"
    paths = [Path(f"/sessions/db-{i}.db") for i in range(3)]
    cache = OrderedDict((path, _file_cache_entry(path.stem)) for path in paths)
    agy_disk_cache.flush_caches(cache_path, 1, cache)

    seeded: OrderedDict[Path, agy_loader._FileCacheEntry] = OrderedDict()
    agy_disk_cache.seed_caches(cache_path, 1, 2, seeded)

    assert paths[0] not in seeded
    assert paths[1] in seeded
    assert paths[2] in seeded
    assert len(seeded) == 2


def test_seed_skips_malformed_entry_but_keeps_other_files(tmp_path: Path) -> None:
    cache_path = tmp_path / "agy.json"
    good_path = Path("/sessions/db-good.db")
    bad_path = Path("/sessions/db-bad.db")
    payload = {
        "schema_version": 1,
        "files": {
            str(good_path): {
                "mtime": 1.0,
                "size": 10,
                "entries": [
                    {
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "model": "test-model",
                        "input_tokens": 1,
                        "output_tokens": 2,
                        "cache_read_tokens": 3,
                        "thinking_tokens": 4,
                        "dedup_key": "good:dedup",
                        "session_id": "db-good",
                    }
                ],
                "skipped_missing_dedup_key": 0,
            },
            str(bad_path): {
                "mtime": 1.0,
                # "size" key missing triggers a KeyError caught by the parser.
                "entries": [],
                "skipped_missing_dedup_key": 0,
            },
        },
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    seeded: OrderedDict[Path, agy_loader._FileCacheEntry] = OrderedDict()
    agy_disk_cache.seed_caches(cache_path, 1, 4096, seeded)

    assert bad_path not in seeded
    assert good_path in seeded
    assert seeded[good_path].entries[0].dedup_key == "good:dedup"
    assert seeded[good_path].entries[0].project == ""
