from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import codex_loader
from history_loader import UsageEntry, load_entries
from pricing import calculate_cost
from usage_client import ClaudeUsageClient, PollState

if TYPE_CHECKING:
    pass

W, H = 220, 310
FONT = "Segoe UI"

_PANEL_STATE_PATH = Path.home() / ".claude" / "usage-widget-panel.json"


@dataclass(frozen=True)
class WidgetPanel:
    id: str
    display_name: str
    bg: str
    border: str
    text: str
    muted: str
    bar_bg: str
    bar_fg: str
    bar_warn: str
    bar_crit: str
    alpha: float = 0.88


DARK_PANEL = WidgetPanel(
    id="dark", display_name="黑夜",
    bg="#1a1d27", border="#2e3250", text="#e2e8f0", muted="#8892b0",
    bar_bg="#2e3250", bar_fg="#1d9e75", bar_warn="#e0a02f", bar_crit="#e05050",
)
LIGHT_PANEL = WidgetPanel(
    id="light", display_name="白日",
    bg="#f0f0f5", border="#c0c0d0", text="#1a1a2e", muted="#555566",
    bar_bg="#c0c0d0", bar_fg="#1a7a50", bar_warn="#b06010", bar_crit="#b02020",
    alpha=0.94,
)
NEON_PANEL = WidgetPanel(
    id="neon", display_name="霓虹",
    bg="#080812", border="#0a2040", text="#00e5ff", muted="#0088aa",
    bar_bg="#0a1530", bar_fg="#00e5ff", bar_warn="#ffcc00", bar_crit="#ff4444",
    alpha=0.92,
)
MATRIX_PANEL = WidgetPanel(
    id="matrix", display_name="矩陣",
    bg="#000800", border="#003300", text="#33ff33", muted="#007700",
    bar_bg="#001a00", bar_fg="#33ff33", bar_warn="#ffff00", bar_crit="#ff3333",
    alpha=0.93,
)

ALL_PANELS: tuple[WidgetPanel, ...] = (DARK_PANEL, LIGHT_PANEL, NEON_PANEL, MATRIX_PANEL)


def load_active_panel_id() -> str:
    try:
        data = json.loads(_PANEL_STATE_PATH.read_text(encoding="utf-8"))
        panel_id = str(data.get("panel_id", "dark"))
        if any(p.id == panel_id for p in ALL_PANELS):
            return panel_id
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        pass
    return "dark"


def save_active_panel_id(panel_id: str) -> None:
    with contextlib.suppress(OSError):
        _PANEL_STATE_PATH.write_text(
            json.dumps({"panel_id": panel_id}), encoding="utf-8"
        )


def _get_panel(panel_id: str) -> WidgetPanel:
    for p in ALL_PANELS:
        if p.id == panel_id:
            return p
    return DARK_PANEL


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
    cost = sum(calculate_cost(e) for e in month_entries)
    sessions = len({e.session_id for e in month_entries})
    return cost, sessions


def _active_tokens(e: UsageEntry) -> int:
    """Input + output + cache_creation — the compute tokens that count toward rate limits."""
    return e.input_tokens + e.output_tokens + (e.cache_creation_tokens or 0)


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def _token_stats(entries: list[UsageEntry]) -> tuple[int, int, int, int]:
    """Returns (five_h_pct, seven_d_pct, five_h_tokens, seven_d_tokens).

    Percentage relative to fixed default caps: 1 M tokens/5 h, 10 M tokens/7 d.
    Used as fallback when the Claude Code hook status file is unavailable.

    NOTE: historical-peak-as-denominator was removed — on heavy usage days
    current ≈ peak → always 100 %.  Fixed caps are a better fallback estimate.
    """
    now = _utcnow()
    five_h_cutoff = now - timedelta(hours=5)
    seven_d_cutoff = now - timedelta(days=7)

    five_h_tokens = sum(_active_tokens(e) for e in entries if e.timestamp >= five_h_cutoff)
    seven_d_tokens = sum(_active_tokens(e) for e in entries if e.timestamp >= seven_d_cutoff)

    max_five_h = 1_000_000
    max_seven_d = 10_000_000

    five_h_pct = min(100, round(five_h_tokens / max_five_h * 100))
    seven_d_pct = min(100, round(seven_d_tokens / max_seven_d * 100))
    return five_h_pct, seven_d_pct, five_h_tokens, seven_d_tokens


def _bar_color(pct: int, panel: WidgetPanel) -> str:
    if pct >= 95:
        return panel.bar_crit
    if pct >= 80:
        return panel.bar_warn
    return panel.bar_fg


def _mock_data() -> dict[str, int | float | str]:
    return {
        "five_pct": 42,
        "five_reset": "45min",
        "seven_pct": 11,
        "seven_reset": "2d 3hr",
        "codex_five_pct": 12,
        "codex_five_reset": "4hr 15min",
        "codex_seven_pct": 28,
        "codex_seven_reset": "4d 0hr",
        "month_cost": 12.34,
        "month_sessions": 42,
        "status": "mock",
    }


