# Design: Windows Widget Auto-Setup statusLine Hook

**Date:** 2026-05-21  
**Scope:** `windows_usage.py` — add `_ensure_hook()` called from `main()`

## Problem

`windows_widget.py` uses `ClaudeUsageClient` which reads `~/.claude/usage-status.json`.
This file is only written when Claude Code's `statusLine` hook is installed (via `setup_hook.setup()`).
On Windows, users have no automatic prompt to run `--setup`, so the hook is silently missing and the widget shows no data.

## Goal

When a user launches the Windows widget normally (no `--setup`/`--unsetup` flags), auto-detect if the hook is installed and install it if not, then show a dialog prompting restart.

## Architecture

### Entry point change — `windows_usage.py`

Add `_ensure_hook()` called from `main()` **before** `windows_widget.run()`.

```
main():
  parse args
  if args.setup  → setup_hook.setup()  → exit   (unchanged)
  if args.unsetup → setup_hook.unsetup() → exit  (unchanged)
  _setup_logging()
  _ensure_hook()           ← NEW
  windows_widget.run(mock=args.mock)
```

### `_ensure_hook()` logic

```python
def _ensure_hook() -> None:
    from setup_hook import _load_settings, _is_usage_hook, setup
    import tkinter
    import tkinter.messagebox

    settings = _load_settings()
    if _is_usage_hook(settings.get("statusLine")):
        return  # already installed, no-op

    ret = setup()  # prints to stdout as usual
    root = tkinter.Tk()
    root.withdraw()
    if ret == 0:
        tkinter.messagebox.showinfo(
            "statusLine Hook 已安裝",
            "請重新啟動 Claude Code 以啟用用量追蹤。",
        )
    else:
        tkinter.messagebox.showerror(
            "安裝失敗",
            "statusLine hook 安裝失敗，請手動執行：\n\n"
            "  python windows_usage.py --setup",
        )
    root.destroy()
```

### Skip condition

- `--mock` mode: `_ensure_hook()` is called after flag check but before `run()`. Mock mode passes through `windows_widget.run(mock=True)` — no change needed; `_ensure_hook()` still runs but that's harmless (idempotent if already installed). If desired, skip with `if args.mock: return` inside `_ensure_hook()` — defer to implementation decision.

## Data flow

```
main()
  └─ _ensure_hook()
       └─ _load_settings()        reads ~/.claude/settings.json
       └─ _is_usage_hook(sl)      checks sl["command"] contains "usage-statusline"
       └─ setup()                 copies hook script + writes settings.json
       └─ messagebox              informs user to restart Claude Code
  └─ windows_widget.run()
       └─ ClaudeUsageClient       reads ~/.claude/usage-status.json (written by hook)
```

## Error handling

| Scenario | Behaviour |
|---|---|
| Hook already installed | no-op, no dialog |
| Hook not installed, setup succeeds | info dialog → user restarts Claude Code |
| Hook not installed, setup fails (missing script, permissions) | error dialog with manual fallback command |
| `~/.claude/settings.json` missing or malformed | `_load_settings()` returns `{}` → `_is_usage_hook({})` → False → setup() handles it |

## Out of scope

- Auto-restart Claude Code (not possible from external script)
- Checking if `usage-status.json` is stale / hook not firing (separate issue)
- Codex integration in Windows widget (tracked separately)

## Files changed

| File | Change |
|---|---|
| `windows_usage.py` | Add `_ensure_hook()`, call it from `main()` |
| `setup_hook.py` | No change — `_load_settings` and `_is_usage_hook` already public enough |
