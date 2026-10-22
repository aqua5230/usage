# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Read shared Muse quota snapshots and schedule bounded background probes."""

from __future__ import annotations

import atexit
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TypedDict, TypeGuard

from loaders import muse_loader
from usage_common.subprocess_utils import hidden_console_kwargs

logger = logging.getLogger(__name__)
CACHE_PATH = Path.home() / ".usage/muse_quota.json"
PROBE_DIR = Path.home() / ".usage/muse-probe"
MUSE_MODEL = "muse-spark-1.3"
STALE_SECONDS = 30 * 60
WINDOW_SECONDS = 5 * 3600
_EXHAUSTED = re.compile(
    r"Subscription quota exhausted\. Your usage window resets at (\d{4}-\d\d-\d\dT[\d:.]+Z)"
)
_probe_lock = threading.Lock()
_probe_running = False
_retry_after = 0.0
_last_attempt_session: float | None = None
_probe_process: subprocess.Popen[str] | None = None
_probe_shutdown = False


class MuseQuotaWindow(TypedDict):
    used_percent: float
    resets_at: float


class MuseQuotaResult(TypedDict):
    checked_at: float
    window: MuseQuotaWindow
    weekly: MuseQuotaWindow


def find_muse() -> str | None:
    """Find Muse even when the app inherits a limited GUI PATH."""
    executable = shutil.which("muse")
    if executable is not None:
        return executable
    for candidate in ("~/.local/bin/muse", "/opt/homebrew/bin/muse", "/usr/local/bin/muse"):
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    return None


