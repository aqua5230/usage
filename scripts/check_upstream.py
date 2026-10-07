#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Check local upstream formats without writing files; run before each release."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
import urllib.error
from collections.abc import Callable, Iterable
from contextlib import closing
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

# Imports must not create Python bytecode in the user's directories either.
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer import session_hooks, setup_hook  # noqa: E402
from loaders import (  # noqa: E402
    agy_loader,
    agy_quota_probe,
    codex_loader,
    grok_loader,
    grok_quota_probe,
)
from usage_common import service_status  # noqa: E402
from usage_hooks import usage_statusline  # noqa: E402

CLAUDE_STATUS_PATH = setup_hook.STATUS_FILE
CLAUDE_PROJECTS_DIR = CLAUDE_STATUS_PATH.parent / "projects"
MAX_AGE = 7 * 24 * 3600
Result = tuple[str, str]

# Observed on 2026-10-06, not a union of hypothetical upstream fields.
KNOWN_STATUS = frozenset(
    [
        "session_id",
        "transcript_path",
        "cwd",
        "scratchpad_dir",
        "prompt_id",
        "effort",
        "session_name",
        "model",
        "workspace",
        "version",
        "output_style",
        "cost",
        "context_window",
        "exceeds_200k_tokens",
        "prompt_cache",
        "fast_mode",
        "thinking",
        "rate_limits",
        "_received_at",
        "_received_at_ts",
    ]
)
KNOWN_CLAUDE_LIMITS = frozenset({"five_hour", "seven_day"})
KNOWN_PROMPT_CACHE = frozenset(
    [
        "warm",
        "caching_observed",
        "ttl",
        "expires_at",
        "requests",
        "misses",
        "expected_rebuilds",
        "hit_ratio",
        "cache_write_tokens",
        "miss_recache_tokens",
        "last_miss_at",
        "last_miss_cause",
        "miss_causes",
        "recache_tokens_if_cold",
    ]
)
KNOWN_CLAUDE_USAGE = frozenset(
    [
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cache_creation",
        "fallback_credit",
        "inference_geo",
        "iterations",
        "output_tokens_details",
        "server_tool_use",
        "service_tier",
        "speed",
    ]
)
KNOWN_CODEX_LIMITS = frozenset(
    [
        "limit_id",
        "limit_name",
        "primary",
        "secondary",
        "credits",
        "individual_limit",
        "spend_control_reached",
        "plan_type",
        "rate_limit_reached_type",
    ]
)
KNOWN_CODEX_WINDOW = frozenset({"used_percent", "window_minutes", "resets_at"})
KNOWN_CODEX_CREDITS = frozenset({"has_credits", "unlimited", "balance"})
KNOWN_CODEX_USAGE = frozenset(
    [
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ]
)
# Required fields trace to usage_statusline._render_core, history_loader._parse_line,
# codex_events._token_usage_from_payload and codex_loader._extract_rate_limits.
CLAUDE_TOKENS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
CODEX_TOKENS = ("input_tokens", "cached_input_tokens", "output_tokens")
# Columns include SELECT, WHERE and ORDER BY dependencies, including legacy queries.
CODEX_SCHEMAS = {
    "STATE_DB": {"threads": {"id", "model", "cwd"}},
    "LOGS_DB": {"logs": {"id", "ts", "ts_nanos", "feedback_log_body", "target"}},
    "THREAD_HISTORY_DB": {"thread_turns": {"started_at", "completed_at"}},
}
AGY_SCHEMA = {
    "steps": {"idx", "metadata", "step_type", "step_payload"},
    "gen_metadata": {"idx", "data"},
    "trajectory_metadata_blob": {"data"},
}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _get(data: Any, field: str) -> Any:
    for key in field.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _required(data: Any, fields: dict[str, Callable[[Any], bool]]) -> list[str]:
    return [
        f"missing or invalid {key}" for key, valid in fields.items() if not valid(_get(data, key))
    ]


def _new(data: Any, known: frozenset[str], prefix: str) -> list[str]:
    return (
        [f"{prefix}.{key}" for key in sorted(data.keys() - known)] if isinstance(data, dict) else []
    )


