# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

import csv
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import codex_loader
from adapters import claude, codex
from adapters.rate_limits import load_rate_limits as load_claude_rate_limits
from adapters.registry import detect_agents
from adapters.types import AgentInfo, RateLimits
from analyzer.aggregator import aggregate_daily, aggregate_monthly, aggregate_sessions, aggregate_weekly
from analyzer.blocks import analyze_blocks, calculate_p90
from setup_hook import is_claude_setup, is_codex_setup, is_setup, setup, unsetup
from i18n import t
from ui.tables import (
    AGENT_LABEL, console, render_daily, render_dashboard,
    render_monthly, render_sessions, render_tab_bar, render_weekly,
)

AGENT_ALIASES = {"claude": "claude-code", "codex": "codex"}
AGENT_LOADERS = {"claude-code": claude, "codex": codex}


def _load_codex_rate_limits() -> RateLimits | None:
    rate_limits = codex_loader.load_rate_limits()
    if rate_limits is None:
        return None
    return RateLimits(
        five_hour_pct=rate_limits.five_hour_pct,
        five_hour_resets_at=(
            int(rate_limits.five_hour_resets_at)
            if rate_limits.five_hour_resets_at is not None
            else None
        ),
        seven_day_pct=rate_limits.seven_day_pct,
        seven_day_resets_at=(
            int(rate_limits.seven_day_resets_at)
            if rate_limits.seven_day_resets_at is not None
            else None
        ),
        model=rate_limits.model or "",
        updated_at=rate_limits.updated_at,
    )


RATE_LIMIT_LOADERS = {"claude-code": load_claude_rate_limits, "codex": _load_codex_rate_limits}

SORT_KEYS = {
    "tokens": ("total_tokens", True),
    "cost": ("cost_usd", True),
    "messages": ("message_count", True),
    "sessions": ("session_count", True),
    "time": None,  # handled per-command
    "input": ("input_tokens", True),
    "output": ("output_tokens", True),
}

REPORT_HELP = """Usage: usage report [--last30|--all|--today|--last7|--week|--month] [--out PATH]

Generate an HTML usage report.

Options:
  --last30    Include the last 30 days (default)
  --all       Include all usage data
  --today     Include today only
  --last7     Include the last 7 days
  --week      Include this week
  --month     Include this month
  --out PATH  Save to a specific path
  -h, --help  Show this help
"""

EXPORT_HELP = """Usage: usage export [--daily|--weekly|--monthly|--sessions] [--out PATH]

Export aggregated usage data as CSV.

Options:
  --daily     Export daily usage (default)
  --weekly    Export weekly usage
  --monthly   Export monthly usage
  --sessions  Export session usage
  --out PATH  Save to a specific path
  -h, --help  Show this help
"""

_REPORT_EXPORT_OPTIONS = {
    "report": {
        "-h",
        "--help",
        "--last30",
        "--today",
        "--last7",
        "--week",
        "--month",
        "--all",
        "--out",
    },
    "export": {
        "-h",
        "--help",
        "--daily",
        "--weekly",
        "--monthly",
        "--sessions",
        "--out",
    },
}

EXPORT_FIELDS: dict[str, list[str]] = {
    "daily": [
        "agent_id", "date", "input_tokens", "output_tokens",
        "cache_creation_tokens", "cache_read_tokens", "total_tokens",
        "cost_usd", "session_count", "message_count",
    ],
    "weekly": [
        "agent_id", "week", "week_start", "week_end", "input_tokens",
        "output_tokens", "cache_creation_tokens", "cache_read_tokens",
        "total_tokens", "cost_usd", "session_count", "message_count",
    ],
    "monthly": [
        "agent_id", "month", "input_tokens", "output_tokens",
        "cache_creation_tokens", "cache_read_tokens", "total_tokens",
        "cost_usd", "session_count", "message_count",
    ],
    "sessions": [
        "agent_id", "session_id", "project", "model", "start_time",
        "end_time", "duration_minutes", "input_tokens", "output_tokens",
        "cache_creation_tokens", "cache_read_tokens", "total_tokens",
        "cost_usd", "message_count",
    ],
}


def _parse_sort_args(args: list[str]) -> tuple[list[str], str | None, bool]:
    """Extract --sort KEY and --asc from args, return (remaining, sort_key, descending)."""
    remaining = []
    sort_key = None
    descending = True
    i = 0
    while i < len(args):
        if args[i] == "--sort" and i + 1 < len(args):
            sort_key = args[i + 1].lower()
            i += 2
        elif args[i] == "--asc":
            descending = False
            i += 1
        elif args[i] == "--desc":
            descending = True
            i += 1
        else:
            remaining.append(args[i])
            i += 1
    return remaining, sort_key, descending