def _number(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def validate_muse_cache(payload: object) -> MuseQuotaResult | None:
    if not isinstance(payload, dict) or not _number(payload.get("checked_at")):
        return None
    windows: list[MuseQuotaWindow] = []
    for name in ("window", "weekly"):
        window = payload.get(name)
        if not isinstance(window, dict):
            return None
        used, reset = window.get("used_percent"), window.get("resets_at")
        # An exhausted window reports past 100 (e.g. 104); the row clamps it for display.
        if not _number(used) or not _number(reset) or used < 0:
            return None
        windows.append(MuseQuotaWindow(used_percent=float(used), resets_at=float(reset)))
    return MuseQuotaResult(
        checked_at=float(payload["checked_at"]), window=windows[0], weekly=windows[1]
    )


def parse_muse_allowance(stdout: str, checked_at: float) -> MuseQuotaResult | None:
    for line in stdout.splitlines():
        try:
            record = json.loads(line)
            if not isinstance(record, dict) or record.get("payload_type") != "run.usage":
                continue
            allowance = record["payload"]["allowance"]
            payload: dict[str, object] = {"checked_at": checked_at}
            for name in ("window", "weekly"):
                raw = allowance[name]
                if not _number(raw["resets_at_ms"]):
                    break
                payload[name] = {
                    "used_percent": raw["used_percent"],
                    "resets_at": raw["resets_at_ms"] / 1000,
                }
            result = validate_muse_cache(payload)
            if result is not None:
                return result
        except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
            continue
    return None


def parse_exhausted_window(
    stdout: str, cached: MuseQuotaResult | None, now: float
) -> MuseQuotaResult | None:
    """Read the 429 Muse returns once a window is used up; it carries no allowance.

    The reply names only a reset time. Within 5 hours it is the 5-hour window, so the weekly
    reading and its age stay from ``cached``. Further out it can only be the weekly allowance.
    """
    match = _EXHAUSTED.search(stdout)
    if cached is None or match is None:
        return None
    try:
        reset = datetime.fromisoformat(match[1]).timestamp()
    except ValueError:
        return None
    used_up = MuseQuotaWindow(used_percent=100.0, resets_at=reset)
    if reset - now <= WINDOW_SECONDS:
        return MuseQuotaResult(
            checked_at=cached["checked_at"], window=used_up, weekly=cached["weekly"]
        )
    window = cached["window"]
    # Nothing runs without weekly allowance, so a lapsed window is empty. One resetting past
    # 5 hours is a weekly 429 that v0.34.5 recorded as the 5-hour window.
    if not now < window["resets_at"] <= now + WINDOW_SECONDS:
        window = MuseQuotaWindow(used_percent=0.0, resets_at=now)
    return MuseQuotaResult(checked_at=now, window=window, weekly=used_up)


def read_cache() -> MuseQuotaResult | None:
    """Ignore invalid shared snapshots without deleting or quarantining them."""
    try:
        return validate_muse_cache(json.loads(CACHE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, OverflowError, RecursionError):
        return None


def latest_session_mtime() -> float | None:
    latest = None
    for path in muse_loader.session_paths():
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        latest = modified if latest is None else max(latest, modified)
    return latest


def is_stale(quota: MuseQuotaResult, latest: float | None, now: float) -> bool:
    return (
        latest is not None
        and latest > quota["checked_at"]
        and now - quota["checked_at"] > STALE_SECONDS
    )


def _write_cache(result: MuseQuotaResult) -> None:
    temporary_path = None
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(dir=CACHE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as snapshot:
            json.dump(result, snapshot)
        os.replace(temporary_path, CACHE_PATH)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                os.unlink(temporary_path)


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    except OSError:
        logger.warning("Could not stop Muse quota probe", exc_info=True)


def _cleanup_probe() -> None:
    global _probe_shutdown
    with _probe_lock:
        _probe_shutdown = True
        process = _probe_process
    if process is not None:
        _stop_process(process)


atexit.register(_cleanup_probe)


def _probe_worker(executable: str) -> None:
    global _probe_running, _retry_after, _probe_process
    succeeded = False
    process = None
    try:
        PROBE_DIR.mkdir(parents=True, exist_ok=True)
        with _probe_lock:
            if _probe_shutdown:
                return
            process = subprocess.Popen(
                [
                    executable,
                    "exec",
                    "--model",
                    MUSE_MODEL,
                    "--reasoning-effort",
                    "low",
                    "--trust-workspace",
                    "--disable-web-tools",
                    "--no-session-log",
                    "--json",
                    "Reply with OK only.",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                cwd=PROBE_DIR,
                **hidden_console_kwargs(),
            )
            _probe_process = process
        try:
            stdout, _ = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        if process.returncode == 0:
            result = parse_muse_allowance(stdout, time.time())
        else:
            result = parse_exhausted_window(stdout, read_cache(), time.time())
        if result is not None:
            _write_cache(result)
            succeeded = True
        else:
            logger.warning(
                "Muse quota probe returned no valid allowance (exit %s)", process.returncode
            )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        logger.warning("Muse quota probe failed", exc_info=True)
    finally:
        if process is not None:
            _stop_process(process)
        with _probe_lock:
            _probe_process = None
            if not succeeded:
                _retry_after = time.monotonic() + STALE_SECONDS
            _probe_running = False


def load_quota_snapshot(*, allow_probe: bool = True) -> tuple[MuseQuotaResult | None, float | None]:
    """Read sessions once and return the snapshot plus its projection context.

    ``allow_probe=False`` only reads: a probe spends Muse quota, so a hidden card never starts one.
    """
    global _probe_running, _retry_after, _last_attempt_session
    cached = read_cache()
    executable = find_muse()
    if executable is None:
        return None, None
    latest = latest_session_mtime()
    if (
        not allow_probe
        or latest is None
        or (cached is not None and not is_stale(cached, latest, time.time()))
    ):
        return cached, latest
    with _probe_lock:
        # A worker may have finished since the first cache read.
        cached = read_cache()
        if (
            latest is None
            or (cached is not None and not is_stale(cached, latest, time.time()))
            or _probe_running
            or _probe_shutdown
            or time.monotonic() < _retry_after
            or (_last_attempt_session is not None and latest <= _last_attempt_session)
        ):
            return cached, latest
        _probe_running = True
        _last_attempt_session = latest
        try:
            threading.Thread(target=_probe_worker, args=(executable,), daemon=True).start()
        except RuntimeError:
            _probe_running = False
            _retry_after = time.monotonic() + STALE_SECONDS
            logger.warning("Could not start Muse quota probe thread", exc_info=True)
    return cached, latest


def load_quota() -> MuseQuotaResult | None:
    """Return the current snapshot immediately; at most one worker may refresh it."""
    return load_quota_snapshot()[0]
