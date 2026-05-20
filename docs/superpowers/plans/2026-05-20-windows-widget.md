# Windows Desktop Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows always-on-desktop tkinter widget to the usage fork, unified under a single `usage-status.json` data source shared with a rewritten Rainmeter Lua script.

**Architecture:** `usage_statusline.py` hook writes raw Claude Code JSON to `~/.claude/usage-status.json`; `windows_widget.py` imports `usage_client` + `history_loader` to read rate-limit percentages and compute month cost/sessions; `main.py` dispatches to the widget on `sys.platform == "win32"`. Rainmeter is updated separately in the dashboard repo to read the same JSON + JSONL directly in Lua.

**Tech Stack:** Python 3.13, tkinter (stdlib), asyncio, existing `usage_client.py` / `history_loader.py` modules; Lua 5.1 (Rainmeter built-in).

---

## File Map

| File | Repo | Action |
|------|------|--------|
| `windows_widget.py` | fork | Create — tkinter floating widget |
| `main.py` | fork | Modify lines 1–14 (imports), 145–166 (main fn) |
| `pyproject.toml` | fork | Modify lines 8–11 (deps) |
| `setup_hook.py` | fork | Modify lines 48–51 (`_statusline_command`) |
| `tests/test_windows_widget.py` | fork | Create — data helper tests |
| `dashboard/rainmeter/ClaudeUsage.lua` | dashboard (`claude_web`) | Rewrite |

---

## Task 1: Guard macOS imports in main.py

`main.py` currently imports `menubar` at the top level — PyObjC crashes on Windows. Move it inside the darwin branch. Also move `tui` imports lazy so tests can import `main` on Windows.

**Files:**
- Modify: `main.py:1-14` and `main.py:145-166`

- [ ] **Step 1: Update top-level imports in main.py**

Replace the current top section (lines 1–14) with:

```python
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from contextlib import suppress
from typing import Any

from usage_client import ClaudeUsageClient, PollOutcome, PollState

SPRITE_INTERVAL_S = [2.0, 0.8, 0.4, 0.15]  # idle/normal/active/heavy
```

(Removed: `import menubar`, `from tui import AppViewState, render_screen`, `from usage_rate import UsageRateTracker`)

- [ ] **Step 2: Update run_tui() to import lazily**

Replace the `run_tui` function (currently at lines 105–142) with:

```python
async def run_tui(mock: bool, interval: int, force_group: int | None = None) -> None:
    from tui import AppViewState, render_screen
    from usage_rate import UsageRateTracker

    Console, Live = _load_rich()
    console = Console()
    state = AppViewState()
    tracker = UsageRateTracker(forced_group=force_group, mock=mock)
    stop_event = asyncio.Event()
    client = ClaudeUsageClient(interval_seconds=interval, mock=mock)

    try:
        first_outcome = await client.fetch_once()
        _apply_outcome(state, first_outcome)

        poll_task = asyncio.create_task(poll_usage(client, state, stop_event))

        with Live(
            render_screen(state, 0),
            console=console,
            screen=True,
            refresh_per_second=10,
            transient=False,
        ) as live:
            start_time = time.monotonic()
            while not stop_event.is_set():
                now = time.monotonic()

                effective_group = tracker.group()
                state.rate_group = effective_group

                interval_s = SPRITE_INTERVAL_S[effective_group]
                frame_index = int((now - start_time) / interval_s) % 4

                live.update(render_screen(state, frame_index), refresh=True)
                await asyncio.sleep(0.1)

        await poll_task
    finally:
        stop_event.set()
        await client.aclose()
```

- [ ] **Step 3: Update main() to add Windows dispatch and lazy menubar import**

Replace `main()` (lines 145–166) with:

```python
def main() -> None:
    _setup_logging()
    args = parse_args()
    if args.setup:
        from setup_hook import setup

        raise SystemExit(setup())
    if args.unsetup:
        from setup_hook import unsetup

        raise SystemExit(unsetup())
    if sys.platform == "win32":
        import windows_widget

        windows_widget.run(mock=args.mock, interval=args.interval)
        return
    if args.tui:
        with suppress(KeyboardInterrupt):
            asyncio.run(
                run_tui(mock=args.mock, interval=args.interval, force_group=args.force_group)
            )
    else:
        import menubar

        menubar.run_app(mock=args.mock, interval=args.interval)
```

- [ ] **Step 4: Run existing tests to verify nothing broke**

```
cd C:\OSEProject\99.SideProject\calude_usage_rain76526
python -m pytest tests/test_main.py -v
```

Expected: all tests pass (imports no longer crash on Windows).

- [ ] **Step 5: Commit**

```
git add main.py
git commit -m "refactor: lazy-import menubar and tui to enable Windows import"
```

---

