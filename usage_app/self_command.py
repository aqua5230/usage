# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Build commands for short-lived workers in source and bundled apps."""

from __future__ import annotations

import sys
from pathlib import Path


def self_command_argv(command: str, args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return [sys.executable, command, *args]
    module = "cli" if command == "status" else command
    arguments = ",".join(repr(arg) for arg in ["usage", command, *args])
    invocation = f"from usage_app import {module};sys.argv=[{arguments}];"
    invocation += "cli.main()" if command == "status" else f"sys.exit({module}.main(sys.argv[2:]))"
    if getattr(sys, "frozen", False):
        resources = str(Path(sys.executable).resolve().parent.parent / "Resources")
        major, minor = sys.version_info[:2]
        bootstrap = (
            f"import sys;sys.path[:0]=[{resources!r}+'/lib/python{major}{minor}.zip',"
            f"{resources!r}+'/lib/python{major}.{minor}',"
            f"{resources!r}+'/lib/python{major}.{minor}/lib-dynload',{resources!r}];" + invocation
        )
        return [
            "/usr/bin/env",
            f"PYTHONHOME={resources}",
            f"RESOURCEPATH={resources}",
            sys.executable,
            "-c",
            bootstrap,
        ]
    root = str(Path(__file__).resolve().parent.parent)
    return [
        sys.executable,
        "-c",
        f"import sys;sys.path.insert(0,{root!r});" + invocation,
    ]
