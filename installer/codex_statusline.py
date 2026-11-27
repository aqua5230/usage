# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Install usage as Codex's MCP status line provider (Codex 0.172+, macOS and Windows).

Three edits to ~/.codex/config.toml, each validated to touch only its own key:
an `[mcp_servers.usage-statusline]` table that runs the deployed provider, the
experimental `features.tui_extensions_statusline` flag, and
`tui.status_line_provider` selecting it. The built-in `tui.status_line` items stay
as Codex's fallback when the provider fails.

A provider or a disabled flag the user chose is never overwritten. The flag is
removed on uninstall only when usage added it, which a sidecar records.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from installer import setup_hook
from loaders.codex_paths import codex_home
from usage_common.cli_lookup import cli_env, resolve_cli
from usage_common.subprocess_utils import hidden_console_kwargs

SERVER = "usage-statusline"
TOOL = "statusline"
TABLE = f"mcp_servers.{SERVER}"
FEATURE = "tui_extensions_statusline"
MIN_CODEX_VERSION = (0, 172, 0)
PYTHON = "/usr/bin/python3"
PROVIDER_TARGET = codex_home() / "usage-statusline-codex.py"
PROVIDER_STATE = codex_home() / "usage-statusline-provider.json"
_SELECTION_LINE = f'status_line_provider = {{ server = "{SERVER}", tool = "{TOOL}" }}'
_SELECTION_REGEX = re.compile(r"(?m)^[ \t]*status_line_provider[ \t]*=[^\n]*(?:\n|$)")
_FEATURE_REGEX = re.compile(rf"(?m)^[ \t]*{FEATURE}[ \t]*=[^\n]*(?:\n|$)")


def _resolve_source() -> Path | None:
    paths = [
        Path(__file__).resolve().parent.parent / "usage_hooks" / "usage_statusline_codex.py",
        Path(sys.executable).resolve().parent.parent / "Resources" / "usage_statusline_codex.py",
    ]
    return next((path for path in paths if path.is_file()), None)


def codex_version() -> tuple[int, ...] | None:
    executable = resolve_cli(
        "codex", ("/opt/homebrew/bin/codex", "/usr/local/bin/codex", "~/.local/bin/codex")
    )
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            env=cli_env(executable),
            check=False,
            **hidden_console_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
    return tuple(int(part) for part in match.groups()) if match else None


def _resolve_python() -> str | None:
    if sys.platform == "darwin":
        return PYTHON
    if sys.platform == "win32":
        try:
            return setup_hook._find_system_python()
        except SystemExit:
            return None
    return None


def _server_lines(python: str) -> str:
    args = json.dumps(["-u", str(PROVIDER_TARGET)], ensure_ascii=False)
    return (
        f"[{TABLE}]\n"
        f"command = {json.dumps(python)}\n"
        f"args = {args}\n"
        # Codex forwards only a fixed set of variables (LANG among them) to MCP servers.
        'env_vars = ["USAGE_LANG", "TT_LANG", "CODEX_HOME"]\n'
    )


def _expected_server(python: str) -> dict[str, Any]:
    return dict(tomllib.loads(_server_lines(python))["mcp_servers"][SERVER])


def _selection(parsed: dict[str, Any]) -> object:
    tui = parsed.get("tui")
    return tui.get("status_line_provider") if isinstance(tui, dict) else None


def _is_our_selection(value: object) -> bool:
    return value == {"server": SERVER, "tool": TOOL}


def _server(parsed: dict[str, Any]) -> object:
    servers = parsed.get("mcp_servers")
    return servers.get(SERVER) if isinstance(servers, dict) else None


def _is_our_server(value: object) -> bool:
    """A server table runs usage's provider when it launches the deployed script."""
    if not isinstance(value, dict):
        return False
    args = value.get("args")
    return isinstance(args, list) and any(
        isinstance(arg, str) and Path(arg).name == PROVIDER_TARGET.name for arg in args
    )


def _feature(parsed: dict[str, Any]) -> object:
    features = parsed.get("features")
    return features.get(FEATURE) if isinstance(features, dict) else None


def _is_installed(parsed: dict[str, Any], python: str) -> bool:
    return (
        _is_our_selection(_selection(parsed))
        and _server(parsed) == _expected_server(python)
        and _feature(parsed) is True
    )


def _parse(content: str) -> dict[str, Any] | None:
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None


def _remove_table(content: str, name: str, parent: str, key: str) -> str:
    """Drop table ``name`` through its last key line.

    Comments after that line sit above the next table and belong to it, so they stay.
    """
    table = setup_hook._find_table(content, name)
    if table is None:
        return content
    start, end = setup_hook._table_section(content, table)
    lines = content[start:end].splitlines(keepends=True)
    last = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            last = index + 1
    cut = start + sum(len(line) for line in lines[:last])
    rest = content[cut:].lstrip("\n")
    head = content[: table.start()]
    candidate = head + rest if rest else head.rstrip("\n") + "\n"
    return setup_hook._validated_table_edit(content, candidate, parent, key)


