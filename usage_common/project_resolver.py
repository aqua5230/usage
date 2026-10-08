# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from usage_common.subprocess_utils import hidden_console_kwargs

__all__ = ["project_from_encoded_path", "resolve_project_name"]

_ENCODED_LIMIT = 200


@lru_cache(maxsize=2048)
def resolve_project_name(cwd: str | Path) -> str:
    """Resolve a cwd to its canonical project name, including git worktrees."""
    if not str(cwd):
        return "unknown"
    path = Path(os.path.expanduser(str(cwd))).resolve(strict=False)
    return _resolve_project_name(str(path))


@lru_cache(maxsize=2048)
def _resolve_project_name(normalized_cwd: str) -> str:
    fallback = Path(normalized_cwd).name or "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", normalized_cwd, "worktree", "list", "--porcelain"],
            capture_output=True,
            check=False,
            text=True,
            # Force UTF-8 instead of the locale default: a .app launched via
            # LaunchServices has no LANG set, so text=True would decode git's
            # output as ASCII and crash on non-ASCII (e.g. Chinese) repo paths.
            encoding="utf-8",
            errors="replace",
            timeout=3,
            stdin=subprocess.DEVNULL,
            **hidden_console_kwargs(),
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
    # Bare repository paths end in .git.
    name = Path(main_path).name
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return name or fallback


def project_from_encoded_path(jsonl_path: Path, projects_dir: Path) -> str:
    """Decode a Claude Code project name from a sessions JSONL path under projects_dir."""
    try:
        project_dir = jsonl_path.relative_to(projects_dir).parts[0]
    except (IndexError, ValueError):
        return "unknown"

    # Claude Code cuts encoded paths longer than 200 characters and appends
    # "-<hash>", so only a prefix of the last directory name survives.
    truncated = len(project_dir) > _ENCODED_LIMIT
    root, encoded = _encoded_path_root(_encode(project_dir[:_ENCODED_LIMIT]))
    if not encoded:
        return "unknown"

    slash_candidate = root.joinpath(*encoded.split("-"))
    if not truncated and "--" not in encoded and slash_candidate.is_dir():
        return slash_candidate.name or "unknown"

    existing_project = _existing_encoded_project_path(root, encoded, truncated)
    if existing_project is not None:
        return existing_project.name or "unknown"

    fallback = project_dir.removeprefix("-")
    return fallback or "unknown"


def _encode(name: str) -> str:
    # Claude Code encodes every non-alphanumeric character, including ".", "_",
    # "-" and non-ASCII letters, as "-". Its JavaScript regex works on UTF-16
    # code units, so a character outside the BMP (e.g. an emoji) becomes "--".
    return re.sub(r"[^A-Za-z0-9]", lambda match: "--" if ord(match[0]) > 0xFFFF else "-", name)


def _existing_encoded_project_path(current: Path, encoded: str, truncated: bool) -> Path | None:
    """Walk real directories whose encoded names spell out the encoded path."""
    try:
        entries = sorted(os.scandir(current), key=lambda entry: entry.name)
    except OSError:
        return None
    for entry in entries:
        name = _encode(entry.name)
        last = encoded == name or (truncated and name.startswith(encoded))
        if not last and not encoded.startswith(name + "-"):
            continue
        try:
            if not entry.is_dir():
                continue
        except OSError:
            continue
        if last:
            return Path(entry.path)
        rest = encoded[len(name) + 1 :]
        result = _existing_encoded_project_path(Path(entry.path), rest, truncated) if rest else None
        if result is not None:
            return result
    return None


def _encoded_path_root(encoded: str) -> tuple[Path, str]:
    """Return the filesystem root and the encoded path below it."""
    if os.sep == "\\":
        # Claude Code encodes "C:\Users\me" as "C--Users-me", so the drive
        # survives only as a bare letter followed by "--".
        match = re.match(r"([A-Za-z])--", encoded)
        if match:
            return Path(f"{match.group(1)}:{os.sep}"), encoded[match.end() :]
    return Path(os.sep), encoded.removeprefix("-")
