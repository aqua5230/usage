from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tui_sprite import render_sprite
from usage_client import PollState, UsageSnapshot

BG = "#000000"
PANEL = "#1f1f1e"
TEXT = "#faf9f5"
DIM = "#b0aea5"
ACCENT = "#d97757"
GREEN = "#788c5d"
RED = "#c0392b"
BAR_BG = "#2a2a28"

SPINNER_FRAMES = ["·", "✻", "✽", "✶", "✳", "✢"]
SPINNER_PHASES = [0, 1, 2, 3, 4, 5, 4, 3, 2, 1]
SPINNER_PHASE_MS = [260, 130, 130, 130, 130, 260, 130, 130, 130, 130]
LOADING_INTERVAL_MS = 4000

LOADING_PHRASES = [
    "Accomplishing",
    "Elucidating",
    "Perusing",
    "Actioning",
    "Enchanting",
    "Philosophising",
    "Actualizing",
    "Envisioning",
    "Pondering",
    "Baking",
    "Finagling",
    "Pontificating",
    "Booping",
    "Flibbertigibbeting",
    "Processing",
    "Brewing",
    "Forging",
    "Puttering",
    "Calculating",
    "Forming",
    "Puzzling",
    "Cerebrating",
    "Frolicking",
    "Reticulating",
    "Channelling",
    "Generating",
    "Ruminating",
    "Churning",
    "Germinating",
    "Scheming",
    "Clauding",
    "Hatching",
    "Schlepping",
    "Coalescing",
    "Herding",
    "Shimmying",
    "Cogitating",
    "Honking",
    "Shucking",
    "Combobulating",
    "Hustling",
    "Simmering",
    "Computing",
    "Ideating",
    "Smooshing",
    "Concocting",
    "Imagining",
    "Spelunking",
    "Conjuring",
    "Incubating",
    "Spinning",
    "Considering",
    "Inferring",
    "Stewing",
    "Contemplating",
    "Jiving",
    "Sussing",
    "Cooking",
    "Manifesting",
    "Synthesizing",
    "Crafting",
    "Marinating",
    "Thinking",
    "Creating",
    "Meandering",
    "Tinkering",
    "Crunching",
    "Moseying",
    "Transmuting",
    "Deciphering",
    "Mulling",
    "Unfurling",
    "Deliberating",
    "Mustering",
    "Unravelling",
    "Determining",
    "Musing",
    "Vibing",
    "Discombobulating",
    "Noodling",
    "Wandering",
    "Divining",
    "Percolating",
    "Whirring",
    "Doing",
    "Wibbling",
    "Effecting",
    "Wizarding",
    "Working",
    "Wrangling",
]


@dataclass(slots=True)
class AppViewState:
    poll_state: PollState = PollState.LOADING
    snapshot: UsageSnapshot | None = None
    message: str = ""
    fatal_message: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    rate_group: int = 0


def format_countdown(reset_at: float, now: float | None = None) -> str:
    current_time = now if now is not None else time.time()
    remaining = max(0, math.ceil(reset_at - current_time))
    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)

    if days > 0:
        return f"Resets in {days}d {hours}h"
    if hours > 0:
        return f"Resets in {hours}h {minutes}m"
    return f"Resets in {minutes}m {seconds}s"


def _bar_style(percent: int) -> str:
    if percent < 50:
        return GREEN
    if percent <= 80:
        return ACCENT
    return RED


def _build_progress_line(percent: int, width: int = 28) -> Text:
    filled = round((percent / 100) * width)
    text = Text()
    text.append("▄" * filled, style=f"bold {_bar_style(percent)}")
    text.append("▄" * max(0, width - filled), style=f"bold {BAR_BG}")
    return text


def _chip(label: str) -> Text:
    return Text(f" {label} ", style=f"bold {TEXT} on {PANEL}")


def _usage_block(percent: int, label: str, reset_at: float, now: float) -> RenderableType:
    row = Table.grid(expand=False, padding=(0, 1))
    row.add_column(width=4)
    row.add_column(width=16)
    row.add_column(width=11)
    row.add_row(
        Text(f"{percent}%", style=f"bold {_bar_style(percent)}"),
        _build_progress_line(percent, width=15),
        _chip(label),
    )

    countdown = Text.assemble("    ", (format_countdown(reset_at, now), DIM))
    return Group(row, countdown)


