from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

__all__ = ["resolve_project_name"]


def resolve_project_name(cwd: str | Path) -> str:
    """Resolve a cwd to its canonical project name, including git worktrees."""
    if not str(cwd):
        return "unknown"
    path = Path(os.path.expanduser(str(cwd))).resolve(strict=False)
    return _resolve_project_name(str(path))


@lru_cache(maxsize=256)
def _resolve_project_name(normalized_cwd: str) -> str:
    fallback = Path(normalized_cwd).name or "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", normalized_cwd, "worktree", "list", "--porcelain"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return fallback

    if result.returncode != 0 or result.stderr or not result.stdout:
        return fallback

    lines = result.stdout.splitlines()
    first_line = lines[0] if lines else ""
    prefix = "worktree "
    if not first_line.startswith(prefix):
        return fallback

    main_path = first_line.removeprefix(prefix).strip()
    if not main_path:
        return fallback
    return Path(main_path).name or fallback
