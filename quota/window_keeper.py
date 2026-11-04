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

Known-unreliable, cause unidentified: on 2026-08-12 two pings ran with
indistinguishable requests (same version, entrypoint, model, token shape) and
only one opened a window. The 06:33 ping lines up with an 11:30 reset; the 17:00
one did not open anything — the next window began only when the user typed into
Claude Code at 18:30. The user confirmed no claude.ai/mobile activity that
morning, so the 06:33 window is not explained away by another device. Not a
model issue (the docs say plan windows are shared across all models).

That ping runs headless, so Claude Code's statusLine hook never fires and
``usage-status.json`` keeps reporting the boundary we already handled. A
cooldown clock therefore re-arms the keeper independently of the payload, so a
machine that never opens Claude Code interactively still gets a fresh window
every cycle instead of wedging after the first ping.

Defaults OFF. All judgement and side effects live here; ``menubar.py`` only
dispatches a one-line call into :func:`maybe_ping`.
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
import threading
import time
from pathlib import Path

from menubar.prefs import _window_keeper_enabled
from quota import keeper_outcome
from usage_common.cli_lookup import cli_env, resolve_cli
from usage_common.subprocess_utils import hidden_console_kwargs

logger = logging.getLogger(__name__)

# State file holding the last handled reset boundary and dispatch time. Module
# constant so tests can monkeypatch it instead of touching the real
# ``~/.usage/`` dir.
WINDOW_KEEPER_STATE_PATH = Path(os.path.expanduser("~/.usage/window_keeper.json"))
KEEPER_CLAUDE_SETTINGS_PATH = Path(
    os.path.expanduser("~/.usage/window_keeper_claude_settings.json")
)

PING_TIMEOUT_SECONDS = 180

# One full window plus five minutes, so a re-arm can never land inside the
# window the previous ping opened.
PING_COOLDOWN_SECONDS = 5 * 3600 + 300

# Wait briefly after a real reset before opening the next window, allowing
# quota observations around the reset boundary to settle.
PING_EXPIRY_GRACE_SECONDS = 120

# ``claude`` binary resolution order: PATH first, then the well-known install
# spots the Claude Code installer/Node/Homebrew lay down. The .app bundle runs
# with a minimal PATH, so the native installer's ~/.local/bin must be listed.
_CLAUDE_BIN_FALLBACKS = (
    "~/.local/bin/claude",
    "~/.local/bin/claude.exe",
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
    last_pinged_reset_at: float | None,
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
    state_path = WINDOW_KEEPER_STATE_PATH if path is None else path
    state = keeper_outcome.read_state(state_path)
    return (
        keeper_outcome.numeric_value(state, "last_pinged_reset_at"),
        keeper_outcome.numeric_value(state, "last_ping_at"),
    )


def _save_ping_state(reset_at: float, ping_at: float, path: Path | None = None) -> None:
    state_path = WINDOW_KEEPER_STATE_PATH if path is None else path
    keeper_outcome.update_state(
        state_path, {"last_pinged_reset_at": reset_at, "last_ping_at": ping_at}
    )


def _resolve_claude_bin() -> str | None:
    return resolve_cli("claude", _CLAUDE_BIN_FALLBACKS)


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


def _run_claude_ping(claude_bin: str) -> subprocess.CompletedProcess[str]:
    # Background pings should not trigger user hooks. Pass a settings file, not
    # inline JSON: cmd.exe mangles the quotes when claude is a .cmd shim.
    KEEPER_CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEEPER_CLAUDE_SETTINGS_PATH.write_text('{"disableAllHooks": true}\n', encoding="utf-8")
    # encoding="utf-8" is mandatory inside the .app bundle (project invariant).
    return subprocess.run(  # noqa: S603 - shelling out to the user's own claude CLI by resolved path
        [
            claude_bin,
            "-p",
            "ok",
            "--model",
            "haiku",
            "--settings",
            str(KEEPER_CLAUDE_SETTINGS_PATH),
            # No tools or MCP servers keeps the ping small; no persistence keeps
            # it out of the user's /resume list.
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=PING_TIMEOUT_SECONDS,
        cwd=os.path.expanduser("~"),
        check=False,
        env=cli_env(claude_bin),
        **hidden_console_kwargs(),
    )


def _ping_worker(started_at: float) -> None:
    try:
        binary = _resolve_claude_bin()
        result = _run_claude_ping(binary) if binary is not None else FileNotFoundError()
        fields = keeper_outcome.classify(result)
    except Exception as exc:
        fields = keeper_outcome.classify(exc)
    try:
        keeper_outcome.record_result(WINDOW_KEEPER_STATE_PATH, fields)
    finally:
        _release()


def _recall_expired_window(
    state: dict[str, object],
    current_reset_at: float | None,
    current_percent: float | None,
    data_source: str,
) -> tuple[float | None, float | None]:
    """Stand in the last reported five-hour reset once the payload drops the window.

    Claude Code omits ``five_hour`` once its ``resets_at`` has passed, and the
    statusLine hook drops the cached copy too (plans without a 5-hour limit never
    send one), so an expired window reaches us as no window at all. The reader
    then reports no percent and no reset, which is not worth keeping.
    Remember every real reset the hook reports; a plan that never reported one
    stays unarmed.
    """
    if data_source != "hook":
        return current_reset_at, current_percent
    remembered = keeper_outcome.numeric_value(state, "last_seen_reset_at")
    if current_percent is None:
        return (current_reset_at, None) if remembered is None else (remembered, 0.0)
    if current_reset_at is None or not math.isfinite(current_reset_at):
        return None, current_percent
    if current_reset_at is not None and current_reset_at != remembered:
        keeper_outcome.update_state(
            WINDOW_KEEPER_STATE_PATH, {"last_seen_reset_at": current_reset_at}
        )
    return current_reset_at, current_percent


def maybe_ping(
    current_reset_at: float | None,
    current_percent: float | None,
    data_source: str,
    mock: bool,
) -> None:
    """High-level entry: read prefs + state, gate, and fire a background ping.

    Returns immediately — the subprocess runs on a daemon thread. Safe to call
    on every UI refresh; boundary deduplication + the in-flight guard make it a
    no-op when busy.
    """
    if mock:
        return
    enabled = _window_keeper_enabled()
    if not enabled:
        # Switch off → zero side effects: don't read or write state, don't spawn.
        return
    now = time.time()
    last_pinged_reset_at, last_ping_at = _load_ping_state()
    state = keeper_outcome.read_state(WINDOW_KEEPER_STATE_PATH)
    current_reset_at, current_percent = _recall_expired_window(
        state, current_reset_at, current_percent, data_source
    )
    idle = should_ping(now, current_reset_at, enabled, None, None, current_percent, data_source)
    fresh = should_ping(
        now,
        current_reset_at,
        enabled,
        last_pinged_reset_at,
        last_ping_at,
        current_percent,
        data_source,
    )
    retry = not fresh and keeper_outcome.should_retry(state, now, current_reset_at, idle)
    if not (fresh or retry):
        return
    if not _try_acquire():
        return
    assert current_reset_at is not None  # guaranteed by should_ping
    keeper_outcome.update_state(
        WINDOW_KEEPER_STATE_PATH,
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
