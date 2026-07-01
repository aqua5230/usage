from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def iter_jsonl_dicts(
    path: Path,
    *,
    encoding: str = "utf-8",
    errors: str | None = None,
) -> Iterator[dict[str, Any]]:
    if errors is None:
        file = path.open(encoding=encoding)
    else:
        file = path.open(encoding=encoding, errors=errors)
    with file:
        for raw_line in file:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data
