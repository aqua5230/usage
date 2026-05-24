# Changelog

[繁體中文](CHANGELOG.md) · English

All notable changes to usage are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.10.1] - 2026-05-24

### Fixed
- **Weekly burn-rate warning false positive**: Extrapolating the last 10 minutes of usage slope onto a 7-day weekly quota was too aggressive (e.g. 56% used → projected 5h50m to exhaustion → "Runs out in 5h50m (resets in 4d6h)" warning), since users don't sustain that rate 24/7. Fix: `_quota_row` gained a `warning_max_seconds` parameter, and the three weekly call sites pass a 24h ceiling — projections beyond 24 hours no longer trigger the warning. Session warnings are unchanged.

## [0.10.0] - 2026-05-24

### Added
- **HTML report Share button**: A new Share button in the top-right opens a file-share modal with two actions — "Download .html" and "Copy file path" — so you can send the report via AirDrop / Mail / Slack / iMessage to a colleague or manager. Recipients open it in any browser on mobile or desktop.
- **"Hide project names" toggle on download**: A checkbox inside the share modal (default ON, privacy-first) swaps every project name to `Project 1 / Project 2 / ...` before the HTML is serialized for download. The on-screen report is unaffected.
- **HTML report sponsor section reworked**: Two Ko-fi badges now flank the brand slogan `No cloud. No tracking. Just yours.` (kept in English across all five UI languages). The slogan carries a subtle wobble animation to draw the eye, and the GitHub link (github.com/aqua5230/usage) appears below.

### Changed
- **statusLine second line removed**: The cumulative token totals / cache / cost line has been dropped to simplify visuals. Key info now lives on line 1 (5h / 7d / Context window) and line 3 (session duration, model).
- **HTML report KPI card widths rebalanced**: tokens / cost are now wider; sessions / messages / active days narrower (grid ratio 1.5fr 1.4fr 1fr 1fr 1fr), preventing 9-digit token counts from wrapping.

### Removed
- HTML report footer line `usage · Local-first analytics · Data stays on device` — replaced by the GitHub link in the sponsor section.

## [0.9.1] - 2026-05-23

### Fixed
- **TUI polling never updated after first fetch**: a `continue` in `poll_usage` caused every timeout to jump back to the loop head, leaving the UI frozen at the initial state. Changed to `pass` so the polling path is actually reached.
- **Inconsistent env var name**: `USAG_FORCE_GROUP` (v0.1.x legacy prefix) renamed to `USAGE_FORCE_GROUP` to match all other env vars in the project.
- **Redundant filesystem scans per refresh**: `_refresh_in_background` was calling `history_loader.load_entries` four times per cycle (24h × 2, 168h × 1, 720h × 1). Now loads the 720h superset once and passes it down, eliminating the duplicate I/O.

### Changed
- `pricing.py` User-Agent updated from the stale `usage/0.2` to `usage/0.9`.
- `--setup` no longer prints a "no migration needed" message on clean installs.

## [0.9.0] - 2026-05-22

### Added
- **New "World Cup 2026" panel**: FIFA broadcast HUD style. Top-down green pitch with grass stripes, white field markings (halfway line, centre circle, penalty boxes, corner arcs), dark broadcast scoreboard showing Claude / Codex Session percentages as large numerals (38 px), bidirectional duel bar (Claude ← centre line → Codex) replacing the standard progress bar. Canvas animation: a pentagon-pattern football rolling in the lower pitch area, 12 stick-figure players (6 per team) roaming their zones — the nearest player chases the ball at 0.8 px/frame and kicks it on contact (60-frame cooldown per team), directing it toward the opponent's goal. Bottom section shows a MATCH STATS standings board. Triggers a golden GOAL! celebration overlay when either side's usage hits ≥ 85 %.

## [0.8.0] - 2026-05-22

### Added
- **New "Prism Arcade" panel**: deep purple-black background, Canvas conic rainbow halo rotating slowly, geometric prism shards (triangles/diamonds) drifting randomly, coloured light particles flickering, cards with holographic gradient borders (CSS background-clip technique), full-spectrum rainbow progress bars with sweep animation.
- **New "Black Hole" panel**: pure-black space background, Canvas 2D star field (120 stars with twinkling), rotating accretion disk (orange-yellow-white gradient ellipse, Doppler brighter-left/darker-right), photon ring, event horizon with blue-purple glow, orange particles orbiting the ellipse, amber glass cards.