## Task 2: Fix pyproject.toml for cross-platform install

**Files:**
- Modify: `pyproject.toml:8-11`

- [ ] **Step 1: Make pyobjc darwin-only**

In `pyproject.toml`, replace:

```toml
dependencies = [
    "pyobjc-framework-Cocoa>=11.0",
    "rich>=14.0.0,<15.0.0",
]
```

with:

```toml
dependencies = [
    "pyobjc-framework-Cocoa>=11.0 ; sys_platform == 'darwin'",
    "rich>=14.0.0,<15.0.0",
]
```

- [ ] **Step 2: Commit**

```
git add pyproject.toml
git commit -m "build: restrict pyobjc to darwin platform"
```

---

## Task 3: Fix setup_hook.py for Windows python command

On Windows, `python3` may not exist — the executable is `python`.

**Files:**
- Modify: `setup_hook.py:48-51`

- [ ] **Step 1: Update _statusline_command()**

Replace:

```python
def _statusline_command() -> str:
    # 用系統 python3，不綁 venv（hook 只用標準庫）
    python = shutil.which("python3") or "python3"
    return f"{shlex.quote(python)} {shlex.quote(str(HOOK_TARGET))}"
```

with:

```python
def _statusline_command() -> str:
    python = (
        shutil.which("python3")
        or shutil.which("python")
        or ("python3" if sys.platform != "win32" else "python")
    )
    return f"{shlex.quote(python)} {shlex.quote(str(HOOK_TARGET))}"
```

- [ ] **Step 2: Run setup_hook tests**

```
python -m pytest tests/test_setup_hook.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```
git add setup_hook.py
git commit -m "fix: resolve python executable on Windows in setup_hook"
```

---

## Task 4: Create windows_widget.py — data helpers + tests

Write and test the pure-logic helpers first (no tkinter), then build the UI in Task 5.

**Files:**
- Create: `windows_widget.py` (data helpers only for now)
- Create: `tests/test_windows_widget.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_windows_widget.py`:

```python
from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

import windows_widget
from history_loader import UsageEntry


def _entry(session_id: str, year: int, month: int, cost: float | None) -> UsageEntry:
    ts = datetime(year, month, 15, 12, 0, 0, tzinfo=UTC)
    return UsageEntry(
        timestamp=ts,
        session_id=session_id,
        message_id="msg1",
        request_id="req1",
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=cost,
        project="test",
    )


def test_format_reset_minutes_only() -> None:
    resets_at = time.time() + 45 * 60
    assert windows_widget.format_reset(resets_at) == "45min"


def test_format_reset_hours_and_minutes() -> None:
    resets_at = time.time() + 2 * 3600 + 30 * 60
    assert windows_widget.format_reset(resets_at) == "2hr 30min"


def test_format_reset_days_and_hours() -> None:
    resets_at = time.time() + 2 * 86400 + 3 * 3600
    assert windows_widget.format_reset(resets_at) == "2d 3hr"


def test_format_reset_past_returns_zero() -> None:
    resets_at = time.time() - 100
    assert windows_widget.format_reset(resets_at) == "0min"


