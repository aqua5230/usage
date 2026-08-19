"""Shared JSONL line-size limit and bounded binary reader."""

from __future__ import annotations

from typing import BinaryIO

MAX_JSONL_LINE_BYTES = 64 * 1024 * 1024


def read_bounded_jsonl_line(file: BinaryIO) -> tuple[bytes, bool]:
    """Read one line, draining and flagging it when it exceeds the shared limit."""
    line = file.readline(MAX_JSONL_LINE_BYTES + 1)
    if len(line) <= MAX_JSONL_LINE_BYTES:
        return line, False
    while line and not line.endswith(b"\n"):
        line = file.readline(65536)
    return b"", True
