# Changelog

[繁體中文](CHANGELOG.md) · English

All notable changes to usage are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## 0.1.5 — 2026-05-18

### CI
- Bumped `actions/setup-python` from v5 to v6 (v6 runs on Node.js 24). GitHub had been warning that v5 runs on Node.js 20 and the runner will force Node 24 after 2026-09-16; pre-empting the breakage.

### Documentation
- `pyproject.toml`'s `description` was rewritten from "在 macOS 終端機顯示 Claude Code 用量的繁中小工具" (terminal-only) to "usage — 在 macOS menu bar 顯示 Claude Code 用量的繁中小工具（也提供終端機 TUI）". The old description misrepresented the project as terminal-only; the new one reflects the menu-bar-first reality and aligns the displayed project name with the repo.

## 0.1.4 — 2026-05-18

### CI
- Release workflow (`.github/workflows/release.yml`) is now self-healing: after a tag is pushed, if the matching GitHub release does not exist yet, the workflow first creates it via `gh release create` (empty notes, target set to the tag's ref) and then uploads `usag.app.zip`. The "workflow assumes release already exists, upload fails" trap hit during 0.1.3 won't recur.

### Build
- Tightened `menubar.py` mypy config from a blanket `# mypy: ignore-errors` to `disable-error-code="import-untyped,misc"`, which only suppresses PyObjC's missing stubs and dynamic base-class errors. Real type errors (the class of bug behind `tracker.sample`'s `AttributeError`) will now be caught.

## 0.1.3 — 2026-05-18

### Changed
- Popover redesigned: Claude / Codex sections now sit in subtle inset cards, with refined spacing, font weights, and muted footer text. Card fill adapts to Dark / Light appearance.
- `docs/popover.png` updated to the new look.

### Fixed
- Live data no longer collapses to `--` with `狀態：錯誤 (AttributeError)`. The stale `self.tracker.sample(...)` call in `menubar.py` (left over from 0.1.2's `sample()` removal) raised `AttributeError` on every successful refresh; dropped the call. `tracker.group()` already reads history entries directly.

## 0.1.2 — 2026-05-17

### Changed
- `pricing.py`: pricing cache moved from the package directory to `~/.claude/pricing_cache.json` so the read-only `.app` bundle can refresh the cache.
- Applied `ruff format` across the project (formatting only; no logic changes).

### Removed
- `UsageRateTracker.sample()` dead code (was a no-op called from `main._apply_outcome`).

### Build
- `.gitignore` now excludes `*.egg-info/` and `.pytest_cache/`.

## 0.1.1 — 2026-05-17

### Added
- py2app `.app` bundle build config (`setup_app.py`, `build_app.sh`) so users can run usag without a terminal.
- GitHub Actions release workflow (`release.yml`) automatically builds `usag.app.zip` and attaches it to each tagged release.
- English README (`README.en.md`) and a language switcher at the top of both READMEs.

## 0.1.0 — 2026-05-17

First public release on GitHub.

### Added
- pytest test suite under `tests/` covering `pricing`, `history_loader`, and `usage_rate` (44 tests, 89% line coverage).
- CI runs `pytest -v` after ruff and mypy.
- GitHub Actions CI runs `ruff check` and `mypy` on push to main and pull requests (macos-latest runner, uv-managed deps).
- `USAG_DEBUG=1` environment variable enables warning-level logger output for the previously silent OSError sites.
- Issue templates (bug report, feature request) and pull request template under `.github/`.

### Changed
- `menubar.py`: I/O moved off the AppKit main thread (background `threading.Thread` + `performSelectorOnMainThread_withObject_waitUntilDone_`), eliminating the periodic UI freeze on each refresh tick. A `_refresh_in_flight` flag prevents re-entry.
- `usage_rate.py`: 30-second TTL cache for `group()`; stops re-scanning the last hour of JSONL on every TUI tick.
- `menubar.py`: divider lines re-centered between provider blocks (first_y=178, second_y=352). "今日" status line returned to 12pt to match the rest of the footer.
- README: use `python3` instead of `python` (the uv venv only ships the `python3` symlink); documented `USAG_DEBUG`.

### Fixed
- `setup_hook.py` and `pricing.py` use atomic writes (`tempfile.mkstemp` + `os.replace`); a crash mid-write no longer corrupts `~/.claude/settings.json` or `pricing_cache.json`.
- `install-launchagent.sh` uses `BASH_SOURCE` to resolve the project directory; previously broke when run from anywhere other than the project root.
- `uninstall-launchagent.sh` removes logs from `~/Library/Logs/usag/` (the actual location), not from the project directory.
- `pricing_cache.json` expires after 7 days based on mtime, so stale prices don't linger after a model price drop.
- Seven previously silent `except OSError` sites in `pricing.py`, `codex_loader.py`, and `history_loader.py` now log a warning before swallowing the error.

### Removed
- `blocks.py` — unused dead code.
