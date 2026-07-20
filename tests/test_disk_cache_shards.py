# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import os
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

import codex_disk_cache
import codex_loader
import history_disk_cache
import history_loader
from codex_events import _SessionFileInfo


def _usage_entry(session_id: str) -> history_loader.UsageEntry:
    return history_loader.UsageEntry(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        session_id=session_id,
        message_id=f"{session_id}:1",
        request_id="",
        model="test-model",
        input_tokens=1,
        output_tokens=2,
        cache_creation_tokens=0,
        cache_read_tokens=3,
        cost_usd=None,
        project="test-project",
    )


def _distinct_paths(indexer: object) -> tuple[Path, Path]:
    first = Path("/sessions/session-0.jsonl")
    first_index = indexer(first)  # type: ignore[operator]
    for number in range(1, 100):
        candidate = Path(f"/sessions/session-{number}.jsonl")
        if indexer(candidate) != first_index:  # type: ignore[operator]
            return first, candidate
    raise AssertionError("failed to find paths in distinct cache shards")


def _history_entry(path: Path, mtime: float = 1.0) -> history_loader._FileCacheEntry:
    return history_loader._FileCacheEntry(
        mtime=mtime,
        size=10,
        entries=[_usage_entry(path.stem)],
        confirmed_offset=10,
        confirmed_prefix_digest=b"digest",
    )


def _codex_entry(path: Path, mtime: float = 1.0) -> codex_loader._JsonlCacheEntry:
    return codex_loader._JsonlCacheEntry(
        mtime=mtime,
        size=10,
        replay_cache_key=None,
        entries=[_usage_entry(path.stem)],
        confirmed_offset=10,
        confirmed_prefix_digest=b"digest",
        state=codex_loader._JsonlParseState(session_model="test-model"),
    )


def test_history_flush_changes_only_the_affected_shard(tmp_path: Path) -> None:
    cache_path = tmp_path / "history.json"
    first, second = _distinct_paths(history_disk_cache._shard_index)
    cache = OrderedDict([(first, _history_entry(first)), (second, _history_entry(second))])
    history_disk_cache.flush_caches(cache_path, 2, cache)
    first_shard = history_disk_cache._shard_path(
        cache_path, history_disk_cache._shard_index(first)
    )
    second_shard = history_disk_cache._shard_path(
        cache_path, history_disk_cache._shard_index(second)
    )
    os.utime(first_shard, ns=(1_000_000_000, 1_000_000_000))
    os.utime(second_shard, ns=(2_000_000_000, 2_000_000_000))

    cache[first] = _history_entry(first, mtime=2.0)
    history_disk_cache.flush_caches(cache_path, 2, cache)

    assert first_shard.stat().st_mtime_ns != 1_000_000_000
    assert second_shard.stat().st_mtime_ns == 2_000_000_000


def test_history_corrupt_shard_is_skipped_and_rebuilt(tmp_path: Path) -> None:
    cache_path = tmp_path / "history.json"
    first, second = _distinct_paths(history_disk_cache._shard_index)
    original = OrderedDict([(first, _history_entry(first)), (second, _history_entry(second))])
    history_disk_cache.flush_caches(cache_path, 2, original)
    corrupt_shard = history_disk_cache._shard_path(
        cache_path, history_disk_cache._shard_index(first)
    )
    corrupt_shard.write_text("broken", encoding="utf-8")
    seeded: OrderedDict[Path, history_loader._FileCacheEntry] = OrderedDict()

    history_disk_cache.seed_caches(cache_path, 2, 4096, seeded)

    assert first not in seeded
    assert second in seeded
    seeded[first] = original[first]
    history_disk_cache.flush_caches(cache_path, 2, seeded)
    assert str(first) in json.loads(corrupt_shard.read_text(encoding="utf-8"))["files"]


