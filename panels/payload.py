# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>

from __future__ import annotations

import base64
import json
import os
import sys
from functools import cache, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from menubar.state import PopoverState, QuotaRowState

CORE_SCRIPT_FILENAME = "panels/panel_core.js"


def resolve_resource(name: str) -> str:
    resource_root = os.environ.get("RESOURCEPATH")
    if resource_root:
        bundled = Path(resource_root) / name
        if bundled.exists():
            return str(bundled)
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        bundled = Path(frozen_root) / "assets" / name
        if bundled.exists():
            return str(bundled)
    return str(Path(__file__).resolve().parent.parent / "assets" / name)


def _i18n_path() -> Path:
    resource_root = os.environ.get("RESOURCEPATH")
    if resource_root:
        bundled = Path(resource_root) / "i18n.json"
        if bundled.exists():
            return bundled
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        bundled = Path(frozen_root) / "i18n.json"
        if bundled.exists():
            return bundled
    return Path(__file__).resolve().parent.parent / "i18n.json"


def _new_state_payload(view: Any, payload: dict[str, object]) -> str | None:
    if payload == getattr(view, "_last_injected_state", None):
        return None
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    view._last_injected_state = payload
    if encoded == view._last_injected_payload:
        return None
    view._last_injected_payload = encoded
    return encoded


@cache
def _load_panel_html(filename: str) -> str:
    html = Path(resolve_resource(f"panels/{filename}")).read_text(encoding="utf-8")
    return (
        html.replace("{{CLAUDE_ICON}}", _data_uri("claude.webp"))
        .replace("{{CODEX_ICON}}", _data_uri("codex.webp"))
        .replace("{{CORE_SCRIPT}}", _load_core_script())
        .replace("{{I18N_BUNDLE}}", json.dumps(_load_i18n_bundle(), ensure_ascii=False))
    )


@lru_cache(maxsize=1)
def _load_core_script() -> str:
    return Path(resolve_resource(CORE_SCRIPT_FILENAME)).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _load_i18n_bundle() -> dict[str, dict[str, str]]:
    data = json.loads(_i18n_path().read_text(encoding="utf-8"))
    return {
        str(lang): {str(key): str(value) for key, value in values.items()}
        for lang, values in data.items()
    }


@lru_cache(maxsize=4)
def _data_uri(asset_name: str) -> str:
    path = Path(resolve_resource(asset_name))
    mime = "image/png" if path.suffix.lower() == ".png" else "image/webp"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _row_payload(row: QuotaRowState) -> dict[str, object]:
    return {
        "percent": row.percent,
        "percentText": row.percent_text,
        "resetText": row.reset_text,
        "resetTextCompact": row.reset_text_compact or row.reset_text,
        "warning": row.warning,
        "available": row.available,
        "title": row.title,
    }


def _state_payload(
    state: PopoverState, *, system_accent_color: str | None = None
) -> dict[str, object]:
    codex_rows = {
        key: _row_payload(row)
        for key, row in (("session", state.codex_session), ("weekly", state.codex_weekly))
        if row.title
    }
    project_payloads = []
    for rows in (
        state.projects,
        state.projects_yesterday,
        state.projects_7d,
        state.projects_30d,
        state.projects_all,
    ):
        project_payloads.append(
            [
                {
                    "name": name,
                    "tokens": tokens,
                    "tokensText": _fmt_tokens(tokens),
                    "costText": _fmt_cost(cost),
                }
                for name, tokens, cost in rows
            ]
        )
    payload: dict[str, object] = {
        "language": state.language,
        "claude": {
            "session": _row_payload(state.claude_session),
            "weekly": _row_payload(state.claude_weekly),
        },
        "codex": {
            **codex_rows,
            "stale": state.codex_stale,
            "credits": state.codex_credits,
        },
        "agy": {
            "session": _row_payload(state.agy_session),
            "weekly": _row_payload(state.agy_weekly),
            "groupName": state.agy_group_name,
            "stale": state.agy_stale,
        },
        "grok": {
            "weekly": _row_payload(state.grok_weekly),
            "stale": state.grok_stale,
        },
        "projects": project_payloads[0],
        "projectsYesterday": project_payloads[1],
        "projects7d": project_payloads[2],
        "projects30d": project_payloads[3],
        "projectsAll": project_payloads[4],
        "hideClaude": state.hide_claude,
        "hideCodex": state.hide_codex,
        "hideAgy": state.hide_agy,
        "hideGrok": state.hide_grok,
        "cardOrder": list(state.card_order),
        "historyError": state.history_error,
        "statusline": state.statusline,
        "talent": state.talent,
        "footer": {
            "rate": state.rate_text,
            "status": state.status_text,
            "today": state.today_text,
            "yesterday": state.yesterday_text,
            "serviceAlerts": list(state.service_alerts),
            "showInstall": state.show_install_button,
        },
    }
    if system_accent_color is not None:
        payload["system_accent_color"] = system_accent_color
    return payload


def _fmt_tokens(tokens: int) -> str:
    return f"{tokens:,}"


def _fmt_cost(cost: float | None) -> str:
    return "--" if cost is None else f"${cost:.2f}"