def _missing_usage_block(label: str) -> RenderableType:
    row = Table.grid(expand=False, padding=(0, 1))
    row.add_column(width=4)
    row.add_column(width=16)
    row.add_column(width=11)
    row.add_row(
        Text("--", style=f"bold {DIM}"),
        _build_progress_line(0, width=15),
        _chip(label),
    )
    return Group(row, Text("    Resets in --", style=DIM))


def _spinner_frame(now: float, started_at: float) -> str:
    elapsed_ms = int((now - started_at) * 1000)
    total_ms = sum(SPINNER_PHASE_MS)
    phase_ms = elapsed_ms % total_ms
    accumulated = 0

    for phase_index, duration in enumerate(SPINNER_PHASE_MS):
        accumulated += duration
        if phase_ms < accumulated:
            return SPINNER_FRAMES[SPINNER_PHASES[phase_index]]
    return SPINNER_FRAMES[SPINNER_PHASES[-1]]


def _status_line(state: AppViewState, now: float) -> Text:
    spinner = _spinner_frame(now, state.started_at)
    elapsed_ms = (now - state.started_at) * 1000
    phrase_index = int(elapsed_ms / LOADING_INTERVAL_MS) % len(LOADING_PHRASES)

    color = ACCENT
    phrase = LOADING_PHRASES[phrase_index]

    if state.poll_state == PollState.RATE_LIMITED:
        phrase = "⚠ Rate limit reached"
        color = RED
    elif state.poll_state == PollState.TOKEN_ERROR:
        phrase = "⚠ Token unavailable"
        color = ACCENT
    elif state.poll_state in (PollState.CONNECTION_ERROR, PollState.FATAL):
        phrase = "⚠ API offline"
        color = RED

    return Text.assemble(
        (f"{spinner} ", f"bold {color}"),
        (phrase, f"bold {color}"),
    )


def render_screen(state: AppViewState, frame_index: int) -> Panel:
    now = time.time()
    anim_now = time.monotonic()
    panel_width = min(Console().size.width, 60)

    # Group label and colors
    groups = ["Idle", "Normal", "Active", "Heavy"]
    group_colors = [DIM, TEXT, ACCENT, RED]
    group_label = groups[state.rate_group]
    group_color = group_colors[state.rate_group]

    # Status dot color
    dot_color = ACCENT
    if state.poll_state == PollState.SUCCESS:
        dot_color = GREEN
    elif state.poll_state in (
        PollState.TOKEN_ERROR,
        PollState.CONNECTION_ERROR,
        PollState.RATE_LIMITED,
        PollState.FATAL,
    ):
        dot_color = RED

    title_table = Table.grid(expand=True, padding=(0, 0))
    title_table.add_column(width=10)
    title_table.add_column(ratio=1, justify="left")
    title_table.add_column(width=4, justify="right")

    title_left = Text.assemble(
        (f"[{group_label}]", f"bold {group_color}"),
        (" •", f"bold {dot_color}"),
    )

    title_table.add_row(
        render_sprite(frame_index),
        Text.assemble(("  Usage  ", f"bold {TEXT}"), title_left),
        Text("🔋"),
    )

    body_items: list[RenderableType] = []

    if state.snapshot is None:
        loading_block = Group(
            _usage_block(0, "Current", now + 3600, now),
            Text(""),
            _usage_block(0, "Weekly", now + 86400, now),
        )
        body_items.append(loading_block)
    else:
        current_block = (
            _usage_block(
                state.snapshot.current_percent,
                "Current",
                state.snapshot.current_reset_at,
                now,
            )
            if state.snapshot.current_percent is not None
            else _missing_usage_block("Current")
        )
        weekly_block = (
            _usage_block(
                state.snapshot.weekly_percent,
                "Weekly",
                state.snapshot.weekly_reset_at,
                now,
            )
            if state.snapshot.weekly_percent is not None
            else _missing_usage_block("Weekly")
        )
        body_items.append(
            Group(
                current_block,
                Text(""),
                weekly_block,
            )
        )

    screen = Group(
        title_table,
        Text(""),
        *body_items,
        Text(""),
        Align.center(_status_line(state, anim_now)),
    )

    return Panel(
        screen,
        border_style=PANEL,
        padding=(1, 2),
        width=panel_width,
        style=f"on {BG}",
    )
