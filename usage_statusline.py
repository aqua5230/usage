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
import math
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, cast


def _configure_windows_utf8_output() -> None:
    """Make hook output UTF-8 when Claude Code reads a Windows pipe."""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, OSError, ValueError):
            # Test runners and embedders may replace the TextIOWrapper streams.
            cast(Any, stream).reconfigure(encoding="utf-8")


def _read_stdin_utf8() -> str:
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    return cast(bytes, buffer.read()).decode("utf-8", "replace")


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

__version__ = "1.13"

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
MIX_DIR = os.path.expanduser("~/.usage/claude-pane/mix")
# Bytes one status-line run may parse; a long transcript catches up over
# several refreshes instead of stalling one.
MIX_READ_BUDGET = 4 * 1024 * 1024
MIX_STALE_SECONDS = 7 * 86400
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
        "mix_images": "圖片 {n} 張",
        "mix_tools": "讀檔與指令輸出 {n}%",
        "total": "累計",
        "in_short": "問:",
        "out_short": "答:",
        "this_turn": "本輪",
        "cached": "快取:",
        "cache_hit": "快取:",
        "cache_miss": "剛失效:",
        "miss_system_prompt_changed": "系統提示改了",
        "miss_tools_changed": "工具換了",
        "miss_model_changed": "換了模型",
        "miss_fast_mode_changed": "切換快速模式",
        "miss_cache_scope_or_ttl_changed": "快取規則變了",
        "miss_betas_changed": "測試功能變了",
        "miss_effort_changed": "換了思考強度",
        "miss_thinking_mode_changed": "開關思考",
        "miss_thinking_display_changed": "思考顯示變了",
        "miss_auto_mode_changed": "切換自動模式",
        "miss_overage_changed": "額度狀態變了",
        "miss_extra_body_changed": "請求欄位變了",
        "miss_defer_loading_changed": "工具載入方式變了",
        "miss_messages_rewritten": "前面對話被改",
        "miss_ttl_expired_5m": "閒置超過5分鐘",
        "miss_ttl_expired_1h": "閒置超過1小時",
        "miss_likely_server_side": "沒改東西,可能是伺服器端",
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
        "mix_images": "图片 {n} 张",
        "mix_tools": "读文件与命令输出 {n}%",
        "total": "累计",
        "in_short": "问:",
        "out_short": "答:",
        "this_turn": "本轮",
        "cached": "缓存:",
        "cache_hit": "缓存:",
        "cache_miss": "刚失效:",
        "miss_system_prompt_changed": "系统提示改了",
        "miss_tools_changed": "工具换了",
        "miss_model_changed": "换了模型",
        "miss_fast_mode_changed": "切换快速模式",
        "miss_cache_scope_or_ttl_changed": "缓存规则变了",
        "miss_betas_changed": "测试功能变了",
        "miss_effort_changed": "换了思考强度",
        "miss_thinking_mode_changed": "开关思考",
        "miss_thinking_display_changed": "思考显示变了",
        "miss_auto_mode_changed": "切换自动模式",
        "miss_overage_changed": "额度状态变了",
        "miss_extra_body_changed": "请求字段变了",
        "miss_defer_loading_changed": "工具加载方式变了",
        "miss_messages_rewritten": "前面对话被改",
        "miss_ttl_expired_5m": "闲置超过5分钟",
        "miss_ttl_expired_1h": "闲置超过1小时",
        "miss_likely_server_side": "没改东西,可能是服务器端",
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
        "mix_images": "Images {n}",
        "mix_tools": "Files & commands {n}%",
        "total": "Total",
        "in_short": "in:",
        "out_short": "out:",
        "this_turn": "this turn",
        "cached": "Cached:",
        "cache_hit": "Cache:",
        "cache_miss": "missed:",
        "miss_system_prompt_changed": "system prompt changed",
        "miss_tools_changed": "tools changed",
        "miss_model_changed": "model changed",
        "miss_fast_mode_changed": "fast mode toggled",
        "miss_cache_scope_or_ttl_changed": "cache scope/TTL changed",
        "miss_betas_changed": "betas changed",
        "miss_effort_changed": "effort changed",
        "miss_thinking_mode_changed": "thinking toggled",
        "miss_thinking_display_changed": "thinking display changed",
        "miss_auto_mode_changed": "auto mode toggled",
        "miss_overage_changed": "usage-limit state changed",
        "miss_extra_body_changed": "request fields changed",
        "miss_defer_loading_changed": "deferred tool loading changed",
        "miss_messages_rewritten": "earlier messages changed",
        "miss_ttl_expired_5m": "idle past 5m TTL",
        "miss_ttl_expired_1h": "idle past 1h TTL",
        "miss_likely_server_side": "unchanged, likely server-side",
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
        "mix_images": "画像 {n} 枚",
        "mix_tools": "ファイル・コマンド出力 {n}%",
        "total": "累計",
        "in_short": "入:",
        "out_short": "出:",
        "this_turn": "今回",
        "cached": "キャッシュ:",
        "cache_hit": "キャッシュ:",
        "cache_miss": "失効:",
        "miss_system_prompt_changed": "システム指示変更",
        "miss_tools_changed": "ツール変更",
        "miss_model_changed": "モデル変更",
        "miss_fast_mode_changed": "高速モード切替",
        "miss_cache_scope_or_ttl_changed": "キャッシュ範囲/TTL変更",
        "miss_betas_changed": "ベータ機能変更",
        "miss_effort_changed": "思考強度変更",
        "miss_thinking_mode_changed": "思考切替",
        "miss_thinking_display_changed": "思考表示変更",
        "miss_auto_mode_changed": "自動モード切替",
        "miss_overage_changed": "利用上限の状態変更",
        "miss_extra_body_changed": "リクエスト項目変更",
        "miss_defer_loading_changed": "ツール遅延読込変更",
        "miss_messages_rewritten": "以前のメッセージ変更",
        "miss_ttl_expired_5m": "5分TTL超過",
        "miss_ttl_expired_1h": "1時間TTL超過",
        "miss_likely_server_side": "変更なし,サーバー側の可能性",
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
        "mix_images": "이미지 {n}장",
        "mix_tools": "파일·명령 출력 {n}%",
        "total": "누적",
        "in_short": "입:",
        "out_short": "출:",
        "this_turn": "이번 턴",
        "cached": "캐시:",
        "cache_hit": "캐시:",
        "cache_miss": "만료:",
        "miss_system_prompt_changed": "시스템 지침 변경",
        "miss_tools_changed": "도구 변경",
        "miss_model_changed": "모델 변경",
        "miss_fast_mode_changed": "빠른 모드 전환",
        "miss_cache_scope_or_ttl_changed": "캐시 범위/TTL 변경",
        "miss_betas_changed": "베타 기능 변경",
        "miss_effort_changed": "사고 강도 변경",
        "miss_thinking_mode_changed": "사고 전환",
        "miss_thinking_display_changed": "사고 표시 변경",
        "miss_auto_mode_changed": "자동 모드 전환",
        "miss_overage_changed": "사용 한도 상태 변경",
        "miss_extra_body_changed": "요청 필드 변경",
        "miss_defer_loading_changed": "도구 지연 로딩 변경",
        "miss_messages_rewritten": "이전 메시지 변경",
        "miss_ttl_expired_5m": "5분 TTL 초과",
        "miss_ttl_expired_1h": "1시간 TTL 초과",
        "miss_likely_server_side": "변경 없음, 서버 측 추정",
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
    "green": "\033[38;5;80m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "blue": "\033[38;5;39m",
    "magenta": "\033[38;5;111m",
    "peach": "\033[38;5;216m",
    "grey": "\033[38;5;240m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}
# A separator only marks a break; it should not compete with the numbers.
SEP = f" {C['grey']}|{C['reset']} "


def _windows_system_lang() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        import locale as _locale

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return ""
        lang_id = int(windll.kernel32.GetUserDefaultUILanguage())
        return _locale.windows_locale.get(lang_id, "") or ""
    except Exception:
        return ""


def _statusline_detect_lang(env: Optional[Dict[str, str]] = None) -> str:
    source = os.environ if env is None else env
    raw = ""
    # Windows 上的 LANG 多半是 Git Bash / MSYS 帶進來的，不代表使用者的系統語言。
    keys = (
        ("USAGE_LANG", "TT_LANG") if sys.platform == "win32" else ("USAGE_LANG", "TT_LANG", "LANG")
    )
    for key in keys:
        value = source.get(key, "").strip()
        if value:
            raw = value
            break
    if not raw and env is None:
        raw = _windows_system_lang()
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
    lock would run save()'s read-modify-write unsynchronized.
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
        locked = False
        deadline = time.monotonic() + _LOCK_TIMEOUT_S
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN) or time.monotonic() >= deadline:
                    break
                time.sleep(_LOCK_POLL_INTERVAL_S)
        try:
            yield
        finally:
            if locked:
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