def test_history_legacy_single_file_is_deleted(tmp_path: Path) -> None:
    cache_path = tmp_path / "history.json"
    cache_path.write_text('{"schema_version":1,"files":{}}', encoding="utf-8")
    seeded: OrderedDict[Path, history_loader._FileCacheEntry] = OrderedDict()

    history_disk_cache.seed_caches(cache_path, 2, 4096, seeded)

    assert not cache_path.exists()
    assert not seeded


def _codex_caches(
    first: Path, second: Path
) -> tuple[
    OrderedDict[Path, codex_loader._JsonlCacheEntry],
    OrderedDict[Path, tuple[float, int, _SessionFileInfo]],
]:
    entries = OrderedDict([(first, _codex_entry(first)), (second, _codex_entry(second))])
    info = OrderedDict(
        (
            path,
            (1.0, 10, _SessionFileInfo(session_id=path.stem, forked_from_id="")),
        )
        for path in (first, second)
    )
    return entries, info


def test_codex_flush_changes_only_the_affected_shard(tmp_path: Path) -> None:
    cache_path = tmp_path / "codex.json"
    first, second = _distinct_paths(codex_disk_cache._shard_index)
    entries, info = _codex_caches(first, second)
    sqlite_cache = codex_loader._SqliteLogCache()
    codex_disk_cache.flush_caches(cache_path, 4, entries, info, sqlite_cache)
    first_shard = codex_disk_cache._shard_path(cache_path, codex_disk_cache._shard_index(first))
    second_shard = codex_disk_cache._shard_path(cache_path, codex_disk_cache._shard_index(second))
    os.utime(first_shard, ns=(1_000_000_000, 1_000_000_000))
    os.utime(second_shard, ns=(2_000_000_000, 2_000_000_000))

    entries[first] = _codex_entry(first, mtime=2.0)
    codex_disk_cache.flush_caches(cache_path, 4, entries, info, sqlite_cache)

    assert first_shard.stat().st_mtime_ns != 1_000_000_000
    assert second_shard.stat().st_mtime_ns == 2_000_000_000


def test_codex_corrupt_shard_is_skipped_and_rebuilt(tmp_path: Path) -> None:
    cache_path = tmp_path / "codex.json"
    first, second = _distinct_paths(codex_disk_cache._shard_index)
    original, info = _codex_caches(first, second)
    sqlite_cache = codex_loader._SqliteLogCache()
    codex_disk_cache.flush_caches(cache_path, 4, original, info, sqlite_cache)
    corrupt_shard = codex_disk_cache._shard_path(
        cache_path, codex_disk_cache._shard_index(first)
    )
    corrupt_shard.write_text("broken", encoding="utf-8")
    seeded: OrderedDict[Path, codex_loader._JsonlCacheEntry] = OrderedDict()
    seeded_info: OrderedDict[Path, tuple[float, int, _SessionFileInfo]] = OrderedDict()

    codex_disk_cache.seed_caches(cache_path, 4, 4096, seeded, seeded_info, sqlite_cache)

    assert first not in seeded
    assert second in seeded
    seeded[first] = original[first]
    seeded_info[first] = info[first]
    codex_disk_cache.flush_caches(cache_path, 4, seeded, seeded_info, sqlite_cache)
    assert str(first) in json.loads(corrupt_shard.read_text(encoding="utf-8"))["files"]


def test_codex_legacy_single_file_is_deleted(tmp_path: Path) -> None:
    cache_path = tmp_path / "codex.json"
    cache_path.write_text('{"schema_version":3,"files":{}}', encoding="utf-8")
    entries: OrderedDict[Path, codex_loader._JsonlCacheEntry] = OrderedDict()
    info: OrderedDict[Path, tuple[float, int, _SessionFileInfo]] = OrderedDict()

    codex_disk_cache.seed_caches(
        cache_path, 4, 4096, entries, info, codex_loader._SqliteLogCache()
    )

    assert not cache_path.exists()
    assert not entries
    assert not info
