# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`usage` is a macOS menu bar (and TUI) app that pins Claude Code + Codex quota usage to the screen. Python 3.13, PyObjC for the menu bar UI, `rich` for the TUI. **No Anthropic/OpenAI APIs are ever called** — all numbers come from files on disk (a statusLine hook Claude Code writes, and Codex's `~/.codex/sessions/*.jsonl` logs).

## Commands

Environment is managed with `uv` in CI and a plain `.venv` locally (both work; `uv.lock` is the source of truth).

```bash
# Setup (one-time)
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
# or: uv sync --frozen --group dev

# Run (menu bar mode, default)
python3 main.py
python3 main.py --mock                  # preview with fake data
python3 main.py --tui                   # terminal TUI mode
python3 main.py --setup / --unsetup     # (un)install Claude Code statusLine hook
USAGE_DEBUG=1 python3 main.py           # surface swallowed exceptions

# Pre-PR checks — all three must pass (CI runs identical commands)
uv run ruff check
uv run mypy .
uv run pytest -v

# Single test
uv run pytest tests/test_usage_client.py::test_name -v

# Build .app bundle (output: dist/usage.app)
./scripts/build_app.sh
```

Tests **must not** touch real `~/.claude/` or `~/.codex/` files — patch the path constants with `monkeypatch` (see existing tests for the pattern). All three checks (`ruff`, `mypy --strict`, `pytest`) are gated by `.github/workflows/check.yml`.

## Architecture

### Data flow — how quota numbers get on screen

Two separate input channels feed one UI:

```
Claude Code ──stdin──> usage_statusline.py (hook) ──write──> ~/.claude/usage-status.json
                                                                       │
~/.codex/sessions/*.jsonl  (Codex writes these natively) ──┐           │
                                                            ▼           ▼
                                              codex_loader.py    usage_client.py
                                                            └────┬──────┘
                                                                 ▼
                                                   menubar.py  /  tui.py
```

- **Claude Code side**: `usage_statusline.py` is installed into `~/.claude/usage-statusline.py` by `setup_hook.py` and wired into `~/.claude/settings.json`'s `statusLine`. Every time Claude Code refreshes its status line, it pipes the session JSON to the hook on stdin; the hook atomically writes it to `~/.claude/usage-status.json`. The UI reads that file — never the network.
- **Codex side**: no hook is possible (Codex CLI has no equivalent), so `codex_loader.py` scans `~/.codex/sessions/**/*.jsonl` and pulls `rate_limits` straight from the conversation logs.
- **Read priority** in `usage_client.py`: `usage-status.json` → `usag-status.json` (v0.1.x legacy) → `tt-status.json` (compat fallback for users migrating from the third-party tool `stormzhang/token-tracker`; **NOT an in-repo module — no `token-tracker` directory or source exists anywhere on this machine**).

### Module map

| Module | Role |
|---|---|
| `main.py` | argparse + entry point; dispatches to `menubar.run_app`, `run_tui`, or `setup_hook.setup/unsetup`. |
| `usage_client.py` | Reads the Claude Code status JSON, builds a `UsageSnapshot`. Async interface preserved for the polling loop even though reads are sync. |
| `codex_loader.py` | Parses Codex JSONL session logs for both rate-limits and per-message token usage. Also reads `~/.codex/state_5.sqlite` (read-only) for thread→model mapping. |
| `history_loader.py` | Parses Claude Code's per-project JSONL logs under `~/.claude/projects/` for token totals and cost. |
| `pricing.py` | Cost estimation. Downloads LiteLLM's `model_prices_and_context_window.json` once, caches to `~/.claude/pricing_cache.json` (TTL 7 days; 10-min TTL on fallback so offline-then-online recovers). |
| `usage_rate.py` | Burn-rate classifier (Idle/Normal/Active/Heavy) — drives sprite animation speed in TUI. |
| `burn_rate.py` | Burn-rate prediction core used by `menubar.py`. |
| `menubar.py` | PyObjC menu bar + popover UI. `# mypy: disable-error-code="import-untyped,misc"` is intentional (PyObjC has no stubs). UI layout constants near the top of the file are part of the visual design — don't tweak casually. |
| `tui.py`, `tui_sprite.py` | `rich`-based terminal renderer. |
| `tips_loader.py` | Loads tips for the TUI. |
| `usage_lang.py` | Detects `USAGE_LANG` / system locale. |
| `setup_hook.py` | Idempotent install/uninstall of the Claude Code statusLine hook, including migration of v0.1.x `usag-*` artifacts. Backs up any pre-existing `statusLine` under `settings["usage"]["previousStatusLine"]`. |
| `usage_statusline.py` | The hook itself. **Stdlib-only** so it can run under macOS's bundled `/usr/bin/python3` (3.9) — that's why `tool.ruff.lint.per-file-ignores` excludes `UP017` (`datetime.UTC`) for this one file; use `timezone.utc` here. |
| `usage_statusline_forwarder.py` | Multi-hook fan-out. **Stdlib-only** so it can run under macOS's bundled `/usr/bin/python3` (3.9), with the same constraints as `usage_statusline.py`. |
| `update_checker.py` | GitHub Releases update check added in v0.11.0. |
| `login_item.py` | Login item toggle for launching at login. |
| `panels/` | HTML panel logic and `NSPopover` / `WKWebView` integration. |
| `adapters/`, `analyzer/`, `ui/` | HTML report subsystem. |
| `setup_app.py` | `py2app` build script invoked by `scripts/build_app.sh`. Bundles `usage_statusline.py` and asset webps as `Resources/`. |

### Naming invariant

Everything user-facing and on-disk uses the `usage` prefix: bundle id `com.lollapalooza.usage`, LaunchAgent label, hook filename, status filename, settings backup key. The `usag-*` form is **legacy v0.1.x only** — kept as a read-fallback for migration, never written. Don't reintroduce it.

### i18n rule

All user-visible strings in panels and UI **must** be looked up from `i18n.json` via the `_t()` helper (or the JS `t()` function in HTML panels). Never hardcode any language's text directly in Python, HTML, or TUI code. When adding a new panel or new UI strings, add the key to all five language sections in `i18n.json` (`zh-TW`, `zh-CN`, `en`, `ja`, `ko`) before shipping.

### Release / changelog

- This project is **fully bilingual**: every CHANGELOG / contributing / development doc has a `.md` (繁中) and `.en.md`. Any user-facing doc change must update both. **Exception — README:** the default `README.md` is **English** (so the GitHub landing page is English for international visitors) and Traditional Chinese lives in `README.zh-TW.md`. The README pair is the inverse of every other doc; don't "fix" it back.
- Version is bumped in `pyproject.toml`; CI builds `usage.app.zip` and attaches it on `v*` tags (`.github/workflows/release.yml`).
- The `.app` build flow renames `dist/main.app` → `dist/usage.app` (see `scripts/build_app.sh`) — this is expected, not a bug.