def _conout_columns() -> Optional[int]:
    """Return the active Windows console window width, if one is available."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _CSBI(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes._COORD),
                ("dwCursorPosition", wintypes._COORD),
                ("wAttributes", wintypes.WORD),
                ("srWindow", wintypes.SMALL_RECT),
                ("dwMaximumWindowSize", wintypes._COORD),
            ]

        win_dll = getattr(ctypes, "WinDLL", None)
        if win_dll is None:
            return None
        kernel32 = win_dll("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.restype = wintypes.HANDLE
        get_console_info = kernel32.GetConsoleScreenBufferInfo
        get_console_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_CSBI)]
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]

        handle = create_file(
            "CONOUT$",
            0x80000000 | 0x40000000,
            0x00000001 | 0x00000002,
            None,
            3,
            0,
            None,
        )
        invalid_handle_value = ctypes.c_void_p(-1).value
        if handle in (None, 0, -1, invalid_handle_value):
            return None
        try:
            csbi = _CSBI()
            if not get_console_info(handle, ctypes.byref(csbi)):
                return None
            columns = csbi.srWindow.Right - csbi.srWindow.Left + 1
            return columns if columns > 0 else None
        finally:
            close_handle(handle)
    except Exception:
        return None


def get_width() -> int:
    try:
        return max(1, os.get_terminal_size(2).columns - 4)
    except Exception:
        if os.name == "nt":
            columns = _conout_columns()
            if columns:
                return max(1, columns - 4)
        return 116


def color_by_pct(pct: float) -> str:
    if pct < 50:
        return "\033[38;5;42m"
    if pct < 80:
        return "\033[38;5;214m"
    return "\033[38;5;160m"


def context_color(pct: float, tokens: Optional[float] = None) -> str:
    if pct >= 80 or (tokens is not None and tokens >= 400_000):
        return "\033[38;5;160m"
    if pct >= 50 or (tokens is not None and tokens >= 200_000):
        return "\033[38;5;214m"
    return "\033[38;5;42m"


def color_by_pct_inverted(pct: float) -> str:
    # Line 2 is secondary info: a healthy cache stays as quiet as its neighbours,
    # only a degraded one is allowed to draw the eye.
    if pct >= 80:
        return f"{C['dim']}{C['magenta']}"
    if pct >= 50:
        return "\033[38;5;214m"
    return "\033[38;5;160m"


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


def progress_bar(
    value: Any,
    bar_width: int = 8,
    color_func: Callable[[float], str] = color_by_pct,
) -> str:
    filled_char = "■"
    empty_char = "□"
    if value is None:
        return f"{C['grey']}{empty_char * bar_width}{C['reset']} n/a"
    pct = max(0.0, min(100.0, float(value)))
    filled = round(pct / 100 * bar_width)
    return (
        f"{color_func(pct)}{filled_char * filled}{C['reset']}"
        f"{C['grey']}{empty_char * (bar_width - filled)}{C['reset']} "
        f"{color_func(pct)}{pct:.0f}%{C['reset']}"
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


def safe_text(value: str) -> str:
    """Drop control characters so untrusted names cannot rewrite the status line."""
    return "".join(ch for ch in value if ch.isprintable())


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


# The CJK ranges of analyzer/diagnoser.py's _is_cjk, as one class so the count
# runs in the regex engine instead of a Python call per character.
_CJK_RE = re.compile(
    "[\u1100-\u11ff\u3040-\u309f\u30a0-\u30ff\u3130-\u318f\u31f0-\u31ff"
    "\u3400-\u4dbf\u4e00-\u9fff\ua960-\ua97f\uac00-\ud7af\uf900-\ufaff"
    "\U0001aff0-\U0001afff\U0001b000-\U0001b16f\U00020000-\U0002ee5d"
    "\U00030000-\U000323af]"
)


def _estimate_tokens(text: str) -> int:
    cjk_chars = len(_CJK_RE.findall(text))
    return cjk_chars + (len(text) - cjk_chars) // 4


def read_mix(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Count complete transcript records, preserving an incremental byte offset."""
    session_id, transcript = data.get("session_id"), data.get("transcript_path")
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        return None
    if not isinstance(transcript, str) or not transcript:
        return None
    temporary = None
    try:
        path = os.path.join(MIX_DIR, session_id + ".json")
        previous: Dict[str, Any] = {}
        try:
            with open(path, encoding="utf-8") as cache:
                previous = json.load(cache)
        except (FileNotFoundError, ValueError):
            pass
        if not isinstance(previous, dict):
            previous = {}
        if previous and (
            previous.get("sessionId") != session_id
            or not isinstance(previous.get("transcript"), str)
            or any(
                type(previous.get(k)) is not int or previous[k] < 0
                for k in ("offset", "size", "images", "toolTokens")
            )
            or previous["offset"] > previous["size"]
            or type(previous.get("complete")) is not bool
            or type(previous.get("updatedAt")) not in (int, float)
            or not math.isfinite(previous["updatedAt"])
            or previous["updatedAt"] < 0
        ):
            # A corrupt or foreign cache starts over rather than pinning the label off.
            previous = {}
        with open(transcript, "rb") as source:
            size = os.fstat(source.fileno()).st_size
            offset = previous.get("offset", 0)
            images, tool_tokens = previous.get("images", 0), previous.get("toolTokens", 0)
            if previous.get("transcript") != transcript or size < offset:
                offset, images, tool_tokens = 0, 0, 0
            source.seek(offset)
            pending = source.read(min(size - offset, MIX_READ_BUDGET))
            # A single record longer than the budget is read whole, never split.
            while b"\n" not in pending and offset + len(pending) < size:
                more = source.read(min(size - offset - len(pending), MIX_READ_BUDGET))
                if not more:
                    break
                pending += more
        consumed = pending.rfind(b"\n") + 1
        complete = offset + len(pending) >= size
        for line in pending[:consumed].splitlines():
            # A line torn by a crash is skipped; failing on it would re-read the
            # same budget on every refresh and never get past it.
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("isSidechain") is True:
                continue
            if (
                record.get("type") == "system" and record.get("subtype") == "compact_boundary"
            ) or record.get("isCompactSummary") is True:
                images, tool_tokens = 0, 0
                continue
            content = _as_dict(record.get("message")).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "image" and record.get("type") == "user":
                    images += 1
                elif block.get("type") == "tool_result":
                    result = block.get("content")
                    if isinstance(result, str):
                        tool_tokens += _estimate_tokens(result)
                    elif isinstance(result, list):
                        for item in result:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "image":
                                images += 1
                            elif item.get("type") == "text" and isinstance(item.get("text"), str):
                                tool_tokens += _estimate_tokens(item["text"])
        mix = {
            "sessionId": session_id,
            "transcript": transcript,
            "offset": offset + consumed,
            "size": size,
            "images": images,
            "toolTokens": tool_tokens,
            "complete": complete,
            "updatedAt": time.time() * 1000,
        }
        if all(previous.get(k) == mix[k] for k in mix if k != "updatedAt"):
            return previous
        os.makedirs(MIX_DIR, exist_ok=True)
        if not previous:
            # One file per session; sweep the old ones only when a new one starts.
            cutoff = time.time() - MIX_STALE_SECONDS
            for name in os.listdir(MIX_DIR):
                stale = os.path.join(MIX_DIR, name)
                with suppress(OSError):
                    if name.endswith(".json") and os.path.getmtime(stale) < cutoff:
                        os.unlink(stale)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=MIX_DIR, delete=False
        ) as target:
            temporary = target.name
            json.dump(mix, target)
        os.replace(temporary, path)
        return mix
    except Exception as exc:
        _debug("context mix failed", exc)
        return None
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)


