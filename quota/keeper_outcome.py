"""Shared keeper outcomes and locked, atomic state updates."""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from i18n import _t

_lock = threading.Lock()
logger = logging.getLogger(__name__)


def numeric_value(state: dict[str, Any], key: str) -> float | None:
    value = state.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update_state(
    path: Path, updates: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    with _lock:
        data = read_state(path)
        fields = updates(data) if callable(updates) else updates
        if not fields:
            return
        data.update(fields)
        tmp_path: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(data) + "\n")
            os.replace(tmp_path, path)
        except OSError:
            logger.warning("keeper state write failed: %s", path, exc_info=True)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)


def record_result(path: Path, fields: dict[str, Any]) -> None:
    def merge(state: dict[str, Any]) -> dict[str, Any]:
        failed = fields["last_result"] == "failed"
        final = failed and (
            state.get("retry_used") is True or fields["last_error_kind"] == "not_found"
        )
        return fields | {
            "last_result_at": time.time(),
            "final_failure": final,
            "warning": final or (failed and state.get("warning") is True),
        }

    update_state(path, merge)


def classify(result: subprocess.CompletedProcess[str] | BaseException) -> dict[str, Any]:
    kind, detail = "", ""
    if isinstance(result, FileNotFoundError):
        kind = "not_found"
    elif isinstance(result, subprocess.TimeoutExpired):
        kind = "timeout"
    elif isinstance(result, BaseException):
        kind, detail = "error", type(result).__name__
    elif result.returncode != 0:
        kind = "exit"
        lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
        if not lines:
            lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        detail = f"exit {result.returncode}: {lines[-1] if lines else ''}".strip()
    fields: dict[str, Any] = {
        "last_result": "failed" if kind else "ok",
        "last_error_kind": kind,
        "last_error_detail": detail[:120],
    }
    if not kind:
        fields["notified_error"] = ""
    return fields


def should_retry(state: dict[str, Any], now: float, boundary: float | None, idle: bool) -> bool:
    result_at = numeric_value(state, "last_result_at")
    return (
        idle
        and state.get("last_result") == "failed"
        and state.get("retry_used", False) is False
        and state.get("last_error_kind") != "not_found"
        and result_at is not None
        and now - result_at >= 600
        and numeric_value(state, "last_pinged_reset_at") == boundary
    )


def final_failure(state: dict[str, Any]) -> bool:
    return state.get("last_result") == "failed" and state.get("final_failure") is True


def warning(state: dict[str, Any]) -> bool:
    return state.get("warning") is True


def error_key(state: dict[str, Any]) -> str:
    return f"{state.get('last_error_kind', '')}:{state.get('last_error_detail', '')}"


def should_notify(state: dict[str, Any]) -> bool:
    ping_at = numeric_value(state, "last_ping_at")
    result_at = numeric_value(state, "last_result_at")
    # retry_used is stamped before dispatch; wait for that attempt's result.
    if ping_at is not None and (result_at is None or result_at < ping_at):
        return False
    return final_failure(state) and error_key(state) != state.get("notified_error", "")


def keeper_states() -> list[tuple[str, Path, dict[str, Any]]]:
    from quota import agy_window_keeper, codex_window_keeper, window_keeper

    paths = [
        ("Claude", window_keeper.WINDOW_KEEPER_STATE_PATH),
        ("Codex", codex_window_keeper.CODEX_WINDOW_KEEPER_STATE_PATH),
        ("Antigravity", agy_window_keeper.AGY_WINDOW_KEEPER_STATE_PATH),
    ]
    return [(tool, path, read_state(path)) for tool, path in paths]


def reason(language: str, state: dict[str, Any]) -> str:
    kind = state.get("last_error_kind")
    if kind in ("not_found", "timeout"):
        return _t(language, f"keeper_reason_{kind}")
    detail = state.get("last_error_detail", "")
    return detail[:120] if isinstance(detail, str) else ""


def notify_failures(
    language: str, enabled: bool, mock: bool, send: Callable[[str, str], None]
) -> None:
    if mock:
        return
    for tool, path, _ in keeper_states():
        claimed: dict[str, Any] = {}

        def claim(state: dict[str, Any], captured: dict[str, Any] = claimed) -> dict[str, Any]:
            if should_notify(state):
                captured.update(state)
                return {"notified_error": error_key(state)}
            return {}

        update_state(path, claim)
        if not claimed:
            continue
        state = claimed
        if enabled:
            send(
                _t(language, "keeper_failed_title"),
                _t(language, "keeper_failed_body").format(
                    tool=tool, reason=reason(language, state)
                ),
            )


def failure_tooltip(language: str) -> str:
    lines = []
    for tool, _, state in keeper_states():
        if warning(state):
            stamp = numeric_value(state, "last_result_at")
            try:
                clock = datetime.fromtimestamp(stamp or 0).strftime("%H:%M")
            except (OSError, OverflowError, ValueError):
                clock = "--:--"
            lines.append(
                _t(language, "keeper_failed_line").format(
                    time=clock, tool=tool, reason=reason(language, state)
                )
            )
    return "\n".join(lines)
