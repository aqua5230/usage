# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Probe Antigravity CLI's ``/quota`` view without creating a conversation."""

from __future__ import annotations

import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

CACHE_PATH = Path(os.path.expanduser("~/.usage/agy_quota_cache.json"))
# A dedicated empty directory so the CLI's workspace-trust prompt has nothing to
# act on; launching from an arbitrary cwd (e.g. "/" under launchd) would stall the
# probe on that prompt forever.
PROBE_WORKSPACE = Path(os.path.expanduser("~/.usage/agy_probe_workspace"))

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_GROUP_RE = re.compile(
    r"(?ms)^\s*(?P<name>[A-Z][A-Z0-9 &-]*)\s*$"
    r"\s*^\s*Models within this group:\s*(?P<models>[^\n]+)\s*$"
    r"(?P<body>.*?)(?=^\s*[A-Z][A-Z0-9 &-]*\s*$\s*^\s*Models within this group:|\Z)"
)
_WINDOW_RE = re.compile(
    r"(?ms)^\s*(?P<label>Weekly Limit|Five Hour Limit)\s*$"
    r"(?P<body>.*?)(?=^\s*(?:Weekly Limit|Five Hour Limit)\s*$|\Z)"
)
_PROGRESS_RE = re.compile(r"\]\s*(?P<percent>\d+(?:\.\d+)?)%")
_REMAINING_RE = re.compile(
    r"(?P<percent>\d+(?:\.\d+)?)%\s+remaining\s*·\s*Refreshes in\s*"
    r"(?P<countdown>(?:\d+h\s*)?(?:\d+m)?)"
)
_COUNTDOWN_RE = re.compile(r"^(?:(?P<hours>\d+)h\s*)?(?:(?P<minutes>\d+)m)?$")


@dataclass(frozen=True, slots=True)
class AgyQuotaWindow:
    """Remaining quota and its reported reset countdown."""

    remaining_percent: float
    resets_in: str | None
    resets_in_minutes: int | None


@dataclass(frozen=True, slots=True)
class AgyQuotaGroup:
    """Quota windows shared by a named group of Antigravity models."""

    name: str
    models: list[str]
    weekly: AgyQuotaWindow
    five_hour: AgyQuotaWindow


@dataclass(frozen=True, slots=True)
class AgyQuotaResult:
    """All model groups returned by one ``/quota`` probe."""

    groups: list[AgyQuotaGroup]
    fetched_at: str


def probe_quota(timeout_seconds: float = 35) -> AgyQuotaResult | None:
    """Run ``agy /quota`` in a PTY, returning no result on any failure.

    Only this call's own spawned process is tracked and cleaned up; an
    unrelated ``agy`` process elsewhere (the user's own session, a dispatched
    task, or an orphan from a previous crash) is never checked for, since a
    global "is agy running" gate can get wedged forever by an orphan and
    then block every future probe.
    """
    agy_path = find_agy()
    if timeout_seconds <= 0 or agy_path is None:
        return None

    master_fd: int | None = None
    slave_fd: int | None = None
    process: subprocess.Popen[bytes] | None = None
    try:
        with suppress(OSError):
            PROBE_WORKSPACE.mkdir(parents=True, exist_ok=True)
        master_fd, slave_fd = pty.openpty()
        _set_window_size(slave_fd)
        process = subprocess.Popen(
            [agy_path],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=_probe_env(agy_path),
            start_new_session=True,
            close_fds=True,
            cwd=str(PROBE_WORKSPACE),
        )
        os.close(slave_fd)
        slave_fd = None

        deadline = time.monotonic() + timeout_seconds
        transcript = ""
        trust_confirmed = False
        prompt_seen_at: float | None = None
        quota_sent_at: float | None = None
        sent_offset = 0
        resent = False
        candidate: AgyQuotaResult | None = None
        last_chunk_at = time.monotonic()
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return None
            now = time.monotonic()
            # A parse can succeed on a partially rendered screen (first group
            # only), so hold the candidate until the stream stays quiet.
            if candidate is not None and now - last_chunk_at >= 0.6:
                return _parse_quota_output(transcript) or candidate
            # A fresh cwd triggers a "Do you trust the contents of this
            # project?" prompt that blocks the input box; its cursor defaults to
            # "Yes, I trust this folder", so a bare Enter accepts it.
            if not trust_confirmed and "Do you trust the contents" in transcript:
                os.write(master_fd, b"\r")
                trust_confirmed = True
            # The banner paints before the input box accepts keystrokes, so
            # wait for the shortcut hint plus a settle delay before typing.
            if prompt_seen_at is None and "? for shortcuts" in transcript:
                prompt_seen_at = now
            if quota_sent_at is None and prompt_seen_at is not None and now - prompt_seen_at >= 0.5:
                sent_offset = len(transcript)
                os.write(master_fd, b"/quota\r")
                quota_sent_at = now
            elif (
                quota_sent_at is not None
                and not resent
                and now - quota_sent_at > 4.0
                and "quota" not in transcript[sent_offset:]
            ):
                # No echo: the keystrokes were swallowed. Clear the line and retype once.
                sent_offset = len(transcript)
                os.write(master_fd, b"\x15/quota\r")
                resent = True
            remaining = deadline - time.monotonic()
            ready, _, _ = select.select([master_fd], [], [], min(0.2, max(remaining, 0.0)))
            if not ready:
                continue
            try:
                chunk = os.read(master_fd, 65536)
            except OSError:
                return None
            if not chunk:
                return None
            transcript += chunk.decode("utf-8", errors="replace")
            last_chunk_at = time.monotonic()
            if quota_sent_at is not None and candidate is None:
                candidate = _parse_quota_output(transcript)
        return candidate
    except Exception:
        return None
    finally:
        if master_fd is not None:
            with suppress(OSError):
                os.write(master_fd, b"/exit\r")
        if slave_fd is not None:
            with suppress(OSError):
                os.close(slave_fd)
        if master_fd is not None:
            with suppress(OSError):
                os.close(master_fd)
        if process is not None:
            _terminate_process_group(process)


