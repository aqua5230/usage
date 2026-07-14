# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import logging
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from jsonl_utils import iter_jsonl_dicts
from project_resolver import project_from_encoded_path, resolve_project_name
from time_utils import parse_optional_iso8601_utc

logger = logging.getLogger(__name__)

CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))
_CACHE_TTL_SECONDS = 300.0
_cache: dict[int, tuple[float, PersonaProfile]] = {}


@dataclass(slots=True)
class PersonaProfile:
    hour_histogram: list[int]
    top_projects: list[tuple[str, int]]
    recent_titles: list[str]
    total_sessions: int
    total_messages: int


@dataclass(slots=True)
class _MetadataLine:
    type: str
    timestamp: datetime | None
    session_id: str
    cwd: str
    title: str


def load_profile(days_back: int = 30) -> PersonaProfile:
    now = time.time()
    cached = _cache.get(days_back)
    if cached is not None:
        cached_at, cached_profile = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached_profile

    profile = _load_profile_uncached(days_back)
    _cache[days_back] = (now, profile)
    return profile


def _reset_cache() -> None:
    _cache.clear()


def _load_profile_uncached(days_back: int) -> PersonaProfile:
    histogram = [0] * 24
    sessions_by_project: dict[str, set[str]] = {}
    message_sessions: set[str] = set()
    session_last_message_at: dict[str, datetime] = {}
    titles_by_session: dict[str, str] = {}
    total_messages = 0

    cutoff = datetime.now(UTC) - timedelta(days=max(0, days_back))
    cutoff_ts = cutoff.timestamp()

    if not CLAUDE_PROJECTS_DIR.is_dir():
        return _empty_profile()

    for jsonl_path in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        try:
            if jsonl_path.stat().st_mtime < cutoff_ts:
                continue
        except OSError as exc:
            logger.warning("failed to stat Claude project log %s: %s", jsonl_path, exc)
            continue

        fallback_project = _project_from_path(jsonl_path)
        try:
            for data in iter_jsonl_dicts(jsonl_path, errors="replace"):
                parsed = _parse_metadata_line(data)
                if parsed is None:
                    continue

                session_id = parsed.session_id
                if session_id:
                    title = parsed.title.strip()
                    if parsed.type == "ai-title" and title:
                        titles_by_session[session_id] = title

                timestamp = parsed.timestamp
                if timestamp is None or timestamp < cutoff:
                    continue

                is_message = parsed.type in {"user", "assistant"}
                if is_message:
                    histogram[timestamp.astimezone().hour] += 1
                    total_messages += 1

                if session_id and is_message:
                    project = _project_from_cwd(parsed.cwd) or fallback_project
                    sessions_by_project.setdefault(project, set()).add(session_id)
                    message_sessions.add(session_id)
                    current_last = session_last_message_at.get(session_id)
                    if current_last is None or timestamp > current_last:
                        session_last_message_at[session_id] = timestamp
        except OSError as exc:
            logger.warning("failed to read Claude project log %s: %s", jsonl_path, exc)

    project_counts = Counter(
        {project: len(session_ids) for project, session_ids in sessions_by_project.items()}
    )
    top_projects = sorted(project_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    recent_titles = _recent_unique_titles(titles_by_session, session_last_message_at)

    return PersonaProfile(
        hour_histogram=histogram,
        top_projects=top_projects,
        recent_titles=recent_titles,
        total_sessions=len(message_sessions),
        total_messages=total_messages,
    )


def _empty_profile() -> PersonaProfile:
    return PersonaProfile(
        hour_histogram=[0] * 24,
        top_projects=[],
        recent_titles=[],
        total_sessions=0,
        total_messages=0,
    )


def _parse_metadata_line(data: dict[str, Any]) -> _MetadataLine | None:
    return _MetadataLine(
        type=_as_str(data.get("type")),
        timestamp=_parse_timestamp(data.get("timestamp")),
        session_id=_as_str(data.get("sessionId") or data.get("session_id")),
        cwd=_as_str(data.get("cwd")),
        title=_as_str(data.get("aiTitle")),
    )


def _parse_timestamp(value: Any) -> datetime | None:
    return parse_optional_iso8601_utc(value)


def _project_from_cwd(cwd: str) -> str:
    if not cwd:
        return ""
    return resolve_project_name(cwd)


def _project_from_path(jsonl_path: Path) -> str:
    return project_from_encoded_path(jsonl_path, CLAUDE_PROJECTS_DIR)


def _recent_unique_titles(
    titles_by_session: dict[str, str],
    session_last_message_at: dict[str, datetime],
) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    ordered_sessions = sorted(
        titles_by_session,
        key=lambda session_id: session_last_message_at.get(
            session_id,
            datetime.min.replace(tzinfo=UTC),
        ),
        reverse=True,
    )
    for session_id in ordered_sessions:
        if session_id not in session_last_message_at:
            continue
        title = titles_by_session[session_id]
        normalized = title.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        titles.append(normalized)
        if len(titles) >= 8:
            break
    return titles


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""
