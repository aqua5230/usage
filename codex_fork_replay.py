# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Stateless scanning for Codex fork-replay deduplication.

Fork logs rewrite replay timestamps but preserve the parent's cumulative token
sequence, so the boundary between replayed and new events is found by matching
token-usage prefixes against candidate parent logs. The LRU cache and its
orchestration (_fork_replay_boundary) stay in codex_loader; these helpers only
read the files they are handed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codex_events import (
    _as_dict,
    _as_str,
    _load_json_line,
    _token_usage_from_payload,
    _TokenUsage,
)

_ReplayCacheKey = tuple[str, float, int, int] | None
_ReplayLookupKey = tuple[float, int, tuple[tuple[str, float, int], ...]]


def _fork_replay_lookup_key(
    path: Path,
    parent_paths: list[Path],
) -> _ReplayLookupKey | None:
    try:
        child_stat = path.stat()
    except OSError:
        return None
    parent_stats: list[tuple[str, float, int]] = []
    for parent_path in parent_paths:
        try:
            parent_stat = parent_path.stat()
        except OSError:
            continue
        parent_stats.append((str(parent_path), parent_stat.st_mtime, parent_stat.st_size))
    return child_stat.st_mtime, child_stat.st_size, tuple(sorted(parent_stats))


def _token_usage_events_after_embedded_parent(
    path: Path,
    parent_session_id: str,
) -> list[tuple[int, _TokenUsage]] | None:
    embedded_parent = False
    root_seen = False
    events: list[tuple[int, _TokenUsage]] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                data = _load_json_line(line)
                if data is None:
                    continue
                if data.get("type") == "session_meta":
                    session_id = _as_str(_as_dict(data.get("payload")).get("id"))
                    if not root_seen:
                        root_seen = True
                    elif session_id == parent_session_id:
                        embedded_parent = True
                    continue
                usage = _token_usage_from_event(data)
                if embedded_parent and usage is not None:
                    events.append((line_number, usage))
    except (OSError, UnicodeDecodeError):
        return None
    return events if embedded_parent else None


def _raw_token_usage_sequence(path: Path) -> list[_TokenUsage]:
    usage_events: list[_TokenUsage] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                data = _load_json_line(line)
                if data is None:
                    continue
                usage = _token_usage_from_event(data)
                if usage is not None:
                    usage_events.append(usage)
    except (OSError, UnicodeDecodeError):
        return []
    return usage_events


def _token_usage_from_event(data: dict[str, Any]) -> _TokenUsage | None:
    if data.get("type") != "event_msg":
        return None
    payload = _as_dict(data.get("payload"))
    if payload.get("type") != "token_count":
        return None
    usage = _as_dict(_as_dict(payload.get("info")).get("total_token_usage"))
    return _token_usage_from_payload(usage) if usage else None


def _common_prefix_length(left: list[_TokenUsage], right: list[_TokenUsage]) -> int:
    matched = 0
    for left_usage, right_usage in zip(left, right, strict=False):
        if left_usage != right_usage:
            break
        matched += 1
    return matched