### Fixed
- **Fix extra space at bottom of three panels**: added `flex: 1` to `.projects-card` in Aquarium, Prism Arcade, and Black Hole so content fills the full panel height.
- **Reduce card opacity in three animated panels**: card background opacity lowered from 0.5–0.75 to 0.14–0.28 in Aquarium, Prism Arcade, and Black Hole so the background animations show through more.

## [0.7.0] - 2026-05-22

### Added
- **New "Midnight Aquarium" panel**: sixth built-in panel with a deep-sea animation theme — Canvas 2D bubbles rising from the bottom (42 bubbles with random drift), 4 CSS jellyfish (floating up/down with cyan glow), bioluminescent particles in the background. Glass-morphism cards with backdrop-filter blur, progress bars with a sweeping light animation. Adds i18n key `panel_aquarium` (all 5 languages).
- **Fix .app language detection**: switched to `NSLocale.preferredLanguages()` instead of `currentLocale().localeIdentifier()` so the bundle language is no longer overridden by `CFBundleDevelopmentRegion = English` — Traditional Chinese users now see the correct UI language when launching the .app.

## [0.6.9] - 2026-05-22

### Added
- **New "Cloud Observation" panel**: fifth built-in panel with a weather-station visual — light blue sky gradient, white cloud layers (with `feGaussianBlur` soft edges), pale contour lines, and translucent glass cards. Light overall tone, with `backdrop-filter` letting the clouds peek through. Adds i18n key `panel_cloud_observation` (all 5 languages).

## [0.6.8] - 2026-05-22

### Fixed
- **Fix .app launch failure when i18n.json is missing**: py2app now includes `i18n.json` in the resource list, and the menu bar / Web panel loaders prefer the `.app` bundle's `Contents/Resources/i18n.json` before falling back to source-tree paths, preventing the `FileNotFoundError` that broke v0.6.0+ launches.

## [0.6.7] - 2026-05-22

### Fixed
- **Burn-rate warning false positives**: after v0.6.6 shipped, real-world testing showed the red warning firing at 1% / 14% / 36% used right after restart, because a 2-point slope based on only 2-3 fresh samples is unstable and low-percent forecasts have huge headroom regardless. Fix adds two guardrails: forecasting only runs when the last-10-minute window holds ≥ 5 samples spanning ≥ 5 minutes; the warning only replaces the reset line when the current percent is ≥ 50%. Otherwise the original "Resets in X" text stays.

## [0.6.6] - 2026-05-22

### Added
- **Burn-rate warning**: when usage projects you'll exhaust a quota before the window resets at your current pace, the normal "Resets in X" line is replaced by a red warning: "⚠ Empty in X (resets in Y)". When you're not burning hot, the panel looks exactly the same as before — no extra noise. Covers Claude Code Session / Weekly and Codex Session / Weekly (all 4 quotas), with theme-matched reds on Classic / Matrix / Newspaper / Win95. Internally it samples percent on a 15-minute rolling buffer and projects from the last-10-minute slope; samples are cleared on quota reset to avoid false alarms.

## [0.6.5] - 2026-05-22

### Added
- **Launch at Login toggle**: the panel-switcher menu (opened from the "Switch Panel" button) gains a checkable "Launch at Login" item. Ticking it makes usage start automatically at next login, so you don't have to relaunch it manually. The .app and source builds each generate the matching LaunchAgent plist; unticking only removes the plist — it never quits a running app.

### Changed
- README "Auto-start on login" section now documents the popover toggle (Traditional Chinese / English).

## [0.6.4] - 2026-05-22

### Added
- **Newspaper panel**: a fourth built-in panel recreating a vintage newspaper front page — aged newsprint background, serif ink type, double-rule page border, newspaper-style section headings, hairline row dividers, solid ink progress bars. Card layout and data logic match the Classic panel; only the CSS styling differs.

### Fixed
- **Traditional Chinese systems detected as Simplified Chinese**: `_detect_language()` read `NSLocale.languageCode`, which returns a bare `"zh"` with no region, so Traditional Chinese systems were normalized to Simplified. It now reads `localeIdentifier` (e.g. `zh_TW`), which keeps the region, so Traditional Chinese systems display Traditional Chinese correctly.

