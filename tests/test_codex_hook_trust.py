from __future__ import annotations

import json
from pathlib import Path

import pytest

from installer import codex_hook_trust as trust
from installer import session_hooks


def install(tmp_path: Path, *, group: int = 0, handler: int = 0) -> tuple[Path, str]:
    path = session_hooks.CODEX_HOOKS_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    groups = [{"hooks": [{"command": "other"}]} for _ in range(group + 1)]
    groups[group]["hooks"] = [{"command": "other"} for _ in range(handler)] + [
        {"command": "python usage-terse-mode.py"}
    ]
    path.write_text(json.dumps({"hooks": {"SessionStart": groups}}), encoding="utf-8")
    return tmp_path / "codex" / "config.toml", f"{path}:session_start:{group}:{handler}"


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ('trusted_hash = "abc"', "trusted"),
        ('trusted_hash = "abc"\nenabled = false', "disabled"),
        ("enabled = true", "untrusted"),
        ('trusted_hash = ""', "untrusted"),
        ("trusted_hash = 42", "untrusted"),
    ],
)
def test_trust_record(tmp_path: Path, entry: str, expected: str) -> None:
    config, key = install(tmp_path, group=1, handler=0)
    config.write_text(f"[hooks.state.{json.dumps(key)}]\n{entry}\n", encoding="utf-8")
    assert trust.codex_terse_hook_trust() == expected


def test_exact_handler_index(tmp_path: Path) -> None:
    config, key = install(tmp_path, group=1, handler=1)
    config.write_text(f'[hooks.state.{json.dumps(key)}]\ntrusted_hash = "yes"\n', encoding="utf-8")
    assert trust.codex_terse_hook_trust() == "trusted"


def test_missing_record(tmp_path: Path) -> None:
    config, _ = install(tmp_path)
    config.write_text("", encoding="utf-8")
    assert trust.codex_terse_hook_trust() == "untrusted"


def test_missing_hook(tmp_path: Path) -> None:
    config, _ = install(tmp_path)
    session_hooks.CODEX_HOOKS_JSON.write_text('{"hooks": {"SessionStart": []}}', encoding="utf-8")
    assert trust.codex_terse_hook_trust() == "not_installed"
    assert not config.exists()


@pytest.mark.parametrize("raw", ["bad [", "\xff"])
def test_broken_config(tmp_path: Path, raw: str) -> None:
    config, _ = install(tmp_path)
    config.write_bytes(raw.encode("latin-1"))
    assert trust.codex_terse_hook_trust() == "unknown"


def test_unreadable_files(tmp_path: Path) -> None:
    assert trust.codex_terse_hook_trust() == "unknown"
    install(tmp_path)
    assert trust.codex_terse_hook_trust() == "unknown"
    session_hooks.CODEX_HOOKS_JSON.write_text("broken", encoding="utf-8")
    assert trust.codex_terse_hook_trust() == "unknown"


def test_realpath_fallback(tmp_path: Path) -> None:
    config, key = install(tmp_path)
    alternate = key.replace("/hooks.json:", "/./hooks.json:")
    config.write_text(
        f'[hooks.state.{json.dumps(alternate)}]\ntrusted_hash = "yes"\n', encoding="utf-8"
    )
    assert trust.codex_terse_hook_trust() == "trusted"


def test_different_path_is_not_trusted(tmp_path: Path) -> None:
    config, key = install(tmp_path)
    other_key = key.replace("hooks.json", "other.json")
    config.write_text(
        f'[hooks.state.{json.dumps(other_key)}]\ntrusted_hash = "yes"\n',
        encoding="utf-8",
    )
    assert trust.codex_terse_hook_trust() == "untrusted"
