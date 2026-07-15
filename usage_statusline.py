#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

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

import errno
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_fcntl: Any = None
_msvcrt: Any = None
if sys.platform == "win32":
    try:
        import msvcrt
    except ImportError:
        pass
    else:
        _msvcrt = msvcrt
else:
    try:
        import fcntl
    except ImportError:
        pass
    else:
        _fcntl = fcntl
fcntl = _fcntl
msvcrt = _msvcrt

__version__ = "1.0"

STATUS_FILE = os.path.expanduser("~/.claude/usage-status.json")
LOCK_FILE = os.path.expanduser("~/.claude/usage-status.lock")
# Windows lock acquisition: poll rather than fail instantly on contention.
_LOCK_TIMEOUT_S = 10.0
_LOCK_POLL_INTERVAL_S = 0.001
# msvcrt.locking reports a contended byte as EACCES; EDEADLOCK is what it
# raises once its own internal retries are exhausted.
_LOCK_CONTENDED_ERRNOS = frozenset(
    (errno.EACCES, getattr(errno, "EDEADLOCK", errno.EDEADLK), errno.EDEADLK)
)
PREFERENCES_FILE = os.path.expanduser("~/.claude/usage-preferences.json")
CONTEXT_BURN_FILE = os.path.expanduser("~/.claude/usage-context-burn.json")
UPDATE_HINT_STALE_SECONDS = 30 * 86400
# Context fill at which a /clear or /compact nudge is worth the noise. Set below
# the default auto-compact line (~80%) so the user can act before the lossy
# automatic pass decides for them. Long contexts degrade quality well before they
# fill: models lose the middle of long inputs and effective context is often only
# ~50-65% of the window. Refs: Liu et al. "Lost in the Middle" (2023,
# arXiv:2307.03172), NVIDIA RULER (2024, arXiv:2404.06654), BABILong (2024,
# arXiv:2406.10149).
HEAVY_CONTEXT_PERCENT = 70.0
CONTEXT_BURN_RESET_DROP_PERCENT = 5.0
CONTEXT_BURN_STALE_SECONDS = 4 * 60 * 60
CONTEXT_BURN_FAST_PERCENT_PER_MIN = 2.0
CONTEXT_BURN_VERY_FAST_PERCENT_PER_MIN = 4.0
CONTEXT_BURN_FAST_THRESHOLD_PERCENT = 60.0
CONTEXT_BURN_VERY_FAST_THRESHOLD_PERCENT = 55.0
CONTEXT_BURN_THRESHOLD_FLOOR_PERCENT = 55.0
# 2%/min reaches the old warning line from 50% in about 10 minutes; 4%/min is
# the "large paste or long replay" case that should warn at the floor.
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
        "warn_clear": "越長 AI 越容易漏記中段 · 切任務 /clear,續做 /compact 留重點",
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
        "warn_clear": "越长 AI 越容易漏记中段 · 切任务 /clear,续做 /compact 留重点",
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
        "warn_clear": "longer chats lose the middle · /clear to switch, /compact to keep focus",
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
        "warn_clear": "長いほど中盤を忘れがち · 切替は /clear、継続は /compact で要点保持",
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
        "warn_clear": "길수록 중간 내용을 놓침 · 전환은 /clear, 계속은 /compact로 핵심 유지",
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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
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


def _rate_limits_complete(rate_limits: Any) -> bool:
    if not isinstance(rate_limits, dict):
        return False
    five = rate_limits.get("five_hour")
    seven = rate_limits.get("seven_day")
    if not isinstance(five, dict) or not isinstance(seven, dict):
        return False
    return five.get("used_percentage") is not None and seven.get("used_percentage") is not None


def _acquire_msvcrt_lock(lock_fd: int) -> bool:
    """Block (bounded) until the byte is locked; False if locking is unavailable.

    msvcrt has no blocking-with-timeout mode: LK_LOCK retries on a fixed
    one-second granularity, and LK_NBLCK gives up instantly. Poll LK_NBLCK so a
    contended lock is waited out rather than silently skipped — dropping the
    lock would run save()'s read-modify-write unsynchronized, which fcntl.flock
    never does on POSIX.
    """
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            if os.fstat(lock_fd).st_size == 0:
                os.write(lock_fd, b"\0")
            os.lseek(lock_fd, 0, os.SEEK_SET)
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno not in _LOCK_CONTENDED_ERRNOS:
                # Locking is unsupported on this descriptor or filesystem;
                # spinning would not help. Fall back to the atomic write alone.
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(_LOCK_POLL_INTERVAL_S)


@contextmanager
def _exclusive_lock(lock_fd: int) -> Any:
    """Use the native lock when available; preserve atomic writes without one."""
    if fcntl is not None:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        return

    locked = _acquire_msvcrt_lock(lock_fd) if msvcrt is not None else False
    try:
        yield
    finally:
        if locked and msvcrt is not None:
            try:
                os.lseek(lock_fd, 0, os.SEEK_SET)
                msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass


