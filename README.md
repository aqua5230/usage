<p align="center">
  <img src="docs/readme-logo.png" alt="usage logo" width="128">
</p>

# usage

### Quota visibility for Claude Code, Codex, and Antigravity, built into the macOS menu bar and Windows system tray.

Keep Claude Code, Codex, and Antigravity quota in view while you work. `usage` puts session limits, weekly limits, and cost context in the macOS menu bar or Windows system tray, so you can manage usage before it interrupts a session.

[繁體中文](README.zh-TW.md) · [简体中文](README.zh-CN.md) · English · [日本語](README.ja.md) · [한국어](README.ko.md) &nbsp;|&nbsp; [Discussions](https://github.com/aqua5230/usage/discussions) &nbsp;|&nbsp; [Landing page](https://aqua5230.github.io/usage/)

[![CI](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![Latest Release](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey.svg)](https://github.com/aqua5230/usage/releases/latest)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13538/badge)](https://www.bestpractices.dev/projects/13538)

<p align="center">
  <img src="docs/showcase.en.png" alt="usage — Claude Code &amp; Codex quota pinned to the macOS menu bar" width="820">
</p>

`usage` keeps your **Claude Code, Codex, and Antigravity** quota pinned to the top-right of your screen, color-coded so warning levels read at a glance. Every number is read passively from local files already on your machine. It **never calls the Anthropic / OpenAI API** and **never reads the Keychain**, so the monitor itself never adds to your token usage.

## Why usage?

Running out of quota mid-session is expensive — especially during a long refactor or debugging run that depends on Claude Code. `usage` surfaces 5-hour and weekly limits *before* you hit the wall, and keeps them visible the whole time. There's no command to run and no page to open; the answer is just there, where you already look.

## Quick Start

```bash
brew install --cask aqua5230/usage/usage
```

It lands in your Applications folder automatically. Right-click **Open** once to pass Gatekeeper, then click the menu bar icon. Prefer a direct download or want the full setup flow? See [Install](#install) below.

## What You Get

### Live Visibility

- **Always-on Monitor:** Your quota lives in the menu bar, color-coded from green to red. Click when you want the full session, weekly, and per-project breakdown.
- **Antigravity Support:** Antigravity (Gemini) session and weekly quota show up as a third card in every panel. Numbers come straight from the official quota API, using the sign-in the Antigravity CLI already keeps on your machine — refreshed every few minutes, with live reset countdowns.
- **Service Status Alerts:** When Claude Code, Claude API, or Codex API has an outage or degraded performance, an orange-red banner appears at the bottom of the relevant panel. It reads only their public Statuspage.io status pages, never an LLM usage API; normal services show no banner. Antigravity is not supported because it has no usable public status page.
- **Context Nudges & Notifications:** When your context window hits 70%, the status line nudges you to `/clear` or `/compact` to prevent token waste. You can also opt-in to system notifications for quota limits and recoveries.
- **Hide Sections:** Only use one or two of the tools? Hide the Claude Code, Codex, or Antigravity section from the menu bar and panels completely with a single click.

### Workflow Helpers

- **Progress Concierge:** Open a new Claude Code session and `usage` hands your last progress straight to the AI, including your last request, uncommitted changes, and unfinished todos. No `/resume`, no recap. Fully local, off by default.
- **Token Saver:** A menu-bar toggle asks Claude Code and Codex to answer more tersely for the session, saving output tokens while keeping code and error messages byte-exact. A light per-message reminder keeps replies from drifting back to verbose in long conversations (A/B-tested: late-conversation replies stay ~40% shorter).
- **Token-waste Health Check:** A daily background diagnosis scans your logs for waste, including repeated file reads, polluter directories, and noisy Bash output. If it finds issues, a one-line heads-up appears; say "show me" and the AI walks you through fixes.

### Reporting & Insight

- **Deep HTML Reports:** Instant, shareable HTML deep reports showing daily and weekly token trends, project rankings, and cost. Includes a **Year in Review** featuring a contribution heatmap and "Wrapped" summary. One click saves a copy as **.html, .csv, or a .png image** — fully offline, with optional project-name masking.
- **TUI & CLI:** Prefer the terminal? Run the rich TUI dashboard with `python3 main.py --tui`, or generate deep analytics with `python3 usage_cli.py report`.

### Experience & Customization

- **10 Visual Themes:** Switch between panel styles including Classic, Matrix, Windows 95, Newspaper, Cloud Observation, Midnight Aquarium, Prism Arcade, Black Hole, World Cup 2026, and Lepidoptera (blueprint).
- **Drag to Reorder:** Grab any quota card and drag it up or down to swap the order — the arrangement is shared across every theme and survives restarts.
- **AI Talent Market:** Bring a ready-made AI team into Claude Code. Browse and install curated subagent personas into `~/.claude/agents/` instantly. Runs fully locally via the bundled CLI.
- **AI Update Daily:** Clicking this menu item opens the public [web page](https://aqua5230.github.io/ai-updates/) in your default browser. The page auto-updates every day, covers Claude Code, Codex, and Antigravity, and keeps the full history; reviewed updates show a plain-language summary in all five languages, while unreviewed ones show the official source text.
- **Spirit Companions:** A small animated white silhouette lives beside your usage percentages — a phoenix for Claude, a dragon for Codex, a lion for Antigravity. Each accelerates dynamically as its own tool's token burn rate climbs.
- **Automatic Localization:** UI text is available in Traditional Chinese, Simplified Chinese, English, Japanese, and Korean, automatically matching your system settings.

## Privacy & Data Sources

- Usage numbers are read **only from local log files** on your machine.
- It **never calls the Anthropic / OpenAI API** and **never reads the Keychain** (macOS's password vault).
- Antigravity quota is fetched from the official quota API using the OAuth token the Antigravity CLI stores locally after sign-in. `usage` treats that token file as strictly read-only, and the call itself only reads quota metadata — it never consumes your model quota.
- The only network activity: fetching a public model-pricing table to estimate cost (falls back to built-in prices offline) and occasionally checking GitHub for a new version. **Nothing is ever uploaded.**

## Requirements

- macOS or Windows 10/11
- Claude Code, Codex, or Antigravity has been used at least once (so local usage data exists).
- (Source runs only) Python 3.13.

## Install

### 1. Homebrew (Recommended)

Installing via Homebrew means a single `brew upgrade --cask usage` keeps it current.

```bash
brew install --cask aqua5230/usage/usage
```

*(First launch: right-click `usage.app` in Finder → **Open** to pass Gatekeeper).*

### 2. Download for macOS

1. Download the latest `usage.app.zip` from the [GitHub Releases page](https://github.com/aqua5230/usage/releases/latest).
2. Unzip it and drag `usage.app` into your Applications folder.
3. First launch: in Finder, right-click `usage.app` → **Open** → confirm Open.

## Windows Support

Windows has the full core experience: the TUI, Claude Code status-line hook, and Codex history parsing all work natively. Download `usage-windows.zip` from the [latest GitHub Release](https://github.com/aqua5230/usage/releases/latest), unzip it, then run `usage.exe`—no installer is needed. The tray UI requires Microsoft Edge WebView2 Runtime, which is normally included with Windows 10 and 11.

The system-tray icon updates with your Claude quota percentage; its tooltip summarizes the Claude and Codex windows. Left-click opens the same 11 HTML panels as macOS (Classic plus the ten themes) in WebView2. Right-click provides panel switching, refresh, launch at login, check for updates, and quit.

Windows differences: the panel opens at the bottom-right of the working area rather than next to the tray icon; update prompts use a system Yes/No dialog; and the AI Talent Market panel is macOS-only.

### First Launch: Set Up the Status Line

If you've used Codex, `usage` picks up its history automatically. For Claude Code, click the **"Set Up Status Line"** button in the app popover to install the sync hook.
Restart the relevant tool afterward (fully Cmd+Q Claude Code and re-open it).

Once set up, the bottom of the Claude Code window will show a status line like this:

<p align="center">
  <img src="docs/statusline.en.png" alt="Claude Code statusLine display (English)" width="640">
</p>

## Theme Gallery

Switch between **10 visual themes** directly from the UI:

<p align="center">
  <img src="docs/matrix.en.png" width="32%" alt="Matrix theme" />
  <img src="docs/win95.en.png" width="32%" alt="Windows 95 theme" />
  <img src="docs/world_cup.en.png" width="32%" alt="World Cup HUD theme" />
  <img src="docs/newspaper.en.png" width="32%" alt="Newspaper theme" />
  <img src="docs/aquarium.en.png" width="32%" alt="Aquarium theme" />
  <img src="docs/black_hole.en.png" width="32%" alt="Black Hole theme" />
</p>

## Troubleshooting

If the menu bar shows `--`, it's usually not broken — there's just no local data yet.

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Menu bar shows `--` | No data yet, or Claude Code hook not refreshed | Run one Codex conversation. For Claude Code, click "Set Up Status Line" or run `python3 main.py --setup` |
| Accidentally hit "Quit" | Process terminated | Launch `usage.app` from Spotlight / Applications, or run `launchctl start com.lollapalooza.usage` |
| Status says "N minutes stale" | Claude Code isn't running | Open Claude Code and let it run |
| Codex section is empty | No Codex history found | Run a Codex conversation to generate logs |
| Today's cost shows $0.00 | Model pricing missing | Delete `~/.usage/pricing_cache.json` or check `USAGE_DEBUG=1` |
| Antigravity card is missing | Antigravity CLI not installed or not signed in | Install and sign in to the Antigravity CLI; the card appears automatically once a background quota fetch succeeds |
| App won't open | macOS Gatekeeper blocked it | Right-click `usage.app` in Finder → Open |
| App crashes immediately (arm64) | py2app bundling bug in older versions | Upgrade to **v0.11.1 or newer** |

## Comparison

| Feature | usage | ccusage | TokenTracker |
|---------|:-----:|:-------:|:------------:|
| Always on screen | ✅ | — | ✅ |
| macOS menu bar | ✅ | — | ✅ |
| Claude Code & Codex usage | ✅ | Claude only | ✅ |
| Antigravity (Gemini) usage | ✅ | — | — |
| Claude Code & Codex service-status alerts | ✅ | — | — |
| HTML deep reports & UI | ✅ | ✅ | — |
| AI Talent Market | ✅ | — | — |
| AI Update Daily | ✅ | — | — |
| Progress Concierge & Token Saver | ✅ | — | — |
| Token-waste Health Check | ✅ | — | — |
| Zero API calls | ✅ | ✅ | ✅ |
| Open-source license | AGPL-3.0 | MIT | — |

## Development

Want to run the terminal TUI, configure custom agents, or build the app yourself? Check out the **[development docs](docs/DEVELOPMENT.md)**.

## License

Licensed under AGPL-3.0-only (see [LICENSE](LICENSE)). If you fork or redistribute a modified version, please credit the original author and link back to:
https://github.com/aqua5230/usage

## Star History

<a href="https://star-history.com/#aqua5230/usage&Date">
  <img src="https://api.star-history.com/svg?repos=aqua5230/usage&type=Date" alt="usage Star History Chart" width="600">
</a>