def _add_server_table(content: str, python: str) -> str:
    candidate = content.rstrip() + "\n\n" + _server_lines(python)
    return setup_hook._validated_table_edit(content, candidate, "mcp_servers", SERVER)


def _read_state() -> dict[str, Any]:
    try:
        data = json.loads(PROVIDER_STATE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def is_setup() -> bool:
    """Whether Codex is configured to draw usage's provider."""
    python = _resolve_python()
    return python is not None and _is_setup(python)


def _is_setup(python: str) -> bool:
    result = setup_hook._read_codex_config()
    return result is not None and PROVIDER_TARGET.is_file() and _is_installed(result[1], python)


def script_is_stale() -> bool:
    source = _resolve_source()
    if source is None:
        return False
    if not PROVIDER_TARGET.is_file():
        return True
    return PROVIDER_TARGET.read_bytes() != source.read_bytes()


def setup() -> bool:
    """Install or refresh the provider; False when skipped or not fully applied.

    All three edits land together or not at all: a server without the selection, or a
    selection without the flag, leaves Codex's footer broken or the edit half done.
    """
    python = _resolve_python()
    if python is None:
        return False
    result = setup_hook._read_codex_config()
    source = _resolve_source()
    if result is None or source is None:
        return False
    content, parsed = result
    selection, feature, server = _selection(parsed), _feature(parsed), _server(parsed)
    # The user's own provider, Codex's default footer, a disabled flag, or a server of
    # theirs that happens to share the name.
    if (selection is not None and not _is_our_selection(selection)) or feature is False:
        return False
    if server is not None and not _is_our_server(server):
        return False

    updated = content
    if server != _expected_server(python):
        updated = _add_server_table(_remove_table(updated, TABLE, "mcp_servers", SERVER), python)
    if feature is None:
        updated = setup_hook._insert_table_line(updated, "features", f"{FEATURE} = true")
    if selection is None:
        updated = setup_hook._insert_table_line(updated, "tui", _SELECTION_LINE)
    final = _parse(updated)
    if final is None or not _is_installed(final, python):
        return False
    version = codex_version()
    if version is None or version < MIN_CODEX_VERSION:
        return False

    try:
        if script_is_stale():
            PROVIDER_TARGET.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, PROVIDER_TARGET)
            PROVIDER_TARGET.chmod(PROVIDER_TARGET.stat().st_mode | stat.S_IXUSR)
        if updated != content:
            setup_hook._atomic_write_text(setup_hook.CODEX_CONFIG, updated)
        # Recorded only once the flag is really in the config, so uninstall never
        # removes a flag the user turned on.
        if feature is None:
            setup_hook._atomic_write_text(PROVIDER_STATE, json.dumps({"added_feature": True}))
        elif server is None:
            PROVIDER_STATE.unlink(missing_ok=True)
    except OSError:
        return False
    return _is_setup(python)


def unsetup() -> bool:
    """Remove usage's provider from the Codex config; the deployed script stays.

    Codex reads its config at startup, so deleting the script would break a session
    that is launching; an unreferenced copy costs nothing.
    """
    result = setup_hook._read_codex_config()
    if result is None:
        return False
    content, parsed = result
    server = _server(parsed)
    ours_server = _is_our_server(server)
    ours_selected = _is_our_selection(_selection(parsed)) and (server is None or ours_server)
    if not ours_selected and not ours_server:
        return False

    updated = content
    if ours_selected:
        updated = _remove_table(updated, "tui.status_line_provider", "tui", "status_line_provider")
        updated = setup_hook._remove_table_line(
            updated, "tui", _SELECTION_REGEX, "status_line_provider"
        )
    if ours_server:
        updated = _remove_table(updated, TABLE, "mcp_servers", SERVER)
    final = _parse(updated)
    # Removing the server but not the selection would leave Codex pointing at nothing.
    if final is None or _is_our_selection(_selection(final)) or _is_our_server(_server(final)):
        return False
    # The flag goes too when usage added it, unless another MCP provider now uses it.
    if (
        _read_state().get("added_feature") is True
        and _feature(final) is True
        and not isinstance(_selection(final), dict)
    ):
        updated = setup_hook._remove_table_line(updated, "features", _FEATURE_REGEX, FEATURE)
    try:
        setup_hook._atomic_write_text(setup_hook.CODEX_CONFIG, updated)
        PROVIDER_STATE.unlink(missing_ok=True)
    except OSError:
        return False
    return True
