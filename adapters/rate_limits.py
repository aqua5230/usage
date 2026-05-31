import json
import math
import os
from datetime import datetime, timezone
from typing import Any

from .types import RateLimits

STATUS_FILE = os.path.expanduser("~/.claude/usage-status.json")
LEGACY_STATUS_FILE = os.path.expanduser("~/.claude/usag-status.json")
TT_STATUS_FILE = os.path.expanduser("~/.claude/tt-status.json")


def _as_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _read_status() -> dict[str, Any] | None:
    for path in (STATUS_FILE, LEGACY_STATUS_FILE, TT_STATUS_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
                return data
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
    return None


def load_rate_limits() -> RateLimits | None:
    data = _read_status()
    if data is None:
        return None

    rl = data.get("rate_limits") or {}
    five = rl.get("five_hour") or {}
    seven = rl.get("seven_day") or {}

    now_ts = datetime.now(timezone.utc).timestamp()
    five_pct = _as_finite_float(five.get("used_percentage"))
    five_reset = _as_finite_float(five.get("resets_at"))
    if five_reset and five_reset < now_ts:
        five_pct = 0.0

    seven_pct = _as_finite_float(seven.get("used_percentage"))
    seven_reset = _as_finite_float(seven.get("resets_at"))
    if seven_reset and seven_reset < now_ts:
        seven_pct = 0.0

    model_info = data.get("model") or {}
    model_name = model_info.get("display_name") or model_info.get("id") or ""

    if five_pct is None and seven_pct is None and not model_name:
        return None

    return RateLimits(
        five_hour_pct=five_pct,
        five_hour_resets_at=int(five_reset) if five_reset is not None else None,
        seven_day_pct=seven_pct,
        seven_day_resets_at=int(seven_reset) if seven_reset is not None else None,
        model=model_name,
        updated_at=data.get("_received_at", ""),
    )
