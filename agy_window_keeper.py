# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Auto-open the next Antigravity 5-hour window."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path

from menubar_agy import AgyRefreshResult
from menubar_prefs import _agy_window_keeper_enabled

logger = logging.getLogger(__name__)

AGY_WINDOW_KEEPER_STATE_PATH = Path(
    os.path.expanduser("~/.usage/agy_window_keeper.json")
)
PING_COOLDOWN_SECONDS = 5 * 3600
PING_TIMEOUT_SECONDS = 180
AGY_MODEL = "Gemini 3.5 Flash (Low)"
_AGY_BIN_FALLBACK = "~/.local/bin/agy"

_lock = threading.Lock()
_ping_in_flight = False


def should_ping(
    now: float,
    enabled: bool,
    last_ping_at: float | None,
    remaining_percent: float | None,
    stale: object | None,
    fallback_projection: bool,
    mock: bool,
) -> bool:
    """Return whether fresh quota data shows no active five-hour window.

    At 100% remaining, the API reset time is a sliding placeholder, so it
    cannot indicate an active window.
    """
    if not enabled or mock or fallback_projection or stale is not None:
        return False
    if remaining_percent is None or remaining_percent < 100.0:
        return False
    return last_ping_at is None or now - last_ping_at >= PING_COOLDOWN_SECONDS


def _load_last_ping(path: Path | None = None) -> float | None:
    state_path = AGY_WINDOW_KEEPER_STATE_PATH if path is None else path
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("last_ping_at")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _save_last_ping(ts: float, path: Path | None = None) -> None:
    state_path = AGY_WINDOW_KEEPER_STATE_PATH if path is None else path
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"last_ping_at": ts}) + "\n"
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=state_path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_path, state_path)
        tmp_path = None
    except OSError:
        _debug_log("agy-window-keeper state write failed", exc_info=True)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with suppress(OSError):
                os.unlink(tmp_path)


def _resolve_agy_bin() -> str | None:
    found = shutil.which("agy")
    if found:
        return found
    fallback = os.path.expanduser(_AGY_BIN_FALLBACK)
    if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
        return fallback
    return None


def _try_acquire() -> bool:
    global _ping_in_flight
    with _lock:
        if _ping_in_flight:
            return False
        _ping_in_flight = True
        return True


def _release() -> None:
    global _ping_in_flight
    with _lock:
        _ping_in_flight = False


def _run_agy_ping(agy_bin: str) -> None:
    subprocess.run(  # noqa: S603 - resolved local Antigravity CLI
        [agy_bin, "-p", "ok", "--model", AGY_MODEL],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=PING_TIMEOUT_SECONDS,
        cwd=os.path.expanduser("~"),
        check=False,
    )


def _ping_worker(started_at: float) -> None:
    try:
        agy_bin = _resolve_agy_bin()
        if agy_bin is None:
            _debug_log("agy-window-keeper: agy binary not found, skipping ping")
            return
        _run_agy_ping(agy_bin)
        _debug_log(f"agy-window-keeper: ping completed (started_at={started_at})")
    except subprocess.TimeoutExpired:
        _debug_log(f"agy-window-keeper: ping timed out after {PING_TIMEOUT_SECONDS}s")
    except Exception:
        _debug_log("agy-window-keeper: ping failed", exc_info=True)
    finally:
        _release()


def maybe_ping(result: AgyRefreshResult, mock: bool) -> None:
    """Read preferences and state, then dispatch a background ping if eligible."""
    if mock:
        return
    enabled = _agy_window_keeper_enabled()
    if not enabled:
        return
    projection = result.projection
    five_hour = projection.five_hour if projection is not None else None
    now = time.time()
    last_ping_at = _load_last_ping()
    if not should_ping(
        now=now,
        enabled=enabled,
        last_ping_at=last_ping_at,
        remaining_percent=(
            five_hour.remaining_percent if five_hour is not None else None
        ),
        stale=projection.stale if projection is not None else None,
        fallback_projection=projection is None,
        mock=mock,
    ):
        return
    if not _try_acquire():
        return
    # Stamp dispatch even on failure to avoid retrying every refresh.
    _save_last_ping(now)
    threading.Thread(target=_ping_worker, args=(now,), daemon=True).start()


def _debug_log(message: str, *, exc_info: bool = False) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning(message, exc_info=exc_info)
