# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

from loaders import grok_loader as shared_grok_loader
from loaders.history_loader import UsageEntry as GrokUsageEntry

from i18n import t

from .types import AgentInfo, UsageEntry


def detect() -> AgentInfo | None:
    log_path = shared_grok_loader.GROK_LOG_PATH
    if log_path.is_file():
        return AgentInfo(
            id="grok",
            name=t("grok_name"),
            data_dir=str(log_path),
            installed=True,
        )
    return None


def load_entries(hours_back: int = 0) -> list[UsageEntry]:
    return [_to_usage_entry(entry) for entry in shared_grok_loader.load_entries(hours_back)]


def _to_usage_entry(entry: GrokUsageEntry) -> UsageEntry:
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
        agent_id="grok",
    )