def _fetch_data(client: ClaudeUsageClient, mock: bool) -> dict[str, int | float | str]:
    if mock:
        return _mock_data()

    outcome = asyncio.run(client.fetch_once())
    snap = outcome.snapshot

    # Always load history entries — used for token stats and month summary
    entries = load_entries()
    five_h_pct, seven_d_pct, five_h_tok, seven_d_tok = _token_stats(entries)
    month_cost, month_sessions = compute_month_stats(entries)

    if outcome.state != PollState.SUCCESS or snap is None:
        # No rate-limit data from Claude Code hook → fall back to JSONL token stats
        codex_five_pct = 0
        codex_five_reset = "--"
        codex_seven_pct = 0
        codex_seven_reset = "--"
        try:
            rl = codex_loader.load_rate_limits()
            if rl is not None:
                if rl.five_hour_pct is not None:
                    codex_five_pct = round(rl.five_hour_pct)
                if rl.five_hour_resets_at is not None:
                    codex_five_reset = format_reset(rl.five_hour_resets_at)
                if rl.seven_day_pct is not None:
                    codex_seven_pct = round(rl.seven_day_pct)
                if rl.seven_day_resets_at is not None:
                    codex_seven_reset = format_reset(rl.seven_day_resets_at)
        except Exception:
            pass
        return {
            "five_pct": five_h_pct,
            "five_reset": f"{_format_tokens(five_h_tok)} tokens",
            "seven_pct": seven_d_pct,
            "seven_reset": f"{_format_tokens(seven_d_tok)} tokens",
            "codex_five_pct": codex_five_pct,
            "codex_five_reset": codex_five_reset,
            "codex_seven_pct": codex_seven_pct,
            "codex_seven_reset": codex_seven_reset,
            "month_cost": month_cost,
            "month_sessions": month_sessions,
            "status": "est",
        }

    # Codex rate limits (best-effort; failure is silent)
    codex_five_pct = 0
    codex_five_reset = "--"
    codex_seven_pct = 0
    codex_seven_reset = "--"
    try:
        rl = codex_loader.load_rate_limits()
        if rl is not None:
            if rl.five_hour_pct is not None:
                codex_five_pct = round(rl.five_hour_pct)
            if rl.five_hour_resets_at is not None:
                codex_five_reset = format_reset(rl.five_hour_resets_at)
            if rl.seven_day_pct is not None:
                codex_seven_pct = round(rl.seven_day_pct)
            if rl.seven_day_resets_at is not None:
                codex_seven_reset = format_reset(rl.seven_day_resets_at)
    except Exception:
        pass

    return {
        "five_pct": snap.current_percent or 0,
        "five_reset": format_reset(snap.current_reset_at),
        "seven_pct": snap.weekly_percent or 0,
        "seven_reset": format_reset(snap.weekly_reset_at),
        "codex_five_pct": codex_five_pct,
        "codex_five_reset": codex_five_reset,
        "codex_seven_pct": codex_seven_pct,
        "codex_seven_reset": codex_seven_reset,
        "month_cost": month_cost,
        "month_sessions": month_sessions,
        "status": "ok",
    }