### Changed
- README panel section updated to show all four panels side-by-side (Traditional Chinese / English).

## [0.6.3] - 2026-05-22

### Added
- **Windows 95 panel**: a third built-in panel recreating the classic Windows 95 desktop — teal wallpaper, navy gradient title bars, grey 3D outset windows, chunked segmented progress bars, raised plastic buttons, Tahoma type.
- **Per-panel window size**: `HTMLPanel` gains `width` / `height` parameters so each panel can use a popover size that fits its content (default stays 364×812). The Windows 95 panel is more compact and uses 364×768.

### Changed
- README panel section updated to show all three panels side-by-side (Traditional Chinese / English).

## [0.6.2] - 2026-05-22

### Fixed
- **Matrix panel "Project Usage" folder icon missing**: each card carried an inline `style="--accent: var(--accent)"` — a self-referential cyclic CSS variable. Per the CSS spec, cyclic var() resolves to invalid-at-computed-value-time and unsets the property, so the inline SVG's `stroke="var(--accent)"` had no color and rendered transparent. Claude / Codex cards use `<img>` so they were unaffected, but the projects card's inline SVG folder icon disappeared. `--accent` is already defined on `:root` and inherits to all descendants, so the per-card overrides were meaningless — removing them restores the icon.

## [0.6.1] - 2026-05-22

### Added
- **Matrix panel**: a second built-in panel — black background, neon green type, falling digital rain. Card layout, progress bars, project ranking, and footer all match the Classic panel; only the palette and background differ. Toggle via the `⇄ Switch panel` button in the popover.
- README now shows Matrix panel screenshots (Traditional Chinese / English) side-by-side with Classic.

### Fixed
- Matrix panel title `line-height: 1` clipped CJK ascenders and the `text-shadow` glow (e.g. `專案用量`, `プロジェクト使用量`) at the card edge; bumped to `1.25` so titles render fully in all five languages and stay vertically aligned with the 30×30 icon.

## [0.6.0] - 2026-05-22

### Added
- **Multi-language UI (i18n)**: automatically detects the macOS system language and displays the interface in Traditional Chinese, Simplified Chinese, English, Japanese, or Korean. No configuration needed.
- **`USAGE_LANG` environment variable**: force a specific language (e.g. `USAGE_LANG=ja`) for development and testing.

### Changed
- **License changed from MIT to AGPL-3.0**: modified versions that are distributed must be open-sourced.
- **Attribution footer in popover**: `based on usage by lollapalooza` shown at the bottom of the panel.

### Fixed
- Removed hardcoded Chinese status strings (e.g. `✓ 已同步`) from `usage_client.py`; all status text now goes through the i18n system.

## [0.5.0] - 2026-05-21

### Added
- **Monthly range in project usage**: cycle through Today / 7 days / Month to view per-project token usage and cost over the last 30 days.

### Fixed
- **Project usage cost now calculated correctly**: Claude Code's JSONL does not write a `costUSD` field, so all projects previously showed $0.00. Now uses the same `calculate_cost()` path as the "Today" footer total.
- **Fallback Opus pricing corrected to $5/M**: the offline fallback price for Opus was $15/M; corrected to $5/M to match LiteLLM's actual value.

### Improved
- Project usage SVG icon resized to 30×30 to match Claude Code / Codex icons.

### Removed
- Removed Taiwan, Matrix, ECG, Minimal, and Sketch PyObjC native panels. All panels are now HTML/CSS-based; new panel designs are in progress.
- Removed Antigravity quota tracking (Google OAuth credentials must not be committed to source; feature to be redesigned)

## [0.4.0] - 2026-05-20

### Added
- **Default panel now renders via WKWebView + HTML/CSS**: the classic default panel moved to a shared HTML/CSS layer, paving the way for a future Windows version; macOS still embeds it in `NSPopover` via `WKWebView`.
- **Antigravity quota tracking**: the popover now shows three cards for Claude Code, Codex, and Antigravity; the Antigravity card has two rows for current usage (Session) and weekly cap (Weekly).
- Antigravity buckets with `remainingFraction == 1.0` (unused) now hide reset times, avoiding the API's rolling placeholder from appearing as an endless "reset in ~24h".

