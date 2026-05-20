from __future__ import annotations

import asyncio
import threading
import time
import tkinter as tk
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from history_loader import UsageEntry, load_entries
from usage_client import ClaudeUsageClient, PollState

if TYPE_CHECKING:
    pass

# ── colours (match Rainmeter skin) ────────────────────────────────────────────
BG       = "#1a1d27"
BORDER   = "#2e3250"
TEXT     = "#e2e8f0"
MUTED    = "#8892b0"
BAR_BG   = "#2e3250"
BAR_FG   = "#1d9e75"
BAR_WARN = "#e0a02f"   # ≥80%
BAR_CRIT = "#e05050"   # ≥95%

W, H     = 220, 176
FONT     = "Segoe UI"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def format_reset(resets_at: float) -> str:
    delta = max(0, round(resets_at - time.time()))
    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}hr"
    if hours:
        return f"{hours}hr {mins}min"
    return f"{mins}min"


def compute_month_stats(entries: list[UsageEntry]) -> tuple[float, int]:
    now = _utcnow()
    month_entries = [
        e for e in entries
        if e.timestamp.year == now.year and e.timestamp.month == now.month
    ]
    cost = sum(e.cost_usd or 0.0 for e in month_entries)
    sessions = len({e.session_id for e in month_entries})
    return cost, sessions


def _bar_color(pct: int) -> str:
    if pct >= 95:
        return BAR_CRIT
    if pct >= 80:
        return BAR_WARN
    return BAR_FG


def _mock_data() -> dict[str, object]:
    return {
        "five_pct": 42,
        "five_reset": "45min",
        "seven_pct": 11,
        "seven_reset": "2d 3hr",
        "month_cost": 12.34,
        "month_sessions": 42,
        "status": "mock",
    }


def _fetch_data(client: ClaudeUsageClient, mock: bool) -> dict[str, object]:
    if mock:
        return _mock_data()

    outcome = asyncio.run(client.fetch_once())
    snap = outcome.snapshot

    if outcome.state != PollState.SUCCESS or snap is None:
        return {
            "five_pct": 0,
            "five_reset": "--",
            "seven_pct": 0,
            "seven_reset": "--",
            "month_cost": 0.0,
            "month_sessions": 0,
            "status": outcome.message or "error",
        }

    entries = load_entries()
    month_cost, month_sessions = compute_month_stats(entries)

    return {
        "five_pct": snap.current_percent or 0,
        "five_reset": format_reset(snap.current_reset_at),
        "seven_pct": snap.weekly_percent or 0,
        "seven_reset": format_reset(snap.weekly_reset_at),
        "month_cost": month_cost,
        "month_sessions": month_sessions,
        "status": "ok",
    }


class UsageWidget:
    def __init__(self, mock: bool, interval: int) -> None:
        self._mock = mock
        self._interval = max(30, interval) * 1000  # ms
        self._client = ClaudeUsageClient(interval_seconds=interval, mock=mock)

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.wm_attributes("-topmost", True)
        self._root.wm_attributes("-alpha", 0.88)
        self._root.configure(bg=BG)
        self._root.geometry(f"{W}x{H}+40+40")
        self._root.resizable(False, False)

        self._drag_x = 0
        self._drag_y = 0

        self._canvas = tk.Canvas(
            self._root, width=W, height=H, bg=BG,
            highlightthickness=0, bd=0,
        )
        self._canvas.pack(fill="both", expand=True)

        self._canvas.bind("<Button-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_motion)
        self._canvas.bind("<Button-3>", self._on_right_click)

        self._menu = tk.Menu(self._root, tearoff=0, bg=BORDER, fg=TEXT,
                             activebackground="#3a3f60", activeforeground=TEXT)
        self._menu.add_command(label="Refresh", command=self._refresh)
        self._menu.add_separator()
        self._menu.add_command(label="Quit", command=self._root.destroy)

        self._fetch_lock = threading.Lock()
        self._data: dict[str, object] = {
            "five_pct": 0, "five_reset": "--",
            "seven_pct": 0, "seven_reset": "--",
            "month_cost": 0.0, "month_sessions": 0,
            "status": "loading",
        }
        self._refresh()

    # ── drag ──────────────────────────────────────────────────────────────────

    def _on_drag_start(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_motion(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        x = self._root.winfo_x() + event.x - self._drag_x
        y = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def _on_right_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._menu.tk_popup(event.x_root, event.y_root)

    # ── data + render ─────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._fetch_lock.locked():
            self._root.after(self._interval, self._refresh)
            return

        def _fetch() -> None:
            with self._fetch_lock:
                data = _fetch_data(self._client, self._mock)
                self._root.after(0, lambda: self._apply(data))

        threading.Thread(target=_fetch, daemon=True).start()
        self._root.after(self._interval, self._refresh)

    def _apply(self, data: dict[str, object]) -> None:
        self._data = data
        self._draw()

    def _draw(self) -> None:
        c = self._canvas
        c.delete("all")
        d = self._data

        # border rect
        c.create_rectangle(1, 1, W - 1, H - 1, outline=BORDER, fill=BG, width=1)

        # title
        c.create_text(12, 12, text="Claude Code Usage", anchor="nw",
                      font=(FONT, 11, "bold"), fill=TEXT)

        # divider
        c.create_line(12, 30, W - 12, 30, fill=BORDER)

        # 5-hour section
        self._draw_section(c, y=38, label="5-Hour Window",
                           pct=int(d["five_pct"]),
                           reset_label=str(d["five_reset"]))

        # divider
        c.create_line(12, 88, W - 12, 88, fill=BORDER)

        # 7-day section
        self._draw_section(c, y=96, label="7-Day Window",
                           pct=int(d["seven_pct"]),
                           reset_label=str(d["seven_reset"]))

        # divider
        c.create_line(12, 146, W - 12, 146, fill=BORDER)

        # monthly summary
        c.create_text(12, 154, text="This Month", anchor="nw",
                      font=(FONT, 9), fill=MUTED)
        cost_str = f"Cost ${d['month_cost']:.2f}  |  Sessions {d['month_sessions']}"
        c.create_text(12, 166, text=cost_str, anchor="nw",
                      font=(FONT, 9), fill=TEXT)

    def _draw_section(self, c: tk.Canvas, y: int, label: str,
                      pct: int, reset_label: str) -> None:
        bar_w = 196
        bar_h = 8
        bar_x = 12
        bar_y = y + 16

        c.create_text(12, y, text=label, anchor="nw", font=(FONT, 9), fill=MUTED)

        # bar background
        c.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h,
                            fill=BAR_BG, outline="")

        # bar fill
        fill_w = int(bar_w * pct / 100)
        if fill_w > 0:
            c.create_rectangle(bar_x, bar_y, bar_x + fill_w, bar_y + bar_h,
                                fill=_bar_color(pct), outline="")

        # percentage text (right-aligned)
        c.create_text(W - 4, bar_y - 1, text=f"{pct}%", anchor="ne",
                      font=(FONT, 9), fill=TEXT)

        # reset label
        c.create_text(12, bar_y + bar_h + 4, text=f"Reset in {reset_label}",
                      anchor="nw", font=(FONT, 8), fill=MUTED)

    def run(self) -> None:
        self._root.mainloop()


def run(mock: bool = False, interval: int = 60) -> None:
    UsageWidget(mock=mock, interval=interval).run()
