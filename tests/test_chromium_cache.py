from __future__ import annotations

import gzip
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import zstandard

from loaders import chromium_cache as cache
from loaders import claude_desktop as desktop
from loaders._shared_cache_file import read_range

NOW = 2_000_000_000.0
URL = b"https://claude.ai/api/organizations/org-a/usage"


@dataclass
class Response:
    fetched: float = NOW
    url: bytes = URL
    encoding: str = "zstd"
    dirty: int = 0
    state: int = 0
    active: bool = True
    status: int = 200
    payload: Any = None


def _block_file(file: int, size: int, blocks: int) -> bytearray:
    raw = bytearray(8192 + size * blocks)
    struct.pack_into("<IIHHi", raw, 0, 0xC104CAC3, 0x20000, file, 0, size)
    return raw


def _address(kind: int, file: int, block: int) -> int:
    return 0x80000000 | kind << 28 | file << 16 | block


def _cache(path: Path, *responses: Response) -> None:
    path.mkdir(parents=True, exist_ok=True)
    index = bytearray(368 + 64 * 4)
    struct.pack_into("<II", index, 0, 0xC103CAC3, 0x30000)
    struct.pack_into("<i", index, 28, 64)
    entries = _block_file(1, 256, len(responses))
    headers = _block_file(2, 1024, len(responses))
    rankings = _block_file(0, 36, len(responses))
    for i, response in enumerate(responses):
        payload = response.payload
        if payload is None:
            payload = {
                "five_hour": {"utilization": 14, "resets_at": _iso(NOW + 100)},
                "seven_day": {"utilization": 1, "resets_at": _iso(NOW + 200)},
            }
        body = json.dumps(payload).encode()
        if response.encoding == "zstd":
            body = zstandard.ZstdCompressor(write_content_size=False).compress(body)
        elif response.encoding == "gzip":
            body = gzip.compress(body)
        elif response.encoding == "deflate":
            body = zlib.compress(body)
        fields = (
            f"HTTP/1.1 {response.status} OK\0content-type: application/json\0"
            f"content-encoding: {response.encoding}\0\0"
        ).encode()
        timestamp = round((response.fetched + cache.TIME_EPOCH) * 1e6)
        # Include both extra flags and original-response-time as real Desktop does.
        metadata = struct.pack(
            "<IIqqqI", 3 | 1 << 31, 6, timestamp, timestamp, timestamp, len(fields)
        )
        metadata += fields
        metadata = struct.pack("<I", len(metadata)) + metadata
        headers[8192 + i * 1024 : 8192 + i * 1024 + len(metadata)] = metadata
        offset = 8192 + i * 256
        key = b"1/0/" + response.url
        assert len(key) < 160
        struct.pack_into(
            "<IIIiiiQ", entries, offset, i + 1, 0, _address(1, 0, i), 0, 0, response.state, 1
        )
        struct.pack_into("<iI", entries, offset + 32, len(key), 0)
        struct.pack_into("<4i", entries, offset + 40, len(metadata), len(body), 0, 0)
        struct.pack_into("<4I", entries, offset + 56, _address(3, 2, i), 0x80000000 | i + 1, 0, 0)
        entries[offset + 96 : offset + 96 + len(key)] = key
        struct.pack_into("<i", rankings, 8192 + i * 36 + 28, response.dirty)
        if response.active:
            struct.pack_into("<I", index, 368 + (i + 1) * 4, _address(2, 1, i))
        (path / f"f_{i + 1:06x}").write_bytes(body)
    for name, raw in [
        ("index", index),
        ("data_0", rankings),
        ("data_1", entries),
        ("data_2", headers),
    ]:
        (path / name).write_bytes(raw)


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


@pytest.mark.parametrize("encoding", ["plain", "gzip", "deflate", "zstd"])
def test_reads_exact_cached_response_without_modifying_files(tmp_path: Path, encoding: str) -> None:
    _cache(tmp_path, Response(encoding=encoding))
    original = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = cache.load_cached_json(tmp_path, URL, NOW - 60, NOW)
    assert result is not None
    assert result.fetched_at == NOW
    assert result.data["five_hour"] == {"utilization": 14, "resets_at": _iso(NOW + 100)}
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == original


def test_selects_latest_response_time_not_creation_time(tmp_path: Path) -> None:
    _cache(tmp_path, Response(fetched=NOW - 10), Response(url=URL + b"?skip_spend=1"))
    result = cache.load_cached_json(tmp_path, URL, NOW - 60, NOW)
    assert result is not None and result.fetched_at == NOW


@pytest.mark.parametrize(
    "response",
    [
        Response(url=b"https://other.example/api/organizations/org-a/usage"),
        Response(url=URL.replace(b"org-a", b"org-b")),
        Response(url=URL + b"-other"),
        Response(dirty=1),
        Response(state=1),
        Response(active=False),
        Response(status=403),
        Response(fetched=NOW - 61),
        Response(fetched=NOW + 61),
        Response(payload=[]),
    ],
)
def test_rejects_unrelated_or_unusable_response(tmp_path: Path, response: Response) -> None:
    _cache(tmp_path, response)
    assert cache.load_cached_json(tmp_path, URL, NOW - 60, NOW) is None


