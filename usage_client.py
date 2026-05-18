from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

STATUS_FILE = os.path.expanduser("~/.claude/usage-status.json")
LEGACY_STATUS_FILE = os.path.expanduser("~/.claude/usag-status.json")
TT_STATUS_FILE = os.path.expanduser("~/.claude/tt-status.json")

# 檔案多久沒更新就視為 stale；只用在訊息提示，不影響數字顯示
STALE_SECONDS = 6 * 3600


class PollState(StrEnum):
    LOADING = "loading"
    SUCCESS = "success"
    TOKEN_ERROR = "token_error"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMITED = "rate_limited"
    FATAL = "fatal"


@dataclass(slots=True)
class UsageSnapshot:
    current_percent: int
    current_reset_at: float
    weekly_percent: int
    weekly_reset_at: float
    current_status: str
    polled_at: float


@dataclass(slots=True)
class PollOutcome:
    state: PollState
    snapshot: UsageSnapshot | None = None
    message: str | None = None


def _pct(value: Any) -> int:
    numeric = _as_finite_float(value)
    if numeric is None:
        return 0
    return max(0, min(100, round(numeric)))


def _reset_at(value: Any, default: float) -> float:
    numeric = _as_finite_float(value)
    if numeric is None:
        return default
    return numeric


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _read_status_file() -> tuple[dict[str, Any], str] | None:
    """讀任一份可用的 status JSON，優先 usage 自己的，fallback 舊檔與 token-tracker。"""
    for path in (STATUS_FILE, LEGACY_STATUS_FILE, TT_STATUS_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data, path
    return None


def _build_snapshot(data: dict[str, Any]) -> UsageSnapshot | None:
    rl = _as_dict(data.get("rate_limits"))
    five = _as_dict(rl.get("five_hour"))
    seven = _as_dict(rl.get("seven_day"))

    five_pct_raw = five.get("used_percentage")
    seven_pct_raw = seven.get("used_percentage")
    if five_pct_raw is None and seven_pct_raw is None:
        return None

    now = time.time()
    five_reset = _reset_at(five.get("resets_at"), now)
    seven_reset = _reset_at(seven.get("resets_at"), now)

    # reset 時間到了就把百分比歸零（跟 token-tracker 同邏輯）
    five_pct = 0 if five_reset and five_reset < now else _pct(five_pct_raw)
    seven_pct = 0 if seven_reset and seven_reset < now else _pct(seven_pct_raw)

    polled_at = _as_finite_float(data.get("_received_at_ts")) or now

    status = ""
    if isinstance(rl.get("status"), str):
        status = rl["status"]

    return UsageSnapshot(
        current_percent=five_pct,
        current_reset_at=five_reset,
        weekly_percent=seven_pct,
        weekly_reset_at=seven_reset,
        current_status=status,
        polled_at=polled_at,
    )


class ClaudeUsageClient:
    """從 Claude Code statusLine hook 寫的本地 JSON 讀取配額狀態。

    保留 async 介面、interval_seconds 參數，方便沿用既有 polling 迴圈
    （即使讀檔不需要等，main loop 還是會以 interval 為節奏更新 UI）。
    """

    def __init__(self, *, interval_seconds: int = 60, mock: bool = False) -> None:
        self.interval_seconds = interval_seconds
        self.mock = mock

    async def aclose(self) -> None:
        return None

    async def fetch_once(self) -> PollOutcome:
        if self.mock:
            return self._mock_outcome()

        result = _read_status_file()
        if result is None:
            return PollOutcome(
                state=PollState.TOKEN_ERROR,
                message="⚠ 找不到狀態檔，請執行 `python3 main.py --setup` 並打開一次 Claude Code",
            )

        data, source_path = result
        snapshot = _build_snapshot(data)
        if snapshot is None:
            return PollOutcome(
                state=PollState.LOADING,
                message="⚠ 狀態檔尚無配額資料，等 Claude Code 再刷新一次 statusLine",
            )

        now = time.time()
        is_stale = (now - snapshot.polled_at) > STALE_SECONDS
        source_tag = "tt-status" if source_path == TT_STATUS_FILE else "usage"
        message = f"✓ 已同步（{source_tag}）"
        if is_stale:
            mins = int((now - snapshot.polled_at) / 60)
            message = f"⚠ 狀態檔已 {mins} 分鐘未更新，數字可能過時"

        return PollOutcome(state=PollState.SUCCESS, snapshot=snapshot, message=message)

    def _mock_outcome(self) -> PollOutcome:
        now = time.time()
        return PollOutcome(
            state=PollState.SUCCESS,
            snapshot=UsageSnapshot(
                current_percent=50,
                current_reset_at=now + 82 * 60,
                weekly_percent=11,
                weekly_reset_at=now + ((6 * 24) + 8) * 3600,
                current_status="ok",
                polled_at=now,
            ),
            message="✓ 已同步",
        )
