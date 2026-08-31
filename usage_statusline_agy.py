#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# ruff: noqa: UP006, UP035, UP045
"""Render Antigravity CLI's stdin payload as a usage-style status line.

This deployed script intentionally uses only the Python standard library and
does not read or write files other than reading a Git HEAD for the branch name.
"""

from __future__ import annotations

import json
import math
import os
import sys
from contextlib import suppress
from typing import Any, Dict, List, Optional, Tuple, cast

STATUSLINE_TRANSLATIONS = {
    "zh-TW": {
        "five_hour": "5小時",
        "weekly": "本週",
        "context": "對話窗",
        "remaining_prefix": "剩",
        "effort_high": "深思",
        "effort_normal": "標準",
        "effort_low": "速答",
    },
    "zh-CN": {
        "five_hour": "5小时",
        "weekly": "本周",
        "context": "对话窗",
        "remaining_prefix": "剩",
        "effort_high": "深思",
        "effort_normal": "标准",
        "effort_low": "速答",
    },
    "en": {
        "five_hour": "5h",
        "weekly": "Weekly",
        "context": "Context",
        "remaining_prefix": "left",
        "effort_high": "Deep",
        "effort_normal": "Standard",
        "effort_low": "Quick",
    },
    "ja": {
        "five_hour": "5時間",
        "weekly": "週間",
        "context": "コンテキスト",
        "remaining_prefix": "残り",
        "effort_high": "熟考",
        "effort_normal": "標準",
        "effort_low": "即答",
    },
    "ko": {
        "five_hour": "5시간",
        "weekly": "주간",
        "context": "컨텍스트",
        "remaining_prefix": "남음",
        "effort_high": "깊은 사고",
        "effort_normal": "표준",
        "effort_low": "빠른 답변",
    },
}
C = {
    "green": "\033[38;5;80m",
    "blue": "\033[38;5;39m",
    "magenta": "\033[38;5;111m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _configure_windows_utf8_output() -> None:
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, OSError, ValueError):
            cast(Any, stream).reconfigure(encoding="utf-8")


def _read_stdin_utf8() -> str:
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    return cast(bytes, buffer.read()).decode("utf-8", "replace")


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
    table = STATUSLINE_TRANSLATIONS.get(_detect_lang(), STATUSLINE_TRANSLATIONS["en"])
    return table.get(key, key)


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