def find_agy() -> str | None:
    """Find the Antigravity CLI in PATH or common user installation paths."""
    path = shutil.which("agy")
    if path is not None:
        return path
    for candidate in ("~/.local/bin/agy", "/opt/homebrew/bin/agy", "/usr/local/bin/agy"):
        expanded = os.path.expanduser(candidate)
        if os.access(expanded, os.X_OK):
            return expanded
    return None


def _probe_env(agy_path: str) -> dict[str, str]:
    """Build an environment with the tools needed by the Antigravity CLI."""
    env = os.environ.copy()
    path_entries = [
        os.path.dirname(agy_path),
        os.path.expanduser("~/.local/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        *env.get("PATH", "").split(os.pathsep),
    ]
    seen: set[str] = set()
    unique_entries: list[str] = []
    for entry in path_entries:
        if entry and entry not in seen:
            seen.add(entry)
            unique_entries.append(entry)
    env["PATH"] = os.pathsep.join(unique_entries)
    env.setdefault("TERM", "xterm-256color")
    return env


def load_quota(max_age_minutes: float = 15) -> AgyQuotaResult | None:
    """Return fresh cached quota, otherwise probe and preserve stale fallback."""
    cached = _read_cache()
    if cached is not None and _is_fresh(cached, max_age_minutes):
        return cached

    probed = probe_quota()
    if probed is None:
        return cached
    _write_cache(probed)
    return probed


def _set_window_size(fd: int) -> None:
    """Give the TUI enough width that its quota lines do not wrap."""
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 48, 140, 0, 0))


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop the PTY child and every process it started."""
    with suppress(OSError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=1)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _parse_quota_output(transcript: str) -> AgyQuotaResult | None:
    """Parse the complete text rendered by Antigravity's ``/quota`` command."""
    text = _normalise_terminal_text(transcript)
    groups: list[AgyQuotaGroup] = []
    for match in _GROUP_RE.finditer(text):
        models = [model.strip() for model in match.group("models").split(",") if model.strip()]
        weekly = _parse_window(match.group("body"), "Weekly Limit")
        five_hour = _parse_window(match.group("body"), "Five Hour Limit")
        if not models or weekly is None or five_hour is None:
            return None
        groups.append(
            AgyQuotaGroup(
                name=match.group("name").strip(),
                models=models,
                weekly=weekly,
                five_hour=five_hour,
            )
        )
    if not groups:
        return None
    return AgyQuotaResult(groups=groups, fetched_at=datetime.now(UTC).isoformat())


def _normalise_terminal_text(transcript: str) -> str:
    text = _ANSI_ESCAPE_RE.sub("", transcript).replace("\r\n", "\n").replace("\r", "\n")
    return "".join(character for character in text if character == "\n" or ord(character) >= 32)


