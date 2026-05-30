#!/usr/bin/env python3
# ruff: noqa: SIM105, UP006, UP035, UP045
"""Claude Code statusLine hook：把 Claude Code 推來的狀態 JSON 持久化並渲染狀態列。

Claude Code 每次刷新 statusLine 時會把當前 session 的完整 JSON
（含 rate_limits.five_hour / seven_day、context_window、cost 等）
從 stdin 傳給這個 script。我們會落地到 usage-status.json，
再輸出多行彩色 statusLine 文字供 Claude Code 顯示。

usage 主程式會反向讀這個檔，呈現給 menubar / TUI。

刻意只用標準庫，方便用系統 python3 跑。
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

__version__ = "1.0"

STATUS_FILE = os.path.expanduser("~/.claude/usage-status.json")
LOCK_FILE = os.path.expanduser("~/.claude/usage-status.lock")
PREFERENCES_FILE = os.path.expanduser("~/.claude/usage-preferences.json")
UPDATE_HINT_STALE_SECONDS = 30 * 86400
STATUSLINE_TRANSLATIONS = {
    "zh-TW": {
        "five_hour": "5小時",
        "seven_day": "7天",
        "context": "對話窗",
        "total": "累計",
        "in_short": "問:",
        "out_short": "答:",
        "this_turn": "本輪",
        "cached": "快取:",
        "cost": "花費:",
        "session_dur": "會話時長:",
        "remaining_prefix": "剩",
        "effort_xhigh": "深思熟慮",
        "effort_high": "深思",
        "effort_normal": "標準",
        "effort_low": "速答",
        "fast_mode": "⚡快速",
        "update_available_suffix": "可更新",
    },
    "zh-CN": {
        "five_hour": "5小时",
        "seven_day": "7天",
        "context": "对话窗",
        "total": "累计",
        "in_short": "问:",
        "out_short": "答:",
        "this_turn": "本轮",
        "cached": "缓存:",
        "cost": "花费:",
        "session_dur": "会话时长:",
        "remaining_prefix": "剩",
        "effort_xhigh": "深思熟虑",
        "effort_high": "深思",
        "effort_normal": "标准",
        "effort_low": "速答",
        "fast_mode": "⚡快速",
        "update_available_suffix": "可更新",
    },
    "en": {
        "five_hour": "5h",
        "seven_day": "7d",
        "context": "Context",
        "total": "Total",
        "in_short": "in:",
        "out_short": "out:",
        "this_turn": "this turn",
        "cached": "Cached:",
        "cost": "Cost:",
        "session_dur": "Session:",
        "remaining_prefix": "left",
        "effort_xhigh": "Extended",
        "effort_high": "Deep",
        "effort_normal": "Standard",
        "effort_low": "Quick",
        "fast_mode": "⚡Fast",
        "update_available_suffix": "available",
    },
    "ja": {
        "five_hour": "5時間",
        "seven_day": "7日",
        "context": "コンテキスト",
        "total": "累計",
        "in_short": "入:",
        "out_short": "出:",
        "this_turn": "今回",
        "cached": "キャッシュ:",
        "cost": "費用:",
        "session_dur": "セッション時間:",
        "remaining_prefix": "残り",
        "effort_xhigh": "熟考",
        "effort_high": "熟考",
        "effort_normal": "標準",
        "effort_low": "即答",
        "fast_mode": "⚡高速",
        "update_available_suffix": "更新あり",
    },
    "ko": {
        "five_hour": "5시간",
        "seven_day": "7일",
        "context": "컨텍스트",
        "total": "누적",
        "in_short": "입:",
        "out_short": "출:",
        "this_turn": "이번 턴",
        "cached": "캐시:",
        "cost": "비용:",
        "session_dur": "세션 시간:",
        "remaining_prefix": "남음",
        "effort_xhigh": "심사숙고",
        "effort_high": "깊은 사고",
        "effort_normal": "표준",
        "effort_low": "빠른 답변",
        "fast_mode": "⚡빠름",
        "update_available_suffix": "업데이트",
    },
}
C = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "peach": "\033[38;5;216m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _statusline_detect_lang(env: Optional[Dict[str, str]] = None) -> str:
    source = os.environ if env is None else env
    override = source.get("TT_LANG", "").strip()
    raw = override or source.get("LANG", "")
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


def _detect_lang() -> str:
    return _statusline_detect_lang()


def _t(key: str) -> str:
    lang = _detect_lang()
    table = STATUSLINE_TRANSLATIONS.get(lang, STATUSLINE_TRANSLATIONS["en"])
    return table.get(key, key)


def _read_update_hint(now_ts: float) -> Optional[str]:
    """Return latest_version when an update is fresh, available, and not skipped."""
    try:
        with open(PREFERENCES_FILE, encoding="utf-8") as f:
            prefs = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(prefs, dict):
        return None
    info = prefs.get("last_update_check")
    if not isinstance(info, dict):
        return None
    latest = info.get("latest_version")
    current = info.get("current_version")
    checked_at = info.get("checked_at")
    if not isinstance(latest, str) or not isinstance(current, str):
        return None
    if not isinstance(checked_at, (int, float)) or isinstance(checked_at, bool):
        return None
    if latest == current:
        return None
    if prefs.get("update_skipped_version") == latest:
        return None
    if now_ts - float(checked_at) > UPDATE_HINT_STALE_SECONDS:
        return None
    return latest


def save(data: Dict[str, Any], now: datetime) -> None:
    data["_received_at"] = now.isoformat()
    data["_received_at_ts"] = now.timestamp()
    target_dir = os.path.dirname(STATUS_FILE)
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    tmp_path: str | None = None
    lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, STATUS_FILE)
            tmp_path = None
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _debug(message: str, exc: Optional[Exception] = None) -> None:
    if os.environ.get("USAGE_DEBUG") != "1":
        return
    if exc is None:
        print(f"usage_statusline: {message}", file=sys.stderr)
        return
    print(f"usage_statusline: {message}: {exc}", file=sys.stderr)


def vlen(s: str) -> int:
    visible = 0
    i = 0
    while i < len(s):
        if s[i] == "\033" and i + 1 < len(s) and s[i + 1] == "[":
            i += 2
            while i < len(s) and s[i] != "m":
                i += 1
            i += 1
            continue
        visible += 1
        i += 1
    return visible


def get_width() -> int:
    try:
        return max(1, os.get_terminal_size(2).columns - 4)
    except Exception:
        return 116


def color_by_pct(pct: float) -> str:
    if pct < 50:
        return "\033[38;5;42m"
    if pct < 80:
        return "\033[38;5;214m"
    return "\033[38;5;160m"


def fmt_tokens(n: Any) -> str:
    try:
        value = int(n)
    except (TypeError, ValueError):
        value = 0
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def progress_bar(value: Any, bar_width: int = 8) -> str:
    filled_char = "■"
    empty_char = "□"
    if value is None:
        return empty_char * bar_width + " n/a"
    pct = max(0.0, min(100.0, float(value)))
    filled = round(pct / 100 * bar_width)
    return (
        f"{color_by_pct(pct)}{filled_char * filled}{C['reset']}"
        f"{empty_char * (bar_width - filled)} "
        f"{color_by_pct(pct)}{pct:.0f}%{C['reset']}"
    )


def fmt_duration(seconds: float) -> str:
    if seconds >= 86400:
        d = int(seconds // 86400)
        rem = int(seconds % 86400)
        return f"{d}d{rem // 3600}h"
    if seconds >= 3600:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h{m}m"
    if seconds >= 60:
        return f"{int(seconds // 60)}min"
    return f"{int(seconds)}s"


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
                if target.startswith("gitdir:"):
                    git_dir = target.split(":", 1)[1].strip()
                    if not os.path.isabs(git_dir):
                        git_dir = os.path.normpath(os.path.join(path, git_dir))
                    head_path = os.path.join(git_dir, "HEAD")
                    break
            except OSError:
                return ""
        parent = os.path.dirname(path)
        if parent == path:
            return ""
        path = parent

    try:
        with open(head_path, encoding="utf-8") as f:
            head = f.read().strip()
    except OSError:
        return ""
    prefix = "ref: refs/heads/"
    if head.startswith(prefix):
        return head[len(prefix) :]
    if head:
        return head[:7]
    return ""


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _render_core(data: Dict[str, Any], now: datetime) -> str:
    width = get_width()
    ctx = _as_dict(data.get("context_window"))
    bar_w = 8 if width >= 100 else 6 if width >= 60 else 4
    lang = _detect_lang()

    line1: List[str] = []
    project = _as_dict(data.get("workspace")).get("project_dir", "")
    if isinstance(project, str) and project:
        name = os.path.basename(project)
        branch = git_branch(project)
        if branch:
            line1.append(
                f"{C['green']}{name}{C['reset']}({C['magenta']}{branch}{C['reset']})"
            )
        else:
            line1.append(f"{C['green']}{name}{C['reset']}")

    rl = _as_dict(data.get("rate_limits"))
    rl_parts: List[Tuple[str, str, str]] = []
    for key, label in (("five_hour", _t("five_hour")), ("seven_day", _t("seven_day"))):
        entry = _as_dict(rl.get(key))
        pct = entry.get("used_percentage")
        if pct is None:
            continue
        pct_float = _as_float(pct)
        if pct_float is None:
            continue
        reset_str = ""
        resets_at = entry.get("resets_at")
        if resets_at:
            remain = int(resets_at) - int(now.timestamp())
            if remain > 0:
                if lang in ("zh-TW", "zh-CN"):
                    reset_str = (
                        f" ({_t('remaining_prefix')}{fmt_duration(remain)})"
                    )
                else:
                    reset_str = (
                        f" ({fmt_duration(remain)} {_t('remaining_prefix')})"
                    )
        rl_parts.append(
            (
                f"{C['blue']}{label}:{C['reset']}{progress_bar(pct_float, bar_w)}{reset_str}",
                f"{C['blue']}{label}:{C['reset']}{progress_bar(pct_float, bar_w)}",
                f"{C['blue']}{label}:{C['reset']}{pct_float:.0f}%",
            )
        )

    ctx_parts: List[str] = []
    ctx_pct = ctx.get("used_percentage")
    if ctx_pct is not None:
        size = ctx.get("context_window_size", 0)
        ctx_parts = [
            f"{C['blue']}{_t('context')}:{C['reset']}"
            f"{progress_bar(ctx_pct, bar_w)} / {fmt_tokens(size)}",
            f"{C['blue']}{_t('context')}:{C['reset']}{float(ctx_pct):.0f}%",
        ]

    full = line1 + [p[0] for p in rl_parts] + (ctx_parts[:1] if ctx_parts else [])
    candidate = " | ".join(full)
    if vlen(candidate) <= width:
        line1 = full
    else:
        no_reset = line1 + [p[1] for p in rl_parts] + (ctx_parts[:1] if ctx_parts else [])
        candidate = " | ".join(no_reset)
        if vlen(candidate) <= width:
            line1 = no_reset
        else:
            line1 = line1 + [p[2] for p in rl_parts] + (ctx_parts[1:2] if ctx_parts else [])

    cost = _as_dict(data.get("cost"))

    line3: List[str] = []
    duration_ms = cost.get("total_duration_ms")
    duration_part = ""
    if duration_ms and duration_ms > 0:
        duration_part = (
            f"{C['dim']}{C['magenta']}{_t('session_dur')} "
            f"{fmt_duration(float(duration_ms) / 1000)}{C['reset']}"
        )
        line3.append(duration_part)

    model_name = _as_dict(data.get("model")).get("display_name", "")
    if isinstance(model_name, str) and model_name:
        effort = _as_dict(data.get("effort")).get("level", "")
        if effort:
            effort_label = {
                "xhigh": _t("effort_xhigh"),
                "high": _t("effort_high"),
                "normal": _t("effort_normal"),
                "low": _t("effort_low"),
            }.get(effort, effort)
            model_name += f"/{effort_label}"
        if data.get("fast_mode"):
            model_name += f" {_t('fast_mode')}"
        line3.append(f"{C['dim']}{C['magenta']}{model_name}{C['reset']}")

    if vlen(" | ".join(line3)) > width and duration_part:
        line3 = [p for p in line3 if p != duration_part]

    update_version = _read_update_hint(now.timestamp())
    if update_version and (line1 or line3):
        line3.append(
            f"{C['cyan']}🆕 v{update_version} {_t('update_available_suffix')}{C['reset']}"
        )

    output = [" | ".join(line) for line in (line1, line3) if line]
    return "\n".join(output) if output else "usage"


def render(data: Dict[str, Any], now: datetime) -> str:
    try:
        return _render_core(data, now)
    except Exception as exc:
        _debug("render failed", exc)
        return "usage"


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception as exc:
        _debug("stdin read failed", exc)
        return
    if not raw.strip():
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _debug("invalid stdin JSON", exc)
        print("usage")
        return
    if not isinstance(data, dict):
        _debug("stdin JSON root is not an object")
        print("usage")
        return
    now = datetime.now(timezone.utc)
    try:
        save(data, now)
        print(render(data, now))
    except Exception as exc:
        _debug("statusline failed", exc)
        print("usage")


if __name__ == "__main__":
    main()
