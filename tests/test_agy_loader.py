# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import agy_loader


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(encoded)


def _varint_field(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _message_field(field: int, payload: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def _timestamp_blob(timestamp: datetime) -> bytes:
    seconds = int(timestamp.timestamp())
    nanos = timestamp.microsecond * 1_000
    return _varint_field(1, seconds) + _varint_field(2, nanos)


def _generation_blob(
    *,
    timestamp: datetime | None,
    dedup_key: str | None,
    model: str = "gemini-3.5-flash-low",
    system_tokens: int = 1_020,
    input_tokens: int = 200,
    cache_read_tokens: int = 70_000,
    output_tokens: int = 30,
    thinking_tokens: int = 4,
) -> bytes:
    usage = b"".join(
        (
            _varint_field(1, system_tokens),
            _varint_field(2, input_tokens),
            _varint_field(5, cache_read_tokens),
            _varint_field(9, output_tokens),
            _varint_field(10, thinking_tokens),
        )
    )
    if dedup_key is not None:
        usage += _message_field(11, dedup_key.encode())
    chat_model = _message_field(4, usage) + _message_field(19, model.encode())
    if timestamp is not None:
        chat_model += _message_field(9, _message_field(4, _timestamp_blob(timestamp)))
    return _message_field(1, chat_model)


def _trajectory_blob(timestamp: datetime) -> bytes:
    return _message_field(2, _timestamp_blob(timestamp))


def _write_database(path: Path, rows: list[bytes], session_timestamp: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB, size INTEGER);"
            "CREATE TABLE trajectory_metadata_blob (data BLOB);"
        )
        connection.executemany(
            "INSERT INTO gen_metadata (idx, data, size) VALUES (?, ?, ?)",
            [(index, blob, len(blob)) for index, blob in enumerate(rows)],
        )
        connection.execute(
            "INSERT INTO trajectory_metadata_blob (data) VALUES (?)",
            (_trajectory_blob(session_timestamp),),
        )


@pytest.fixture
def sessions_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "conversations"
    monkeypatch.setattr(agy_loader, "AGY_SESSIONS_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def _clear_file_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    agy_loader._file_cache.clear()
    monkeypatch.setattr(agy_loader, "AGY_CACHE_PATH", tmp_path / "agy_db_cache.json")
    monkeypatch.setattr(agy_loader, "_disk_cache_seeded", False)
    monkeypatch.setattr(agy_loader, "_disk_cache_dirty", False)
    monkeypatch.setattr(agy_loader, "_last_disk_cache_flush_at", None)


def test_load_entries_parses_usage_deduplicates_and_skips_non_generation_rows(
    sessions_dir: Path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=250_000)
    _write_database(
        sessions_dir / "first.db",
        [
            _message_field(1, b"feature-flag-setting"),
            _generation_blob(timestamp=now, dedup_key="opaque-response-id"),
            _generation_blob(timestamp=now, dedup_key="opaque-response-id"),
            _generation_blob(timestamp=now, dedup_key=None),
        ],
        now - timedelta(minutes=1),
    )

    result = agy_loader.load_entries_with_stats()

    assert result.skipped_missing_dedup_key == 1
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.timestamp == now
    assert entry.session_id == "first"
    assert entry.model == "gemini-3.5-flash-low"
    assert entry.input_tokens == 1_220
    assert entry.output_tokens == 30
    assert entry.cache_read_tokens == 70_000
    assert entry.thinking_tokens == 4
    assert entry.dedup_key == "opaque-response-id"


def test_load_entries_filters_on_generation_timestamp_and_falls_back_to_session_timestamp(
    sessions_dir: Path,
) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(hours=2)
    _write_database(
        sessions_dir / "timestamps.db",
        [
            _generation_blob(timestamp=old, dedup_key="old"),
            _generation_blob(timestamp=None, dedup_key="fallback"),
        ],
        now,
    )

    entries = agy_loader.load_entries(hours_back=1)

    assert [entry.dedup_key for entry in entries] == ["fallback"]
    assert entries[0].timestamp == now


def test_recent_input_output_tokens_excludes_cache_and_thinking(sessions_dir: Path) -> None:
    now = datetime.now(UTC)
    _write_database(
        sessions_dir / "totals.db",
        [
            _generation_blob(
                timestamp=now,
                dedup_key="total",
                system_tokens=1_000,
                input_tokens=20,
                output_tokens=30,
                cache_read_tokens=99_999,
                thinking_tokens=500,
            )
        ],
        now,
    )

    assert agy_loader.recent_input_output_tokens(1) == 1_050


def test_load_entries_skips_database_when_sqlite_is_locked(
    monkeypatch: pytest.MonkeyPatch, sessions_dir: Path
) -> None:
    (sessions_dir / "locked.db").parent.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "locked.db").touch()

    def _locked_connect(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(sqlite3, "connect", _locked_connect)

    assert agy_loader.load_entries() == []


def test_load_entries_reuses_unchanged_database_cache(
    monkeypatch: pytest.MonkeyPatch, sessions_dir: Path
) -> None:
    now = datetime.now(UTC)
    _write_database(
        sessions_dir / "cached.db",
        [_generation_blob(timestamp=now, dedup_key="cached")],
        now,
    )
    original_parse_database = agy_loader._parse_database
    parse_calls = 0

    def _counting_parse_database(
        path: Path,
    ) -> tuple[list[agy_loader.AgyUsageEntry], int] | None:
        nonlocal parse_calls
        parse_calls += 1
        return original_parse_database(path)

    monkeypatch.setattr(agy_loader, "_parse_database", _counting_parse_database)

    first = agy_loader.load_entries_with_stats()
    second = agy_loader.load_entries_with_stats()

    assert first == second
    assert parse_calls == 1


def test_load_entries_reparses_database_when_mtime_changes(
    monkeypatch: pytest.MonkeyPatch, sessions_dir: Path
) -> None:
    now = datetime.now(UTC)
    path = sessions_dir / "changed.db"
    _write_database(path, [_generation_blob(timestamp=now, dedup_key="changed")], now)
    original_parse_database = agy_loader._parse_database
    parse_calls = 0

    def _counting_parse_database(
        database_path: Path,
    ) -> tuple[list[agy_loader.AgyUsageEntry], int] | None:
        nonlocal parse_calls
        parse_calls += 1
        return original_parse_database(database_path)

    monkeypatch.setattr(agy_loader, "_parse_database", _counting_parse_database)

    agy_loader.load_entries_with_stats()
    stat = path.stat()
    path.touch(exist_ok=True)
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))
    agy_loader.load_entries_with_stats()

    assert parse_calls == 2


def test_load_entries_reuses_disk_cache_after_reseed(
    monkeypatch: pytest.MonkeyPatch, sessions_dir: Path
) -> None:
    now = datetime.now(UTC)
    _write_database(
        sessions_dir / "persisted.db",
        [_generation_blob(timestamp=now, dedup_key="persisted")],
        now,
    )
    expected = agy_loader.load_entries_with_stats()
    assert agy_loader.AGY_CACHE_PATH.is_file()

    agy_loader._file_cache.clear()
    monkeypatch.setattr(agy_loader, "_disk_cache_seeded", False)

    def _unexpected_connect(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise AssertionError("disk cache miss unexpectedly opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", _unexpected_connect)

    assert agy_loader.load_entries_with_stats() == expected
