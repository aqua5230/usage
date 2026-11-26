#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# ruff: noqa: UP006, UP007, UP035, UP045
"""Codex status line provider: usage's Claude Code status line, drawn in Codex's footer.

Codex (0.172+, experimental `tui_extensions_statusline`) runs this as a stdio MCP
server and reads the advertised `ui://` resource once a second, passing the
displayed thread's snapshot in `params._meta`. The reply is a JSON UI tree.

This deployed script runs under macOS /usr/bin/python3 3.9 and uses only the
standard library. It reads files and never writes any. Each read has one second
to finish, and one error stops Codex from polling until the user reselects the
provider, so every read returns something drawable.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

SERVER_NAME = "usage-statusline"
TOOL_NAME = "statusline"
URI = "ui://usage-statusline/footer"
STATE_KEY = "com.openai/codex-statusline-state"
TOOL = {
    "name": TOOL_NAME,
    "title": "usage",
    "description": "Show the usage status line in the Codex footer.",
    "inputSchema": {"type": "object", "properties": {}},
    "_meta": {
        # Without a visibility list Codex also declares the tool to the model on every
        # turn; "app" alone keeps it out (codex-mcp tool_catalog.rs tool_is_model_visible).
        "ui": {"visibility": ["app"]},
        "openai/ui": {"entrypoints": [{"type": "statusline", "resourceUri": URI}]},
    },
}

QUOTA_SNAPSHOT = os.path.expanduser("~/.usage/quota_snapshot.json")
PREFERENCES_FILE = os.path.expanduser("~/.claude/usage-preferences.json")
SESSIONS_DIR = os.path.join(
    os.path.expanduser(os.environ.get("CODEX_HOME") or "~/.codex"), "sessions"
)
SESSION_LOOKBACK_DAYS = 3
UPDATE_HINT_STALE_SECONDS = 30 * 86400
# Same thresholds as usage_statusline.py's /clear nudge.
HEAVY_CONTEXT_PERCENT = 70.0
CONTEXT_BURN_RESET_DROP_PERCENT = 5.0
CONTEXT_BURN_FAST_PERCENT_PER_MIN = 2.0
CONTEXT_BURN_VERY_FAST_PERCENT_PER_MIN = 4.0
CONTEXT_BURN_FAST_THRESHOLD_PERCENT = 60.0
CONTEXT_BURN_VERY_FAST_THRESHOLD_PERCENT = 55.0

# usage_statusline.py's xterm-256 colours as hex, which Codex's UI tree accepts.
GREEN, ORANGE, RED = "#00d787", "#ffaf00", "#d70000"  # 42, 214, 160
PROJECT, BLUE, MAGENTA, GREY = "#5fd7d7", "#00afff", "#87afff", "#585858"  # 80, 39, 111, 240
CYAN = "#00cdcd"
DIM = "#808080"  # \033[2m on default text
DIM_MAGENTA = "#5f7fa8"  # \033[2m on 111

STATUSLINE_TRANSLATIONS = {
    "zh-TW": {
        "five_hour": "5小時",
        "seven_day": "7天",
        "context": "對話窗",
        "cache_hit": "快取:",
        "session_dur": "會話時長:",
        "remaining_prefix": "剩",
        "effort_xhigh": "深思熟慮",
        "effort_high": "深思",
        "effort_normal": "標準",
        "effort_low": "速答",
        "update_available_suffix": "可更新",
        "warn_clear": "越長 AI 越容易漏記中段 · 切任務 /clear,續做 /compact 留重點",
    },
    "zh-CN": {
        "five_hour": "5小时",
        "seven_day": "7天",
        "context": "对话窗",
        "cache_hit": "缓存:",
        "session_dur": "会话时长:",
        "remaining_prefix": "剩",
        "effort_xhigh": "深思熟虑",
        "effort_high": "深思",
        "effort_normal": "标准",
        "effort_low": "速答",
        "update_available_suffix": "可更新",
        "warn_clear": "越长 AI 越容易漏记中段 · 切任务 /clear,续做 /compact 留重点",
    },
    "en": {
        "five_hour": "5h",
        "seven_day": "7d",
        "context": "Context",
        "cache_hit": "Cache:",
        "session_dur": "Session:",
        "remaining_prefix": "left",
        "effort_xhigh": "Extended",
        "effort_high": "Deep",
        "effort_normal": "Standard",
        "effort_low": "Quick",
        "update_available_suffix": "available",
        "warn_clear": "longer chats lose the middle · /clear to switch, /compact to keep focus",
    },
    "ja": {
        "five_hour": "5時間",
        "seven_day": "7日",
        "context": "コンテキスト",
        "cache_hit": "キャッシュ:",
        "session_dur": "セッション時間:",
        "remaining_prefix": "残り",
        "effort_xhigh": "熟考",
        "effort_high": "熟考",
        "effort_normal": "標準",
        "effort_low": "即答",
        "update_available_suffix": "更新あり",
        "warn_clear": "長いほど中盤を忘れがち · 切替は /clear、継続は /compact で要点保持",
    },
    "ko": {
        "five_hour": "5시간",
        "seven_day": "7일",
        "context": "컨텍스트",
        "cache_hit": "캐시:",
        "session_dur": "세션 시간:",
        "remaining_prefix": "남음",
        "effort_xhigh": "심사숙고",
        "effort_high": "깊은 사고",
        "effort_normal": "표준",
        "effort_low": "빠른 답변",
        "update_available_suffix": "업데이트",
        "warn_clear": "길수록 중간 내용을 놓침 · 전환은 /clear, 계속은 /compact로 핵심 유지",
    },
}
# Codex reasoning levels mapped onto the Claude hook's effort labels.
EFFORT_KEYS = {
    "xhigh": "effort_xhigh",
    "high": "effort_high",
    "medium": "effort_normal",
    "low": "effort_low",
    "minimal": "effort_low",
}

Node = Union[str, Dict[str, Any]]
Part = List[Node]

# Per-thread memory; the process lives as long as the Codex session.
_session_starts: Dict[str, Tuple[float, bool]] = {}
_context_samples: Dict[str, Tuple[float, float, float]] = {}


def detect_lang(env: Optional[Dict[str, str]] = None) -> str:
    source = os.environ if env is None else env
    raw = ""
    keys = (
        ("USAGE_LANG", "TT_LANG") if sys.platform == "win32" else ("USAGE_LANG", "TT_LANG", "LANG")
    )
    for key in keys:
        value = source.get(key, "").strip()
        if value:
            raw = value
            break
    code = raw.split(".")[0].replace("_", "-")
    table = {
        "zh-TW": "zh-TW",
        "zh-HK": "zh-TW",
        "zh-CN": "zh-CN",
        "zh": "zh-CN",
        "ja-JP": "ja",
        "ja": "ja",
        "ko-KR": "ko",
        "ko": "ko",
    }
    return table.get(code, "en")


def _t(key: str, lang: str) -> str:
    return STATUSLINE_TRANSLATIONS.get(lang, STATUSLINE_TRANSLATIONS["en"]).get(key, key)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def safe_text(value: str) -> str:
    return "".join(ch for ch in value if ch.isprintable())


def _text(value: str, color: Optional[str] = None) -> Node:
    if color is None:
        return value
    return {"type": "text", "props": {"color": color}, "children": [value]}


def color_by_pct(pct: float) -> str:
    if pct < 50:
        return GREEN
    if pct < 80:
        return ORANGE
    return RED


def context_color(pct: float, tokens: Optional[float] = None) -> str:
    if pct >= 80 or (tokens is not None and tokens >= 400_000):
        return RED
    if pct >= 50 or (tokens is not None and tokens >= 200_000):
        return ORANGE
    return GREEN


def cache_color(pct: float) -> str:
    if pct >= 80:
        return DIM_MAGENTA
    if pct >= 50:
        return ORANGE
    return RED


def progress_bar(pct: float, color: str, width: int = 8) -> Part:
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * width)
    return [
        _text("■" * filled, color),
        _text("□" * (width - filled), GREY),
        " ",
        _text(f"{pct:.0f}%", color),
    ]


def fmt_duration(seconds: float) -> str:
    if seconds >= 86400:
        return f"{int(seconds // 86400)}d{int(seconds % 86400) // 3600}h"
    if seconds >= 3600:
        return f"{int(seconds // 3600)}h{int((seconds % 3600) // 60)}m"
    if seconds >= 60:
        return f"{int(seconds // 60)}min"
    return f"{int(seconds)}s"


def fmt_tokens(n: Any) -> str:
    try:
        value = int(n)
    except (TypeError, ValueError):
        value = 0
    if value >= 999_950_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 999_500:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def git_branch(cwd: str) -> str:
    path = os.path.abspath(cwd)
    while True:
        git_path = os.path.join(path, ".git")
        if os.path.isdir(git_path):
            head_path = os.path.join(git_path, "HEAD")
            break
        if os.path.isfile(git_path):
            try:
                with open(git_path, encoding="utf-8") as f:
                    target = f.read().strip()
            except (OSError, UnicodeDecodeError):
                return ""
            if target.startswith("gitdir:"):
                git_dir = target.split(":", 1)[1].strip()
                if not os.path.isabs(git_dir):
                    git_dir = os.path.normpath(os.path.join(path, git_dir))
                head_path = os.path.join(git_dir, "HEAD")
                break
        parent = os.path.dirname(path)
        if parent == path:
            return ""
        path = parent
    try:
        with open(head_path, encoding="utf-8") as f:
            head = f.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""
    prefix = "ref: refs/heads/"
    if head.startswith(prefix):
        return head[len(prefix) :]
    return head[:7]


def _cached_codex_limits() -> Optional[Dict[str, Any]]:
    """Codex sends no rate limits before the thread's first response; usage's cache fills in."""
    try:
        with open(QUOTA_SNAPSHOT, encoding="utf-8") as f:
            codex = json.load(f)["agents"]["codex"]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(codex, dict) or not codex.get("available"):
        return None

    def window(key: str) -> Optional[Dict[str, Any]]:
        raw = _as_dict(codex.get(key))
        if raw.get("used_percent") is None:
            return None
        return {"used_percent": raw.get("used_percent"), "resets_at": raw.get("resets_at")}

    return {"primary_limit": window("five_hour"), "secondary_limit": window("seven_day")}


def _codex_limits(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = _as_dict(state.get("account")).get("rate_limits")
    snapshots = [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
    for snapshot in snapshots:
        if snapshot.get("limit_id") == "codex":
            return snapshot
    return snapshots[0] if snapshots else _cached_codex_limits()


def _limit_part(label: str, window: Dict[str, Any], now: float, lang: str) -> Optional[Part]:
    pct = _as_float(window.get("used_percent"))
    if pct is None:
        return None
    head: Part = [_text(f"{label}:", BLUE)]
    resets_at = _as_float(window.get("resets_at"))
    if resets_at is None:
        return head + progress_bar(pct, color_by_pct(pct))
    remain = int(resets_at) - int(now)
    if remain <= 0:
        return head + progress_bar(0.0, color_by_pct(0.0))
    try:
        reset = datetime.fromtimestamp(resets_at)
    except (OverflowError, OSError, ValueError):
        return head + progress_bar(pct, color_by_pct(pct))
    clock = f"{reset:%H:%M}"
    if reset.date() != datetime.fromtimestamp(now).date():
        clock = f"{reset.month}/{reset.day} {clock}"
    if lang in ("zh-TW", "zh-CN"):
        remaining = f"{_t('remaining_prefix', lang)}{fmt_duration(remain)}"
    else:
        remaining = f"{fmt_duration(remain)} {_t('remaining_prefix', lang)}"
    if pct >= 100:
        return head + [_text(f"{clock}({remaining})", RED)]
    return head + progress_bar(pct, color_by_pct(pct)) + [" ", _text(f"{clock}({remaining})", DIM)]


def session_start(thread_id: str, now: float) -> float:
    """Start time from the rollout file name; first sight until Codex writes the file."""
    known = _session_starts.get(thread_id)
    if known is not None and known[1]:
        return known[0]
    suffix = f"-{thread_id}.jsonl"
    for days_back in range(SESSION_LOOKBACK_DAYS):
        day = datetime.fromtimestamp(now - days_back * 86400)
        folder = os.path.join(SESSIONS_DIR, f"{day:%Y}", f"{day:%m}", f"{day:%d}")
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if not (name.startswith("rollout-") and name.endswith(suffix)):
                continue
            try:
                started = datetime.strptime(name[8:27], "%Y-%m-%dT%H-%M-%S").timestamp()
            except ValueError:
                continue
            _session_starts[thread_id] = (started, True)
            return started
    if known is None:
        _session_starts[thread_id] = (now, False)
        return now
    return known[0]


def heavy_threshold(thread_id: str, pct: float, now: float) -> float:
    """usage_statusline.py's burn-rate rule, sampled each time the percentage moves.

    The Claude hook compares consecutive renders, one per message. Codex reads every
    second, so the sample advances only when the percentage changes.
    """
    previous = _context_samples.get(thread_id)
    if previous is None:
        _context_samples[thread_id] = (pct, now, HEAVY_CONTEXT_PERCENT)
        return HEAVY_CONTEXT_PERCENT
    previous_pct, previous_ts, threshold = previous
    if pct == previous_pct:
        return threshold
    threshold = HEAVY_CONTEXT_PERCENT
    elapsed = now - previous_ts
    increase = pct - previous_pct
    if previous_pct - pct <= CONTEXT_BURN_RESET_DROP_PERCENT and elapsed > 0 and increase > 0:
        per_minute = increase / (elapsed / 60.0)
        if per_minute >= CONTEXT_BURN_VERY_FAST_PERCENT_PER_MIN:
            threshold = CONTEXT_BURN_VERY_FAST_THRESHOLD_PERCENT
        elif per_minute >= CONTEXT_BURN_FAST_PERCENT_PER_MIN:
            threshold = CONTEXT_BURN_FAST_THRESHOLD_PERCENT
    _context_samples[thread_id] = (pct, now, threshold)
    return threshold


def read_update_hint(now: float) -> Optional[str]:
    try:
        with open(PREFERENCES_FILE, encoding="utf-8") as f:
            prefs = json.load(f)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    info = _as_dict(_as_dict(prefs).get("last_update_check"))
    latest = info.get("latest_version")
    current = info.get("current_version")
    checked_at = _as_float(info.get("checked_at"))
    if not isinstance(latest, str) or not isinstance(current, str) or checked_at is None:
        return None
    if latest == current or _as_dict(prefs).get("update_skipped_version") == latest:
        return None
    if now - checked_at > UPDATE_HINT_STALE_SECONDS:
        return None
    return latest


def render(state: Dict[str, Any], now: Optional[float] = None, lang: Optional[str] = None) -> Node:
    """Build the footer: the Claude hook's two lines joined into Codex's single row."""
    now = time.time() if now is None else now
    lang = detect_lang() if lang is None else lang
    thread = _as_dict(state.get("thread"))
    thread_id = thread.get("id") if isinstance(thread.get("id"), str) else ""
    parts: List[Part] = []

    cwd = _as_dict(thread.get("workspace")).get("cwd")
    if isinstance(cwd, str) and cwd:
        name: Part = [_text(safe_text(os.path.basename(cwd.rstrip("/\\")) or cwd), PROJECT)]
        branch = safe_text(git_branch(cwd))
        if branch:
            name += ["(", _text(branch, MAGENTA), ")"]
        parts.append(name)

    limits = _as_dict(_codex_limits(state))
    for key, label_key in (("primary_limit", "five_hour"), ("secondary_limit", "seven_day")):
        window = limits.get(key)
        part = (
            _limit_part(_t(label_key, lang), window, now, lang)
            if isinstance(window, dict)
            else None
        )
        if part:
            parts.append(part)

    if thread_id:
        elapsed = now - session_start(thread_id, now)
        parts.append([_text(f"{_t('session_dur', lang)} {fmt_duration(elapsed)}", DIM_MAGENTA)])

    model = _as_dict(thread.get("model"))
    model_name = model.get("display_name")
    if isinstance(model_name, str) and model_name:
        level = model.get("reasoning_level")
        if isinstance(level, str) and level:
            label = EFFORT_KEYS.get(level)
            model_name += f"/{_t(label, lang) if label else level}"
        parts.append([_text(safe_text(model_name), DIM_MAGENTA)])

    usage = _as_dict(thread.get("usage"))
    total = _as_dict(usage.get("total"))
    inputs = _as_float(total.get("total_input_tokens")) or 0.0
    cached = _as_float(total.get("cache_read_input_tokens"))
    if inputs > 0 and cached is not None:
        hit = max(0.0, min(100.0, cached / inputs * 100))
        parts.append(
            [_text(_t("cache_hit", lang), DIM_MAGENTA), _text(f"{hit:.0f}%", cache_color(hit))]
        )

    warning: Optional[Part] = None
    context = _as_dict(usage.get("context"))
    ctx_pct = _as_float(context.get("used_percentage"))
    if ctx_pct is not None:
        size = _as_float(context.get("context_window_size"))
        tokens = ctx_pct / 100 * size if size and size > 0 else None
        part = [_text(f"{_t('context', lang)}:", BLUE)] + progress_bar(
            ctx_pct, context_color(ctx_pct, tokens)
        )
        if size and size > 0:
            part += [" ", _text(f"/ {fmt_tokens(size)}", DIM)]
        parts.append(part)
        if thread_id and ctx_pct >= heavy_threshold(thread_id, ctx_pct, now):
            detail = f"⚠ {_t('context', lang)} {ctx_pct:.0f}% · {_t('warn_clear', lang)}"
            warning = [_text(detail, RED)]

    update = read_update_hint(now)
    if update:
        parts.append(
            [_text(f"🆕 v{safe_text(update)} {_t('update_available_suffix', lang)}", CYAN)]
        )
    # Codex 0.172 gives a provider one row and cuts the right end, so the warning leads.
    if warning:
        parts.insert(0, warning)
    if not parts:
        return "usage"
    children: List[Node] = []
    for index, part in enumerate(parts):
        if index:
            children += [" ", _text("|", GREY), " "]
        children += part
    return {"type": "text", "children": children}


def safe_render(state: Dict[str, Any]) -> Node:
    try:
        return render(state)
    except Exception:
        return "usage"


class ResourceNotFound(Exception):
    pass


def respond(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "1.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method == "tools/call":
        if params.get("name") != TOOL_NAME:
            raise ValueError("Unknown tool name")
        return {"content": [{"type": "text", "text": f"The statusline resource is {URI}."}]}
    if method == "resources/list":
        return {"resources": [{"name": "footer", "uri": URI, "mimeType": "application/json"}]}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "resources/read":
        if params.get("uri") != URI:
            raise ResourceNotFound
        state = _as_dict(_as_dict(params.get("_meta")).get(STATE_KEY))
        text = json.dumps(safe_render(state), ensure_ascii=False)
        return {"contents": [{"uri": URI, "mimeType": "application/json", "text": text}]}
    raise KeyError(method)


def handle_line(line: bytes) -> Optional[Dict[str, Any]]:
    reply: Dict[str, Any] = {"jsonrpc": "2.0", "id": None}
    try:
        request = json.loads(line)
        if not isinstance(request, dict) or not isinstance(request.get("method"), str):
            reply["error"] = {"code": -32600, "message": "Invalid request"}
        elif "id" not in request:
            return None
        else:
            reply["id"] = request["id"]
            reply["result"] = respond(request["method"], _as_dict(request.get("params")))
    except ValueError as exc:
        if isinstance(exc, json.JSONDecodeError):
            reply["error"] = {"code": -32700, "message": "Parse error"}
        else:
            reply["error"] = {"code": -32602, "message": "Invalid parameters"}
    except ResourceNotFound:
        reply["error"] = {"code": -32002, "message": "Resource not found"}
    except KeyError:
        reply["error"] = {"code": -32601, "message": "Method not found"}
    except (TypeError, AttributeError):
        reply["error"] = {"code": -32602, "message": "Invalid parameters"}
    return reply


def main() -> None:
    for line in sys.stdin.buffer:
        reply = handle_line(line)
        if reply is not None:
            sys.stdout.buffer.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
