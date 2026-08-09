# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import importlib
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

import codex_loader
from adapters import codex as codex_adapter

FIXTURE = Path(__file__).parent / "fixtures" / "codex_session_golden.jsonl"


@pytest.fixture(autouse=True)
def _clear_loader_caches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    codex_loader._jsonl_cache.clear()
    codex_adapter._file_cache.clear()
    # Keep the loader away from the developer's real ~/.codex and ~/.usage:
    # the archived-sessions dir and the JSONL disk cache would otherwise leak
    # real entries into assertions on machines with usage history.
    monkeypatch.setattr(
        codex_loader, "ARCHIVED_SESSIONS_DIR", tmp_path / "archived_sessions"
    )
    monkeypatch.setattr(
        codex_loader, "JSONL_CACHE_PATH", tmp_path / "codex_jsonl_cache.json"
    )
    monkeypatch.setattr(codex_loader, "_disk_cache_seeded", True)


def _sum_field(entries: Sequence[object], field: str) -> int:
    return sum(int(getattr(entry, field)) for entry in entries)


def test_codex_paths_follow_codex_home_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom_home = tmp_path / "custom-codex"
    monkeypatch.setenv("CODEX_HOME", str(custom_home))
    importlib.reload(codex_loader)
    importlib.reload(codex_adapter)

    assert codex_loader.SESSIONS_DIR == custom_home / "sessions"
    assert codex_loader.ARCHIVED_SESSIONS_DIR == custom_home / "archived_sessions"
    assert codex_loader.STATE_DB == custom_home / "state_5.sqlite"
    assert codex_loader.LOGS_DB == custom_home / "logs_2.sqlite"
    assert codex_adapter.CODEX_DIR == str(custom_home)
    assert codex_adapter.SESSIONS_DIR == str(custom_home / "sessions")
    assert codex_adapter.STATE_DB == str(custom_home / "state_5.sqlite")

    monkeypatch.delenv("CODEX_HOME")
    importlib.reload(codex_loader)
    importlib.reload(codex_adapter)

    default_home = Path(os.path.expanduser("~/.codex"))
    assert codex_loader.SESSIONS_DIR == default_home / "sessions"
    assert codex_adapter.CODEX_DIR == str(default_home)


def test_codex_session_token_totals_match_between_delta_and_session_loaders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    shutil.copyfile(FIXTURE, sessions_dir / FIXTURE.name)

    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(codex_loader, "LOGS_DB", tmp_path / "missing-logs.sqlite")
    monkeypatch.setattr(codex_adapter, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(codex_loader, "_load_thread_models", lambda: {})
    monkeypatch.setattr(codex_adapter, "_load_thread_models", lambda: {})

    delta_entries = codex_loader.load_entries(0)
    session_entries = codex_adapter.load_entries(0)

    assert len(delta_entries) == 4
    assert len(session_entries) == 1

    # These fields are intentionally not compared:
    # project/model are resolved by different functions, session_id/message_id
    # have different shapes, and cache_creation_tokens is a known design
    # difference because codex_loader does not track it.
    for field in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "total_tokens",
    ):
        assert _sum_field(delta_entries, field) == _sum_field(session_entries, field)
