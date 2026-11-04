# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

"""Resolve local CLIs and preserve their sibling runtime in subprocess PATH."""

from __future__ import annotations

import glob
import os
import re
import shutil
import sys
from collections.abc import Mapping, Sequence

_MANAGER_PATHS = (
    "~/.volta/bin",
    "~/.local/share/mise/shims",
    "~/.asdf/shims",
    "~/.local/share/fnm/aliases/default/bin",
    "~/Library/Application Support/fnm/aliases/default/bin",
    "~/.bun/bin",
    "~/Library/pnpm",
    "~/.npm-global/bin",
)


def resolve_cli(name: str, fallbacks: Sequence[str]) -> str | None:
    """Search PATH, caller fallbacks, then Unix version managers in order."""
    found = shutil.which(name)
    if found is not None:
        return found
    for candidate in fallbacks:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    if sys.platform == "win32":
        return None
    candidates = [os.path.join(directory, name) for directory in _MANAGER_PATHS]
    versions: list[tuple[tuple[int, ...], str]] = []
    for directory in glob.glob(os.path.expanduser("~/.nvm/versions/node/*")):
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", os.path.basename(directory))
        if match is not None:
            versions.append((tuple(int(part) for part in match.groups()), directory))
    candidates.extend(
        os.path.join(directory, "bin", name) for _, directory in sorted(versions, reverse=True)
    )
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    return None


def cli_env(executable: str, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy the environment and prepend the CLI directory on Unix."""
    env = dict(os.environ if base is None else base)
    if sys.platform != "win32":
        directory = os.path.dirname(executable)
        path = env.get("PATH", "")
        if directory and path.split(os.pathsep)[0] != directory:
            env["PATH"] = directory + (os.pathsep + path if path else "")
    return env
