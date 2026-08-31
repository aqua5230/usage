# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loaders.jsonl_utils import iter_jsonl_dicts
from project_resolver import project_from_encoded_path, resolve_project_name
from usage_common.time_utils import parse_optional_iso8601_utc

logger = logging.getLogger(__name__)

CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))
_CACHE_TTL_SECONDS = 300.0
_cache: dict[int, tuple[float, PersonaProfile]] = {}


@dataclass(slots=True)
class OnePassModelStats:
    model: str
    turns: int
    interruptions: int
    denied_tools: int
    pass_rate: float


@dataclass(slots=True)
class OnePassStats:
    total_sessions: int
    total_turns: int
    interruptions: int
    denied_tools: int
    pass_rate: float
    by_model: list[OnePassModelStats]
    unattributed_interruptions: int
    unattributed_denied_tools: int


@dataclass(slots=True)
class PersonaProfile:
    hour_histogram: list[int]
    top_projects: list[tuple[str, int]]
    recent_titles: list[str]
    total_sessions: int
    total_messages: int
    titles_by_session: dict[str, str] = field(default_factory=dict)
    one_pass: OnePassStats | None = None


@dataclass(slots=True)
class _MetadataLine:
    type: str
    timestamp: datetime | None
    session_id: str
    cwd: str
    title: str


