# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import usage_common.usage_logging as usage_logging


@pytest.fixture
def isolated_root_logger() -> Iterator[logging.Logger]:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    root_logger.handlers.clear()
    try:
        yield root_logger
    finally:
        for handler in root_logger.handlers:
            handler.close()
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)
        root_logger.setLevel(original_level)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_parse_debug_flags_without_a_value_disables_debug(raw: str | None) -> None:
    assert usage_logging.parse_debug_flags(raw) == (False, [])


@pytest.mark.parametrize("raw", ["1", "all", "ALL", "*"])
def test_parse_debug_flags_global_values_enable_debug(raw: str) -> None:
    assert usage_logging.parse_debug_flags(raw) == (True, [])


def test_parse_debug_flags_trims_subsystem_names() -> None:
    assert usage_logging.parse_debug_flags("codex_loader, pricing") == (
        False,
        ["codex_loader", "pricing"],
    )


def test_parse_debug_flags_is_case_insensitive() -> None:
    assert usage_logging.parse_debug_flags("Codex_Loader") == (False, ["codex_loader"])


def test_setup_logging_rotates_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_root_logger: logging.Logger
) -> None:
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(usage_logging, "LOG_DIR", log_dir)
    monkeypatch.setattr(usage_logging, "MAX_BYTES", 128)
    monkeypatch.setenv("USAGE_DEBUG", "1")

    usage_logging.setup_logging()
    logger = logging.getLogger("usage_logging.rotation")
    for _ in range(10):
        logger.debug("x" * 128)
    for handler in isolated_root_logger.handlers:
        handler.flush()

    backups = list(log_dir.glob(f"{usage_logging.LOG_FILENAME}.*"))
    assert backups
    assert len(backups) <= usage_logging.BACKUP_COUNT
    if sys.platform != "win32":  # POSIX file modes; Windows chmod only toggles the read-only bit
        assert log_dir.stat().st_mode & 0o777 == 0o700
        assert (log_dir / usage_logging.LOG_FILENAME).stat().st_mode & 0o777 == 0o600
        assert all(backup.stat().st_mode & 0o777 == 0o600 for backup in backups)


def test_setup_logging_keeps_console_when_directory_creation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_root_logger: logging.Logger
) -> None:
    monkeypatch.setattr(usage_logging, "LOG_DIR", tmp_path)
    console_handler = logging.StreamHandler()
    isolated_root_logger.addHandler(console_handler)

    def fail_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("blocked")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    usage_logging.setup_logging()

    assert console_handler in isolated_root_logger.handlers