def _render_core(data: Dict[str, Any], now: datetime) -> str:
    width = get_width()
    ctx = _as_dict(data.get("context_window"))
    bar_w = 8 if width >= 100 else 6 if width >= 60 else 4
    lang = _detect_lang()

    line1: List[str] = []
    project = _as_dict(data.get("workspace")).get("project_dir", "")
    if isinstance(project, str) and project:
        name = safe_text(os.path.basename(project))
        branch = safe_text(git_branch(project))
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
                reset_dt = datetime.fromtimestamp(resets_at)
                clock = f"{reset_dt:%H:%M}"
                if reset_dt.date() != datetime.fromtimestamp(now.timestamp()).date():
                    clock = f"{reset_dt.month}/{reset_dt.day} {clock}"
                if lang in ("zh-TW", "zh-CN"):
                    reset_str = f" {clock}({_t('remaining_prefix')}{fmt_duration(remain)})"
                else:
                    reset_str = f" {clock}({fmt_duration(remain)} {_t('remaining_prefix')})"
                reset_str = f" {C['dim']}{reset_str[1:]}{C['reset']}"
        rl_parts.append(
            (
                f"{C['blue']}{label}:{C['reset']}{progress_bar(pct_float, bar_w)}{reset_str}",
                f"{C['blue']}{label}:{C['reset']}{progress_bar(pct_float, bar_w)}",
                f"{C['blue']}{label}:{C['reset']}{pct_float:.0f}%",
            )
        )

    mix = read_mix(data)
    ctx_parts: List[str] = []
    ctx_label_part = ""
    ctx_pct = _as_float(ctx.get("used_percentage"))
    if ctx_pct is not None:
        size = ctx.get("context_window_size", 0)
        # total_input_tokens was a session-wide sum in older Claude Code builds;
        # percent x window always matches the figure on screen.
        window_size = _as_float(size)
        tokens = ctx_pct / 100 * window_size if window_size is not None else None
        ctx_parts = [
            f"{C['blue']}{_t('context')}:{C['reset']}"
            f"{progress_bar(ctx_pct, bar_w, color_func=lambda pct: context_color(pct, tokens))} "
            f"{C['dim']}/ {fmt_tokens(size)}{C['reset']}",
            f"{C['blue']}{_t('context')}:{C['reset']}{ctx_pct:.0f}%",
        ]
        if (
            mix is not None
            and mix["complete"]
            and context_color(ctx_pct, tokens) != context_color(0)
        ):
            parts = []
            if mix["images"] >= 1:
                parts.append(_t("mix_images").format(n=mix["images"]))
            share = (
                int(min(100, max(0, mix["toolTokens"] / tokens * 100)) + 0.5)
                if tokens and tokens > 0
                else 0
            )
            parts.append(_t("mix_tools").format(n=share))
            ctx_label_part = f"{ctx_parts[0]} · {C['dim']}{' · '.join(parts)}{C['reset']}"

    full = line1 + [p[0] for p in rl_parts]
    candidate = SEP.join(full)
    if vlen(candidate) <= width:
        line1 = full
    else:
        no_reset = line1 + [p[1] for p in rl_parts]
        candidate = SEP.join(no_reset)
        line1 = no_reset if vlen(candidate) <= width else line1 + [p[2] for p in rl_parts]

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
        line3.append(f"{C['dim']}{C['magenta']}{safe_text(model_name)}{C['reset']}")

    cache_pct_part = ""
    cache_miss_part = ""
    prompt_cache = _as_dict(data.get("prompt_cache"))
    if prompt_cache.get("caching_observed") is True:
        hit_ratio = _as_float(prompt_cache.get("hit_ratio"))
        if hit_ratio is not None:
            cache_pct_part = (
                f"{C['dim']}{C['magenta']}{_t('cache_hit')}{C['reset']}"
                f"{color_by_pct_inverted(hit_ratio * 100)}{hit_ratio * 100:.0f}%{C['reset']}"
            )
            last_miss_at = prompt_cache.get("last_miss_at")
            causes = _as_dict(prompt_cache.get("last_miss_cause")).get("causes")
            if (
                isinstance(last_miss_at, (int, float))
                and not isinstance(last_miss_at, bool)
                and 0 <= now.timestamp() - last_miss_at <= 600
                and isinstance(causes, list)
            ):
                for cause in causes:
                    if isinstance(cause, str) and f"miss_{cause}" in STATUSLINE_TRANSLATIONS[lang]:
                        reason = safe_text(f"{_t('cache_miss')}{_t(f'miss_{cause}')}")
                        cache_miss_part = (
                            f"{cache_pct_part} {C['dim']}{C['magenta']}{reason}{C['reset']}"
                        )
                        break
            line3.append(cache_miss_part or cache_pct_part)

    if ctx_parts:
        line3.append(ctx_label_part or ctx_parts[0])

    # The label goes first, so a narrow terminal keeps the bar it annotates.
    if vlen(SEP.join(line3)) > width and ctx_label_part:
        line3[-1] = ctx_parts[0]

    if vlen(SEP.join(line3)) > width and cache_miss_part:
        line3 = [cache_pct_part if p == cache_miss_part else p for p in line3]
    if vlen(SEP.join(line3)) > width and duration_part:
        line3 = [p for p in line3 if p != duration_part]
    if vlen(SEP.join(line3)) > width and cache_pct_part:
        line3 = [p for p in line3 if p != cache_pct_part]
    if len(ctx_parts) > 1 and vlen(SEP.join(line3)) > width:
        line3[-1] = ctx_parts[1]

    update_version = _read_update_hint(now.timestamp())
    if update_version and (line1 or line3):
        line3.append(
            f"{C['cyan']}🆕 v{safe_text(update_version)} "
            f"{_t('update_available_suffix')}{C['reset']}"
        )

    output = [SEP.join(line) for line in (line1, line3) if line]
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
    _configure_windows_utf8_output()
    try:
        raw = _read_stdin_utf8()
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
