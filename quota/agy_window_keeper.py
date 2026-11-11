# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Auto-open the next Antigravity 5-hour window."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from loaders import agy_quota_probe
from menubar.agy import AgyRefreshResult
from menubar.prefs import _agy_window_keeper_enabled
from quota import keeper_outcome
from usage_common.cli_lookup import cli_env, resolve_cli
from usage_common.network import google_auth_reachable
from usage_common.subprocess_utils import hidden_console_kwargs

logger = logging.getLogger(__name__)

AGY_WINDOW_KEEPER_STATE_PATH = Path(os.path.expanduser("~/.usage/agy_window_keeper.json"))
PING_COOLDOWN_SECONDS = 5 * 3600
PING_TIMEOUT_SECONDS = 180
AGY_MODEL = "gemini-3.8-flash-low"
_AGY_BIN_FALLBACKS = (
    "~/.local/bin/agy",
    "~/AppData/Local/agy/bin/agy.exe",
)

_lock = threading.Lock()
_ping_in_flight = False


class _PingSkipped(Exception):
    """The background safety gate refused this launch."""


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
    return keeper_outcome.numeric_value(keeper_outcome.read_state(state_path), "last_ping_at")


def _resolve_agy_bin() -> str | None:
    return resolve_cli("agy", _AGY_BIN_FALLBACKS)


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


def _run_agy_ping(agy_bin: str) -> subprocess.CompletedProcess[str]:
    if not agy_quota_probe.BACKGROUND_AGY_LOCK.acquire(blocking=False):
        raise _PingSkipped("background agy is busy")
    try:
        if not agy_quota_probe.agy_cli_signed_in(PING_TIMEOUT_SECONDS):
            raise _PingSkipped("CLI is signed out")
        result = subprocess.run(  # noqa: S603 - resolved local Antigravity CLI
            [agy_bin, "-p", "ok", "--model", AGY_MODEL],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=PING_TIMEOUT_SECONDS,
            cwd=os.path.expanduser("~"),
            check=False,
            env=cli_env(agy_bin),
            **hidden_console_kwargs(),
        )
        output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        if result.returncode != 0 and (
            "authentication required" in output or "authentication failed" in output
        ):
            agy_quota_probe.mark_cli_signed_out()
        return result
    finally:
        agy_quota_probe.BACKGROUND_AGY_LOCK.release()


def _ping_worker(started_at: float) -> None:
    try:
        binary = _resolve_agy_bin()
        result = _run_agy_ping(binary) if binary is not None else FileNotFoundError()
        fields = keeper_outcome.classify(result)
    except _PingSkipped as exc:
        _debug_log(f"Antigravity ping skipped: {exc}")
        # A probe may win the shared lock after dispatch. Allow the next refresh
        # to retry, and preserve any previous outcome rather than recording failure.
        try:
            keeper_outcome.update_state(
                AGY_WINDOW_KEEPER_STATE_PATH,
                lambda state: (
                    {"last_ping_at": None} if state.get("last_ping_at") == started_at else {}
                ),
            )
        finally:
            _release()
        return
    except Exception as exc:
        fields = keeper_outcome.classify(exc)
    try:
        keeper_outcome.record_result(AGY_WINDOW_KEEPER_STATE_PATH, fields)
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
    five_hour = projection.gemini_five_hour if projection is not None else None
    now = time.time()
    last_ping_at = _load_last_ping()
    state = keeper_outcome.read_state(AGY_WINDOW_KEEPER_STATE_PATH)

    def gate(previous: float | None) -> bool:
        return should_ping(
            now=now,
            enabled=enabled,
            last_ping_at=previous,
            remaining_percent=five_hour.remaining_percent if five_hour is not None else None,
            stale=projection.stale if projection is not None else None,
            fallback_projection=projection is None,
            mock=mock,
        )

    fresh = gate(last_ping_at)
    retry = not fresh and keeper_outcome.should_retry(state, now, None, gate(None))
    if not (fresh or retry):
        return
    # Offline (e.g. just after a sleep wake) the CLI would open a browser sign-in page;
    # leave the state untouched so the next refresh tries again.
    if not google_auth_reachable():
        return
    if agy_quota_probe.BACKGROUND_AGY_LOCK.locked():
        _debug_log("Antigravity ping skipped: background agy is busy")
        return
    if not agy_quota_probe.agy_cli_signed_in(PING_TIMEOUT_SECONDS):
        _debug_log("Antigravity ping skipped: CLI is signed out")
        return
    if not _try_acquire():
        return
    keeper_outcome.update_state(
        AGY_WINDOW_KEEPER_STATE_PATH,
        {
            "last_pinged_reset_at": None,
            "last_ping_at": now,
            "retry_used": retry,
        },
    )
    threading.Thread(target=_ping_worker, args=(now,), daemon=True).start()


def _debug_log(message: str, *, exc_info: bool = False) -> None:
    if os.environ.get("USAGE_DEBUG") == "1":
        logger.warning(message, exc_info=exc_info)