def _parse_report_args(args: list[str]) -> tuple[str, str | None, bool]:
    period = "last30"
    out_path, show_help = _parse_out_and_help(args, "report")
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in {"-h", "--help"}:
            pass
        elif arg == "--last30":
            period = "last30"
        elif arg == "--today":
            period = "today"
        elif arg == "--last7":
            period = "last7"
        elif arg == "--week":
            period = "week"
        elif arg == "--month":
            period = "month"
        elif arg == "--all":
            period = "all"
        elif _is_out_arg(arg):
            if arg == "--out":
                i += 1
        elif arg.startswith("-"):
            _exit_unknown_option("report", arg)
        else:
            console.print(f"[red]Error:[/red] unexpected report argument: {arg}")
            sys.exit(1)
        i += 1
    return period, out_path, show_help


def _parse_export_args(args: list[str]) -> tuple[str, str | None, bool]:
    export_type = "daily"
    out_path, show_help = _parse_out_and_help(args, "export")
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in {"-h", "--help"}:
            pass
        elif arg == "--daily":
            export_type = "daily"
        elif arg == "--weekly":
            export_type = "weekly"
        elif arg == "--monthly":
            export_type = "monthly"
        elif arg == "--sessions":
            export_type = "sessions"
        elif _is_out_arg(arg):
            if arg == "--out":
                i += 1
        elif arg.startswith("-"):
            _exit_unknown_option("export", arg)
        else:
            console.print(f"[red]Error:[/red] unexpected export argument: {arg}")
            sys.exit(1)
        i += 1
    return export_type, out_path, show_help


def _is_out_arg(arg: str) -> bool:
    return arg == "--out" or arg.startswith("--out=")


def _exit_unknown_option(command: str, arg: str) -> None:
    console.print(f"[red]Error:[/red] unknown {command} option: {arg}")
    sys.exit(1)


def _parse_out_and_help(args: list[str], command: str) -> tuple[str | None, bool]:
    out_path = None
    show_help = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in {"-h", "--help"}:
            show_help = True
        elif arg.startswith("--out="):
            out_path = arg[6:]
        elif arg == "--out":
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                console.print("[red]Error:[/red] --out requires a path")
                sys.exit(1)
            out_path = args[i + 1]
            i += 1
        elif arg.startswith("-") and arg not in _REPORT_EXPORT_OPTIONS[command]:
            _exit_unknown_option(command, arg)
        i += 1
    return out_path, show_help


