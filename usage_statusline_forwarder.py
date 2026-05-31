#!/usr/bin/env python3
"""usage app statusLine forwarder: fan stdin out to ~/.claude/*-statusline.py."""

from __future__ import annotations

import concurrent.futures
import glob
import os
import subprocess
import sys

__version__ = "1.0"
TIMEOUT_SECONDS = 5
HOOK_DIR = os.path.expanduser("~/.claude")
SELF_NAME = "usage-statusline-forwarder.py"


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

    py = sys.executable or "/usr/bin/python3"
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(hooks))) as ex:
        futures = [ex.submit(_run_hook, py, hook, raw) for hook in hooks]
        for future in futures:
            out = future.result()
            if out:
                sys.stdout.write(out)

    sys.stdout.flush()


if __name__ == "__main__":
    main()
