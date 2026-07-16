#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""usage app statusLine forwarder: fan stdin out to ~/.claude/*-statusline.py."""

from __future__ import annotations

import concurrent.futures
import contextlib
import glob
import os
import shutil
import subprocess
import sys
from typing import Any, cast

__version__ = "1.0"
TIMEOUT_SECONDS = 5
HOOK_DIR = os.path.expanduser("~/.claude")
SELF_NAME = "usage-statusline-forwarder.py"


def _configure_windows_utf8_output() -> None:
    """Make forwarded hook output UTF-8 when Claude Code reads a pipe."""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            # Test runners and embedders may replace the TextIOWrapper streams.
            cast(Any, stream).reconfigure(encoding="utf-8")


def _run_hook(py: str, hook: str, raw: str) -> str:
    try:
        result = subprocess.run(
            [py, hook],
            input=raw,
            text=True,
            check=False,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
        return ""
    return result.stdout or ""


def main() -> None:
    _configure_windows_utf8_output()
    raw = sys.stdin.read()
    if not raw.strip():
        return

    hooks: list[str] = []
    for path in sorted(glob.glob(os.path.join(HOOK_DIR, "*-statusline.py"))):
        name = os.path.basename(path)
        if name == SELF_NAME:
            continue
        if "-forwarder" in name:
            continue
        hooks.append(path)

    py = sys.executable or shutil.which("python") or "python"
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(hooks))) as ex:
        futures = [ex.submit(_run_hook, py, hook, raw) for hook in hooks]
        for future in futures:
            out = future.result()
            if out:
                sys.stdout.write(out)

    sys.stdout.flush()


if __name__ == "__main__":
    main()
