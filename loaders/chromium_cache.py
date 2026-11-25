# SPDX-License-Identifier: AGPL-3.0-only

"""Read one local JSON response from Chromium's HTTP cache.

Formats: Chromium net/disk_cache/blockfile/{disk_format,addr}.h,
net/disk_cache/simple/simple_entry_format.h, and net/http/http_response_info.cc.
No cookies, credentials, or requests are used. Unsupported formats and
incomplete/in-flight entries return no response.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from loaders._shared_cache_file import read_bounded, read_range

MAX_BODY = 1024 * 1024
MAX_WINDOW = 8 * 1024 * 1024
MAX_INDEX = 4 * 1024 * 1024
MAX_ENTRIES = 16 * 1024 * 1024
MAX_CHAIN_FILES = 16
BLOCK_MAGIC = 0xC103CAC3
BLOCK_SIZES = {1: 36, 2: 256, 3: 1024, 4: 4096, 5: 8, 6: 256, 7: 256}
INDEX_HEADER = 368
BLOCK_HEADER = 8192
TIME_EPOCH = 11644473600
# Simple-cache backend (Claude Desktop on macOS since late 2026): one file per entry.
SIMPLE_MAGIC = 0xFCFB6D1BA7725C30
SIMPLE_EOF_MAGIC = 0xF4FA6F45970D41D8
SIMPLE_ENTRY_VERSION = 5
SIMPLE_HEADER = 24
SIMPLE_EOF = 24
SIMPLE_HAS_CRC32 = 1
SIMPLE_HAS_KEY_SHA256 = 2
MAX_SIMPLE_ENTRY = MAX_BODY + 256 * 1024
MAX_SIMPLE_CANDIDATES = 4096
FRESH_SECONDS = 7200


@dataclass(frozen=True)
class CachedResponse:
    data: dict[str, object]
    fetched_at: float


def _response_info(raw: bytes) -> tuple[float, bytes]:
    if len(raw) < 28 or struct.unpack_from("<I", raw)[0] != len(raw) - 4:
        raise ValueError("Invalid response info")
    flags = struct.unpack_from("<I", raw, 4)[0]
    if flags & 255 != 3 or flags & (1 << 12):
        raise ValueError("Unsupported or truncated response")
    extra = struct.unpack_from("<I", raw, 8)[0] if flags & (1 << 31) else 0
    offset = 12 if flags & (1 << 31) else 8
    fetched_at = struct.unpack_from("<q", raw, offset + 8)[0] / 1e6 - TIME_EPOCH
    offset += 16 + (8 if extra & 4 else 0)
    length = struct.unpack_from("<I", raw, offset)[0]
    headers = raw[offset + 4 : offset + 4 + length]
    if len(headers) != length or not re.match(rb"^HTTP/\S+ 200(?: |\x00)", headers):
        raise ValueError("No successful response headers")
    if b"application/json" not in headers.lower():
        raise ValueError("Not a JSON response")
    return fetched_at, headers


def _decode(raw: bytes, headers: bytes) -> dict[str, object]:
    # Chrome may store a zstd frame even when the original HTTP response used
    # another encoding. Detect the on-disk frame first.
    if raw.startswith(b"\x28\xb5\x2f\xfd"):
        try:
            import zstandard
        except (ImportError, OSError) as exc:
            raise ValueError("Zstandard decoder is unavailable") from exc
        try:
            size = zstandard.frame_content_size(raw)
            if size != zstandard.CONTENTSIZE_UNKNOWN and size > MAX_BODY:
                raise ValueError("Response body exceeds the size limit")
            if zstandard.get_frame_parameters(raw).window_size > MAX_WINDOW:
                raise ValueError("Response compression window exceeds the size limit")
            decoder = zstandard.ZstdDecompressor(max_window_size=MAX_WINDOW)
            raw = decoder.decompress(raw, max_output_size=MAX_BODY, allow_extra_data=False)
        except zstandard.ZstdError as exc:
            raise ValueError("Invalid Zstandard response") from exc
    elif raw.startswith(b"\x1f\x8b") or b"content-encoding: deflate" in headers.lower():
        decoder_z = zlib.decompressobj(31 if raw.startswith(b"\x1f\x8b") else 15)
        raw = decoder_z.decompress(raw, MAX_BODY + 1)
        if not decoder_z.eof:
            raise ValueError("Incomplete or oversized compressed response")
    if len(raw) > MAX_BODY:
        raise ValueError("Response body exceeds the size limit")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Not a JSON object")
    return cast(dict[str, object], data)


class _BlockCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.index = read_bounded(path / "index", MAX_INDEX)
        magic, version = struct.unpack_from("<II", self.index)
        if magic != BLOCK_MAGIC or version not in {0x20000, 0x20001, 0x30000}:
            raise ValueError("Unsupported cache index")
        self.table_len = struct.unpack_from("<i", self.index, 28)[0] or 65536
        if (
            self.table_len <= 0
            or self.table_len & (self.table_len - 1)
            or len(self.index) != INDEX_HEADER + 4 * self.table_len
        ):
            raise ValueError("Invalid cache index size")

    def stream(self, address: int, length: int) -> bytes:
        if not address & 0x80000000 or not 0 < length <= MAX_BODY:
            raise ValueError("Invalid cache stream")
        kind = (address >> 28) & 7
        if kind == 0:
            raw = read_range(self.path / f"f_{address & 0x0FFFFFFF:06x}", 0, length)
        else:
            size = BLOCK_SIZES[kind]
            if length > size * (((address >> 24) & 3) + 1):
                raise ValueError("Invalid block allocation")
            offset = BLOCK_HEADER + (address & 65535) * size
            raw = read_range(self.path / f"data_{(address >> 16) & 255}", offset, length)
        if len(raw) != length:
            raise ValueError("Incomplete cache stream")
        return raw

    def _active(self, entry: bytes, file: int, block: int) -> bool:
        bucket = struct.unpack_from("<I", entry)[0] & (self.table_len - 1)
        address = struct.unpack_from("<I", self.index, INDEX_HEADER + bucket * 4)[0]
        visited: set[int] = set()
        for _ in range(128):
            if not address or address in visited or (address >> 28) & 7 not in {2, 6}:
                return False
            visited.add(address)
            if ((address >> 16) & 255, address & 65535) == (file, block):
                return True
            address = struct.unpack_from("<I", self.stream(address, 256), 4)[0]
        return False

    def responses(self, url: bytes, earliest: float, now: float) -> list[CachedResponse]:
        files = {
            (address >> 16) & 255
            for (address,) in struct.iter_unpack("<I", self.index[INDEX_HEADER:])
            if (address >> 28) & 7 in {2, 6}
        }
        results = []
        pending = [(file, 0) for file in sorted(files)]
        visited: set[int] = set()
        while pending:
            file, depth = pending.pop(0)
            if file in visited:
                continue
            visited.add(file)
            try:
                raw = read_bounded(self.path / f"data_{file}", MAX_ENTRIES)
            except (OSError, ValueError):
                continue
            if (
                len(raw) < BLOCK_HEADER
                or struct.unpack_from("<II", raw) != (0xC104CAC3, 0x20000)
                or struct.unpack_from("<H", raw, 8)[0] != file
                or struct.unpack_from("<i", raw, 12)[0] != 256
            ):
                continue
            next_file = struct.unpack_from("<H", raw, 10)[0]
            if next_file and depth + 1 < MAX_CHAIN_FILES:
                pending.append((next_file, depth + 1))
            for offset in range(BLOCK_HEADER, len(raw) - 255, 256):
                entry = raw[offset : offset + 256]
                try:
                    response = self._response(raw, offset, entry, file, url, earliest, now)
                except (
                    OSError,
                    ValueError,
                    struct.error,
                    zlib.error,
                    RecursionError,
                ):
                    continue
                if response is not None:
                    results.append(response)
        return results

    def _response(
        self,
        raw: bytes,
        offset: int,
        entry: bytes,
        file: int,
        url: bytes,
        earliest: float,
        now: float,
    ) -> CachedResponse | None:
        if struct.unpack_from("<i", entry, 20)[0] != 0:
            return None
        key_len, long_key = struct.unpack_from("<iI", entry, 32)
        if not 0 < key_len <= 4096:
            return None
        key = (
            self.stream(long_key, key_len) if long_key else raw[offset + 96 : offset + 96 + key_len]
        )
        if not _matches(key, url):
            return None
        if not self._active(entry, file, (offset - BLOCK_HEADER) // 256):
            return None
        ranking = self.stream(struct.unpack_from("<I", entry, 8)[0], 36)
        if struct.unpack_from("<i", ranking, 28)[0] != 0:
            return None
        sizes = struct.unpack_from("<4i", entry, 40)
        addresses = struct.unpack_from("<4I", entry, 56)
        metadata = self.stream(addresses[0], sizes[0])
        fetched_at, headers = _response_info(metadata)
        if not max(earliest, now - FRESH_SECONDS) <= fetched_at <= now + 60:
            return None
        body = self.stream(addresses[1], sizes[1])
        # Cache updates are concurrent; refuse entries whose metadata changed
        # while reading. No files are copied, modified, or locked exclusively.
        if read_range(self.path / f"data_{file}", offset, 96) != entry[:96]:
            return None
        if self.stream(addresses[0], sizes[0]) != metadata:
            return None
        return CachedResponse(_decode(body, headers), fetched_at)


class _SimpleCache:
    """One `<hash>_0` file per entry: header, key, body, EOF, response info, EOF."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def responses(self, url: bytes, earliest: float, now: float) -> list[CachedResponse]:
        # Entry names hash the full key. The plain key (Desktop 7) gives its
        # file name directly; keys with a query string (Desktop 6, `?via=plan`)
        # can't be predicted, so also scan by mtime. A busy or freshly installed
        # profile writes thousands of files in minutes, which is why the direct
        # name comes first. Older responses are rejected below anyway; the cap
        # bounds the work.
        direct = _simple_name(b"1/0/" + url)
        lower = max(earliest, now - FRESH_SECONDS) - 60
        candidates: list[tuple[float, str]] = []
        with os.scandir(self.path) as entries:
            for entry in entries:
                if len(entry.name) != 18 or not entry.name.endswith("_0") or entry.name == direct:
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                if stat.st_mtime >= lower and stat.st_size <= MAX_SIMPLE_ENTRY:
                    candidates.append((stat.st_mtime, entry.name))
        candidates.sort(reverse=True)
        results = []
        for name in [direct, *(name for _mtime, name in candidates[:MAX_SIMPLE_CANDIDATES])]:
            try:
                response = self._response(self.path / name, url, earliest, now)
            except (OSError, ValueError, struct.error, zlib.error, RecursionError):
                continue
            if response is not None:
                results.append(response)
        return results

    def _response(
        self, path: Path, url: bytes, earliest: float, now: float
    ) -> CachedResponse | None:
        # Most candidates are other responses, so match the key from a short
        # read before reading the whole file. The full read checks the key
        # again, and the CRCs below reject a concurrent rewrite.
        head_key = _simple_key(read_range(path, 0, SIMPLE_HEADER + 4096))
        if head_key is None or not _matches(head_key, url):
            return None
        raw = read_bounded(path, MAX_SIMPLE_ENTRY)
        key = _simple_key(raw)
        if len(raw) < SIMPLE_HEADER + 2 * SIMPLE_EOF or key is None or not _matches(key, url):
            return None
        end = len(raw) - SIMPLE_EOF
        eof_magic, flags, info_crc, info_len = struct.unpack_from("<QIII", raw, end)
        if eof_magic != SIMPLE_EOF_MAGIC:
            return None
        if flags & SIMPLE_HAS_KEY_SHA256:
            end -= 32
            if raw[end : end + 32] != hashlib.sha256(key).digest():
                return None
        info_start = end - info_len
        body_end = info_start - SIMPLE_EOF
        body_start = SIMPLE_HEADER + len(key)
        if not 0 < info_len <= MAX_BODY or not 0 < body_end - body_start <= MAX_BODY:
            return None
        body_magic, body_flags, body_crc, _unused = struct.unpack_from("<QIII", raw, body_end)
        if body_magic != SIMPLE_EOF_MAGIC:
            return None
        info = raw[info_start:end]
        body = raw[body_start:body_end]
        if flags & SIMPLE_HAS_CRC32 and zlib.crc32(info) != info_crc:
            return None
        if body_flags & SIMPLE_HAS_CRC32 and zlib.crc32(body) != body_crc:
            return None
        fetched_at, headers = _response_info(info)
        if not max(earliest, now - FRESH_SECONDS) <= fetched_at <= now + 60:
            return None
        return CachedResponse(_decode(body, headers), fetched_at)


