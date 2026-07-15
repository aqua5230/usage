# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import logging
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from Foundation import NSBundle

logger = logging.getLogger(__name__)

LABEL = "com.lollapalooza.usage"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
_LOG_DIR = Path.home() / "Library" / "Logs" / "usage"


def build_plist(program_args: list[str], working_dir: str | None) -> str:
    log_dir = str(_LOG_DIR)
    payload: dict[str, object] = {
        "Label": LABEL,
        "RunAtLoad": True,
        "ProgramArguments": program_args,
        "StandardOutPath": f"{log_dir}/usage.log",
        "StandardErrorPath": f"{log_dir}/usage.err.log",
        "ThrottleInterval": 15,
        "StartDelay": 10,
        "ProcessType": "Interactive",
    }
    if working_dir is None:
        # .app launchd entry uses `open <bundle>`; KeepAlive would re-open endlessly.
        pass
    else:
        payload["KeepAlive"] = {"SuccessfulExit": False}
        payload["WorkingDirectory"] = working_dir
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")


def _bundle_value(bundle: Any, attr_name: str) -> str | None:
    attr = getattr(bundle, attr_name, None)
    value = attr() if callable(attr) else attr
    return str(value) if value is not None else None


def _program_context() -> tuple[list[str], str | None]:
    bundle = NSBundle.mainBundle()
    if _bundle_value(bundle, "bundleIdentifier") == LABEL:
        bundle_path = _bundle_value(bundle, "bundlePath")
        if bundle_path:
            return ["/usr/bin/open", bundle_path], None
    project_dir = Path(__file__).resolve().parent
    main_py = project_dir / "main.py"
    return [sys.executable, str(main_py)], str(project_dir)


def is_enabled() -> bool:
    return PLIST_PATH.exists()


def _plist_text() -> str:
    program_args, working_dir = _program_context()
    return build_plist(program_args, working_dir)


def _ensure_parent_dirs() -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _write_plist(contents: str) -> None:
    PLIST_PATH.write_text(contents, encoding="utf-8")


def _launchctl_domain_target() -> str:
    # login_item is only imported on macOS; the guard also keeps mypy's win32
    # run (which has no os.getuid) off the POSIX call.
    if sys.platform == "win32":
        raise RuntimeError("login_item is macOS-only")
    return f"gui/{os.getuid()}"


def _stderr_summary(stderr: str) -> str:
    return stderr.strip().replace("\n", " ")[:300]


def _log_launchctl_error(action: str, message: str) -> None:
    logger.warning("launchctl %s failed: %s", action, message)


def _launchctl_bootstrap() -> None:
    cmd = ["launchctl", "bootstrap", _launchctl_domain_target(), str(PLIST_PATH)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except FileNotFoundError as exc:
        _log_launchctl_error("bootstrap", str(exc))
        return
    except subprocess.TimeoutExpired as exc:
        _log_launchctl_error("bootstrap", f"timed out after {exc.timeout} seconds")
        return

    if result.returncode not in (0, 17):
        stderr = _stderr_summary(result.stderr)
        _log_launchctl_error("bootstrap", f"returncode={result.returncode} stderr={stderr!r}")


def enable() -> None:
    _ensure_parent_dirs()
    _write_plist(_plist_text())
    _launchctl_bootstrap()


def _remove_plist() -> None:
    PLIST_PATH.unlink(missing_ok=True)


def _launchctl_bootout() -> None:
    cmd = ["launchctl", "bootout", f"{_launchctl_domain_target()}/{LABEL}"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except FileNotFoundError as exc:
        _log_launchctl_error("bootout", str(exc))
        return
    except subprocess.TimeoutExpired as exc:
        _log_launchctl_error("bootout", f"timed out after {exc.timeout} seconds")
        return

    if result.returncode not in (0, 113):
        stderr = _stderr_summary(result.stderr)
        _log_launchctl_error("bootout", f"returncode={result.returncode} stderr={stderr!r}")


def disable() -> None:
    _launchctl_bootout()
    _remove_plist()