def _result(path: Path, broken: list[str], new: list[str] | None = None) -> Result:
    if broken:
        return "BROKEN", f"{path}: {'; '.join(broken)}"
    if new:
        return "NEW", f"{path}: new {', '.join(sorted(set(new)))}"
    return "OK", str(path)


def _fresh(path: Path, timestamp: float | None = None) -> Result | None:
    if not path.is_file():
        return "NO_DATA", f"{path}: no local file"
    updated = path.stat().st_mtime if timestamp is None else timestamp
    if time.time() - updated > MAX_AGE:
        return "NO_DATA", f"{path}: data older than 7 days"
    return None


def _latest(paths: Iterable[Path]) -> Path | None:
    return max(paths, key=lambda p: p.stat().st_mtime, default=None)


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _rows(path: Path, limit: int = 500) -> list[dict[str, Any]]:
    # Bound memory and disk reads for long sessions. Ignore a partial trailing line
    # while the CLI is appending, as the loaders do.
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        start = max(0, size - 8 * 1024 * 1024)
        stream.seek(start)
        if start:
            stream.readline()
        lines = stream.read().splitlines()[-limit:]
    rows = []
    for index, line in enumerate(lines):
        try:
            data = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            if index == len(lines) - 1:
                continue
            raise ValueError(f"{path}: invalid JSONL in tail: {exc}") from exc
        if isinstance(data, dict):
            rows.append(data)
    return rows


def check_claude_statusline() -> Result:
    path = CLAUDE_STATUS_PATH
    if result := _fresh(path):
        return result
    data = _json(path)
    received = _get(data, "_received_at_ts")
    if _number(received) and (result := _fresh(path, received)):
        return result
    fields: dict[str, Callable[[Any], bool]] = {
        "_received_at_ts": _number,
        "workspace.project_dir": lambda v: isinstance(v, str),
        "model.display_name": lambda v: isinstance(v, str),
        "cost.total_duration_ms": _number,
        "context_window.used_percentage": _number,
        "context_window.context_window_size": _number,
        "prompt_cache.caching_observed": lambda v: isinstance(v, bool),
        "prompt_cache.hit_ratio": _number,
    }
    for slot in ("five_hour", "seven_day"):
        for key in ("used_percentage", "resets_at"):
            fields[f"rate_limits.{slot}.{key}"] = _number
    broken = _required(data, fields)
    new = _new(data, KNOWN_STATUS, "stdin")
    new += _new(_get(data, "rate_limits"), KNOWN_CLAUDE_LIMITS, "rate_limits")
    cache = _get(data, "prompt_cache")
    new += _new(cache, KNOWN_PROMPT_CACHE, "prompt_cache")
    reasons = {
        key.removeprefix("miss_")
        for key in usage_statusline.STATUSLINE_TRANSLATIONS["en"]
        if key.startswith("miss_")
    } | {"unknown"}
    misses = _get(cache, "miss_causes")
    if misses is not None:
        if isinstance(misses, dict):
            new += [f"miss_causes.{key}" for key in misses.keys() - reasons]
        else:
            broken.append("invalid prompt_cache.miss_causes (expected object)")
    last = _get(cache, "last_miss_cause")
    if last is not None:
        causes = _get(last, "causes")
        if not isinstance(causes, list) or not all(isinstance(c, str) for c in causes):
            broken.append("invalid prompt_cache.last_miss_cause.causes (expected string list)")
        else:
            new += [f"last_miss_cause.causes.{c}" for c in causes if c not in reasons]
    return _result(path, broken, new)


def check_claude_transcript() -> Result:
    path = _latest(CLAUDE_PROJECTS_DIR.glob("*/*.jsonl"))
    if path is None:
        return "NO_DATA", f"{CLAUDE_PROJECTS_DIR}: no transcripts"
    if result := _fresh(path):
        return result
    rows = [r for r in _rows(path) if r.get("type") == "assistant"]
    fields: dict[str, Callable[[Any], bool]] = {
        f"message.usage.{key}": _number for key in CLAUDE_TOKENS
    }
    fields.update(
        {
            "timestamp": lambda v: _timestamp(v) is not None,
            "message.model": lambda v: isinstance(v, str) and bool(v),
        }
    )
    broken = [
        f"missing or invalid {key} in all assistant rows"
        for key, valid in fields.items()
        if not any(valid(_get(row, key)) for row in rows)
    ]
    new = [
        key
        for row in rows
        for key in _new(_get(row, "message.usage"), KNOWN_CLAUDE_USAGE, "message.usage")
    ]
    return _result(path, broken, new)


