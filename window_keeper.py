# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Auto-open the next Claude 5-hour window.

When the user's Claude quota window has expired (``current_reset_at < now``) and
no window is currently running, this fires a single ``claude -p ok --model haiku``
message in the background to start a fresh window. The ping is the cheapest
possible Claude call; it does NOT touch any Anthropic quota API — it only shells
out to the user's local ``claude`` CLI.

Defaults OFF. All judgement and side effects live here; ``menubar.py`` only
dispatches a one-line call into :func:`maybe_ping`.
"""

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

from menubar_prefs import _window_keeper_enabled

logger = logging.getLogger(__name__)

# State file holding ``{"last_ping_at": <float epoch>}``. Module constant so
# tests can monkeypatch it instead of touching the real ``~/.usage/`` dir.
WINDOW_KEEPER_STATE_PATH = Path(os.path.expanduser("~/.usage/window_keeper.json"))

# Our own ping does not refresh the status file (``claude -p`` print mode never
# triggers the statusLine hook), so we must self-throttle: after a ping, wait a
# full window before trying again, regardless of subprocess success/failure.
PING_COOLDOWN_SECONDS = 5 * 3600
PING_TIMEOUT_SECONDS = 180

# usage_client defaults a missing ``resets_at`` to parse-time "now", which one
# refresh later reads as "expired seconds ago". Requiring the expiry to be at
# least this old filters those synthetic timestamps without delaying a real
# expired-while-away ping by more than two minutes.
PING_EXPIRY_GRACE_SECONDS = 120

# ``claude`` binary resolution order: PATH first, then the well-known install
# spots the Claude Code installer/Node/Homebrew lay down. The .app bundle runs
# with a minimal PATH, so the native installer's ~/.local/bin must be listed.
_CLAUDE_BIN_FALLBACKS = (
    "~/.local/bin/claude",
    "~/.claude/local/claude",
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
)

_lock = threading.Lock()
_ping_in_flight = False


def should_ping(
    now: float,
    current_reset_at: float | None,
    enabled: bool,
    last_ping_at: float | None,
    current_percent: float | None,
    data_source: str,
) -> bool:
    """Pure gate — no I/O. See module docstring for the rules."""
    if not enabled:
        return False
    # Only the statusLine hook carries trustworthy reset timestamps; fallback
    # sources (tt-fallback / claude-json) may default a missing resets_at to
    # parse time, which would read as "expired" and fire a spurious ping.
    if data_source != "hook":
        return False
    # No five-hour block in the payload at all — we can't tell whether a window
    # is running, so stay quiet rather than risk a false start.
    if current_percent is None:
        return False
    if current_reset_at is None or now - current_reset_at < PING_EXPIRY_GRACE_SECONDS:
        return False
    # Outside the self-throttle cooldown (None last_ping_at means we never have).
    return last_ping_at is None or now - last_ping_at >= PING_COOLDOWN_SECONDS


def _load_last_ping(path: Path | None = None) -> float | None:
    state_path = WINDOW_KEEPER_STATE_PATH if path is None else path
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
    state_path = WINDOW_KEEPER_STATE_PATH if path is None else path
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
        _debug_log("window-keeper state write failed", exc_info=True)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with suppress(OSError):
                os.unlink(tmp_path)


def _resolve_claude_bin() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    for candidate in _CLAUDE_BIN_FALLBACKS:
        resolved = os.path.expanduser(candidate)
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved
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


def _run_claude_ping(claude_bin: str) -> None:
    # encoding="utf-8" is mandatory inside the .app bundle (project invariant).
    subprocess.run(  # noqa: S603 - shelling out to the user's own claude CLI by resolved path
        [claude_bin, "-p", "ok", "--model", "haiku"],
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
        claude_bin = _resolve_claude_bin()
        if claude_bin is None:
            _debug_log("window-keeper: claude binary not found, skipping ping")
            return
        _run_claude_ping(claude_bin)
        _debug_log(f"window-keeper: ping completed (started_at={started_at})")
    except subprocess.TimeoutExpired:
        _debug_log(f"window-keeper: ping timed out after {PING_TIMEOUT_SECONDS}s")
    except Exception:
        # Never let a ping failure escape into the app — this runs on a daemon
        # thread whose exception would otherwise be silently swallowed anyway,
        # but be explicit so a future refactor can't crash the main loop.
        _debug_log("window-keeper: ping failed", exc_info=True)
    finally:
        _release()


def maybe_ping(
    current_reset_at: float | None,
    current_percent: float | None,
    data_source: str,
    mock: bool,
) -> None:
    """High-level entry: read prefs + state, gate, and fire a background ping.

    Returns immediately — the subprocess runs on a daemon thread. Safe to call
    on every UI refresh; cooldown + in-flight guard make it a no-op when busy.
    """
    if mock:
        return
    enabled = _window_keeper_enabled()
    if not enabled:
        # Switch off → zero side effects: don't read or write state, don't spawn.
        return
    now = time.time()
    last_ping_at = _load_last_ping()
    if not should_ping(now, current_reset_at, enabled, last_ping_at, current_percent, data_source):
        return
    if not _try_acquire():
        return
    # Stamp the ping at dispatch time regardless of subprocess outcome, so a
    # failed ping doesn't retry on every refresh; the next window naturally
    # re-arms 5h later.
    _save_last_ping(now)
    worker = threading.Thread(target=_ping_worker, args=(now,), daemon=True)
    worker.start()


def _debug_log(message: str, *, exc_info: bool = False) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning(message, exc_info=exc_info)