def _simple_name(key: bytes) -> str:
    # Chromium names a simple-cache entry after the first 8 bytes of SHA-1(key).
    digest = hashlib.sha1(key, usedforsecurity=False).digest()
    return f"{struct.unpack_from('<Q', digest)[0]:016x}_0"


def _simple_key(raw: bytes) -> bytes | None:
    if len(raw) < SIMPLE_HEADER:
        return None
    magic, version, key_len, _key_hash = struct.unpack_from("<QIII", raw)
    if magic != SIMPLE_MAGIC or version != SIMPLE_ENTRY_VERSION or not 0 < key_len <= 4096:
        return None
    key = raw[SIMPLE_HEADER : SIMPLE_HEADER + key_len]
    return key if len(key) == key_len else None


def _matches(key: bytes, url: bytes) -> bool:
    # Chromium prefixes keys with upload identifiers (e.g. "1/0/") and may
    # also add a network-isolation key before the request URL. Desktop now
    # also appends query strings such as `?via=plan`.
    return key[key.rfind(b"https://") :].partition(b"?")[0] == url


def _open_cache(path: Path) -> _BlockCache | _SimpleCache:
    # The simple backend keeps only a 24-byte placeholder `index` that starts
    # with the same magic as its entry files; the real index is in index-dir/.
    if read_range(path / "index", 0, 8) == struct.pack("<Q", SIMPLE_MAGIC):
        return _SimpleCache(path)
    return _BlockCache(path)


def load_cached_json(path: Path, url: bytes, earliest: float, now: float) -> CachedResponse | None:
    try:
        responses = _open_cache(path).responses(url, earliest, now)
    except (OSError, ValueError, struct.error):
        return None
    return max(responses, key=lambda response: response.fetched_at, default=None)