def _csv_row(stat: Any, fields: list[str]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for field in fields:
        value = getattr(stat, field)
        if field in {"start_time", "end_time"}:
            value = value.isoformat()
        row[field] = value
    return row


def _write_export_csv(stats: list[Any], export_type: str, out_path: str | None) -> str | None:
    fields = EXPORT_FIELDS[export_type]
    if out_path:
        path = Path(out_path)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for stat in stats:
                writer.writerow(_csv_row(stat, fields))
        return str(path)

    writer = csv.DictWriter(sys.stdout, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for stat in stats:
        writer.writerow(_csv_row(stat, fields))
    return None


def _apply_sort(stats: list[Any], sort_key: str | None, descending: bool, default_attr: str, default_reverse: bool) -> None:
    if sort_key is None:
        stats.sort(key=lambda s: getattr(s, default_attr), reverse=default_reverse)
        return
    if sort_key not in SORT_KEYS:
        valid = ", ".join(SORT_KEYS.keys())
        console.print(f"[yellow]{t('unknown_sort_field', field=sort_key, valid=valid)}[/yellow]")
        stats.sort(key=lambda s: getattr(s, default_attr), reverse=default_reverse)
        return
    mapping = SORT_KEYS[sort_key]
    if mapping is None:
        stats.sort(key=lambda s: getattr(s, default_attr), reverse=descending)
    else:
        attr, _ = mapping
        stats.sort(key=lambda s: getattr(s, attr), reverse=descending)


def _load_entries(agent_id: str, hours_back: int = 0) -> list[Any]:
    loader = AGENT_LOADERS.get(agent_id)
    if loader is None:
        return []
    entries: list[Any] = loader.load_entries(hours_back=hours_back)
    return entries


def _aggregate_per_agent(agents: list[AgentInfo], agg_fn: Callable[[list[Any]], list[Any]]) -> list[Any]:
    stats: list[Any] = []
    for a in agents:
        entries = _load_entries(a.id)
        for s in agg_fn(entries):
            s.agent_id = a.id
            stats.append(s)
    return stats


def _show_agent_dashboard(agent_id: str) -> None:
    agent_name = AGENT_LABEL.get(agent_id, agent_id)
    data = _build_agent_data(agent_id, agent_name)
    if not data:
        console.print(f"[yellow]{t('no_token_data')}[/yellow]")
        return
    render_dashboard(**data)


def _build_agent_data(agent_id: str, agent_name: str) -> dict[str, Any] | None:
    entries = _load_entries(agent_id)
    if not entries:
        return None
    daily = aggregate_daily(entries)
    weekly = aggregate_weekly(entries)
    monthly = aggregate_monthly(entries)
    sessions = aggregate_sessions(entries)
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    recent = [e for e in entries if e.timestamp >= cutoff]
    blocks = analyze_blocks(recent)
    rate_limits = RATE_LIMIT_LOADERS.get(agent_id, lambda: None)()
    p90 = None
    has_limits = rate_limits and (rate_limits.five_hour_pct is not None or rate_limits.seven_day_pct is not None)
    if not has_limits:
        p90 = calculate_p90(daily)
    return dict(
        daily_stats=daily, weekly_stats=weekly, monthly_stats=monthly,
        sessions=sessions, blocks=blocks, rate_limits=rate_limits,
        p90=p90, agents=[agent_name],
    )


def _initial_agent_index(agents: list[AgentInfo]) -> int:
    import os

    preferred = None
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SANDBOX"):
        preferred = "codex"
    elif os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDECODE"):
        preferred = "claude-code"

    if preferred:
        for i, agent in enumerate(agents):
            if agent.id == preferred:
                return i
    return 0


def _fit_screen(text: str, height: int, scroll_offset: int) -> tuple[str, int]:
    lines = text.splitlines()
    if not lines:
        return "", 0
    max_body = max(1, height - 1)
    max_scroll = max(0, len(lines) - max_body)
    scroll_offset = max(0, min(scroll_offset, max_scroll))
    visible = lines[:1] + lines[1 + scroll_offset:1 + scroll_offset + max_body - 1]
    return "\n".join(visible), max_scroll


def _dashboard_sort_cycle() -> list[tuple[str, str, str]]:
    return [
        ("time", "start_time", t("sort_time")),
        ("tokens", "total_tokens", t("sort_token")),
        ("cost", "cost_usd", t("sort_cost")),
        ("messages", "message_count", t("sort_messages")),
    ]


def _show_interactive_dashboard(agents: list[AgentInfo]) -> None:
    import shutil
    from io import StringIO
    from rich.console import Console as RichConsole
    import ui.tables as _tables

    agent_names = [a.name for a in agents]
    current = _initial_agent_index(agents)
    scroll_offset = 0
    sort_idx = 0
    sort_desc = True
    session_limit = 30
    orig = _tables.console

    sys.stdout.write("\033[?1049h\033[?7l\033[2J\033[3J\033[H\033[?25l")
    cache = {}
    sort_cycle = _dashboard_sort_cycle()

    try:
        while True:
            agent = agents[current]
            if agent.id not in cache:
                sys.stdout.write(f"\033[2J\033[3J\033[H\033[2m{t('loading')}\033[0m")
                sys.stdout.flush()
                cache[agent.id] = _build_agent_data(agent.id, agent.name)

            size = shutil.get_terminal_size((80, 24))
            width = size.columns
            height = size.lines

            data = cache[agent.id]
            if data:
                _, sort_attr, sort_label = sort_cycle[sort_idx]
                sorted_sessions = sorted(
                    data["sessions"],
                    key=lambda s: getattr(s, sort_attr),
                    reverse=sort_desc,
                )
                arrow = "↓" if sort_desc else "↑"
                session_title = t("session_title", limit=session_limit, label=sort_label, arrow=arrow)
            else:
                sorted_sessions = []
                session_title = None

            buf = StringIO()
            _tables.console = RichConsole(
                file=buf, width=width, force_terminal=True,
            )
            render_tab_bar(agent_names, current)
            if data:
                render_data = {**data, "sessions": sorted_sessions}
                render_dashboard(**render_data, session_limit=session_limit, top_margin=False, session_title=session_title)
            else:
                _tables.console.print(f"[yellow]{t('no_data')}[/yellow]")
            _tables.console = orig

            screen, max_scroll = _fit_screen(buf.getvalue(), height, scroll_offset)
            sys.stdout.write("\033[2J\033[3J\033[H" + screen)
            sys.stdout.flush()

            key = _read_key()
            if key == "left":
                current = (current - 1) % len(agents)
                scroll_offset = 0
            elif key == "right":
                current = (current + 1) % len(agents)
                scroll_offset = 0
            elif key == "up":
                scroll_offset = max(0, scroll_offset - 1)
            elif key == "down":
                scroll_offset = min(max_scroll, scroll_offset + 1)
            elif key == "page_up":
                scroll_offset = max(0, scroll_offset - max(1, height - 3))
            elif key == "page_down":
                scroll_offset = min(max_scroll, scroll_offset + max(1, height - 3))
            elif key == "sort":
                sort_idx = (sort_idx + 1) % len(sort_cycle)
                scroll_offset = 0
            elif key == "reverse":
                sort_desc = not sort_desc
            elif key == "more":
                session_limit += 10
            elif key == "less":
                session_limit = max(10, session_limit - 10)
            elif key == "report":
                import time

                from analyzer.reporter import build_report_data
                from ui.html_report import save_and_open

                report_data = build_report_data(agents, "month")
                saved = save_and_open(report_data)
                msg = f"\033[32m✓ Report saved: {saved}\033[0m"
                sys.stdout.write(f"\033[{height};1H\033[2K{msg}")
                sys.stdout.flush()
                time.sleep(2)
            elif key == "quit":
                break
    finally:
        sys.stdout.write("\033[?7h\033[?25h\033[?1049l")
        sys.stdout.flush()
        _tables.console = orig


def _read_key_unix() -> str:
    import os as _os
    import select
    import tty
    import termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = _os.read(fd, 1)
        if ch == b"\x1b":
            if not select.select([fd], [], [], 0.05)[0]:
                return "quit"
            ch2 = _os.read(fd, 1)
            if ch2 == b"[":
                ch3 = _os.read(fd, 1)
                if ch3 == b"D":
                    return "left"
                if ch3 == b"C":
                    return "right"
                if ch3 == b"A":
                    return "up"
                if ch3 == b"B":
                    return "down"
                if ch3 in (b"5", b"6"):
                    if select.select([fd], [], [], 0.05)[0]:
                        _os.read(fd, 1)
                    return "page_up" if ch3 == b"5" else "page_down"
            return "other"
        if ch == b"h":
            return "left"
        if ch == b"l":
            return "right"
        if ch == b"k":
            return "up"
        if ch == b"j":
            return "down"
        if ch == b"b":
            return "page_up"
        if ch == b"f":
            return "page_down"
        if ch == b"s":
            return "sort"
        if ch == b"r":
            return "reverse"
        if ch == b"e":
            return "report"
        if ch in (b"+", b"="):
            return "more"
        if ch in (b"-", b"_"):
            return "less"
        if ch in (b"q", b"Q", b"\x03"):
            return "quit"
        return "other"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key_win() -> str:
    import msvcrt
    ch = msvcrt.getch()  # type: ignore[attr-defined]
    if ch in (b"\xe0", b"\x00"):
        ch2 = msvcrt.getch()  # type: ignore[attr-defined]
        if ch2 == b"K":
            return "left"
        if ch2 == b"M":
            return "right"
        if ch2 == b"H":
            return "up"
        if ch2 == b"P":
            return "down"
        if ch2 == b"I":
            return "page_up"
        if ch2 == b"Q":
            return "page_down"
        return "other"
    if ch == b"h":
        return "left"
    if ch == b"l":
        return "right"
    if ch == b"k":
        return "up"
    if ch == b"j":
        return "down"
    if ch == b"b":
        return "page_up"
    if ch == b"f":
        return "page_down"
    if ch == b"e":
        return "report"
    if ch in (b"q", b"Q", b"\x03", b"\x1b"):
        return "quit"
    return "other"


_read_key = _read_key_win if sys.platform == "win32" else _read_key_unix


def _get_version() -> str:
    from importlib.metadata import version
    return version("usage")


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "dashboard"

    if command in ("--version", "-v", "-V"):
        print(f"usage {_get_version()}")
        return
    if command == "report" and any(arg in {"-h", "--help"} for arg in args[1:]):
        console.print(REPORT_HELP)
        return
    if command == "export" and any(arg in {"-h", "--help"} for arg in args[1:]):
        console.print(EXPORT_HELP)
        return
    if command == "setup":
        setup()
        return
    if command == "unsetup":
        unsetup()
        return

    agents = detect_agents()
    if not agents:
        console.print(f"[red]{t('no_agent')}[/red]")
        sys.exit(1)

    agent_ids = {a.id for a in agents}

    if command not in {"dashboard", "export"}:
        console.print(f"[dim]{t('detected', agents=', '.join(a.name + ' ✓' for a in agents))}[/dim]")

    hook_warning_needed = (
        (command == "claude" and not is_claude_setup())
        or (command == "codex" and not is_codex_setup())
        or (command not in AGENT_ALIASES and command != "export" and not is_setup())
    )
    if hook_warning_needed:
        console.print(f"[yellow]{t('hook_not_installed')}[/yellow]")

    # usage claude / usage codex
    if command in AGENT_ALIASES:
        agent_id = AGENT_ALIASES[command]
        if agent_id not in agent_ids:
            console.print(f"[red]{t('agent_not_found', name=command)}[/red]")
            sys.exit(1)
        _show_agent_dashboard(agent_id)
        return

    if command == "dashboard":
        agent_filter = args[1] if len(args) > 1 and args[1] in AGENT_ALIASES else None
        if agent_filter:
            agent_id = AGENT_ALIASES[agent_filter]
            if agent_id not in agent_ids:
                console.print(f"[red]{t('agent_not_found', name=agent_filter)}[/red]")
                sys.exit(1)
            _show_agent_dashboard(agent_id)
        elif len(agents) > 1 and sys.stdin.isatty():
            _show_interactive_dashboard(agents)
        else:
            _show_agent_dashboard(agents[0].id)
        return

    # 其他命令使用合并数据
    agent_names = [a.name for a in agents]
    rest_args, sort_key, sort_desc = _parse_sort_args(args[1:])

    if command == "report":
        period, out_path, show_help = _parse_report_args(args[1:])
        if show_help:
            console.print(REPORT_HELP)
            return
        from analyzer.reporter import build_report_data
        from ui.html_report import save_and_open

        data = build_report_data(agents, period)
        saved = save_and_open(data, out_path)
        console.print(f"[green]✓[/green] Report saved: {saved}")
    elif command == "export":
        export_type, out_path, show_help = _parse_export_args(args[1:])
        if show_help:
            console.print(EXPORT_HELP)
            return
        if export_type == "daily":
            stats = _aggregate_per_agent(agents, aggregate_daily)
            stats.sort(key=lambda s: s.date, reverse=True)
        elif export_type == "weekly":
            stats = _aggregate_per_agent(agents, aggregate_weekly)
            stats.sort(key=lambda s: s.week, reverse=True)
        elif export_type == "monthly":
            stats = _aggregate_per_agent(agents, aggregate_monthly)
            stats.sort(key=lambda s: s.month, reverse=True)
        else:
            stats = _aggregate_per_agent(agents, aggregate_sessions)
            stats.sort(key=lambda s: s.start_time, reverse=True)

        export_saved = _write_export_csv(stats, export_type, out_path)
        if export_saved is not None:
            console.print(f"[green]✓[/green] Export saved: {export_saved}")
    elif command == "daily":
        stats = _aggregate_per_agent(agents, aggregate_daily)
        default_attr = "date" if sort_key == "time" else "total_tokens"
        _apply_sort(stats, sort_key, sort_desc, default_attr, default_reverse=True)
        render_daily(stats, agents=agent_names)
    elif command == "weekly":
        stats = _aggregate_per_agent(agents, aggregate_weekly)
        default_attr = "week"
        _apply_sort(stats, sort_key, sort_desc, default_attr, default_reverse=True)
        render_weekly(stats, agents=agent_names)
    elif command == "monthly":
        stats = _aggregate_per_agent(agents, aggregate_monthly)
        default_attr = "month"
        _apply_sort(stats, sort_key, sort_desc, default_attr, default_reverse=False)
        render_monthly(stats, agents=agent_names)
    elif command == "sessions":
        limit = 20
        for a in rest_args:
            try:
                limit = int(a)
                break
            except ValueError:
                pass
        stats = _aggregate_per_agent(agents, aggregate_sessions)
        default_attr = "start_time"
        _apply_sort(stats, sort_key, sort_desc, default_attr, default_reverse=True)
        render_sessions(stats, limit)
    else:
        console.print(f"[red]{t('unknown_cmd', cmd=command)}[/red]")
        console.print(f"[dim]{t('available_cmds')}[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