def test_compute_month_stats_sums_current_month(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("windows_widget._utcnow", lambda: now)

    entries = [
        _entry("s1", 2026, 5, 1.50),
        _entry("s2", 2026, 5, 2.00),
        _entry("s3", 2026, 4, 5.00),  # last month — excluded
    ]
    cost, sessions = windows_widget.compute_month_stats(entries)

    assert abs(cost - 3.50) < 0.001
    assert sessions == 2


def test_compute_month_stats_deduplicates_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("windows_widget._utcnow", lambda: now)

    entries = [
        _entry("same-session", 2026, 5, 1.00),
        _entry("same-session", 2026, 5, 1.00),
    ]
    _cost, sessions = windows_widget.compute_month_stats(entries)

    assert sessions == 1


def test_compute_month_stats_handles_none_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("windows_widget._utcnow", lambda: now)

    entries = [_entry("s1", 2026, 5, None)]
    cost, sessions = windows_widget.compute_month_stats(entries)

    assert cost == 0.0
    assert sessions == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_windows_widget.py -v
```

Expected: `ModuleNotFoundError: No module named 'windows_widget'`

- [ ] **Step 3: Create windows_widget.py with data helpers**

Create `windows_widget.py`:

```python
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from history_loader import UsageEntry


def _utcnow() -> datetime:
    return datetime.now(UTC)


def format_reset(resets_at: float) -> str:
    delta = max(0, int(resets_at - time.time()))
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


def run(mock: bool = False, interval: int = 60) -> None:
    pass  # placeholder — implemented in Task 5
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/test_windows_widget.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```
git add windows_widget.py tests/test_windows_widget.py
git commit -m "feat: add windows_widget data helpers with tests"
```

---

## Task 5: Implement windows_widget.py — tkinter UI

**Files:**
- Modify: `windows_widget.py` (replace the `run` placeholder with full UI)

- [ ] **Step 1: Replace windows_widget.py with full implementation**

```python
from __future__ import annotations

import asyncio
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
    delta = max(0, int(resets_at - time.time()))
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

        self._menu = tk.Menu(self._root, tearoff=0, bg="#2e3250", fg=TEXT,
                             activebackground="#3a3f60", activeforeground=TEXT)
        self._menu.add_command(label="Refresh", command=self._refresh)
        self._menu.add_separator()
        self._menu.add_command(label="Quit", command=self._root.destroy)

        self._data: dict[str, object] = {}
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
        self._data = _fetch_data(self._client, self._mock)
        self._draw()
        self._root.after(self._interval, self._refresh)

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
```

- [ ] **Step 2: Smoke-test with mock data**

```
cd C:\OSEProject\99.SideProject\calude_usage_rain76526
python main.py --mock
```

Expected: floating dark widget appears at top-left of screen showing mock values (42%, 11%, Cost $12.34, Sessions 42). Drag works. Right-click shows Refresh / Quit.

- [ ] **Step 3: Run all tests**

```
python -m pytest -v
```

Expected: all tests pass (new test file passes; existing tests still pass).

- [ ] **Step 4: Commit**

```
git add windows_widget.py
git commit -m "feat: add Windows tkinter desktop widget"
```

---

## Task 6: Rewrite ClaudeUsage.lua for unified data source

This task is in the **dashboard repo** (`C:\OSEProject\99.SideProject\claude_web`), not the fork.

**Files:**
- Modify: `dashboard/rainmeter/ClaudeUsage.lua`

- [ ] **Step 1: Rewrite ClaudeUsage.lua**

Replace the entire contents of `C:\OSEProject\99.SideProject\claude_web\dashboard\rainmeter\ClaudeUsage.lua`:

```lua
-- ClaudeUsage.lua v4.0
-- Reads ~/.claude/usage-status.json (written by usage_statusline.py hook)
-- Scans ~/.claude/projects/**/*.jsonl for month cost + sessions

local data = {}
local statusFile = ''
local projectsDir = ''

function Initialize()
    local home = os.getenv('USERPROFILE') or ''
    statusFile  = home .. '\\.claude\\usage-status.json'
    projectsDir = home .. '\\.claude\\projects'
end

-- ── helpers ──────────────────────────────────────────────────────────────────

local function readFile(path)
    local f = io.open(path, 'r')
    if not f then return nil end
    local s = f:read('*all')
    f:close()
    return s
end

local function formatReset(resets_at)
    local now = os.time()
    local delta = math.max(0, math.floor(resets_at - now))
    local days  = math.floor(delta / 86400)
    local rem   = delta % 86400
    local hours = math.floor(rem / 3600)
    local mins  = math.floor((rem % 3600) / 60)
    if days > 0  then return days .. 'd ' .. hours .. 'hr' end
    if hours > 0 then return hours .. 'hr ' .. mins .. 'min' end
    return mins .. 'min'
end

-- ── rate limit data ───────────────────────────────────────────────────────────

local function loadRateLimits()
    local s = readFile(statusFile)
    if not s then
        data.fh  = 0
        data.fhr = '--'
        data.sd  = 0
        data.sdr = '--'
        return
    end

    -- five_hour
    local fh_block = s:match('"five_hour"%s*:%s*(%b{})')
    if fh_block then
        data.fh  = tonumber(fh_block:match('"used_percentage"%s*:%s*([%d.]+)')) or 0
        local fResets = tonumber(fh_block:match('"resets_at"%s*:%s*([%d.]+)')) or 0
        data.fhr = fResets > 0 and formatReset(fResets) or '--'
    end

    -- seven_day
    local sd_block = s:match('"seven_day"%s*:%s*(%b{})')
    if sd_block then
        data.sd  = tonumber(sd_block:match('"used_percentage"%s*:%s*([%d.]+)')) or 0
        local sResets = tonumber(sd_block:match('"resets_at"%s*:%s*([%d.]+)')) or 0
        data.sdr = sResets > 0 and formatReset(sResets) or '--'
    else
        data.sd  = 0
        data.sdr = '--'
    end
end

-- ── month cost + sessions from JSONL ─────────────────────────────────────────

local function currentYearMonth()
    return tonumber(os.date('%Y')), tonumber(os.date('%m'))
end

local function loadMonthStats()
    local cost     = 0.0
    local sessions = {}
    local curYear, curMonth = currentYearMonth()

    -- list all jsonl files under projectsDir
    local pipe = io.popen('dir /s /b "' .. projectsDir .. '\\*.jsonl" 2>nul')
    if not pipe then
        data.mc = '0.00'
        data.ms = 0
        return
    end

    for filePath in pipe:lines() do
        local f = io.open(filePath, 'r')
        if f then
            for line in f:lines() do
                -- quick pre-filter: must be assistant type with usage data
                if line:find('"type":"assistant"', 1, true) and
                   line:find('"costUSD"', 1, true) then

                    -- extract timestamp year/month
                    local ts = line:match('"timestamp":"(%d%d%d%d%-%d%d)')
                    if ts then
                        local y = tonumber(ts:sub(1, 4))
                        local m = tonumber(ts:sub(6, 7))
                        if y == curYear and m == curMonth then
                            local c = tonumber(line:match('"costUSD"%s*:%s*([%d.eE+-]+)'))
                            if c then cost = cost + c end
                            local sid = line:match('"sessionId"%s*:%s*"([^"]+)"')
                            if sid then sessions[sid] = true end
                        end
                    end
                end
            end
            f:close()
        end
    end
    pipe:close()

    -- count distinct sessions
    local n = 0
    for _ in pairs(sessions) do n = n + 1 end

    data.mc = string.format('%.2f', cost)
    data.ms = n
end

-- ── main update ───────────────────────────────────────────────────────────────

function Update()
    loadRateLimits()
    loadMonthStats()
    return data.fh
end

function GetFiveHourPct()   return data.fh  or 0      end
function GetFiveHourReset() return data.fhr or '--'   end
function GetSevenDayPct()   return data.sd  or 0      end
function GetSevenDayReset() return data.sdr or '--'   end
function GetMonthCost()     return data.mc  or '0.00' end
function GetMonthSessions() return data.ms  or 0      end
```

- [ ] **Step 2: Manual test — verify Rainmeter still shows data**

1. Confirm `~/.claude/usage-status.json` exists (run a Claude Code session if not)
2. In Rainmeter: right-click skin → Refresh skin
3. Verify 5-Hour %, 7-Day %, Cost, Sessions all show non-zero values

- [ ] **Step 3: Commit in dashboard repo**

```
cd C:\OSEProject\99.SideProject\claude_web
git add dashboard/rainmeter/ClaudeUsage.lua
git commit -m "feat: rewrite Rainmeter Lua to read usage-status.json + JSONL"
```

---

## Task 7: Update README (fork repo)

**Files:**
- Modify: `README.md` (add Windows section)
- Modify: `README.en.md` (add Windows section)

- [ ] **Step 1: Add Windows section to README.md**

After the existing installation section, add:

```markdown
## Windows 桌面小工具

> **注意：** 目前僅 Windows 桌面小工具為 Windows 專屬，TUI 模式（`--tui`）同樣可在 Windows 使用。

### 安裝

```powershell
# 建立虛擬環境並安裝
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# 安裝 statusLine hook（只需跑一次）
python main.py --setup

# 重新啟動 Claude Code 讓 hook 生效
```

### 啟動

```powershell
# 啟動浮動視窗（置頂、可拖動）
python main.py

# 用假資料預覽介面
python main.py --mock
```

視窗操作：
- **拖動**：點住視窗任意位置移動
- **右鍵**：Refresh（立即更新）/ Quit（結束）
```

- [ ] **Step 2: Add Windows section to README.en.md**

After the existing installation section, add:

```markdown
## Windows Desktop Widget

> **Note:** Only the desktop widget is Windows-specific. TUI mode (`--tui`) also works on Windows.

### Installation

```powershell
# Create venv and install
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# Install statusLine hook (run once)
python main.py --setup

# Restart Claude Code to activate the hook
```

### Launch

```powershell
# Launch floating widget (always-on-top, draggable)
python main.py

# Preview with mock data
python main.py --mock
```

Widget controls:
- **Drag**: click and drag anywhere on the widget to reposition
- **Right-click**: Refresh (update immediately) / Quit (exit)
```

- [ ] **Step 3: Commit**

```
git add README.md README.en.md
git commit -m "docs: add Windows widget installation and usage instructions"
```

---

## Task 8: Push fork to GitHub

- [ ] **Step 1: Push all commits**

```
cd C:\OSEProject\99.SideProject\calude_usage_rain76526
git push origin main
```

Expected: all commits pushed to `https://github.com/rain76526/usage`.

---

## Verification Checklist

- [ ] `python -m pytest -v` passes in fork repo
- [ ] `python main.py --mock` shows widget with mock data on Windows
- [ ] `python main.py --setup` installs hook without error on Windows
- [ ] After Claude Code restart, `~/.claude/usage-status.json` exists
- [ ] `python main.py` shows real data in widget
- [ ] Rainmeter skin refreshes and shows correct values from `usage-status.json`