def _parse_window(group_body: str, label: str) -> AgyQuotaWindow | None:
    match = next(
        (
            candidate
            for candidate in _WINDOW_RE.finditer(group_body)
            if candidate.group("label") == label
        ),
        None,
    )
    if match is None:
        return None
    body = match.group("body")
    if "Quota available" in body:
        return AgyQuotaWindow(remaining_percent=100.0, resets_in=None, resets_in_minutes=None)

    summary = _REMAINING_RE.search(body)
    if summary is None:
        return None
    countdown = summary.group("countdown").strip()
    minutes = _countdown_minutes(countdown)
    if minutes is None:
        return None
    progress = _PROGRESS_RE.search(body)
    try:
        percent_text = (
            progress.group("percent") if progress is not None else summary.group("percent")
        )
        remaining_percent = float(percent_text)
    except ValueError:
        return None
    if not 0 <= remaining_percent <= 100:
        return None
    return AgyQuotaWindow(
        remaining_percent=remaining_percent,
        resets_in=countdown,
        resets_in_minutes=minutes,
    )


def _countdown_minutes(countdown: str) -> int | None:
    match = _COUNTDOWN_RE.fullmatch(countdown)
    if match is None or (match.group("hours") is None and match.group("minutes") is None):
        return None
    return int(match.group("hours") or 0) * 60 + int(match.group("minutes") or 0)


def _is_fresh(result: AgyQuotaResult, max_age_minutes: float) -> bool:
    if max_age_minutes < 0:
        return False
    fetched_at = _parse_timestamp(result.fetched_at)
    if fetched_at is None:
        return False
    return datetime.now(UTC) - fetched_at <= timedelta(minutes=max_age_minutes)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp.astimezone(UTC)


def _read_cache() -> AgyQuotaResult | None:
    try:
        with CACHE_PATH.open(encoding="utf-8") as cache_file:
            payload: object = json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None
    return _result_from_payload(payload)


def _write_cache(result: AgyQuotaResult) -> None:
    temporary_path: str | None = None
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(dir=CACHE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as cache_file:
            json.dump(_result_to_payload(result), cache_file, ensure_ascii=False)
        os.replace(temporary_path, CACHE_PATH)
        temporary_path = None
    except OSError:
        return
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                os.unlink(temporary_path)


def _result_to_payload(result: AgyQuotaResult) -> dict[str, object]:
    return {
        "fetched_at": result.fetched_at,
        "groups": [
            {
                "name": group.name,
                "models": group.models,
                "weekly": _window_to_payload(group.weekly),
                "five_hour": _window_to_payload(group.five_hour),
            }
            for group in result.groups
        ],
    }


def _window_to_payload(window: AgyQuotaWindow) -> dict[str, float | int | str | None]:
    return {
        "remaining_percent": window.remaining_percent,
        "resets_in": window.resets_in,
        "resets_in_minutes": window.resets_in_minutes,
    }


def _result_from_payload(payload: object) -> AgyQuotaResult | None:
    if not isinstance(payload, dict):
        return None
    fetched_at = payload.get("fetched_at")
    raw_groups = payload.get("groups")
    if not isinstance(fetched_at, str) or _parse_timestamp(fetched_at) is None:
        return None
    if not isinstance(raw_groups, list) or not raw_groups:
        return None
    groups: list[AgyQuotaGroup] = []
    for raw_group in raw_groups:
        group = _group_from_payload(raw_group)
        if group is None:
            return None
        groups.append(group)
    return AgyQuotaResult(groups=groups, fetched_at=fetched_at)


def _group_from_payload(payload: object) -> AgyQuotaGroup | None:
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    models = payload.get("models")
    weekly = _window_from_payload(payload.get("weekly"))
    five_hour = _window_from_payload(payload.get("five_hour"))
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(models, list)
        or not all(isinstance(model, str) and model for model in models)
        or weekly is None
        or five_hour is None
    ):
        return None
    return AgyQuotaGroup(name=name, models=models, weekly=weekly, five_hour=five_hour)


def _window_from_payload(payload: object) -> AgyQuotaWindow | None:
    if not isinstance(payload, dict):
        return None
    remaining_percent = payload.get("remaining_percent")
    resets_in = payload.get("resets_in")
    resets_in_minutes = payload.get("resets_in_minutes")
    if (
        not isinstance(remaining_percent, (int, float))
        or isinstance(remaining_percent, bool)
        or not 0 <= float(remaining_percent) <= 100
        or (resets_in is not None and not isinstance(resets_in, str))
        or (resets_in_minutes is not None and not isinstance(resets_in_minutes, int))
    ):
        return None
    if (resets_in is None) != (resets_in_minutes is None):
        return None
    return AgyQuotaWindow(
        remaining_percent=float(remaining_percent),
        resets_in=resets_in,
        resets_in_minutes=resets_in_minutes,
    )
