# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import agy_loader as shared_agy_loader

from i18n import t

from .types import AgentInfo, UsageEntry

# Source: tokscale's aliases.rs. Keep unknown Antigravity model IDs unchanged
# so pricing's existing fallback can handle them.
_MODEL_ALIASES = {
    "gemini-3-flash-a": "gemini-3-flash-preview",
    "gemini-3-flash-c": "gemini-3-flash-preview",
    "gemini-3-flash": "gemini-3-flash-preview",
    "gemini-3.1-pro-high": "gemini-3.1-pro",
    "gemini-3.1-pro-low": "gemini-3.1-pro",
    "gemini-3-pro-high": "gemini-3-pro",
    "gemini-3-pro-low": "gemini-3-pro",
}


def detect() -> AgentInfo | None:
    sessions_dir = shared_agy_loader.AGY_SESSIONS_DIR
    if sessions_dir.is_dir():
        return AgentInfo(
            id="antigravity",
            name=t("agy_name"),
            data_dir=str(sessions_dir),
            installed=True,
        )
    return None


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    result = shared_agy_loader.load_entries_with_stats(hours_back)
    return [_to_usage_entry(entry) for entry in result.entries]


def _to_usage_entry(entry: shared_agy_loader.AgyUsageEntry) -> UsageEntry:
    return UsageEntry(
        timestamp=entry.timestamp,
        session_id=entry.session_id,
        message_id=entry.dedup_key,
        request_id="",
        model=_normalize_model(entry.model),
        input_tokens=entry.input_tokens,
        # Match Codex's existing convention: only its reported output tokens
        # are attributed to UsageEntry.output_tokens; separate reasoning data
        # is not added here.
        output_tokens=entry.output_tokens,
        cache_creation_tokens=0,
        cache_read_tokens=entry.cache_read_tokens,
        cost_usd=None,
        project="unknown",
        agent_id="antigravity",
    )


def _normalize_model(model: str) -> str:
    return _MODEL_ALIASES.get(model.lower(), model)
