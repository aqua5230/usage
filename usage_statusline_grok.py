#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

# ruff: noqa: UP006, UP017, UP035, UP045
"""Render Grok CLI's stdin payload as a usage-style status line.

This deployed script intentionally uses only the Python standard library.  Grok
does not send rate-limit data in its stdin payload, so the current-week quota is
read from the CLI's own local unified log.
"""

from __future__ import annotations

import json
import math
import os
import sys
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, cast

STATUSLINE_TRANSLATIONS = {
    "zh-TW": {
        "weekly": "週配額",
        "context": "對話窗",
        "session_duration": "會話時長",
        "remaining_prefix": "剩",
        "effort_high": "深思",
        "effort_normal": "標準",
        "effort_low": "速答",
    },
    "zh-CN": {
        "weekly": "周配额",
        "context": "对话窗",
        "session_duration": "会话时长",
        "remaining_prefix": "剩",
        "effort_high": "深思",
        "effort_normal": "标准",
        "effort_low": "速答",
    },
    "en": {
        "weekly": "Weekly",
        "context": "Context",
        "session_duration": "Session",
        "remaining_prefix": "left",
        "effort_high": "Deep",
        "effort_normal": "Standard",
        "effort_low": "Quick",
    },
    "ja": {
        "weekly": "週枠",
        "context": "コンテキスト",
        "session_duration": "セッション",
        "remaining_prefix": "残り",
        "effort_high": "熟考",
        "effort_normal": "標準",
        "effort_low": "即答",
    },
    "ko": {
        "weekly": "주간 할당량",
        "context": "컨텍스트",
        "session_duration": "세션 시간",
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
GROK_LOG_PATH = Path(os.path.expanduser("~/.grok/logs/unified.jsonl"))
_BILLING_MESSAGE = "billing: fetched credits config"
_MAX_TAIL_LINES = 10_000
_MAX_TAIL_BYTES = 4 * 1024 * 1024
_TAIL_CHUNK_BYTES = 64 * 1024


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
    pct = max(0.0, min(100.0, float(value)))
    filled = round(pct / 100 * bar_width)
    return (
        f"{color_by_pct(pct)}{'■' * filled}{C['reset']}"
        f"{'□' * (bar_width - filled)} "
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


def _terminal_width() -> int:
    try:
        return max(1, int(os.environ.get("COLUMNS", "116")))
    except ValueError:
        return 116


def _tail_lines(path: Path) -> Iterator[bytes]:
    """Yield recent JSONL lines newest first without buffering the entire log."""
    with path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        position = log_file.tell()
        remaining = b""
        scanned_bytes = 0
        scanned_lines = 0
        while position > 0 and scanned_bytes < _MAX_TAIL_BYTES and scanned_lines < _MAX_TAIL_LINES:
            chunk_size = min(_TAIL_CHUNK_BYTES, position, _MAX_TAIL_BYTES - scanned_bytes)
            position -= chunk_size
            log_file.seek(position)
            chunk = log_file.read(chunk_size)
            scanned_bytes += len(chunk)
            parts = (chunk + remaining).split(b"\n")
            remaining = parts[0]
            for line in reversed(parts[1:]):
                scanned_lines += 1
                if line:
                    yield line
                if scanned_lines >= _MAX_TAIL_LINES:
                    return
        if remaining and scanned_lines < _MAX_TAIL_LINES:
            yield remaining


def _parse_iso8601(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _read_weekly_quota() -> Optional[Tuple[float, float]]:
    """Return the latest local used percentage and seconds until its weekly reset."""
    try:
        for line in _tail_lines(GROK_LOG_PATH):
            try:
                payload = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                continue
            if not isinstance(payload, dict) or payload.get("msg") != _BILLING_MESSAGE:
                continue
            config = _as_dict(_as_dict(payload.get("ctx")).get("config"))
            # xAI drops creditUsagePercent from the snapshot when the weekly
            # usage is exactly zero, which is what a freshly reset week looks like.
            used = _as_float(config.get("creditUsagePercent", 0.0))
            period = _as_dict(config.get("currentPeriod"))
            end = period.get("end")
            if used is None or not 0.0 <= used <= 100.0 or not isinstance(end, str):
                return None
            reset_at = _parse_iso8601(end)
            if reset_at is None:
                return None
            remaining = (reset_at - datetime.now(timezone.utc)).total_seconds()
            return (used, remaining) if remaining >= 0 else None
    except OSError:
        return None
    return None


_EFFORT_SUFFIXES = {"(low)": "low", "(medium)": "medium", "(high)": "high"}


def _split_effort_suffix(name: str) -> Tuple[str, Optional[str]]:
    """Display names carry English effort suffixes; render the local label instead."""
    head, sep, tail = name.rpartition(" ")
    effort = _EFFORT_SUFFIXES.get(tail.lower()) if sep else None
    return (head, effort) if effort else (name, None)


def _render_core(data: Dict[str, Any]) -> str:
    width = _terminal_width()
    bar_width = 8 if width >= 100 else 6 if width >= 60 else 4
    project_parts: List[str] = []
    workspace = _as_dict(data.get("workspace"))
    project = workspace.get("repo_root") or workspace.get("current_dir")
    branch = workspace.get("branch")
    if isinstance(project, str) and project:
        name = safe_text(os.path.basename(os.path.normpath(project)))
        if name:
            if isinstance(branch, str) and branch:
                project_parts.append(
                    f"{C['green']}{name}{C['reset']}({C['magenta']}{safe_text(branch)}{C['reset']})"
                )
            else:
                project_parts.append(f"{C['green']}{name}{C['reset']}")

    quota_parts: List[Tuple[str, str, str]] = []
    quota = _read_weekly_quota()
    if quota is not None:
        used, seconds = quota
        reset = ""
        if _detect_lang() in ("zh-TW", "zh-CN"):
            reset = f" ({_t('remaining_prefix')}{fmt_duration(seconds)})"
        else:
            reset = f" ({fmt_duration(seconds)} {_t('remaining_prefix')})"
        label = f"{C['blue']}{_t('weekly')}:{C['reset']}"
        quota_parts.append(
            (
                f"{label}{progress_bar(used, bar_width)}{reset}",
                f"{label}{progress_bar(used, bar_width)}",
                f"{label}{used:.0f}%",
            )
        )

    context_parts: List[str] = []
    context = _as_dict(data.get("context_window"))
    context_pct = _as_float(context.get("used_percentage"))
    context_size = _as_float(context.get("context_window_size"))
    if context_pct is not None and context_size is not None and context_size >= 0:
        context_pct = max(0.0, min(100.0, context_pct))
        label = f"{C['blue']}{_t('context')}:{C['reset']}"
        context_parts = [
            f"{label}{progress_bar(context_pct, bar_width)} / {fmt_tokens(context_size)}",
            f"{label}{context_pct:.0f}%",
        ]

    duration_parts: List[str] = []
    duration_ms = _as_float(_as_dict(data.get("cost")).get("total_duration_ms"))
    if duration_ms is not None and duration_ms >= 0:
        duration_parts.append(
            f"{C['blue']}{_t('session_duration')}:{C['reset']}{fmt_duration(duration_ms / 1000)}"
        )

    model_parts: List[str] = []
    model = _as_dict(data.get("model"))
    model_name = model.get("display_name") or model.get("id")
    if isinstance(model_name, str) and model_name:
        model_name, suffix_effort = _split_effort_suffix(model_name)
        effort = _as_dict(data.get("effort")).get("level")
        if not (isinstance(effort, str) and effort):
            effort = suffix_effort
        if isinstance(effort, str) and effort:
            effort_label = {
                "low": _t("effort_low"),
                "normal": _t("effort_normal"),
                "medium": _t("effort_normal"),
                "high": _t("effort_high"),
            }.get(effort.lower(), effort)
            model_name += f"/{effort_label}"
        model_parts.append(f"{C['dim']}{C['magenta']}{safe_text(model_name)}{C['reset']}")

    first_full = project_parts + [part[0] for part in quota_parts] + context_parts[:1]
    first_no_reset = project_parts + [part[1] for part in quota_parts] + context_parts[:1]
    first_minimal = project_parts + [part[2] for part in quota_parts] + context_parts[1:2]
    if vlen(" | ".join(first_full)) <= width:
        first = first_full
    elif vlen(" | ".join(first_no_reset)) <= width:
        first = first_no_reset
    else:
        first = first_minimal

    second = duration_parts + model_parts
    lines = [" | ".join(first)] if first else []
    if second:
        lines.append(" | ".join(second))
    return "\n".join(lines) if lines else "usage"


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
