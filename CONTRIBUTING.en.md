# Contributing

[繁體中文](CONTRIBUTING.md) · English

Issues and PRs are welcome. This document only spells out hard requirements; it does not dictate process.

## Opening an Issue

- **Bug report**: use the `.github/ISSUE_TEMPLATE/bug_report.md` template. Please include macOS version, Python version, `git rev-parse --short HEAD`, and which mode you were running (menu bar / TUI / mock).
- **Feature request**: use the `.github/ISSUE_TEMPLATE/feature_request.md` template.

## Required checks before opening a PR

```bash
source .venv/bin/activate
uv run ruff check
uv run mypy .
uv run pytest -v
```

All three must be green to merge. CI runs the same three (`.github/workflows/check.yml`).

## Code change guidelines

- **When changing prod modules, add tests alongside.** Pick the closest existing file under `tests/` as a style reference. Tests must never touch real `~/.claude/` or `~/.codex/` — use `monkeypatch` to redirect path constants.
- **Keep internal and public naming unified as `usage`.** File paths, settings keys, binary names, environment variables, and the LaunchAgent label all use the `usage` prefix.
- **Be deliberate with `menubar.py` UI constants** (`CARD_HEIGHT`, `CARD_RADIUS`, `SECTION_GAP`, etc.); they are part of the popover's visual design.

## CHANGELOG and releases

- For every change, add an entry to the `## Unreleased` section of `CHANGELOG.md`, **and also update the corresponding section in `CHANGELOG.en.md`** (this project keeps the README, CHANGELOG, and release notes bilingual).
- Releases are cut by the maintainer (bump version in `pyproject.toml`, rename `## Unreleased` to `## X.Y.Z — YYYY-MM-DD`, commit `Release vX.Y.Z`, push tag).

## Commit message style

Match the existing `git log`: imperative subject line; add a body explaining *why* (not *what* — the diff already shows what) when useful. Example:

```
Fix AttributeError: drop stale tracker.sample() call

072a088 removed UsageRateTracker.sample() but missed the lone caller in
menubar.py:435...
```
