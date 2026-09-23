# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import json
import os
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from loaders import (
    cache_quarantine,
    codex_disk_cache,
    codex_loader,
    disk_cache_common,
    history_disk_cache,
    history_loader,
)
from loaders.codex_events import _SessionFileInfo


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


def _distinct_paths(indexer: object, parent: Path = Path("/sessions")) -> tuple[Path, Path]:
    first = parent / "session-0.jsonl"
    first_index = indexer(first)  # type: ignore[operator]
    for number in range(1, 100):
        candidate = parent / f"session-{number}.jsonl"
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
    first_shard = history_disk_cache._shard_path(cache_path, history_disk_cache._shard_index(first))
    second_shard = history_disk_cache._shard_path(
        cache_path, history_disk_cache._shard_index(second)
    )
    os.utime(first_shard, ns=(1_000_000_000, 1_000_000_000))
    os.utime(second_shard, ns=(2_000_000_000, 2_000_000_000))

    cache[first] = _history_entry(first, mtime=2.0)
    history_disk_cache.flush_caches(cache_path, 2, cache)

    assert first_shard.stat().st_mtime_ns != 1_000_000_000
    assert second_shard.stat().st_mtime_ns == 2_000_000_000


def test_history_flush_serializes_only_requested_shards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "history.json"
    first, second = _distinct_paths(history_disk_cache._shard_index)
    cache = OrderedDict([(first, _history_entry(first)), (second, _history_entry(second))])
    serialized: list[str] = []
    original = disk_cache_common._serialize_usage_entry

    def record(entry: history_loader.UsageEntry) -> dict[str, object]:
        serialized.append(entry.session_id)
        return original(entry)

    monkeypatch.setattr(history_disk_cache, "_serialize_usage_entry", record)

    written = history_disk_cache.flush_caches(
        cache_path,
        2,
        cache,
        {history_disk_cache._shard_index(first)},
    )

    assert written == {history_disk_cache._shard_index(first)}
    assert serialized == [first.stem]


def test_history_corrupt_shard_is_skipped_and_rebuilt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "history.json"
    first, second = _distinct_paths(history_disk_cache._shard_index, tmp_path / "sessions")
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    original = OrderedDict([(first, _history_entry(first)), (second, _history_entry(second))])
    history_disk_cache.flush_caches(cache_path, 2, original)
    corrupt_shard = history_disk_cache._shard_path(
        cache_path, history_disk_cache._shard_index(first)
    )
    corrupt_shard.write_text("broken", encoding="utf-8")
    seeded: OrderedDict[Path, history_loader._FileCacheEntry] = OrderedDict()
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", tmp_path / "quarantine")

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


def test_history_seed_skips_missing_but_keeps_stat_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "history.json"
    live, missing = _distinct_paths(history_disk_cache._shard_index, tmp_path / "sessions")
    denied = live.with_name("denied.jsonl")
    for path in (live, missing, denied):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    cache = OrderedDict((path, _history_entry(path)) for path in (live, missing, denied))
    history_disk_cache.flush_caches(cache_path, 2, cache)
    missing.unlink()
    original_stat = Path.stat

    def stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path == denied:
            raise PermissionError("denied")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", stat)
    seeded: OrderedDict[Path, history_loader._FileCacheEntry] = OrderedDict()

    dirty = history_disk_cache.seed_caches(cache_path, 2, 4096, seeded)

    assert set(seeded) == {live, denied}
    assert dirty == {history_disk_cache._shard_index(missing)}


def test_history_seed_deduplicates_old_cache_and_marks_shard(tmp_path: Path) -> None:
    cache_path = tmp_path / "history.json"
    source = tmp_path / "sessions" / "session.jsonl"
    source.parent.mkdir()
    source.write_text("", encoding="utf-8")
    cached = _history_entry(source)
    cached.entries.append(_usage_entry(source.stem))
    history_disk_cache.flush_caches(cache_path, 2, OrderedDict([(source, cached)]))
    seeded: OrderedDict[Path, history_loader._FileCacheEntry] = OrderedDict()

    dirty = history_disk_cache.seed_caches(cache_path, 2, 4096, seeded)

    assert len(seeded[source].entries) == 1
    assert dirty == {history_disk_cache._shard_index(source)}


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


def test_codex_corrupt_shard_is_skipped_and_rebuilt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "codex.json"
    first, second = _distinct_paths(codex_disk_cache._shard_index, tmp_path / "sessions")
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    original, info = _codex_caches(first, second)
    sqlite_cache = codex_loader._SqliteLogCache()
    codex_disk_cache.flush_caches(cache_path, 4, original, info, sqlite_cache)
    corrupt_shard = codex_disk_cache._shard_path(cache_path, codex_disk_cache._shard_index(first))
    corrupt_shard.write_text("broken", encoding="utf-8")
    seeded: OrderedDict[Path, codex_loader._JsonlCacheEntry] = OrderedDict()
    seeded_info: OrderedDict[Path, tuple[float, int, _SessionFileInfo]] = OrderedDict()
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", tmp_path / "quarantine")

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

    codex_disk_cache.seed_caches(cache_path, 4, 4096, entries, info, codex_loader._SqliteLogCache())

    assert not cache_path.exists()
    assert not entries
    assert not info


def test_codex_seed_skips_missing_but_keeps_stat_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_path = tmp_path / "codex.json"
    live, missing = _distinct_paths(codex_disk_cache._shard_index, tmp_path / "sessions")
    denied = live.with_name("denied.jsonl")
    for path in (live, missing, denied):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    entries = OrderedDict((path, _codex_entry(path)) for path in (live, missing, denied))
    info = OrderedDict(
        (
            path,
            (1.0, 10, _SessionFileInfo(session_id=path.stem, forked_from_id="")),
        )
        for path in entries
    )
    sqlite_cache = codex_loader._SqliteLogCache()
    codex_disk_cache.flush_caches(cache_path, 4, entries, info, sqlite_cache)
    missing.unlink()
    original_stat = Path.stat

    def stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path == denied:
            raise PermissionError("denied")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", stat)
    seeded: OrderedDict[Path, codex_loader._JsonlCacheEntry] = OrderedDict()
    seeded_info: OrderedDict[Path, tuple[float, int, _SessionFileInfo]] = OrderedDict()

    dirty = codex_disk_cache.seed_caches(cache_path, 4, 4096, seeded, seeded_info, sqlite_cache)

    assert set(seeded) == {live, denied}
    assert set(seeded_info) == {live, denied}
    assert dirty == {codex_disk_cache._shard_index(missing)}
