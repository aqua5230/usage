# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Stateless value parsing for Codex session logs.

Leaf helpers shared by codex_loader's JSONL and sqlite readers: coercing raw
JSON/log values into scalars, token-usage payloads and per-file metadata.
Nothing here touches module state, the filesystem layout constants, or caches —
those all stay in codex_loader so test monkeypatching keeps working.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class _ThreadMetadata:
    model: str = "unknown"
    cwd: str = ""


@dataclass(frozen=True, slots=True)
class _SessionFileInfo:
    session_id: str = ""
    forked_from_id: str = ""


@dataclass(frozen=True, slots=True)
class _TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens

    def delta(self, previous: _TokenUsage | None) -> _TokenUsage:
        if previous is None:
            return self
        return _TokenUsage(
            input_tokens=max(0, self.input_tokens - previous.input_tokens),
            output_tokens=max(0, self.output_tokens - previous.output_tokens),
            cache_read_tokens=max(0, self.cache_read_tokens - previous.cache_read_tokens),
        )


def _token_usage_from_payload(usage: dict[str, Any]) -> _TokenUsage:
    cached = _as_int(usage.get("cached_input_tokens"))
    input_tokens = max(0, _as_int(usage.get("input_tokens")) - cached)
    output_tokens = _as_int(usage.get("output_tokens"))
    return _TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cached,
    )


def _load_json_line(line: str) -> dict[str, Any] | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


_EVENT_VALUE_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _event_value(body: str, key: str) -> str:
    pattern = _EVENT_VALUE_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(rf'(?:^|[\s{{]){re.escape(key)}=(?:"([^"]*)"|([^\s}}]+))')
        _EVENT_VALUE_RE_CACHE[key] = pattern
    match = pattern.search(body)
    if match is None:
        return ""
    return match.group(1) if match.group(1) is not None else match.group(2)


def _timestamp_from_log_ts(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp):
        return None
    return datetime.fromtimestamp(timestamp, UTC)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _session_model(payload: Any, fallback: str) -> str:
    model = _as_str(_as_dict(payload).get("model"))
    return model or fallback


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number):
        return 0
    return max(0, int(number))


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number
