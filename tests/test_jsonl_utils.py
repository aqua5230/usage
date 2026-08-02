# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jsonl_utils import iter_jsonl_dicts


def test_iter_jsonl_dicts_returns_dicts_in_file_order(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    records = [{"id": 1}, {"id": 2, "name": "second"}]
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    assert list(iter_jsonl_dicts(path)) == records


def test_iter_jsonl_dicts_skips_empty_and_whitespace_lines(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text("\n  \n\t\n{\"kept\": true}\n\n", encoding="utf-8")

    assert list(iter_jsonl_dicts(path)) == [{"kept": True}]


def test_iter_jsonl_dicts_skips_invalid_json_and_continues(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text("{\"before\": 1}\n{\"broken\": }\n{\"after\": 2}\n", encoding="utf-8")

    assert list(iter_jsonl_dicts(path)) == [{"before": 1}, {"after": 2}]


def test_iter_jsonl_dicts_filters_non_object_json_values(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text("123\n\"text\"\n[1, 2]\n{\"kept\": true}\n", encoding="utf-8")

    assert list(iter_jsonl_dicts(path)) == [{"kept": True}]


def test_iter_jsonl_dicts_returns_empty_sequence_for_blank_file(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(" \n\t\n", encoding="utf-8")

    assert list(iter_jsonl_dicts(path)) == []


def test_iter_jsonl_dicts_replaces_invalid_utf8_when_requested(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_bytes(b'{"before": 1}\n\xff\n{"after": 2}\n')

    assert list(iter_jsonl_dicts(path, errors="replace")) == [{"before": 1}, {"after": 2}]


def test_iter_jsonl_dicts_raises_for_invalid_utf8_by_default(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_bytes(b'{"valid": true}\n\xff\n')

    with pytest.raises(UnicodeDecodeError):
        list(iter_jsonl_dicts(path))
