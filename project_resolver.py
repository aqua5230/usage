from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

__all__ = ["project_from_encoded_path", "resolve_project_name"]


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


def project_from_encoded_path(jsonl_path: Path, projects_dir: Path) -> str:
    """Decode a Claude Code project name from a sessions JSONL path under projects_dir."""
    try:
        project_dir = jsonl_path.relative_to(projects_dir).parts[0]
    except (IndexError, ValueError):
        return "unknown"

    parts = [part for part in project_dir.split("-") if part]
    if not parts:
        return "unknown"

    slash_candidate = Path(os.sep, *parts)
    if slash_candidate.is_dir():
        return slash_candidate.name or "unknown"

    existing_project = _existing_encoded_project_path(parts)
    if existing_project is not None:
        return existing_project.name or "unknown"

    fallback = project_dir.removeprefix("-")
    return fallback or "unknown"


def _existing_encoded_project_path(parts: list[str]) -> Path | None:
    def search(index: int, current: Path) -> Path | None:
        for end in range(index + 1, len(parts) + 1):
            candidate = current / "-".join(parts[index:end])
            if not candidate.is_dir():
                continue
            if end == len(parts):
                return candidate
            result = search(end, candidate)
            if result is not None:
                return result
        return None

    return search(0, Path(os.sep))