### Changed
- `antigravity_loader` now splits quota buckets by reset window: shorter windows become Session and longer windows become Weekly. When Google's API exposes a weekly bucket, Weekly fills automatically.
- WKWebView integration adds a JS bridge (refresh / quit / switch), preload support, and a dark backing layer to remove launch-time white flash; panel switching tears down the web view to break retain cycles.
- Panel buttons now have pressed-depth and subtle scale feedback on click.
- New dependencies: `pyobjc-framework-WebKit`, `pyobjc-framework-Quartz`.

### Removed
- Removed the CoreGraphics `panels/classic.py` implementation in favor of `HTMLPanel`.

### Internal
- Tightened `codex_loader` / `history_loader._as_int` typing with `max(0, int(value))`.
- Use Quartz `CGColorCreateGenericRGB` to create the `CGColorRef`, eliminating the launch-time `ObjCPointerWarning`.

## 0.3.3 — 2026-05-19

### Added
- **Minimal panel**: dark minimal panel inspired by Linear / Raycast. Near-black background (`#0A0A0C`), rounded cards, accent-coloured progress bars (Claude warm-orange / Codex cyan). Each card has a Session row (26pt number) and a Weekly row (24pt), each with a label, percentage text, 2px progress bar, and reset countdown. Footer card presents rate, status, and today's cost as a two-column label-left / value-right layout with horizontal dividers between rows. Three-button bar (Refresh / Quit / Switch panel) uses accent gradient for primary and translucent bordered fill for secondary.

## 0.3.2 — 2026-05-19

### Added
- **ECG panel**: medical-monitor style panel. `ECGView` drives a dual-channel ECG waveform animation via `NSTimer` at 80 ms — LEAD A for Claude Code, LEAD B for Codex. Waveform amplitude scales with quota usage percent; higher burn rate produces more intense rhythms. Text labels and waveform zones are separated into fixed vertical sections so they never overlap.

## 0.3.1 — 2026-05-19

### Added
- **Matrix panel (駭客任務)**: animated digital-rain panel — black background, cascading katakana + digit characters in Matrix green. `MatrixRainView` is driven by an `NSTimer` at 80 ms; each tick draws one bright head glyph and a 10-character fading trail per column. Card areas use a translucent dark-green fill with green borders; all buttons and headers use terminal bracket style (`[ SWITCH ]`, `[ REFRESH ]`, `[ EXIT ]`); rate/status/today labels use uppercase English prefixes.

## 0.3.0 — 2026-05-19

### Added
- **Panel switching system**: a `⇄ Switch panel` button in the popover top-right opens an `NSMenu` of all registered panels; the selected panel applies immediately and is persisted via `NSUserDefaults` (key `usage.activePanelId`), so the last choice survives restarts.
- **Classic panel**: the original two-card + footer layout, with the switch button embedded in the Claude card's top-right and a new `ClassicSwitchButton` that stays legible in both light and dark mode.
- **Taiwan panel**: red-on-white themed panel (a 20-line `ThemeConfig`), with a top header bar containing the TAIWAN flag icon, the "台灣用量監控" title, and the switch button. Popover height grows from 574 → 672 when this panel is active.
- New `panels/` module: `base.py` provides the `Panel` Protocol, `ThemeConfig` dataclass, generic `ThemedPanel`, and `NSUserDefaults` helpers; `classic.py` / `taiwan.py` are concrete panels; `__init__.py` provides the panel registry (`get_panel(id)`, `all_panels()`, with classic fallback for unknown ids).
- New `assets/taiwan.png`, registered in `setup_app.py`'s `resources` list so it ships inside the `.app` bundle.

### Refactored
- `menubar.py` shrunk significantly (1041 → 524 lines): all popover drawing and layout moved into `panels/`; `PopoverViewController` is now a lightweight container that rebuilds its content view from the active `Panel`; `AppDelegate` gains `switchPanel:` / `selectPanel:` and `_set_active_panel_id` to drive panel transitions.

