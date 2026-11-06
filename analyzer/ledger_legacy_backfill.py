# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Restore dimensions of total-only ledger days from read-only Codex state."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import TYPE_CHECKING

from loaders import codex_loader

from .ledger_backfill import _allocate

if TYPE_CHECKING:
    from .reporter import _YearDay

logger = logging.getLogger(__name__)


def backfill_days(days: dict[str, _YearDay]) -> bool:
    """Mutate eligible days only after a successful source read; report changes."""
    eligible = {
        key: day
        for key, day in days.items()
        if day["total_tokens"] > 0 and all(tokens == 0 for tokens in day["agent_tokens"].values())
    }
    if not eligible:
        return False
    try:
        with closing(
            sqlite3.connect(codex_loader._readonly_sqlite_uri(codex_loader.STATE_DB), uri=True)
        ) as connection:
            rows = connection.execute(
                "SELECT created_at, tokens_used, model, cwd FROM threads WHERE tokens_used > 0"
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        logger.warning("Legacy ledger backfill could not read %s: %s", codex_loader.STATE_DB, exc)
        return False

    models: dict[str, dict[str, int]] = {key: {} for key in eligible}
    projects: dict[str, dict[str, int]] = {key: {} for key in eligible}
    for created_at, tokens, model, cwd in rows:
        if not isinstance(created_at, int | float) or not isinstance(tokens, int) or tokens <= 0:
            logger.warning("Legacy ledger backfill skipped invalid thread counts or timestamp")
            continue
        try:
            day_key = datetime.fromtimestamp(created_at).date().isoformat()
        except (OSError, OverflowError, ValueError):
            logger.warning("Legacy ledger backfill skipped invalid thread timestamp %r", created_at)
            continue
        if day_key not in eligible:
            continue
        model = model if isinstance(model, str) and model else "unknown"
        project = codex_loader._project_from_cwd(cwd) if isinstance(cwd, str) and cwd else "unknown"
        models[day_key][model] = models[day_key].get(model, 0) + tokens
        projects[day_key][project] = projects[day_key].get(project, 0) + tokens

    for day_key, day in eligible.items():
        source_total = sum(models[day_key].values())
        codex_tokens = min(source_total, day["total_tokens"])
        unknown_tokens = day["total_tokens"] - codex_tokens
        day["agent_tokens"] = {"codex": codex_tokens} if codex_tokens else {}
        day["model_tokens"] = (
            dict(_allocate(models[day_key], {}, codex_tokens)) if codex_tokens else {}
        )
        day["project_tokens"] = (
            dict(_allocate(projects[day_key], {}, codex_tokens)) if codex_tokens else {}
        )
        if unknown_tokens:
            for dimension in (day["agent_tokens"], day["model_tokens"], day["project_tokens"]):
                dimension["unknown"] = dimension.get("unknown", 0) + unknown_tokens
    return True