@dataclass(slots=True)
class _UserTurn:
    session_id: str
    is_recent: bool
    model: str = ""
    saw_assistant: bool = False
    failed: bool = False


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
    assistant_by_message_id: dict[str, str] = {}
    assistant_by_uuid: dict[str, str] = {}
    model_turns: Counter[str] = Counter()
    model_failed_turns: Counter[str] = Counter()
    model_interruptions: Counter[str] = Counter()
    model_denied_tools: Counter[str] = Counter()
    one_pass_sessions: set[str] = set()
    unattributed_interruptions = 0
    unattributed_denied_tools = 0
    total_messages = 0

    cutoff = datetime.now(UTC) - timedelta(days=max(0, days_back))
    cutoff_ts = cutoff.timestamp()

    if not CLAUDE_PROJECTS_DIR.is_dir():
        return _empty_profile()

    jsonl_paths = _recent_jsonl_paths(cutoff_ts)
    assistant_by_message_id, assistant_by_uuid = _build_assistant_indexes(jsonl_paths)

    for jsonl_path in jsonl_paths:
        current_turn: _UserTurn | None = None
        try:
            fallback_project = _project_from_path(jsonl_path)
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
                is_recent = timestamp is not None and timestamp >= cutoff
                if parsed.type == "assistant":
                    if current_turn is not None and not current_turn.saw_assistant:
                        current_turn.model = _assistant_model(data)
                        current_turn.saw_assistant = True
                elif parsed.type == "user":
                    if is_recent and "interruptedMessageId" in data:
                        model = assistant_by_message_id.get(
                            _as_str(data.get("interruptedMessageId"))
                        )
                        if model is None or not _is_reportable_model(model):
                            unattributed_interruptions += 1
                        elif _is_reportable_model(model):
                            model_interruptions[model] += 1
                        if current_turn is not None:
                            current_turn.failed = True

                    denied_tools = _denied_tool_count(data) if is_recent else 0
                    if denied_tools:
                        model = assistant_by_uuid.get(_as_str(data.get("parentUuid")))
                        if model is None or not _is_reportable_model(model):
                            unattributed_denied_tools += denied_tools
                        elif _is_reportable_model(model):
                            model_denied_tools[model] += denied_tools
                        if current_turn is not None:
                            current_turn.failed = True

                    if _is_user_turn_start(data):
                        _finish_turn(
                            current_turn,
                            model_turns,
                            model_failed_turns,
                            one_pass_sessions,
                        )
                        current_turn = _UserTurn(session_id=session_id, is_recent=is_recent)

                if not is_recent or timestamp is None:
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
        _finish_turn(
            current_turn,
            model_turns,
            model_failed_turns,
            one_pass_sessions,
        )

    project_counts = Counter(
        {project: len(session_ids) for project, session_ids in sessions_by_project.items()}
    )
    top_projects = sorted(project_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    recent_titles = _recent_unique_titles(titles_by_session, session_last_message_at)
    one_pass = _build_one_pass_stats(
        total_sessions=len(one_pass_sessions),
        model_turns=model_turns,
        model_failed_turns=model_failed_turns,
        model_interruptions=model_interruptions,
        model_denied_tools=model_denied_tools,
        unattributed_interruptions=unattributed_interruptions,
        unattributed_denied_tools=unattributed_denied_tools,
    )

    return PersonaProfile(
        hour_histogram=histogram,
        top_projects=top_projects,
        recent_titles=recent_titles,
        total_sessions=len(message_sessions),
        total_messages=total_messages,
        titles_by_session=titles_by_session,
        one_pass=one_pass,
    )


def _empty_profile() -> PersonaProfile:
    return PersonaProfile(
        hour_histogram=[0] * 24,
        top_projects=[],
        recent_titles=[],
        total_sessions=0,
        total_messages=0,
        titles_by_session={},
        one_pass=None,
    )


def _build_one_pass_stats(
    *,
    total_sessions: int,
    model_turns: Counter[str],
    model_failed_turns: Counter[str],
    model_interruptions: Counter[str],
    model_denied_tools: Counter[str],
    unattributed_interruptions: int,
    unattributed_denied_tools: int,
) -> OnePassStats | None:
    total_turns = sum(model_turns.values())
    if len(model_turns) < 2 or total_turns < 30:
        return None

    interruption_count = sum(model_interruptions.values()) + unattributed_interruptions
    denied_tool_count = sum(model_denied_tools.values()) + unattributed_denied_tools
    by_model = [
        OnePassModelStats(
            model=model,
            turns=turns,
            interruptions=model_interruptions[model],
            denied_tools=model_denied_tools[model],
            pass_rate=_pass_rate(turns, model_failed_turns[model]),
        )
        for model, turns in sorted(model_turns.items(), key=lambda item: (-item[1], item[0]))
    ]
    return OnePassStats(
        total_sessions=total_sessions,
        total_turns=total_turns,
        interruptions=interruption_count,
        denied_tools=denied_tool_count,
        pass_rate=_pass_rate(total_turns, sum(model_failed_turns.values())),
        by_model=by_model,
        unattributed_interruptions=unattributed_interruptions,
        unattributed_denied_tools=unattributed_denied_tools,
    )


def _pass_rate(turns: int, failed_turns: int) -> float:
    if turns <= 0:
        return 0.0
    rate = (turns - failed_turns) / turns * 100
    return round(max(0.0, min(100.0, rate)), 1)


def _assistant_model(data: dict[str, Any]) -> str:
    message = data.get("message")
    if not isinstance(message, dict):
        return ""
    return _as_str(message.get("model")).strip()


def _assistant_message_id(data: dict[str, Any]) -> str:
    message = data.get("message")
    if not isinstance(message, dict):
        return ""
    return _as_str(message.get("id"))


def _recent_jsonl_paths(cutoff_ts: float) -> list[Path]:
    paths: list[Path] = []
    for jsonl_path in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        try:
            if jsonl_path.stat().st_mtime >= cutoff_ts:
                paths.append(jsonl_path)
        except OSError as exc:
            logger.warning("failed to stat Claude project log %s: %s", jsonl_path, exc)
    return paths


def _build_assistant_indexes(
    jsonl_paths: list[Path],
) -> tuple[dict[str, str], dict[str, str]]:
    by_message_id: dict[str, str] = {}
    by_uuid: dict[str, str] = {}
    for jsonl_path in jsonl_paths:
        try:
            for data in iter_jsonl_dicts(jsonl_path, errors="replace"):
                if _as_str(data.get("type")) != "assistant":
                    continue
                model = _assistant_model(data)
                message_id = _assistant_message_id(data)
                if message_id:
                    by_message_id.setdefault(message_id, model)
                uuid = _as_str(data.get("uuid"))
                if uuid:
                    by_uuid.setdefault(uuid, model)
        except OSError as exc:
            logger.warning("failed to index Claude project log %s: %s", jsonl_path, exc)
    return by_message_id, by_uuid


def _finish_turn(
    turn: _UserTurn | None,
    model_turns: Counter[str],
    model_failed_turns: Counter[str],
    one_pass_sessions: set[str],
) -> None:
    if turn is None or not turn.is_recent or not _is_reportable_model(turn.model):
        return
    model_turns[turn.model] += 1
    if turn.failed:
        model_failed_turns[turn.model] += 1
    if turn.session_id:
        one_pass_sessions.add(turn.session_id)


def _is_reportable_model(model: str) -> bool:
    return bool(model) and re.fullmatch(r"<.*>", model) is None


def _is_user_turn_start(data: dict[str, Any]) -> bool:
    if _as_str(data.get("type")) != "user":
        return False
    message = data.get("message")
    if not isinstance(message, dict):
        return True
    content = message.get("content")
    if not isinstance(content, list) or not content:
        return True
    first = content[0]
    if not isinstance(first, dict):
        return True
    if first.get("type") == "tool_result":
        return False
    return not (
        first.get("type") == "text"
        and _as_str(first.get("text")).strip() == "[Request interrupted by user]"
    )


def _denied_tool_count(data: dict[str, Any]) -> int:
    message = data.get("message")
    if not isinstance(message, dict):
        return 0
    content = message.get("content")
    if not isinstance(content, list):
        return 0
    count = 0
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_result":
            continue
        result = item.get("content")
        if (
            isinstance(result, str)
            and result.startswith("Permission to use ")
            and " has been denied" in result
        ):
            count += 1
    return count


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