### Tests
- Added `tests/test_panels.py` (11 cases) covering: panel registry contents, each panel's `preferred_size`, `NSUserDefaults` round-trip, unknown-id fallback, `ThemeConfig` application, and `ThemedPanel` height difference with/without a header.

## 0.2.1 — 2026-05-18

### Fixed
- `scripts/install-hook.sh`: wrap paths with `shlex.quote()` when generating the statusLine command, matching `setup_hook.py`. Prevents broken hook installs when the user's Python or hook path contains spaces.
- `pricing.py`: `_pricing_cache` now records its source (cache / fetched / fallback) and timestamp. Fallback results use a short 10-minute TTL so cost estimates no longer stay stuck on stale fallback values after offline startup when the network recovers.
- `menubar.py` / `codex_loader.py`: silent `except` blocks now emit `logger.warning(exc_info=True)` when `USAGE_DEBUG=1`, otherwise stay quiet. Debug sessions no longer mistake parse failures for "Codex not installed".

### Documentation
- `README.md` / `README.en.md`: added a sentence to the pricing table section noting that first launch without a cache does a synchronous fetch and may take ~10 seconds on slow networks, so new users don't think the app is hung.

### Tests
- New `tests/test_main.py` (9 cases) covering `parse_args` and `_apply_outcome` behaviour.
- New `tests/test_menubar.py` (14 cases) covering pure helpers: `format_human_time`, `_format_percent`, `_bar_color`, `_quota_row`, `_missing_row`, `_today_title(mock=True)`, `_empty_state`, `_error_state`, `_popover_size`.
- Added 4 new cases in `tests/test_pricing.py` covering fallback TTL, retry-then-fetched, and no-refetch for fetched / cache sources.
- Test suite grew from 63 → 90 passed.

## 0.2.0 — 2026-05-18

### Breaking Changes
- Internal app identifiers changed from `usag` to `usage`: bundle id, filenames, launchctl label, and `~/.claude/` paths were renamed.

### Added
- `setup_hook.py` now detects and clears old v0.1.x `usag` leftovers: hook script, settings statusLine, backup key, and status file.
- `install-launchagent.sh` / `uninstall-launchagent.sh` now clean the old LaunchAgent plist and label automatically.
- `usage_client.py` now falls back to the old `usag-status.json` path for upgrade compatibility.

### Fixed
- Public app naming and internal bundle identifiers are now consistently `usage`.

## 0.1.11 — 2026-05-18

### Fixed
- `setup_app.py` now packages `usag_statusline.py` so the `.app` bundle ships the hook source.
- `setup_hook.py` now resolves the hook source in both source-tree mode and `.app` bundle mode.

### UI
- The popover now shows a one-click "立即安裝 hook" recovery button when the status file is missing.

## 0.1.10 — 2026-05-18

### UI
- Progress bars now change colour based on usage level: below 50% keeps the brand colour, 50–80% shifts to amber, ≥ 80% turns red.

### Fixed
- `codex_loader.py`: use last token-event timestamp for `hours_back` filtering; per-file fault-tolerant sort.
- `history_loader.py`: composite dedup key when id fields are absent; reject bool and negative token values.
- `usage_client.py`: guard `rate_limits` sub-fields against non-dict values.
- `setup_hook.py`: validate settings before writing; safely rebuild backup field if not a dict.

### Documentation
- README: corrected three factual inaccuracies (network claim, Codex data source, cost is an estimate).
- README: added Quick start table, Download the app section, and Troubleshooting table.

## 0.1.9 — 2026-05-18

### UI
- Progress bars now change colour based on usage level: below 50% keeps the brand colour (Claude orange / Codex cyan), 50–80% shifts to amber, ≥ 80% turns red.