def test_rejects_two_hour_old_cache_even_when_history_is_older(tmp_path: Path) -> None:
    _cache(tmp_path, Response(fetched=NOW - 7201))
    assert cache.load_cached_json(tmp_path, URL, NOW - 10000, NOW) is None


@pytest.mark.parametrize("filename", ["index", "data_0", "data_1", "data_2", "f_000001"])
def test_truncated_cache_is_unavailable(tmp_path: Path, filename: str) -> None:
    _cache(tmp_path, Response())
    (tmp_path / filename).write_bytes(b"invalid")
    assert cache.load_cached_json(tmp_path, URL, NOW - 60, NOW) is None


def test_rejects_changed_response_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _cache(tmp_path, Response())
    real_read = read_range

    def changed(path: Path, offset: int, length: int) -> bytes:
        raw = real_read(path, offset, length)
        return b"\xff" + raw[1:] if path.name == "data_1" else raw

    monkeypatch.setattr(cache, "read_range", changed)
    assert cache.load_cached_json(tmp_path, URL, NOW - 60, NOW) is None


@pytest.mark.parametrize("content_size", [True, False])
def test_zstd_decompression_output_is_bounded(content_size: bool) -> None:
    body = zstandard.ZstdCompressor(write_content_size=content_size).compress(
        b" " * (cache.MAX_BODY + 1)
    )
    with pytest.raises((ValueError, zstandard.ZstdError)):
        cache._decode(body, b"")


def test_rejects_truncated_zstd_frame() -> None:
    body = zstandard.ZstdCompressor(write_content_size=False).compress(b'{"a":1}')
    with pytest.raises(ValueError, match="Invalid Zstandard response"):
        cache._decode(body[:-1], b"")


def test_cache_enriches_history_only_for_latest_org(tmp_path: Path) -> None:
    history = tmp_path / desktop.HISTORY_NAME
    history.write_text(
        json.dumps(
            {"version": 2, "samples": [{"t": NOW * 1000, "org": "org-a", "u": {"fh": 14, "sd": 1}}]}
        ),
        encoding="utf-8",
    )
    _cache(tmp_path / "Cache/Cache_Data", Response())
    assert desktop._read_history(history, NOW) == desktop.DesktopQuota(
        14, 1, NOW, NOW + 100, NOW + 200
    )
    updated = json.loads(history.read_text())
    updated["samples"].append({"t": NOW * 1000, "org": "org-b", "u": {"fh": 5}})
    history.write_text(json.dumps(updated), encoding="utf-8")
    assert desktop._read_history(history, NOW) == desktop.DesktopQuota(5, None, NOW)


@pytest.mark.parametrize(
    "reset", [None, "bad", _iso(NOW), _iso(NOW + 604861), "2033-05-18T03:33:20"]
)
def test_reset_parser_rejects_unknown_past_naive_or_impossible_times(reset: object) -> None:
    assert desktop._reset_time({"utilization": 1, "resets_at": reset}, NOW, NOW + 604860) is None


def test_missing_or_unsupported_cache_does_not_hide_valid_percentages(tmp_path: Path) -> None:
    history = tmp_path / desktop.HISTORY_NAME
    history.write_text(
        json.dumps({"version": 2, "samples": [{"t": NOW * 1000, "org": "org-a", "u": {"fh": 14}}]}),
        encoding="utf-8",
    )
    assert desktop._read_history(history, NOW) == desktop.DesktopQuota(14, None, NOW)


def test_mismatched_cached_percentage_does_not_supply_reset_time() -> None:
    assert (
        desktop._reset_time({"utilization": 14, "resets_at": _iso(NOW + 100)}, NOW, NOW + 18060, 13)
        is None
    )


def test_fresher_cached_observation_replaces_throttled_history(tmp_path: Path) -> None:
    history = tmp_path / desktop.HISTORY_NAME
    history.write_text(
        json.dumps(
            {"version": 2, "samples": [{"t": NOW * 1000, "org": "org-a", "u": {"fh": 12, "sd": 0}}]}
        ),
        encoding="utf-8",
    )
    _cache(tmp_path / "Cache/Cache_Data", Response(fetched=NOW + 1))
    assert desktop._read_history(history, NOW + 1) == desktop.DesktopQuota(
        14, 1, NOW + 1, NOW + 100, NOW + 200
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing semantics")
def test_reads_file_opened_with_delete_access_on_windows(tmp_path: Path) -> None:
    from loaders._shared_cache_file import _kernel

    path = tmp_path / "cache-block"
    path.write_bytes(b"quota-data")
    kernel = _kernel()
    owner = kernel.CreateFileW(str(path), 0xC0010000, 7, None, 3, 0, None)
    try:
        assert read_range(path, 6, 4) == b"data"
    finally:
        kernel.CloseHandle(owner)
