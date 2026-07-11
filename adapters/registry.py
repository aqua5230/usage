# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from .types import AgentInfo
from . import agy, claude, codex


def detect_agents() -> list[AgentInfo]:
    agents: list[AgentInfo] = []
    for detector in [claude.detect, codex.detect, agy.detect]:
        info = detector()
        if info:
            agents.append(info)
    return agents
