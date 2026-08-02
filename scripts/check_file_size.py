#!/usr/bin/env python3
"""Fail CI when a file guarded by a growth policy creeps past its ceiling.

`menubar.py` has been split apart twice and grown back both times, because the
policy in CLAUDE.md was enforced by nothing but good intentions. Lower a ceiling
whenever a cut lands; never raise one to make CI green.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CEILINGS = {
    "menubar.py": 2120,
}


def main() -> int:
    failures = []
    for name, ceiling in CEILINGS.items():
        path = REPO_ROOT / name
        if not path.is_file():
            failures.append(f"{name}: guarded file is missing")
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        status = "over" if lines > ceiling else "ok"
        print(f"{name}: {lines}/{ceiling} lines ({status})")
        if lines > ceiling:
            failures.append(
                f"{name}: {lines} lines exceeds the {ceiling}-line ceiling. "
                f"Move the new logic into a leaf module instead of raising this limit."
            )

    for failure in failures:
        print(f"error: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
