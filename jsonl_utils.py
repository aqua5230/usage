from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from jsonl_limits import read_bounded_jsonl_line

logger = logging.getLogger(__name__)


def iter_jsonl_dicts(
    path: Path,
    *,
    encoding: str = "utf-8",
    errors: str | None = None,
) -> Iterator[dict[str, Any]]:
    with path.open("rb") as file:
        while True:
            raw_bytes, too_long = read_bounded_jsonl_line(file)
            if too_long:
                logger.warning("skipping oversized JSONL line in %s", path)
                continue
            if not raw_bytes:
                break
            line = (
                raw_bytes.decode(encoding)
                if errors is None
                else raw_bytes.decode(encoding, errors=errors)
            ).strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, RecursionError):
                continue
            if isinstance(data, dict):
                yield data
