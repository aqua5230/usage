# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Shared paths for Codex's local data directory."""

from __future__ import annotations

import os
from pathlib import Path


def codex_home() -> Path:
    """Return Codex's configured home directory."""
    configured_home = os.environ.get("CODEX_HOME")
    if configured_home:
        return Path(configured_home)
    return Path(os.path.expanduser("~/.codex"))
