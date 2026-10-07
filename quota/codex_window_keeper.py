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

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from loaders.codex_loader import load_rate_limits
from menubar.prefs import _window_keeper_enabled
from quota import keeper_outcome
from usage_common.subprocess_utils import hidden_console_kwargs

logger = logging.getLogger(__name__)

# State file holding the last handled reset boundary and dispatch time. Module
# constant so tests can monkeypatch it instead of touching the real
# ``~/.usage/`` dir.
CODEX_WINDOW_KEEPER_STATE_PATH = Path(os.path.expanduser("~/.usage/codex_window_keeper.json"))

PING_TIMEOUT_SECONDS = 180

# One full window plus five minutes, so a re-arm can never land inside the
# window the previous ping opened.
PING_COOLDOWN_SECONDS = 5 * 3600 + 300

# loaders.claude_usage defaults a missing ``resets_at`` to parse-time "now", which one
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


def _load_ping_state(path: Path | None = None) -> tuple[float | None, float | None]:
    state_path = CODEX_WINDOW_KEEPER_STATE_PATH if path is None else path
    state = keeper_outcome.read_state(state_path)
    return (
        keeper_outcome.numeric_value(state, "last_pinged_reset_at"),
        keeper_outcome.numeric_value(state, "last_ping_at"),
    )


def _save_ping_state(reset_at: float | None, ping_at: float, path: Path | None = None) -> None:
    state_path = CODEX_WINDOW_KEEPER_STATE_PATH if path is None else path
    keeper_outcome.update_state(
        state_path, {"last_pinged_reset_at": reset_at, "last_ping_at": ping_at}
    )


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


def _run_codex_ping(codex_bin: str) -> subprocess.CompletedProcess[str]:
    # encoding="utf-8" is mandatory inside the .app bundle (project invariant).
    return subprocess.run(  # noqa: S603 - shelling out to the user's own codex CLI by resolved path
        [codex_bin, "exec", "-m", "gpt-5.6-luna", "--skip-git-repo-check", "ok"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=PING_TIMEOUT_SECONDS,
        cwd=os.path.expanduser("~"),
        check=False,
        **hidden_console_kwargs(),
    )


def _ping_worker(started_at: float) -> None:
    try:
        binary = _resolve_codex_bin()
        result = _run_codex_ping(binary) if binary is not None else FileNotFoundError()
        fields = keeper_outcome.classify(result)
    except Exception as exc:
        fields = keeper_outcome.classify(exc)
    try:
        keeper_outcome.record_result(CODEX_WINDOW_KEEPER_STATE_PATH, fields)
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
    state = keeper_outcome.read_state(CODEX_WINDOW_KEEPER_STATE_PATH)
    idle = should_ping(
        now, current_reset_at, enabled, None, None, current_percent, has_five_hour_window
    )
    fresh = should_ping(
        now,
        current_reset_at,
        enabled,
        last_pinged_reset_at,
        last_ping_at,
        current_percent,
        has_five_hour_window,
    )
    retry = not fresh and keeper_outcome.should_retry(state, now, current_reset_at, idle)
    if not (fresh or retry):
        return
    if not _try_acquire():
        return
    keeper_outcome.update_state(
        CODEX_WINDOW_KEEPER_STATE_PATH,
        {
            "last_pinged_reset_at": current_reset_at,
            "last_ping_at": now,
            "retry_used": retry,
        },
    )
    worker = threading.Thread(target=_ping_worker, args=(now,), daemon=True)
    worker.start()


def _debug_log(message: str, *, exc_info: bool = False) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning(message, exc_info=exc_info)
