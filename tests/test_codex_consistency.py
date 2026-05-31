from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

import codex_loader
from adapters import codex as codex_adapter

FIXTURE = Path(__file__).parent / "fixtures" / "codex_session_golden.jsonl"


@pytest.fixture(autouse=True)
def _clear_loader_caches() -> None:
    codex_loader._jsonl_cache.clear()
    codex_adapter._file_cache.clear()


def _sum_field(entries: Sequence[object], field: str) -> int:
    return sum(int(getattr(entry, field)) for entry in entries)


def test_codex_session_token_totals_match_between_delta_and_session_loaders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    shutil.copyfile(FIXTURE, sessions_dir / FIXTURE.name)

    monkeypatch.setattr(codex_loader, "SESSIONS_DIR", sessions_dir)
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