def save(data: Dict[str, Any], now: datetime) -> None:
    data["_received_at"] = now.isoformat()
    data["_received_at_ts"] = now.timestamp()
    target_dir = os.path.dirname(STATUS_FILE)
    lock_file = os.path.join(target_dir, os.path.basename(LOCK_FILE))
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(lock_file), exist_ok=True)
    tmp_path: Optional[str] = None
    lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with _exclusive_lock(lock_fd):
            if not _rate_limits_complete(data.get("rate_limits")):
                try:
                    with open(STATUS_FILE, encoding="utf-8") as f:
                        existing = json.load(f)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    existing = None
                if isinstance(existing, dict):
                    existing_rate_limits = existing.get("rate_limits")
                    if _rate_limits_complete(existing_rate_limits):
                        data["rate_limits"] = existing_rate_limits
            fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, STATUS_FILE)
            tmp_path = None
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


def _read_context_burn_sample(now_ts: float) -> Optional[Tuple[float, float]]:
    try:
        with open(CONTEXT_BURN_FILE, encoding="utf-8") as f:
            sample = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(sample, dict):
        return None
    percent = _as_float(sample.get("percent"))
    ts = _as_float(sample.get("ts"))
    if percent is None or ts is None:
        return None
    if now_ts - ts > CONTEXT_BURN_STALE_SECONDS:
        return None
    return percent, ts


def _write_context_burn_sample(percent: float, now_ts: float) -> None:
    target_dir = os.path.dirname(CONTEXT_BURN_FILE)
    tmp_path: Optional[str] = None
    try:
        os.makedirs(target_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"percent": percent, "ts": now_ts}, f, ensure_ascii=False)
        os.replace(tmp_path, CONTEXT_BURN_FILE)
        tmp_path = None
    except OSError:
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _context_burn_threshold(percent: float, now_ts: float) -> float:
    previous = _read_context_burn_sample(now_ts)
    _write_context_burn_sample(percent, now_ts)
    if previous is None:
        return HEAVY_CONTEXT_PERCENT

    previous_percent, previous_ts = previous
    if previous_percent - percent > CONTEXT_BURN_RESET_DROP_PERCENT:
        return HEAVY_CONTEXT_PERCENT

    elapsed_seconds = now_ts - previous_ts
    if elapsed_seconds <= 0:
        return HEAVY_CONTEXT_PERCENT

    increase = percent - previous_percent
    if increase <= 0:
        return HEAVY_CONTEXT_PERCENT

    percent_per_minute = increase / (elapsed_seconds / 60.0)
    threshold = HEAVY_CONTEXT_PERCENT
    if percent_per_minute >= CONTEXT_BURN_VERY_FAST_PERCENT_PER_MIN:
        threshold = CONTEXT_BURN_VERY_FAST_THRESHOLD_PERCENT
    elif percent_per_minute >= CONTEXT_BURN_FAST_PERCENT_PER_MIN:
        threshold = CONTEXT_BURN_FAST_THRESHOLD_PERCENT
    return max(CONTEXT_BURN_THRESHOLD_FLOOR_PERCENT, threshold)


def _heavy_warning(data: Dict[str, Any], now_ts: Optional[float] = None) -> Optional[str]:
    """A /clear or /compact nudge once the context window gets heavy enough
    that quality starts to slip (see HEAVY_CONTEXT_PERCENT)."""
    pct = _as_float(_as_dict(data.get("context_window")).get("used_percentage"))
    if pct is None:
        return None
    threshold = _context_burn_threshold(
        pct,
        datetime.now(timezone.utc).timestamp() if now_ts is None else now_ts,
    )
    if pct < threshold:
        return None
    detail = f"{_t('context')} {pct:.0f}%"
    return f"\033[38;5;160m⚠ {detail} · {_t('warn_clear')}{C['reset']}"


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
            line1.append(f"{C['green']}{name}{C['reset']}({C['magenta']}{branch}{C['reset']})")
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
        resets_at = _as_float(entry.get("resets_at"))
        if resets_at is not None:
            remain = int(resets_at) - int(now.timestamp())
            if remain > 0:
                if lang in ("zh-TW", "zh-CN"):
                    reset_str = f" ({_t('remaining_prefix')}{fmt_duration(remain)})"
                else:
                    reset_str = f" ({fmt_duration(remain)} {_t('remaining_prefix')})"
        rl_parts.append(
            (
                f"{C['blue']}{label}:{C['reset']}{progress_bar(pct_float, bar_w)}{reset_str}",
                f"{C['blue']}{label}:{C['reset']}{progress_bar(pct_float, bar_w)}",
                f"{C['blue']}{label}:{C['reset']}{pct_float:.0f}%",
            )
        )

    ctx_parts: List[str] = []
    ctx_pct = _as_float(ctx.get("used_percentage"))
    if ctx_pct is not None:
        size = ctx.get("context_window_size", 0)
        ctx_parts = [
            f"{C['blue']}{_t('context')}:{C['reset']}"
            f"{progress_bar(ctx_pct, bar_w)} / {fmt_tokens(size)}",
            f"{C['blue']}{_t('context')}:{C['reset']}{ctx_pct:.0f}%",
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
        line3.append(f"{C['cyan']}🆕 v{update_version} {_t('update_available_suffix')}{C['reset']}")

    output = [" | ".join(line) for line in (line1, line3) if line]
    warning = _heavy_warning(data, now.timestamp())
    if warning:
        output.append(warning)
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
