# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Auto-open the next Codex 5-hour window.

When the user's Codex quota window has expired and no window is currently
running, this fires a single ``codex exec -m gpt-5.6-luna
--skip-git-repo-check "ok"`` message in the background to start a fresh
window. The ping is the cheapest possible Codex call; it does NOT touch any
OpenAI quota API — it only shells out to the user's local ``codex`` CLI.

Codex has no usage hook, so a cooldown clock re-arms the keeper
independently of the payload: a machine that never opens Codex
interactively still gets a fresh window every cycle instead of wedging
after the first ping.

Plans that never report a 5-hour window (``five_hour_window_minutes is
None``) stay quiet rather than risk pinging an unrestricted account. The
loader zeros ``five_hour_pct`` / ``five_hour_resets_at`` once a window
expires but keeps ``five_hour_window_minutes``, so that field is the
has-a-5h-window signal.

Defaults OFF. All judgement and side effects live here; the refresh loop
only dispatches a one-line call into :func:`maybe_ping`.
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

from loaders.codex_loader import load_rate_limits
from menubar.prefs import _window_keeper_enabled

logger = logging.getLogger(__name__)

# State file holding the last handled reset boundary and dispatch time. Module
# constant so tests can monkeypatch it instead of touching the real
# ``~/.usage/`` dir.
CODEX_WINDOW_KEEPER_STATE_PATH = Path(
    os.path.expanduser("~/.usage/codex_window_keeper.json")
)

PING_TIMEOUT_SECONDS = 180

# One full window plus five minutes, so a re-arm can never land inside the
# window the previous ping opened.
PING_COOLDOWN_SECONDS = 5 * 3600 + 300

# usage_client defaults a missing ``resets_at`` to parse-time "now", which one
# refresh later reads as "expired seconds ago". Requiring the expiry to be at
# least this old filters those synthetic timestamps without delaying a real
# expired-while-away ping by more than two minutes. Codex's loader already
# zeros a past ``resets_at``, so this grace mainly applies if a timestamp
# still arrives.
PING_EXPIRY_GRACE_SECONDS = 120

# ``codex`` binary resolution order: PATH first, then the well-known install
# spots Homebrew / the native installer lay down. The .app bundle runs with a
# minimal PATH, so ~/.local/bin must be listed.
_CODEX_BIN_FALLBACKS = (
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
    "~/.local/bin/codex",
    "~/.local/bin/codex.exe",
)

_lock = threading.Lock()
_ping_in_flight = False


def should_ping(
    now: float,
    current_reset_at: float | None,
    enabled: bool,
    last_pinged_reset_at: float | None,
    last_ping_at: float | None,
    current_percent: float | None,
    has_five_hour_window: bool,
) -> bool:
    """Pure gate — no I/O. See module docstring for the rules."""
    if not enabled:
        return False
    # $100/$200 plans (and machines with no Codex history) never report a
    # 5-hour window. Stay quiet rather than risk a false start.
    if not has_five_hour_window:
        return False
    # Codex's loader zeros an expired window: ``five_hour_resets_at`` becomes
    # None and percent becomes 0.0 (jsonl) or None (sqlite), while
    # ``five_hour_window_minutes`` stays. A missing percent is therefore not
    # the "no five-hour block" signal it is for Claude — that job belongs to
    # ``has_five_hour_window``. With no timestamp to compare, re-arm on the
    # dispatch clock so the same cleared payload cannot ignore the cooldown.
    if current_reset_at is None:
        return last_ping_at is None or now - last_ping_at >= PING_COOLDOWN_SECONDS
    # A live (or still-timestamped) slot without a percent is unreadable —
    # stay quiet rather than guess.
    if current_percent is None:
        return False
    if now - current_reset_at < PING_EXPIRY_GRACE_SECONDS:
        return False
    # Two independent re-arm paths, because the two cases run on different
    # clocks. A different real boundary means the user was active and the
    # window genuinely rolled over — fire regardless of how recent the last
    # ping was. The same boundary reported over and over means the payload has
    # gone stale (see module docstring), and only the dispatch clock can tell
    # us another window's worth of time has passed.
    if current_reset_at != last_pinged_reset_at:
        return True
    return last_ping_at is None or now - last_ping_at >= PING_COOLDOWN_SECONDS


