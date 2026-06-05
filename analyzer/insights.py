from __future__ import annotations

from datetime import date
from math import sqrt
from typing import Any, cast

INSIGHT_CHANGE_HEADLINE = "change_headline"
INSIGHT_SPIKE = "spike"
INSIGHT_SHIFT = "shift"
INSIGHT_PACE_NOTE = "pace_note"
INSIGHT_ACTION = "action"

_SPIKE_MULTIPLIER_THRESHOLD = 1.5


def build_insights(data: dict[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []

    change = _build_change_headline(data)
    if change is not None:
        components.append(change)

    spike = _find_spike(data.get("daily_trend"))
    if spike is not None:
        components.append(
            {
                "type": INSIGHT_SPIKE,
                "key": "insights_spike_v2",
                "date": spike["date"],
                "tokens": spike["tokens"],
                "mean_multiplier": spike["mean_multiplier"],
            }
        )

    shift = _build_shift(data)
    if shift is not None:
        components.append(shift)

    pace_note = _build_pace_note(data)
    if pace_note is not None:
        components.append(pace_note)

    action = _build_action(change, spike)
    if action is not None:
        components.append(action)

    return components[:5]


def _build_change_headline(data: dict[str, Any]) -> dict[str, Any] | None:
    comparison = _mapping_value(data.get("comparison"))
    if comparison is None or not bool(comparison.get("has_prev")):
        return None

    prev_tokens = _int_value(comparison.get("prev_tokens"))
    if prev_tokens <= 0:
        return None

    summary = _mapping_value(data.get("summary"))
    if summary is None:
        return None

    cur_tokens = _int_value(summary.get("total_tokens"))
    delta_pct = round((cur_tokens - prev_tokens) / prev_tokens * 100)
    if delta_pct >= 8:
        key = "insights_change_up"
        direction = "up"
    elif delta_pct <= -8:
        key = "insights_change_down"
        direction = "down"
    else:
        key = "insights_change_flat"
        direction = "flat"

    return {
        "type": INSIGHT_CHANGE_HEADLINE,
        "key": key,
        "tokens": cur_tokens,
        "cost_usd": _round_cost(_float_value(summary.get("cost_usd"))),
        "pct": abs(delta_pct),
        "direction": direction,
        "delta_pct": delta_pct,
    }


def _build_shift(data: dict[str, Any]) -> dict[str, Any] | None:
    return (
        _build_new_project_shift(data)
        or _build_model_shift(data)
        or _build_trend_shift(data)
    )


def _build_new_project_shift(data: dict[str, Any]) -> dict[str, Any] | None:
    comparison = _mapping_value(data.get("comparison"))
    if comparison is None or not bool(comparison.get("has_prev")):
        return None

    prev_projects = {
        _str_value(project, "")
        for project in _list_value(comparison.get("prev_projects"))
    }
    for project in _list_value(data.get("by_project")):
        item = _mapping_value(project)
        if item is None:
            continue
        name = _str_value(item.get("project"), "unknown")
        pct = _float_value(item.get("pct"))
        if pct >= 15.0 and name not in prev_projects:
            return {
                "type": INSIGHT_SHIFT,
                "key": "insights_shift_new_project",
                "project": name,
                "pct": _round_pct(pct),
            }
    return None


def _build_model_shift(data: dict[str, Any]) -> dict[str, Any] | None:
    comparison = _mapping_value(data.get("comparison"))
    if comparison is None or not bool(comparison.get("has_prev")):
        return None

    top_model = _first_mapping(data.get("by_model"))
    prev_model_share = _mapping_value(comparison.get("prev_model_share"))
    if top_model is None or prev_model_share is None:
        return None

    model = _str_value(top_model.get("model"), "unknown")
    pct = _float_value(top_model.get("pct"))
    prev_pct = _float_value(prev_model_share.get(model))
    if pct - prev_pct < 10.0:
        return None

    return {
        "type": INSIGHT_SHIFT,
        "key": "insights_shift_model_up",
        "model": model,
        "prev_pct": _round_pct(prev_pct),
        "pct": _round_pct(pct),
    }


def _build_trend_shift(data: dict[str, Any]) -> dict[str, Any] | None:
    weekly = _weekly_token_totals(data.get("daily_trend"))
    if len(weekly) < 2:
        return None

    if len(weekly) >= 3 and weekly[-3] < weekly[-2] < weekly[-1]:
        return {"type": INSIGHT_SHIFT, "key": "insights_shift_trend_up"}
    if weekly[-2] > 0 and weekly[-1] <= weekly[-2] * 0.75:
        return {"type": INSIGHT_SHIFT, "key": "insights_shift_trend_down"}
    return None


def _build_pace_note(data: dict[str, Any]) -> dict[str, Any] | None:
    summary = _mapping_value(data.get("summary"))
    if summary is None:
        return None

    active_days = _int_value(summary.get("active_days"))
    sessions = _int_value(summary.get("sessions"))
    if active_days <= 0:
        return None

    per_day = round(sessions / active_days)
    if per_day < 12:
        return None

    return {
        "type": INSIGHT_PACE_NOTE,
        "key": "insights_pace_dense",
        "active_days": active_days,
        "sessions": sessions,
        "per_day": per_day,
    }


def _build_action(
    change: dict[str, Any] | None,
    spike: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if (
        change is not None
        and change.get("direction") == "up"
        and _int_value(change.get("delta_pct")) >= 50
    ):
        return {"type": INSIGHT_ACTION, "key": "insights_action_watch_quota"}

    if spike is not None:
        return {
            "type": INSIGHT_ACTION,
            "key": "insights_action_smooth_spike",
            "date": spike["date"],
        }
    return None


def _find_spike(raw_daily: object) -> dict[str, Any] | None:
    daily = _daily_points(raw_daily)
    if len(daily) < 2:
        return None

    token_values = [point["tokens"] for point in daily]
    mean = sum(token_values) / len(token_values)
    if mean <= 0.0:
        return None

    variance = sum((tokens - mean) ** 2 for tokens in token_values) / len(token_values)
    stdev = sqrt(variance)
    threshold = mean + stdev

    candidates = [
        point
        for point in daily
        if point["tokens"] > threshold
        and point["tokens"] >= mean * _SPIKE_MULTIPLIER_THRESHOLD
    ]
    if not candidates:
        return None

    spike = sorted(candidates, key=lambda point: (-point["tokens"], point["date"]))[0]
    return {
        "date": spike["date"],
        "tokens": spike["tokens"],
        "cost_usd": _round_cost(spike["cost"]),
        "mean_tokens": round(mean, 1),
        "stdev_tokens": round(stdev, 1),
        "mean_multiplier": round(spike["tokens"] / mean, 2),
    }


def _daily_points(raw_daily: object) -> list[dict[str, Any]]:
    daily = _list_value(raw_daily)
    points: list[dict[str, Any]] = []
    for raw_point in daily:
        point = _mapping_value(raw_point)
        if point is None:
            continue
        date = _str_value(point.get("date"), "")
        tokens = _int_value(point.get("tokens"))
        if not date or tokens < 0:
            continue
        points.append(
            {
                "date": date,
                "tokens": tokens,
                "cost": _float_value(point.get("cost")),
            }
        )
    return points


def _weekly_token_totals(raw_daily: object) -> list[int]:
    daily = _daily_points(raw_daily)
    if not daily:
        return []

    weekly: dict[tuple[int, int], int] = {}
    for point in daily:
        try:
            parsed = date.fromisoformat(point["date"][:10])
        except ValueError:
            continue
        iso_year, iso_week, _weekday = parsed.isocalendar()
        key = (iso_year, iso_week)
        weekly[key] = weekly.get(key, 0) + point["tokens"]
    return [weekly[key] for key in sorted(weekly)]


def _first_mapping(value: object) -> dict[str, Any] | None:
    items = _list_value(value)
    if not items:
        return None
    return _mapping_value(items[0])


def _mapping_value(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return None


def _list_value(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def _str_value(value: object, default: str) -> str:
    if isinstance(value, str):
        return value
    return default


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _float_value(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _round_cost(value: float) -> float:
    return round(value, 4)


def _round_pct(value: float) -> float:
    return round(value, 1)
