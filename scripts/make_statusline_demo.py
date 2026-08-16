#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""印出一份範例 statusLine，給 scripts/*.tape 錄 README 示範動圖用。

只呼叫 render()，不呼叫 save()——不會寫到真的 ~/.claude/usage-status.json。
語言看 TT_LANG 環境變數，跟 usage_statusline.py 讀的變數一致。
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import usage_statusline  # noqa: E402

_PAYLOAD = {
    "workspace": {"project_dir": str(_REPO_ROOT)},
    "model": {"display_name": "Opus 5"},
    "effort": {"level": "high"},
    "context_window": {
        "used_percentage": 23,
        "context_window_size": 1_000_000,
        "total_input_tokens": 180_000,
        "total_output_tokens": 12_000,
        "current_usage": {
            "input_tokens": 1200,
            "cache_creation_input_tokens": 300,
            "cache_read_input_tokens": 4567,
            "output_tokens": 890,
        },
    },
    "cost": {"total_cost_usd": 12.34, "total_duration_ms": 3_723_000},
}

if __name__ == "__main__":
    os.environ.setdefault("TT_LANG", "en")
    now = datetime.now(UTC)
    _PAYLOAD["rate_limits"] = {
        "five_hour": {"used_percentage": 88, "resets_at": now.timestamp() + 4 * 3600 + 23 * 60},
        "seven_day": {"used_percentage": 32, "resets_at": now.timestamp() + 5 * 86400 + 19 * 3600},
    }
    print(usage_statusline.render(_PAYLOAD, now))
