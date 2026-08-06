# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Background workers behind the menu's hook, statusline and report actions."""

from __future__ import annotations

import contextlib
import io
import logging
import os
from typing import Any, Protocol

from statusline_settings import (
    _disable_statusline_settings,
    _enable_statusline_settings,
    _toggle_statusline_settings,
)

logger = logging.getLogger(__name__)


class _ActionApp(Protocol):
    language: str

    def performSelectorOnMainThread_withObject_waitUntilDone_(
        self, selector: str, obj: Any, wait: bool
    ) -> None: ...


def toggle_session_resume_in_background(app: _ActionApp) -> None:
    import session_hooks

    output = io.StringIO()
    ok = True
    enabled = False
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            if session_hooks.is_resume_enabled():
                session_hooks.disable_session_resume()
            else:
                ok = session_hooks.enable_session_resume() == 0
                enabled = ok
    except SystemExit as exc:
        if exc.code:
            ok = False
            print(exc.code, file=output)
    except Exception as exc:
        ok = False
        print(f"{type(exc).__name__}: {exc}", file=output)

    app.performSelectorOnMainThread_withObject_waitUntilDone_(
        "_finishSessionResume:",
        {"ok": ok, "enabled": enabled, "output": output.getvalue().strip()},
        False,
    )


def toggle_terse_mode_in_background(app: _ActionApp) -> None:
    import session_hooks

    output = io.StringIO()
    ok = True
    enabled = False
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            if session_hooks.is_terse_mode_enabled():
                session_hooks.disable_terse_mode()
            else:
                ok = session_hooks.enable_terse_mode() == 0
                enabled = ok
    except SystemExit as exc:
        if exc.code:
            ok = False
            print(exc.code, file=output)
    except Exception as exc:
        ok = False
        print(f"{type(exc).__name__}: {exc}", file=output)

    app.performSelectorOnMainThread_withObject_waitUntilDone_(
        "_finishTerseMode:",
        {"ok": ok, "enabled": enabled, "output": output.getvalue().strip()},
        False,
    )


def install_hook_in_background(app: _ActionApp) -> None:
    output = io.StringIO()
    exit_code = 1
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            import session_hooks
            import setup_hook

            exit_code = setup_hook.setup()
            if exit_code == 0:
                session_hooks._migrate_bundled_python_commands_if_needed()
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
        if exc.code:
            print(exc.code, file=output)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=output)

    result = {
        "success": exit_code == 0,
        "message": output.getvalue().strip(),
    }
    app.performSelectorOnMainThread_withObject_waitUntilDone_(
        "_finishHookInstall:",
        result,
        False,
    )


def statusline_action_in_background(app: _ActionApp, action: str) -> None:
    output = io.StringIO()
    ok = True
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            if action == "toggle":
                _toggle_statusline_settings()
            elif action == "uninstall":
                _disable_statusline_settings()
            else:
                _enable_statusline_settings()
    except SystemExit as exc:
        if exc.code:
            ok = False
            print(exc.code, file=output)
    except Exception as exc:
        ok = False
        print(f"{type(exc).__name__}: {exc}", file=output)

    app.performSelectorOnMainThread_withObject_waitUntilDone_(
        "_finishStatuslineAction:",
        {"ok": ok, "action": action, "output": output.getvalue().strip()},
        False,
    )


def analyze_usage_in_background(app: _ActionApp, period: str) -> None:
    from menubar import _generate_analysis_report

    result: dict[str, str | bool]
    try:
        saved = _generate_analysis_report(period=period, language=app.language)
        result = {"success": True, "message": saved}
    except Exception as exc:
        if os.environ.get("USAGE_DEBUG") == "1":
            logger.warning("analysis report failed", exc_info=True)
        result = {"success": False, "message": f"{type(exc).__name__}: {exc}"}
    app.performSelectorOnMainThread_withObject_waitUntilDone_(
        "_finishAnalyzeUsage:",
        result,
        False,
    )
