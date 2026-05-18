# usage

[繁體中文](README.md) · English

[![CI](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![Latest Release](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![License](https://img.shields.io/github/license/aqua5230/usage)](LICENSE)

`usage` is a macOS menu bar tool that pins your **Claude Code and Codex** usage to the top-right of your screen. Click the icon for a popover showing the current 5-hour usage, the current 7-day usage, and today's token usage and cost estimate.

It **never calls the Anthropic / OpenAI API** and **never reads the Keychain**, so it avoids the observer effect of "pinging once a minute counts as usage."

<p align="center">
  <img src="docs/popover.png" alt="usage popover" width="320">
</p>

## How it gets the data

Usage numbers come from local files written by Claude Code and Codex — no Anthropic / OpenAI API calls. The one exception: to estimate Codex costs, usage needs a token pricing table. If no local cache exists (`~/.claude/pricing_cache.json`), it downloads the public [LiteLLM pricing JSON](https://github.com/BerriAI/litellm) once and caches it for 7 days. If the download fails, a built-in fallback price is used — usage percentage display is unaffected.

### Claude Code usage

usage installs a small **statusLine hook** — a script that Claude Code automatically pipes data into every time it refreshes its status line. The flow:

1. Claude Code refreshes the status line and packages usage info (5-hour percentage, 7-day percentage, etc.) as JSON.
2. It pipes that JSON to the hook via stdin.
3. The hook writes the JSON to `~/.claude/usage-status.json`.
4. The usage UI reads that file.

Since both sides look at the same source data, **the numbers match exactly what Claude Code itself shows**.

```mermaid
flowchart LR
    A[Claude Code main process] -->|pipes JSON to stdin<br/>on every statusLine refresh| B[usage-statusline.py<br/>hook script]
    B -->|writes| C[(~/.claude/<br/>usage-status.json)]
    D[usage menu bar / TUI] -->|reads| C
    D -->|renders| E[macOS menu bar]
    F((Anthropic API)) -.x.- D
    style F stroke:#c0392b,stroke-dasharray:5 5
```

Read priority:

1. `~/.claude/usage-status.json` — written by the hook usage installs.
2. `~/.claude/tt-status.json` — fallback. If you also use [token-tracker](https://github.com/stormzhang/token-tracker), usage will share its status file.

### Codex usage

Codex CLI doesn't expose a statusLine hook, so usage takes a different route: it scans the conversation logs Codex CLI leaves on disk (`~/.codex/sessions/*.jsonl`). Codex writes `rate_limits` data directly into each log entry — usage reads those fields to get the 5-hour and 7-day quota percentages directly. Today's token count and cost are summed from the token usage recorded in the same files.

If Codex isn't installed or the directory doesn't exist, that part of the UI hides itself and Claude Code stats continue to work normally.

## Requirements

- macOS
- Python 3.13
- Claude Code installed and signed in (Codex is optional)

## Quick start

| I want to… | How |
|-----------|-----|
| Just use it, no setup | [Download the app](#download-the-app) |
| Run from source | [Set up the environment](#set-up-the-environment) |
| Preview the UI without installing | [Preview mode](#preview-mode-no-install-required) |

## Download the app

Go to the [GitHub Releases page](https://github.com/aqua5230/usage/releases/latest) and download the latest `usage.app.zip`. Unzip it and move `usage.app` wherever you like (e.g. `/Applications`).

⚠️ Because this app is not signed with an Apple Developer certificate, **macOS Gatekeeper will block the first launch**.
To open it: find `usage.app` in Finder → right-click → Open → confirm Open. After that, double-clicking works normally.

### First launch: install the hook

The first time you open usage, if Claude Code has never been wired up yet, the popover will detect the missing status file and **show an extra "立即安裝 hook" (Install hook now) button at the bottom**. Click it once — it installs the hook for you. Then **fully quit Claude Code (Cmd+Q) and re-open it**, click "Refresh now" in usage, and the numbers will appear.

If the button doesn't show, usage is already reading data (e.g. you previously installed [token-tracker](https://github.com/stormzhang/token-tracker) and its status file works as a fallback) — nothing else to do.

> **Fallback: install via curl**
> If the in-app button doesn't work or you prefer the command line, paste this in Terminal:
>
> ```bash
> bash <(curl -fsSL https://raw.githubusercontent.com/aqua5230/usage/main/scripts/install-hook.sh)
> ```

## Download

```bash
git clone https://github.com/aqua5230/usage.git
cd usage
```

If you don't use git, go to the [GitHub project page](https://github.com/aqua5230/usage), click the green **Code → Download ZIP**, then `cd` into the unzipped folder.

## Set up the environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This creates an isolated Python environment (`.venv`) for the project, activates it, and installs usage plus its dependencies into it.

## First install (wire up the Claude Code hook — source mode only)

> Using the .app? Just click the "立即安裝 hook" button in the popover on first launch instead — you don't need this section. The steps below are for developers running usage from source.

This single command does two things: copies the hook script into `~/.claude/`, and updates your Claude Code settings to point at it.

```bash
source .venv/bin/activate
python3 main.py --setup
```

**Restart Claude Code once after running this** so it re-reads `~/.claude/settings.json` and refreshes its status line. That refresh is when usage data first lands on disk.

What `--setup` does in detail:

- Copies `usage_statusline.py` to `~/.claude/usage-statusline.py`.
- Points `statusLine` in `~/.claude/settings.json` at that hook.
- If you already had a custom `statusLine`, it is backed up to `settings.usage.previousStatusLine` so nothing is overwritten.

To uninstall:

```bash
python3 main.py --unsetup
```

`--unsetup` restores your original statusLine and removes the hook and `~/.claude/usage-status.json`.

## Run modes

### Menu bar mode (default)

Stays in the macOS menu bar with a short percentage readout. Click it to open the full popover.

```bash
source .venv/bin/activate
python3 main.py
```

- **Menu bar format:** `🐾 37%`. If Codex usage is also detected, a Codex suffix is appended: `🐾 37% · 📜 10%`.

  <img src="docs/menubar.png" alt="menu bar display" width="240">

- **Click the icon to expand the popover.** It has three sections:
  1. Two cards for Claude Code and Codex, each with Session (5-hour) and Weekly (7-day) progress bars and a reset countdown.
  2. A footer card showing current rate, sync status, and today's token usage and cost estimate (Claude uses the actual `costUSD` from its log when available; Codex cost is estimated from token count × pricing table).
  3. Two buttons: "Refresh now" and "Quit".
- **Permissions:** on first launch, macOS may ask whether to allow background execution. Click Allow.

### Terminal TUI mode

If you'd rather stay in a terminal, run the Rich Live TUI — everything draws inside your terminal window via repeated text repaints. You get a pixel-art Claude logo, a spinner, a rotating set of Claude Code's playful loading phrases, and the same two progress bars as the menu bar popover:

<p align="center">
  <img src="docs/tui.png" alt="usage TUI mode" width="480">
</p>

```bash
source .venv/bin/activate
python3 main.py --tui
```

Press `Ctrl+C` to exit.

## Auto-start on login

A LaunchAgent (the macOS service that handles "what should start when this user logs in") makes usage start automatically.

1. **Install:**
   ```bash
   ./scripts/install-launchagent.sh
   ```
   This drops a plist into `~/Library/LaunchAgents/` and loads usage immediately.

2. **Manual start (for testing):**
   ```bash
   launchctl start com.lollapalooza.usage
   ```

3. **Logs:**
   - stdout: `~/Library/Logs/usage/usage.log`
   - stderr: `~/Library/Logs/usage/usage.err.log`

4. **Uninstall:**
   ```bash
   ./scripts/uninstall-launchagent.sh
   ```

## Preview mode (no install required)

If you haven't installed the hook yet, or you just want to see what the UI looks like, run with fake data:

```bash
# Menu bar preview
python3 main.py --mock

# TUI preview
python3 main.py --tui --mock
```

## Options

- `--setup` / `--unsetup` — install or remove the Claude Code statusLine hook.
- `--tui` — force terminal TUI mode (no menu bar).
- `--interval N` — how often (seconds) the UI re-reads the status file. Minimum 30, default 60.
- `--mock` — use fake data; don't read any status file.
- `--force-group {0,1,2,3}` — force a specific rate group (TUI only).

## Debug

To see internal warnings (e.g. swallowed `OSError`s), set:

```bash
USAGE_DEBUG=1 python3 main.py
```

## Behaviour notes

- usage only reads `~/.claude/usage-status.json`, `~/.claude/tt-status.json`, and Codex's session files. It does not call the Anthropic / OpenAI API and does not read the Keychain. The only network activity is a one-time download of the LiteLLM pricing table for Codex cost estimates (cached for 7 days; offline fallback available).
- When Claude Code isn't running, the status file isn't updated — but actual usage isn't changing either (until reset time), so the displayed value is still accurate. After reset time passes, it auto-resets to zero.
- If the status file hasn't been updated for more than 6 hours, the status line notes "status file is N minutes stale, numbers may be out of date."

## Troubleshooting

The "Fix" column distinguishes three kinds of users — find yours first:

- **.app users** — downloaded `usage.app.zip` from GitHub Releases, unzipped, dragged `usage.app` to `/Applications`, double-click to launch like any Mac app. No Terminal, no Python.
- **LaunchAgent users** — cloned the source and ran `./scripts/install-launchagent.sh` so macOS auto-starts usage on login.
- **Source users** — cloned the source and run `python3 main.py` manually in Terminal each time.

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Menu bar shows `--` | Hook not installed, or Claude Code hasn't refreshed yet | **.app users**: click the "立即安裝 hook" button in the popover. **Source users**: run `python3 main.py --setup`. Either way, restart Claude Code once afterwards |
| Accidentally hit "Quit", paw icon disappeared from the menu bar | "Quit" fully terminates the usage process; you have to relaunch it | **.app users**: press `Cmd+Space` for Spotlight, type `usage`, hit Enter; or double-click `usage.app` from `/Applications`. **LaunchAgent users**: run `launchctl start com.lollapalooza.usage` in Terminal. **Source users**: run `python3 main.py` in Terminal again |
| Status says "N minutes stale" | Claude Code isn't running | Open Claude Code and let it run; it updates the file on its next status refresh |
| Codex section is empty | `~/.codex/sessions/` doesn't exist or has no `rate_limits` events yet | Run a Codex conversation to generate log entries |
| Today's cost shows $0.00 | Model name doesn't match the pricing table, or pricing download/cache failed | Delete `~/.claude/pricing_cache.json` to force a re-fetch; or run with `USAGE_DEBUG=1` for details |
| App won't open (blocked by macOS) | Gatekeeper blocks unsigned apps | Finder → find `usage.app` → right-click → Open → confirm Open |

## Build a .app bundle (optional)

If you want to launch usage by double-clicking instead of opening a terminal, build a native macOS app bundle:

```bash
./scripts/build_app.sh
```

The output is `dist/usage.app`. Double-click it or run `open dist/usage.app`.

Each GitHub Release build (push a `v*` tag) automatically builds the app in CI and attaches `usage.app.zip` to the Release page.
