# Windows Desktop Widget — Design Spec

**Date:** 2026-05-20  
**Repo:** rain76526/usage (fork of aqua5230/usage)  
**Goal:** Add a Windows always-on-desktop floating widget that mirrors the Rainmeter skin layout, unified under a single hook + JSON data source.

---

## Problem

The existing repo is macOS-only (PyObjC). Windows users have no native widget. A Rainmeter skin exists but uses a separate pre-processing hook (`claude_usage_hook.py`) that writes a different JSON format than the project's canonical `usage-status.json`.

---

## Solution

1. Add `windows_widget.py` — tkinter floating widget for Windows
2. Unify data source: both widget and Rainmeter read from `~/.claude/usage-status.json` (written by `usage_statusline.py`, the project's existing hook)
3. Update Rainmeter Lua to parse `usage-status.json` + JSONL history for cost/sessions
4. Update `main.py` to dispatch to Windows widget on `sys.platform == "win32"`

---

## Architecture

```
Claude Code statusLine hook (usage_statusline.py)
        ↓
~/.claude/usage-status.json
        ├── windows_widget.py (import usage_client + history_loader)
        └── ClaudeUsage.lua (Rainmeter — reads JSON + JSONL)

main.py
  sys.platform == "win32"  → windows_widget.run()
  sys.platform == "darwin" → menubar.run_app()
```

---

## Files Changed

| File | Action | Notes |
|------|--------|-------|
| `windows_widget.py` | **New** | tkinter widget, imports usage_client + history_loader |
| `main.py` | **Modify** | Add win32 branch; guard PyObjC import behind darwin check |
| `pyproject.toml` | **Modify** | `pyobjc` dep: add `; sys_platform == "darwin"` |
| `setup_hook.py` | **Verify** | Already uses `os.path.expanduser` — Windows compatible |
| `dashboard/rainmeter/ClaudeUsage.lua` | **Rewrite** | Parse usage-status.json + JSONL for cost/sessions |
| `README.md` / `README.en.md` | **Modify** | Add Windows installation section |

---

## `windows_widget.py` — Detailed Design

### Visual Layout (matches Rainmeter skin)

```
┌─────────────────────────────┐
│ Claude Code Usage           │  ← title, font Segoe UI 11px bold
├─────────────────────────────┤
│ 5-Hour Window               │  ← label, muted
│ ████████░░░░░░░░░░  42%     │  ← Canvas progress bar (green)
│ Reset in 45min              │  ← muted small text
├─────────────────────────────┤
│ 7-Day Window                │
│ ██░░░░░░░░░░░░░░░░  11%     │
│ Reset in 2d 3hr             │
├─────────────────────────────┤
│ This Month                  │
│ Cost $12.34  |  Sessions 42 │
└─────────────────────────────┘
```

**Size:** 220×176px  
**Colors:** bg `#1a1d27` (alpha 0.88), text `#e2e8f0`, muted `#8892b0`, bar `#1d9e75`, border `#2e3250`  
**Font:** Segoe UI (Windows native)

### Behavior

- Frameless: `overrideredirect(True)`
- Always-on-top: `wm_attributes("-topmost", True)`
- Semi-transparent: `wm_attributes("-alpha", 0.88)`
- Draggable: bind `<Button-1>` records offset, `<B1-Motion>` moves window
- Right-click context menu: **Refresh** / **Quit**
- Auto-refresh: `widget.after(60_000, refresh)` every 60s

### Data Flow

```python
# Rate limits
outcome = asyncio.run(ClaudeUsageClient().fetch_once())
snapshot = outcome.snapshot  # five_hour%, seven_day%, reset timestamps

# Cost / sessions (this calendar month)
entries = load_entries()
now = datetime.now(UTC)
month_entries = [e for e in entries if e.timestamp.year == now.year and e.timestamp.month == now.month]
month_cost = sum(e.cost_usd or 0 for e in month_entries)
month_sessions = len({e.session_id for e in month_entries})
```

### Reset Label Format

```python
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
```

---

## `ClaudeUsage.lua` — Rewrite Design

**Current:** reads `claude_usage_rainmeter.json` (pre-processed)  
**New:** reads `usage-status.json` (raw) + scans JSONL for cost/sessions

### Lua Logic

1. Read `%USERPROFILE%\.claude\usage-status.json` via `io.open`
2. Parse JSON (minimal hand-rolled parser or regex — Lua has no JSON lib)
3. Extract `rate_limits.five_hour.used_percentage`, `resets_at`, same for seven_day
4. Compute reset label from `resets_at` timestamp
5. Scan `%USERPROFILE%\.claude\projects\**\*.jsonl` via `io.lines`
6. Filter lines where `type == "assistant"` and timestamp in current month
7. Sum `costUSD`, count distinct `sessionId`

---

## `main.py` — Changes

```python
import sys

def main():
    ...
    if sys.platform == "win32":
        import windows_widget
        windows_widget.run(mock=args.mock, interval=args.interval)
        return
    # existing macOS path below
    import menubar
    ...
```

PyObjC imports stay inside the macOS branch — no import-time failure on Windows.

---

## `pyproject.toml` — Changes

```toml
dependencies = [
    "pyobjc-framework-Cocoa>=11.0 ; sys_platform == 'darwin'",
    "rich>=14.0.0,<15.0.0",
]
```

---

## Launch Commands (Windows)

```powershell
# Install hook (run once)
python main.py --setup

# Run widget
python main.py

# Preview with mock data
python main.py --mock
```

---

## Out of Scope

- Windows system tray icon (user chose always-on-desktop)
- Codex data on Windows (no Codex CLI for Windows)
- Auto-start on login (can be added separately via Task Scheduler)
- `.exe` packaging (can be added separately with PyInstaller)

---

## Testing

- `--mock` flag exercises full render path without real data files
- Existing tests (`pytest`) must still pass on macOS
- No new Windows-specific tests required (tkinter render not testable headlessly)
