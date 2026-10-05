"""Read Codex's approval record without granting hook trust."""

from __future__ import annotations

import json
import os
import tomllib

from installer import session_hooks
from loaders.codex_paths import codex_home


def codex_terse_hook_trust() -> str:
    """Return the usage SessionStart hook's trust state.

    A trusted_hash alone cannot detect Modified (a hook edited after approval).
    Codex remains responsible for verifying the hash and asking for approval.
    """
    path = session_hooks.CODEX_HOOKS_JSON
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return "unknown"
        groups = session_hooks._codex_session_start_list(data)
        if groups is None:
            return "not_installed"
        index = None
        for group_index, group in enumerate(groups):
            handlers = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(handlers, list):
                continue
            for handler_index, handler in enumerate(handlers):
                command = handler.get("command") if isinstance(handler, dict) else None
                if isinstance(command, str) and session_hooks._TERSE_MARKER in command:
                    index = (group_index, handler_index)
                    break
            if index is not None:
                break
        if index is None:
            return "not_installed"
        with (codex_home() / "config.toml").open("rb") as handle:
            config = tomllib.load(handle)
        hooks = config.get("hooks", {})
        states = hooks.get("state", {}) if isinstance(hooks, dict) else {}
        if not isinstance(states, dict):
            return "unknown"
        suffix = f":session_start:{index[0]}:{index[1]}"
        entry = states.get(f"{path}{suffix}")
        if entry is None:
            entry = next(
                (
                    value
                    for key, value in states.items()
                    if key.endswith(suffix)
                    and os.path.realpath(key[: -len(suffix)]) == os.path.realpath(path)
                ),
                {},
            )
        if not isinstance(entry, dict):
            return "untrusted"
        if entry.get("enabled") is False:
            return "disabled"
        trusted_hash = entry.get("trusted_hash")
        return "trusted" if isinstance(trusted_hash, str) and trusted_hash else "untrusted"
    except (OSError, UnicodeError, ValueError):
        return "unknown"