def check_codex_sessions() -> Result:
    paths = sorted(
        codex_loader.SESSIONS_DIR.glob("**/*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not paths:
        return "NO_DATA", f"{codex_loader.SESSIONS_DIR}: no sessions"
    if result := _fresh(paths[0]):
        return result
    # A session that has only just started has no token_count rows yet. Check the
    # newest recent session that has some; if none has any, report the newest.
    path, rows = paths[0], []
    for candidate in paths:
        if _fresh(candidate):
            break
        found = [
            r
            for r in _rows(candidate, 10000)
            if r.get("type") == "event_msg" and _get(r, "payload.type") == "token_count"
        ]
        if found:
            path, rows = candidate, found
            break
    fields: dict[str, Callable[[Any], bool]] = {
        "timestamp": lambda v: _timestamp(v) is not None,
        **{f"payload.info.total_token_usage.{key}": _number for key in CODEX_TOKENS},
    }
    broken = [
        f"missing or invalid {key} in all token_count rows"
        for key, valid in fields.items()
        if not any(valid(_get(row, key)) for row in rows)
    ]
    limits = [
        _get(r, "payload.rate_limits")
        for r in rows
        if isinstance(_get(r, "payload.rate_limits"), dict) and _get(r, "payload.rate_limits")
    ]
    if not limits:
        broken.append("missing rate_limits in token_count rows")
    new = []
    for rate in limits:
        new += _new(rate, KNOWN_CODEX_LIMITS, "rate_limits")
        slots = [slot for slot in ("primary", "secondary") if rate.get(slot) is not None]
        if not slots:
            broken.append("missing rate_limits.primary/secondary")
        for slot in slots:
            broken += _required(rate, {f"{slot}.{key}": _number for key in KNOWN_CODEX_WINDOW})
            new += _new(rate.get(slot), KNOWN_CODEX_WINDOW, f"rate_limits.{slot}")
        credits = rate.get("credits")
        if credits is not None:
            broken += _required(
                rate,
                {
                    "credits.has_credits": lambda v: isinstance(v, bool),
                    "credits.unlimited": lambda v: isinstance(v, bool),
                    "credits.balance": lambda v: v is None or isinstance(v, str),
                },
            )
            new += _new(credits, KNOWN_CODEX_CREDITS, "rate_limits.credits")
    for row in rows:
        for kind in ("total_token_usage", "last_token_usage"):
            usage = _get(row, f"payload.info.{kind}")
            new += _new(usage, KNOWN_CODEX_USAGE, kind)
    return _result(path, broken, new)


def _schema(path: Path, schema: dict[str, set[str]]) -> list[str]:
    try:
        with closing(sqlite3.connect(codex_loader._readonly_sqlite_uri(path), uri=True)) as conn:
            missing = []
            for table, columns in schema.items():
                actual = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
                missing += [f"missing {table}.{column}" for column in sorted(columns - actual)]
            return missing
    except (OSError, ValueError, sqlite3.Error) as exc:
        return [f"cannot read SQLite schema: {exc}"]


def check_codex_sqlite() -> Result:
    broken, new, fresh, stale = [], [], [], []
    for constant, schema in CODEX_SCHEMAS.items():
        path = getattr(codex_loader, constant)
        prefix, version = path.stem.rsplit("_", 1)
        new += [
            p.name
            for p in path.parent.glob(f"{prefix}_*.sqlite")
            if p.stem.rsplit("_", 1)[1].isdigit() and int(p.stem.rsplit("_", 1)[1]) > int(version)
        ]
        if not path.is_file():
            broken.append(f"{path}: missing SQLite file")
        elif _fresh(
            path,
            max(
                candidate.stat().st_mtime
                for candidate in (path, Path(str(path) + "-wal"))
                if candidate.is_file()
            ),
        ):
            stale.append(str(path))
        else:
            fresh.append(str(path))
            broken += [f"{path}: {detail}" for detail in _schema(path, schema)]
    if broken:
        return "BROKEN", "; ".join(broken)
    if new:
        return "NEW", f"new SQLite files: {', '.join(sorted(new))}"
    if not fresh:
        return "NO_DATA", f"data older than 7 days: {', '.join(stale)}"
    return "OK", ", ".join(fresh) + (f"; stale: {', '.join(stale)}" if stale else "")


def check_agy_conversations() -> Result:
    path = _latest(agy_loader.AGY_SESSIONS_DIR.glob("*.db"))
    if path is None:
        return "NO_DATA", f"{agy_loader.AGY_SESSIONS_DIR}: no conversations"
    if result := _fresh(path):
        return result
    return _result(path, _schema(path, AGY_SCHEMA))


def check_agy_quota_cache() -> Result:
    path = agy_quota_probe.CACHE_PATH
    if not path.is_file():
        return "NO_DATA", f"{path}: no quota cache"
    data = _json(path)
    fetched = _timestamp(_get(data, "fetched_at"))
    if fetched is None:
        return _result(path, ["missing or invalid fetched_at"])
    if result := _fresh(path, fetched):
        return result
    groups = _get(data, "groups")
    if not isinstance(groups, list) or not groups:
        return _result(path, ["missing or empty groups"])
    broken = []
    for index, group in enumerate(groups):
        for slot in ("weekly", "five_hour"):
            if agy_quota_probe._window_from_payload(_get(group, slot)) is None:
                broken.append(f"groups[{index}]: missing or invalid {slot}")
    return _result(path, broken)


def check_grok() -> Result:
    if not grok_loader.GROK_HOME.is_dir():
        return "NO_DATA", f"{grok_loader.GROK_HOME}: no Grok directory"
    path = grok_loader.GROK_LOG_PATH
    if result := _fresh(path):
        return result
    rows = _rows(path, 50000)
    broken = []
    stale = []
    for event, parser in (
        (
            grok_loader._MSG_INFERENCE,
            lambda r: grok_loader._event_from_line(json.dumps(r).encode(), 0),
        ),
        (
            grok_quota_probe._BILLING_MESSAGE,
            lambda r: grok_quota_probe._result_from_line(json.dumps(r).encode()),
        ),
    ):
        matches = [r for r in rows if r.get("msg") == event]
        if not matches:
            broken.append(f"missing event {event}")
            continue
        latest = matches[-1]
        fields: dict[str, Callable[[Any], bool]] = {
            "ts": lambda v: _timestamp(v) is not None,
        }
        if event == grok_loader._MSG_INFERENCE:
            fields.update(
                {
                    "sid": lambda v: isinstance(v, str) and bool(v),
                    "ctx.loop_index": lambda v: isinstance(v, int) and not isinstance(v, bool),
                    **{
                        f"ctx.{key}": _number
                        for key in ("prompt_tokens", "cached_prompt_tokens", "completion_tokens")
                    },
                }
            )
        else:
            fields["ctx.config.currentPeriod.end"] = lambda v: _timestamp(v) is not None
        errors = _required(latest, fields)
        if errors:
            broken += [f"{event}: {error}" for error in errors]
        elif parser(latest) is None:
            broken.append(f"{event}: invalid ctx.config.creditUsagePercent")
        elif (ts := _timestamp(latest.get("ts"))) is not None and time.time() - ts > MAX_AGE:
            stale.append(event)
    if broken:
        return _result(path, broken)
    if stale:
        return "NO_DATA", f"{path}: events older than 7 days: {', '.join(stale)}"
    return _result(path, [])


def hook_pairs() -> list[tuple[Path, Path]]:
    return [
        (ROOT / "usage_hooks" / source, target)
        for source, target in (
            ("usage_statusline.py", setup_hook.HOOK_TARGET),
            ("usage_statusline_forwarder.py", setup_hook.FORWARDER_TARGET),
            ("usage_statusline_agy.py", setup_hook.AGY_HOOK_TARGET),
            ("usage_statusline_grok.py", setup_hook.GROK_HOOK_TARGET),
            ("usage_session_resume.py", session_hooks.RESUME_HOOK_TARGET),
            ("usage_terse_mode.py", session_hooks.TERSE_HOOK_TARGET),
            ("usage_terse_mode.py", session_hooks.CODEX_TERSE_HOOK_TARGET),
            ("usage_terse_reminder.py", session_hooks.TERSE_REMINDER_HOOK_TARGET),
        )
    ]


def check_hook_copies(source: Path, target: Path) -> Result:
    # Installed hooks are persistent code, not samples; their mtime is irrelevant.
    if not target.is_file():
        return "NO_DATA", f"{target}: hook not installed"
    original, installed = source.read_bytes(), target.read_bytes()
    pattern = rb'(?m)^__version__\s*=\s*[\'"]([^\'"\r\n]+)[\'"]'
    old, current = re.search(pattern, installed), re.search(pattern, original)
    # These two installers compare bytes rather than versions (setup_hook's
    # _agy_hook_script_is_stale / _grok_hook_script_is_stale); neither is versioned.
    if source.name in {"usage_statusline_agy.py", "usage_statusline_grok.py"} and current is None:
        return _result(
            target,
            []
            if original == installed
            else ["installed copy is outdated; rebuild and reinstall the app"],
        )
    if old is None or current is None:
        return _result(target, [f"missing __version__ in {source if current is None else target}"])
    if old[1] != current[1]:
        return _result(target, ["installed copy is outdated; rebuild and reinstall the app"])
    if original != installed:
        return _result(
            target,
            [
                "source changed without bumping __version__; installed copy will "
                "never update; bump both source __version__ and installer version constant"
            ],
        )
    return _result(target, [])


def check_service_status(offline: bool = False) -> Result:
    if offline:
        return "NO_DATA", "network check skipped (--offline)"
    broken = []
    for config in (service_status.CLAUDE_STATUS, service_status.CODEX_STATUS):
        # _fetch_status only downloads; get_service_status would write a cache.
        payload = service_status._fetch_status(config)
        if payload is None:
            broken.append(f"{config.status_url}: unable to fetch components.json")
            continue
        components = payload.get("components")
        names = (
            {
                r["name"]
                for r in components
                if isinstance(r, dict) and isinstance(r.get("name"), str)
            }
            if isinstance(components, list)
            else set()
        )
        broken += [
            f"{config.status_url}: missing component {name}"
            for name in config.component_names
            if name not in names
        ]
    return ("BROKEN", "; ".join(broken)) if broken else ("OK", "all watched components present")


def _run(check: Callable[[], Result]) -> Result:
    try:
        return check()
    except (OSError, ValueError, sqlite3.Error, urllib.error.URLError) as exc:
        return "BROKEN", str(exc).replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="skip network checks")
    args = parser.parse_args()
    checks: list[tuple[str, Callable[[], Result]]] = [
        ("claude_statusline", check_claude_statusline),
        ("claude_transcript", check_claude_transcript),
        ("codex_sessions", check_codex_sessions),
        ("codex_sqlite", check_codex_sqlite),
        ("agy_conversations", check_agy_conversations),
        ("agy_quota_cache", check_agy_quota_cache),
        ("grok", check_grok),
    ]
    checks += [
        (
            f"hook_copies[{target.parent.name}/{target.name}]",
            partial(check_hook_copies, source, target),
        )
        for source, target in hook_pairs()
    ]
    checks.append(("service_status", lambda: check_service_status(args.offline)))
    counts = dict.fromkeys(("OK", "NEW", "BROKEN", "NO_DATA"), 0)
    for name, check in checks:
        status, detail = _run(check)
        counts[status] += 1
        print(f"{status} {name} — {detail}")
    print("TOTAL " + " ".join(f"{status}={count}" for status, count in counts.items()))
    return 1 if counts["BROKEN"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