### Fixed
- Sync status label changed from `usag-status` to `usage` to match the public-facing project name.
- `setup_hook.py`: wrap interpreter and hook paths with `shlex.quote()` so hooks work when the project directory contains spaces (PR #1, thanks @DennisWei9898).
- `usag_statusline.py`: replace `datetime.UTC` (Python 3.11+) with `timezone.utc` for compatibility with macOS system Python 3.9 (PR #1, thanks @DennisWei9898).
- `codex_loader.py`: use the last token-event timestamp for `hours_back` filtering so long sessions no longer drop recent tokens; per-file fault-tolerant sort so a single bad file doesn't break the entire session scan.
- `history_loader.py`: fall back to a composite dedup key when `message_id` / `request_id` is absent; reject bool and negative token values.
- `usage_client.py`: guard `rate_limits` and its sub-fields against non-dict values.
- `setup_hook.py`: validate `settings.json` structure before writing; safely rebuild the backup field if it is not a dict.

### Documentation
- README: replaced mainland Chinese phrasing ("打API", "打網路") with standard Taiwanese usage ("呼叫 API", "連網路").

## 0.1.8 — 2026-05-18

### UI
- Popover redesign:
  - Claude Code / Codex cards now show a branded icon in the header (`claude.webp` / `codex.webp`).
  - Card surfaces and progress fills switched to gradient (`NSGradient`); accent colours brightened (Claude leans warm orange, Codex leans cyan).
  - "Refresh now" and "Quit" buttons replaced with a custom `ActionButton` that draws primary / secondary styles (primary uses the accent gradient, secondary uses a translucent bordered fill).
  - Rate / status / today-cost line wrapped in its own card so the three sections share one visual language.
  - Spacing, weights, tracking, and muted colours re-tuned for stronger contrast in both Light and Dark Mode.

### Packaging
- `setup_app.py` declares `claude.webp` / `codex.webp` as py2app `resources` so the `.app` bundle ships the icons.
- `menubar.py` resolves icon paths via `NSBundle.mainBundle().pathForResource_ofType_`, so both the dev deployment (LaunchAgent runs `main.py` directly) and the `.app` bundle find the assets.

## 0.1.7 — 2026-05-18

### Documentation
- README now ships 5 badges (CI status, latest release, Python version, platform, license).
- README's "How it gets the data" section now includes a mermaid diagram visualizing the `Claude Code → hook → JSON file → usage` chain, with `Anthropic API` explicitly drawn as **never called** (dashed broken line).
- Added bilingual `CONTRIBUTING.md` / `CONTRIBUTING.en.md`: spells out what issues / PRs should include, the three checks required before merge, off-limits technical identifiers and UI constants, the bilingual CHANGELOG rule, and commit message style.

### Tests
- Added three new test files covering the three highest-risk "I/O / parse boundary" modules (previously zero coverage, the same class of code that produced the 0.1.2 → 0.1.3 "change one place, miss another" bug):
  - `tests/test_usage_client.py`: `_read_status_file` with both paths missing / `USAG_STATUS` bad JSON / fallback to TT_STATUS; `_build_snapshot` missing fields / percent out-of-range clamp; `ClaudeUsageClient` outcomes in mock and real mode.
  - `tests/test_codex_loader.py`: `load_entries` with missing sessions dir / valid JSONL / `hours_back` cutoff filter / bad JSON line / missing fields / `_parse_timestamp` across three ISO 8601 variants; `load_rate_limits` returns None when file missing / parses primary + secondary windows.
  - `tests/test_setup_hook.py`: `setup` in a clean env / existing custom statusLine gets backed up / idempotent on repeat; `unsetup` restores backup / behaves cleanly when never installed; `_is_usag_hook` discriminator.
- All tests use `monkeypatch` to redirect path constants; **real `~/.claude` and `~/.codex` are never touched** (verified by before/after mtime comparison).
- Test count: 44 → 60. Runtime: 0.04s → 0.08s.

## 0.1.6 — 2026-05-18

### Changed
- Public-facing name unified from `usag` to `usage`, matching the GitHub repo:
  - `pyproject.toml`'s `name` changed from `"usag"` to `"usage"` (so PyPI / `pip list` now show `usage`).
  - `README.md` / `README.en.md` headers and prose now say `usage`.
  - `.github/ISSUE_TEMPLATE/bug_report.md` updated likewise.
- **Intentionally unchanged** (to avoid breaking existing installs): all file paths, settings keys, and binary names keep the `usag` prefix — `~/.claude/usag-status.json`, `~/.claude/usag-statusline.py`, `~/Library/Logs/usag/`, `com.lollapalooza.usag` (LaunchAgent label), `usag.app` (bundle), `USAG_DEBUG` (env var), `settings.usag.previousStatusLine` (JSON key) are all untouched. The technical short name is `usag`; the public name is `usage`.

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
