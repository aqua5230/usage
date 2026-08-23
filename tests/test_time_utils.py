# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from usage_common.time_utils import parse_iso8601_utc_or_raise, parse_optional_iso8601_utc


def test_parse_optional_iso8601_utc_accepts_z_suffix() -> None:
    assert parse_optional_iso8601_utc("2026-08-02T01:02:03Z") == datetime(
        2026, 8, 2, 1, 2, 3, tzinfo=UTC
    )


def test_parse_optional_iso8601_utc_converts_offset_to_utc() -> None:
    assert parse_optional_iso8601_utc("2026-08-02T09:02:03+08:00") == datetime(
        2026, 8, 2, 1, 2, 3, tzinfo=UTC
    )


def test_parse_optional_iso8601_utc_treats_naive_value_as_utc() -> None:
    assert parse_optional_iso8601_utc("2026-08-02T01:02:03") == datetime(
        2026, 8, 2, 1, 2, 3, tzinfo=UTC
    )


@pytest.mark.parametrize("value", [None, 123, datetime(2026, 8, 2, 1, 2, 3)])
def test_parse_optional_iso8601_utc_rejects_non_string_values(value: object) -> None:
    assert parse_optional_iso8601_utc(value) is None


def test_parse_optional_iso8601_utc_rejects_empty_string() -> None:
    assert parse_optional_iso8601_utc("") is None


def test_parse_optional_iso8601_utc_rejects_malformed_string() -> None:
    assert parse_optional_iso8601_utc("not-a-date") is None


def test_parse_iso8601_utc_or_raise_returns_utc_datetime() -> None:
    assert parse_iso8601_utc_or_raise("2026-08-02T09:02:03+08:00") == datetime(
        2026, 8, 2, 1, 2, 3, tzinfo=UTC
    )


def test_parse_iso8601_utc_or_raise_raises_for_malformed_string() -> None:
    with pytest.raises(ValueError):
        parse_iso8601_utc_or_raise("not-a-date")