class UsageWidget:
    def __init__(self, mock: bool, interval: int) -> None:
        self._mock = mock
        self._interval = max(30, interval) * 1000  # ms
        self._client = ClaudeUsageClient(interval_seconds=interval, mock=mock)
        self._panel = _get_panel(load_active_panel_id())

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.wm_attributes("-topmost", True)
        self._root.wm_attributes("-alpha", self._panel.alpha)
        self._root.configure(bg=self._panel.bg)
        self._root.geometry(f"{W}x{H}+40+40")
        self._root.resizable(False, False)

        self._drag_x = 0
        self._drag_y = 0

        self._canvas = tk.Canvas(
            self._root, width=W, height=H, bg=self._panel.bg,
            highlightthickness=0, bd=0,
        )
        self._canvas.pack(fill="both", expand=True)

        self._canvas.bind("<Button-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_motion)
        self._canvas.bind("<Button-3>", self._on_right_click)

        self._menu = self._build_menu()

        self._fetch_lock = threading.Lock()
        self._data: dict[str, int | float | str] = {
            "five_pct": 0, "five_reset": "--",
            "seven_pct": 0, "seven_reset": "--",
            "codex_five_pct": 0, "codex_five_reset": "--",
            "codex_seven_pct": 0, "codex_seven_reset": "--",
            "month_cost": 0.0, "month_sessions": 0,
            "status": "loading",
        }
        self._refresh()

    def _build_menu(self) -> tk.Menu:
        p = self._panel
        active_bg = "#3a3f60" if p.id == "dark" else p.border
        menu = tk.Menu(
            self._root, tearoff=0,
            bg=p.border, fg=p.text,
            activebackground=active_bg, activeforeground=p.text,
        )
        menu.add_command(label="Refresh", command=self._refresh)
        menu.add_separator()

        panel_menu = tk.Menu(
            menu, tearoff=0,
            bg=p.border, fg=p.text,
            activebackground=active_bg, activeforeground=p.text,
        )
        for panel in ALL_PANELS:
            pid = panel.id
            prefix = "● " if pid == p.id else "  "
            panel_menu.add_command(
                label=f"{prefix}{panel.display_name}",
                command=lambda pid=pid: self._set_panel(pid),  # type: ignore[misc]
            )
        menu.add_cascade(label="切換面板", menu=panel_menu)
        menu.add_separator()
        menu.add_command(label="Quit", command=self._root.destroy)
        return menu

    def _set_panel(self, panel_id: str) -> None:
        self._panel = _get_panel(panel_id)
        save_active_panel_id(panel_id)
        p = self._panel
        self._root.configure(bg=p.bg)
        self._root.wm_attributes("-alpha", p.alpha)
        self._canvas.configure(bg=p.bg)
        self._menu = self._build_menu()
        self._draw()

    # ── drag ──────────────────────────────────────────────────────────────────

    def _on_drag_start(self, event: tk.Event[tk.Canvas]) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_motion(self, event: tk.Event[tk.Canvas]) -> None:
        x = self._root.winfo_x() + event.x - self._drag_x
        y = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def _on_right_click(self, event: tk.Event[tk.Canvas]) -> None:
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

    def _apply(self, data: dict[str, int | float | str]) -> None:
        self._data = data
        self._draw()

    def _draw(self) -> None:
        p = self._panel
        c = self._canvas
        c.delete("all")
        d = self._data

        c.create_rectangle(1, 1, W - 1, H - 1, outline=p.border, fill=p.bg, width=1)
        c.create_text(12, 12, text="Claude Code Usage", anchor="nw",
                      font=(FONT, 11, "bold"), fill=p.text)
        c.create_line(12, 30, W - 12, 30, fill=p.border)

        # ── Claude Code ────────────────────────────────────────────────────────
        self._draw_section(c, y=38, label="5-Hour Window",
                           pct=int(d["five_pct"]),
                           reset_label=str(d["five_reset"]))
        c.create_line(12, 88, W - 12, 88, fill=p.border)

        self._draw_section(c, y=96, label="7-Day Window",
                           pct=int(d["seven_pct"]),
                           reset_label=str(d["seven_reset"]))
        c.create_line(12, 146, W - 12, 146, fill=p.border)

        # ── Codex ──────────────────────────────────────────────────────────────
        c.create_text(12, 152, text="Codex", anchor="nw",
                      font=(FONT, 8, "bold"), fill=p.muted)

        self._draw_section(c, y=162, label="5-Hour Window",
                           pct=int(d["codex_five_pct"]),
                           reset_label=str(d["codex_five_reset"]))
        c.create_line(12, 212, W - 12, 212, fill=p.border)

        self._draw_section(c, y=220, label="7-Day Window",
                           pct=int(d["codex_seven_pct"]),
                           reset_label=str(d["codex_seven_reset"]))
        c.create_line(12, 270, W - 12, 270, fill=p.border)

        # ── Monthly ────────────────────────────────────────────────────────────
        c.create_text(12, 278, text="This Month", anchor="nw",
                      font=(FONT, 9), fill=p.muted)
        cost_str = f"Cost ${d['month_cost']:.2f}  |  Sessions {d['month_sessions']}"
        c.create_text(12, 290, text=cost_str, anchor="nw",
                      font=(FONT, 9), fill=p.text)

    def _draw_section(self, c: tk.Canvas, y: int, label: str,
                      pct: int, reset_label: str) -> None:
        p = self._panel
        bar_w = 196
        bar_h = 8
        bar_x = 12
        bar_y = y + 16

        c.create_text(12, y, text=label, anchor="nw", font=(FONT, 9), fill=p.muted)
        c.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h,
                            fill=p.bar_bg, outline="")
        fill_w = int(bar_w * pct / 100)
        if fill_w > 0:
            c.create_rectangle(bar_x, bar_y, bar_x + fill_w, bar_y + bar_h,
                                fill=_bar_color(pct, p), outline="")
        c.create_text(W - 4, bar_y - 1, text=f"{pct}%", anchor="ne",
                      font=(FONT, 9), fill=p.text)
        # "Xh Ymin tokens" means token-based estimate; otherwise show "Reset in ..."
        sub = reset_label if reset_label.endswith("tokens") else f"Reset in {reset_label}"
        c.create_text(12, bar_y + bar_h + 4, text=sub,
                      anchor="nw", font=(FONT, 8), fill=p.muted)

    def run(self) -> None:
        self._root.mainloop()


def run(mock: bool = False, interval: int = 60) -> None:
    UsageWidget(mock=mock, interval=interval).run()
