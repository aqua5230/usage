# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

from loaders import muse_loader
from loaders.history_loader import UsageEntry as MuseUsageEntry

from i18n import t

from .types import AgentInfo, UsageEntry


def detect() -> AgentInfo | None:
    if muse_loader.session_paths():
        return AgentInfo(
            id="muse",
            name=t("muse_name"),
            data_dir=str(muse_loader.MUSE_SESSIONS_DIR),
            installed=True,
        )
    return None


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    return [_to_usage_entry(entry) for entry in muse_loader.load_entries(hours_back)]


def _to_usage_entry(entry: MuseUsageEntry) -> UsageEntry:
    return UsageEntry(
        timestamp=entry.timestamp,
        session_id=entry.session_id,
        message_id=entry.message_id,
        request_id=entry.request_id,
        model=entry.model,
        input_tokens=entry.input_tokens,
        output_tokens=entry.output_tokens,
        cache_creation_tokens=entry.cache_creation_tokens,
        cache_read_tokens=entry.cache_read_tokens,
        cost_usd=entry.cost_usd,
        project=entry.project,
        agent_id="muse",
    )