def color_by_pct(pct: float) -> str:
    if pct < 50:
        return "\033[38;5;42m"
    if pct < 80:
        return "\033[38;5;214m"
    return "\033[38;5;160m"


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
        days = int(seconds // 86400)
        remainder = int(seconds % 86400)
        return f"{days}d{remainder // 3600}h"
    if seconds >= 3600:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h{minutes}m"
    if seconds >= 60:
        return f"{int(seconds // 60)}min"
    return f"{int(seconds)}s"


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
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _terminal_width(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 116


def _quota_keys(data: Dict[str, Any]) -> Tuple[str, str]:
    model_id = _as_dict(data.get("model")).get("id", "")
    if isinstance(model_id, str) and "gemini" in model_id.lower():
        return "gemini-5h", "gemini-weekly"
    return "3p-5h", "3p-weekly"


def _quota_parts(data: Dict[str, Any], bar_width: int) -> List[Tuple[str, str, str]]:
    quota = _as_dict(data.get("quota"))
    lang = _detect_lang()
    parts: List[Tuple[str, str, str]] = []
    five_hour_key, weekly_key = _quota_keys(data)
    for key, label in (
        (five_hour_key, _t("five_hour")),
        (weekly_key, _t("weekly")),
    ):
        entry = _as_dict(quota.get(key))
        remaining = _as_float(entry.get("remaining_fraction"))
        if remaining is None:
            continue
        pct = max(0.0, min(100.0, (1.0 - remaining) * 100.0))
        reset = _as_float(entry.get("reset_in_seconds"))
        reset_str = ""
        if reset is not None and reset > 0:
            if lang in ("zh-TW", "zh-CN"):
                reset_str = f" ({_t('remaining_prefix')}{fmt_duration(reset)})"
            else:
                reset_str = f" ({fmt_duration(reset)} {_t('remaining_prefix')})"
        parts.append(
            (
                f"{C['blue']}{label}:{C['reset']}{progress_bar(pct, bar_width)}{reset_str}",
                f"{C['blue']}{label}:{C['reset']}{progress_bar(pct, bar_width)}",
                f"{C['blue']}{label}:{C['reset']}{pct:.0f}%",
            )
        )
    return parts


_EFFORT_SUFFIXES = {"(low)": "low", "(medium)": "medium", "(high)": "high"}


def _split_effort_suffix(name: str) -> Tuple[str, Optional[str]]:
    """Antigravity 的 display_name 自帶英文 "(High)"，等級由下面用當地語言另外標。"""
    head, sep, tail = name.rpartition(" ")
    effort = _EFFORT_SUFFIXES.get(tail.lower()) if sep else None
    return (head, effort) if effort else (name, None)


def _render_core(data: Dict[str, Any]) -> str:
    width = _terminal_width(data.get("terminal_width"))
    bar_width = 8 if width >= 100 else 6 if width >= 60 else 4
    project_parts: List[str] = []
    workspace = _as_dict(data.get("workspace"))
    project = workspace.get("current_dir") or data.get("cwd")
    if isinstance(project, str) and project:
        name = safe_text(os.path.basename(os.path.normpath(project)))
        branch = safe_text(git_branch(project))
        if branch:
            project_parts.append(
                f"{C['green']}{name}{C['reset']}({C['magenta']}{branch}{C['reset']})"
            )
        elif name:
            project_parts.append(f"{C['green']}{name}{C['reset']}")

    quota_parts = _quota_parts(data, bar_width)
    context = _as_dict(data.get("context_window"))
    context_pct = _as_float(context.get("used_percentage"))
    context_parts: List[str] = []
    if context_pct is not None:
        context_pct = max(0.0, min(100.0, context_pct))
        context_parts = [
            f"{C['blue']}{_t('context')}:{C['reset']}"
            f"{progress_bar(context_pct, bar_width)} / "
            f"{fmt_tokens(context.get('context_window_size', 0))}",
            f"{C['blue']}{_t('context')}:{C['reset']}{context_pct:.0f}%",
        ]

    model_parts: List[str] = []
    model = _as_dict(data.get("model"))
    model_name = model.get("display_name") or model.get("id")
    if isinstance(model_name, str) and model_name:
        model_name, suffix_effort = _split_effort_suffix(model_name)
        effort = model.get("effort")
        if not (isinstance(effort, str) and effort):
            effort = suffix_effort
        if isinstance(effort, str) and effort:
            effort_label = {
                "low": _t("effort_low"),
                "medium": _t("effort_normal"),
                "high": _t("effort_high"),
            }.get(effort.lower(), effort)
            model_name += f"/{effort_label}"
        model_parts.append(f"{C['dim']}{C['magenta']}{safe_text(model_name)}{C['reset']}")

    full = project_parts + [part[0] for part in quota_parts] + context_parts[:1] + model_parts
    if vlen(" | ".join(full)) <= width:
        selected = full
    else:
        no_reset = (
            project_parts + [part[1] for part in quota_parts] + context_parts[:1] + model_parts
        )
        if vlen(" | ".join(no_reset)) <= width:
            selected = no_reset
        else:
            selected = (
                project_parts
                + [part[2] for part in quota_parts]
                + context_parts[1:2]
                + model_parts
            )
    return " | ".join(selected) if selected else "usage"


def render(data: Dict[str, Any]) -> str:
    try:
        return _render_core(data)
    except Exception:
        return "usage"


def main() -> None:
    _configure_windows_utf8_output()
    try:
        raw = _read_stdin_utf8()
        if not raw.strip():
            return
        data = json.loads(raw)
        if not isinstance(data, dict):
            print("usage")
            return
        print(render(data))
    except Exception:
        print("usage")


if __name__ == "__main__":
    main()