def _load_ping_state(
    path: Path | None = None,
) -> tuple[float | None, float | None]:
    state_path = CODEX_WINDOW_KEEPER_STATE_PATH if path is None else path
    if not state_path.exists():
        return None, None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None

    def numeric_value(key: str) -> float | None:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    return numeric_value("last_pinged_reset_at"), numeric_value("last_ping_at")


def _save_ping_state(
    reset_at: float | None,
    ping_at: float,
    path: Path | None = None,
) -> None:
    state_path = CODEX_WINDOW_KEEPER_STATE_PATH if path is None else path
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"last_pinged_reset_at": reset_at, "last_ping_at": ping_at}
    ) + "\n"
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=state_path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_path, state_path)
        tmp_path = None
    except OSError:
        _debug_log("codex-window-keeper state write failed", exc_info=True)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with suppress(OSError):
                os.unlink(tmp_path)


def _resolve_codex_bin() -> str | None:
    found = shutil.which("codex")
    if found:
        return found
    for candidate in _CODEX_BIN_FALLBACKS:
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


def _run_codex_ping(codex_bin: str) -> None:
    # encoding="utf-8" is mandatory inside the .app bundle (project invariant).
    subprocess.run(  # noqa: S603 - shelling out to the user's own codex CLI by resolved path
        [codex_bin, "exec", "-m", "gpt-5.6-luna", "--skip-git-repo-check", "ok"],
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
        codex_bin = _resolve_codex_bin()
        if codex_bin is None:
            _debug_log("codex-window-keeper: codex binary not found, skipping ping")
            return
        _run_codex_ping(codex_bin)
        _debug_log(f"codex-window-keeper: ping completed (started_at={started_at})")
    except subprocess.TimeoutExpired:
        _debug_log(f"codex-window-keeper: ping timed out after {PING_TIMEOUT_SECONDS}s")
    except Exception:
        # Never let a ping failure escape into the app — this runs on a daemon
        # thread whose exception would otherwise be silently swallowed anyway,
        # but be explicit so a future refactor can't crash the main loop.
        _debug_log("codex-window-keeper: ping failed", exc_info=True)
    finally:
        _release()


def maybe_ping(mock: bool) -> None:
    """High-level entry: read prefs + rate limits + state, gate, and fire a ping.

    Returns immediately — the subprocess runs on a daemon thread. Safe to call
    on every UI refresh; boundary deduplication + the in-flight guard make it a
    no-op when busy. Rate limits are loaded here so the refresh loop does not
    have to thread Codex fields through its intermediate dict.
    """
    if mock:
        return
    enabled = _window_keeper_enabled()
    if not enabled:
        # Switch off → zero side effects: don't read or write state, don't spawn.
        return
    rate_limits = load_rate_limits()
    if rate_limits is None:
        return
    current_reset_at = rate_limits.five_hour_resets_at
    current_percent = rate_limits.five_hour_pct
    has_five_hour_window = rate_limits.five_hour_window_minutes is not None
    now = time.time()
    last_pinged_reset_at, last_ping_at = _load_ping_state()
    if not should_ping(
        now,
        current_reset_at,
        enabled,
        last_pinged_reset_at,
        last_ping_at,
        current_percent,
        has_five_hour_window,
    ):
        return
    if not _try_acquire():
        return
    # Mark this boundary handled at dispatch time regardless of subprocess
    # outcome, so a failed ping doesn't retry on every refresh.
    _save_ping_state(current_reset_at, now)
    worker = threading.Thread(target=_ping_worker, args=(now,), daemon=True)
    worker.start()


def _debug_log(message: str, *, exc_info: bool = False) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning(message, exc_info=exc_info)
