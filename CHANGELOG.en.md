# Changelog

[繁體中文](CHANGELOG.md) · English

All notable changes to usage are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.11.11] - 2026-05-27

### Changed
- **Weekly burn warning no longer over-reacts to short bursts**: previously the weekly warning extrapolated from the most recent 10-minute sample window, so a single large prompt could trigger a scary "8 hours until empty" warning that vanished once the user took a break. The weekly warning now uses a 30-minute sample window with a 30-minute minimum span, requiring sustained high usage for at least half an hour before triggering. Session warnings keep the 10-minute window (session resets are frequent, can't be too strict). `burn_rate.ROLLING_WINDOW_SECONDS` was raised from 15 to 60 minutes so the longer window has enough history.
- **Burn warning text now says "at current pace"**: all 5 languages' burn warning strings now explicitly include "按目前速度 / At current pace / 現在のペース / 현재 속도", making it clear that this is a momentary extrapolation rather than a stable prediction.

## [0.11.10] - 2026-05-27

### Fixed
- **"Launch at login" toggle now takes effect immediately, no reboot needed**: `login_item.enable()` / `disable()` now invoke `launchctl bootstrap gui/<uid> <plist>` / `launchctl bootout gui/<uid>/<label>` in addition to writing/removing `~/Library/LaunchAgents/com.lollapalooza.usage.plist`, so launchd learns about the change right away. Previously only the plist file was touched, so the toggle did nothing until the next reboot, and disabling left a KeepAlive orphan process behind. `launchctl` "already bootstrapped" (exit 17) and "not bootstrapped" (exit 113) are treated as success; other failures log a warning without affecting the plist operation (signatures stay `() -> None`).

## [0.11.9] - 2026-05-27

### Fixed
- **TUI session table no longer crashes on `cost_usd=None`**: widened `ui/tables.py:_fmt_cost` to `float | None` so entries written without a cost (a known path on the Codex side) now render as `--`, matching the popover-side behavior in `panels/web_panel.py`. Previously the `>=` comparison raised `TypeError` and broke the whole table.
- **Update check now handles pre-release versions**: `update_checker._parse_version` now strips pre-release / build suffixes via regex, so `0.11.0-beta.1` / `0.11.0+build.5` no longer return `None` and no longer make `compare_versions` raise. Beta testers receive update prompts correctly. No new package dependencies were added.
- **Pricing falls back to a stale cache when offline**: the fallback order in `pricing.py` is now fresh cache → network fetch → stale cache → hardcoded fallback. Previously a >7-day-old cache combined with no network dropped straight to the hardcoded prices, skewing cost estimates; the real (if stale) historical cache is now preferred.

## [0.11.8] - 2026-05-27

### Changed
- **git worktree entries collapse into the main project**: running Claude Code or Codex inside a worktree (a duplicate working tree of the same repo) no longer splits `usage` and `usage-fix-bug` into two separate rows in the HTML report and TUI ranking. They are now grouped under the main worktree's directory name. A new `project_resolver.py` module (stdlib only, 3-second timeout, falls back to the previous basename behavior when git is unavailable) is shared by `history_loader.py` and `codex_loader.py`. Seeing historical totals merge on first upgrade is the intended behavior.

## [0.11.7] - 2026-05-27

### Changed
- **Pricing cache moved under `~/.usage/`**: the LiteLLM pricing cache now lives at `~/.usage/pricing_cache.json` instead of `~/.claude/pricing_cache.json`, following the principle that usage-owned state belongs in its own directory. The legacy path stays as a read-only fallback for seamless migration. Thanks @ericweichun.

### Fixed
- **Explicit `usage report --help` and unknown-option handling**: previously the CLI silently ignored unknown report options and `--help` still triggered agent detection. Now `--help` returns the help text immediately and unknown options error out cleanly. Thanks @ericweichun.

## [0.11.6] - 2026-05-27

### Added
- **Codex model shown in the popover footer**: the footer now displays the currently detected Codex model; when no model data is available it falls back to `unknown` instead of leaving the state blank.

### Changed
- **Analysis report period follows the Project Usage range**: the Report button now switches output periods with the current project range, mapping 1d to today, 7d to week, and 30d to month. No new UI was added; it uses the existing range control.

### Fixed
- **Japanese / Korean Codex model labels completed**: added the missing ja / ko `model_label` translations so footer model information no longer renders blank in Japanese and Korean UIs.

### Performance
- **Codex today / week / month reports now use tail scanning**: users with many sessions no longer wait for a full history scan when opening reports. Today reports drop from roughly 7 seconds to the 0.03-second range, with week / month benefiting from the same path.

## [0.11.5] - 2026-05-26

### Added
- **Terminal toggle button now changes background when enabled**: previously only the `✓` check mark indicated that the statusLine hook was active; now the button background tints with each panel's accent color too, so the on/off state is obvious at a glance.

### Changed
- **Friendlier button labels for non-developers**: "Analyze" → "Report", "CLI" → "Terminal" (with per-language translations: 終端 / ターミナル / 터미널 / 终端). All five languages updated together.
- **All buttons now have hover feedback**: previously only "Refresh Now" reacted to mouse hover; "Quit", "Switch Panel", "Today", "Report", "Terminal" looked disabled. Hover now produces visual feedback at a graded intensity (primary > secondary > switch).
- **Classic panel large visual refinement**: pushed towards a "macOS system tool" feel — card corners 18→8, tightened spacing, progress bars gained inset track shadow and outer glow, projects list got a relative-share comparison bar (top-3 ranks emphasized), footer status became chip pills, brand-color accent stripe added on the left, brand icons gained background tint and glow.
- **Six themed panels adopt the same UX trio** (matrix / win95 / newspaper / aquarium / cloud_observation / prism_arcade / black_hole): comparison bars, Terminal active-state coloring, button hover. Each panel's own theme art is preserved in full (Matrix green / Win95 pixel / newspaper print / aquarium ripple / cloud / prism rainbow / black-hole orange).
- **Landing page panel gallery expanded from 6 to 9 themes**: added aquarium / prism_arcade / black_hole; classic now uses its own screenshot instead of borrowing `popover.png`.
- **Refreshed all 9 panel screenshots (zh-TW & en)** in the README and on https://aqua5230.github.io/usage/.

### Fixed
- **Analysis reports now follow the menu bar popover language**: clicking Report (formerly Analyze) now passes the menu bar's current language into HTML report generation instead of redetecting from environment variables only, avoiding English fallback when LaunchAgent does not set `LANG`.
- **Visible popovers are repositioned when switching panels**: changing the active theme/panel while the popover is open now closes the old popover, rebuilds the content and size, then shows it again to avoid transient indentation or sizing glitches.
- **Codex project usage and analysis reports now share one counting path**: when the same Codex session appears in multiple JSONL files, usage keeps the newer cumulative token entry; analysis reports now reuse `codex_loader.load_entries()`, and Project Usage includes Codex sessions so the app and report do not disagree for the same local data. Project Usage's Today range now matches the footer's local calendar day, and the footer no longer reloads Codex when the caller already supplied Codex entries.
- **Project Usage header truncation fixed across all 9 panels**: classic & matrix were patched by @ericweichun (#9); this release completes the remaining six (win95 / newspaper / aquarium / cloud_observation / prism_arcade / black_hole). All now use a 2-row grid (icon + title on top, three buttons evenly distributed below) so English "Project Usage" and longer Japanese/Korean titles no longer clip.
- **macOS now opens analysis reports with `/usr/bin/open`**: previously `webbrowser.open()` constructed a `file://` URI, which some browsers refused for paths containing spaces or CJK characters. Switching to `/usr/bin/open` with the resolved path is more reliable. Thanks to @ericweichun (#9).
- **Matrix panel footer clipping**: the ASCII border + raindrop background made the content taller than the default 812 panel height, clipping the "Refresh Now / Quit" buttons. Raised to 880.
- **win95 / newspaper "Resets in X" text was glued to the card edge**: bumped win95 panel height 768 → 800, newspaper → 850, and added padding-bottom to the Claude/Codex card's `.row:last-child`.
- **Four grid panels (aquarium / cloud_observation / prism_arcade / black_hole) — Projects row layout rebuilt**: the original row-as-mini-card design (border + radius + background) fundamentally fought with the new column-spanning comparison bar (the bar always glued to the row card's bottom border; padding / margin / grid-template-rows tweaks all failed). Switched to flat rows with border-top dividers (same as classic), preserving each panel's theme color on the rank chip and background. Also removed the comparison bar from these four panels (grid + row-card + spanning bar is fundamentally conflicting; ROI too low). The other four panels (classic / matrix / win95 / newspaper) keep their comparison bars.

## [0.11.4] - 2026-05-25

### Added
- **statusLine shows an "update available" hint**: after every successful update check, menubar writes the result to `~/.claude/usage-preferences.json` under `last_update_check`. statusLine reads this and renders `🆕 vX.Y.Z available` (cyan) on the model line when a newer version is cached, the cache is fresh (<30 days), and the version isn't on the user's skip list. New `update_available_suffix` translation across all 5 languages (zh-TW「可更新」/ zh-CN「可更新」/ en「available」/ ja「更新あり」/ ko「업데이트」).

### Changed
- **statusLine context-window label format**: `對話窗(1.0M):[bar]` → `對話窗:[bar] 15% / 1.0M`. The capacity moves from a middle parenthetical to a right-aligned suffix, reading more naturally as "15% of 1M".
- **statusLine fast-mode display flipped**: previously both states showed a label (`⚡Fast` vs `/nofast`); now only the *on* state shows `⚡Fast`, off renders nothing — like an AC unit's indicator light: the light *being on* is the signal.
- **statusLine percentages now share the bar color**: previously rendered in neutral gray; now matched to the bar's warning color (yellow / green / red). The number alone tells you the warning level at a glance.
- **statusLine `(X left)` no longer dimmed**: previously rendered with ANSI dim, hard to read on dark terminal backgrounds. Removed dim; parentheses alone now carry the "supplementary info" semantic.

## [0.11.3] - 2026-05-25

### Fixed
- **Read-only CLI commands silently mutated user settings**: `usage daily` / `report` / `sessions` / `dashboard` and other read commands unconditionally called `setup()` or `update_hook()`, potentially writing to `~/.claude/settings.json` or `~/.codex/config.toml` on every invocation. Fix: only `setup` / `unsetup` mutate user settings; other commands now show a one-line "Hook not installed. Run: usage setup" hint when the hook isn't installed.
- **Opus 4.6 / 4.7 cost was underestimated 3× on offline cold start**: `pricing.py`'s fallback table listed Opus as `5e-6 / 25e-6` (input / output per token), but the published Anthropic rate is `15e-6 / 75e-6`. Affected scenario: no pricing cache *and* LiteLLM live fetch fails. Users with network access or a cached price table are unaffected.
- **`adapters/codex.py` sqlite connection leak**: `_load_thread_models()` wrapped the work in `try / except`, but `conn.close()` ran *after* `execute().fetchall()` — any exception in between left the connection dangling. Now uses `contextlib.closing()` to guarantee release.
- **Mid-write crash could leave `~/.codex/config.toml` truncated**: `setup_hook.py`'s `_setup_codex` / `_unsetup_codex` used plain `write_text()`, so a crash or kill during setup could corrupt Codex config. Now uses `mkstemp + os.replace` atomic write, sharing a single module-private helper with Claude settings.

### Changed
- **`analyzer/cost.py` removed**: it was a weakened duplicate of `pricing.py` — bidirectional substring model matching (prone to misclassification), no cache TTL, and an SSL-cert-verification-disabled fallback when fetching the price table (a security concern for cost data). `analyzer/{aggregator,blocks,reporter}` now import `pricing.calculate_cost` directly; the latter accepts a `typing.Protocol` so both `history_loader.UsageEntry` and `adapters.types.UsageEntry` work. Net 76 lines of duplicate cost-calc code removed.

## [0.11.2] - 2026-05-25

### Fixed
- **`usage_cli.py` crashed on every first run** (thanks @will30-blockchain — [#7](https://github.com/aqua5230/usage/pull/7)): `setup(auto=True)` passed a non-existent keyword argument to `setup_hook.setup()`, causing a `TypeError` on any fresh install or after `unsetup`. Users who already had the hook installed were unaffected. Fix: drop the stale `auto=True` kwarg.

### Performance
- **Incremental JSONL parsing**: `history_loader` and `codex_loader` now maintain module-level mtime+size caches and skip re-parsing files whose content hasn't changed, significantly reducing per-refresh disk I/O.
- **Parallel hook forwarding**: `usage_statusline_forwarder` now dispatches all hooks concurrently via `ThreadPoolExecutor`; a single slow or timing-out hook no longer stalls the others. Worst-case latency drops from `n × 5s` to `5s`.
- **Multi-session write protection**: `usage_statusline.py`'s `save()` now acquires `fcntl.LOCK_EX` before writing, preventing concurrent Claude Code sessions from clobbering each other's data.
- **Python path resolution**: `setup_hook` now uses `_find_system_python()` when building hook commands — preferring the bundled `.app` Python, then `/usr/bin/python3`, avoiding the broken Xcode stub that `shutil.which("python3")` can resolve to after an Xcode update.
- **FSEvents-driven UI refresh**: `menubar` now uses a CoreServices `FSEventStream` (via ctypes) to watch `~/.claude/`. Changes to `usage-status.json` trigger `_refresh()` immediately, cutting update latency from up to 60 seconds to milliseconds. `NSTimer` is demoted to a 300-second fallback; silently degrades to timer-only mode if CoreServices is unavailable.

## [0.11.1] - 2026-05-24

### Fixed
- **[P0] Released `.app` crashes on launch on macOS Sequoia / arm64** (thanks @cmhcm — [#6](https://github.com/aqua5230/usage/pull/6)): all three prior releases (v0.10.0 / v0.10.1 / v0.11.0) are affected. Root cause: in py2app builds `i18n.py` is compiled into `lib/python313.zip` but `i18n.json` lives in `Contents/Resources/`. The old `Path(__file__).with_name("i18n.json")` resolved to a path *through* the zipfile and raised `NotADirectoryError` on first read. Fix: new `i18n.packaged_resource_path()` helper prefers the `RESOURCEPATH` env var that py2app injects at launch (pointing at `Contents/Resources/`) and falls back to the source-adjacent path. All four packaged-resource callsites updated (`i18n.py` / `tui.py` / `main.py` / `menubar.py`). Source-mode runs are unaffected.

### Changed
- **Packaging metadata completed**: `pyproject.toml` `py-modules` adds the previously-missing `burn_rate` / `update_checker` / `tips_loader` / `usage_lang` / `usage_statusline_forwarder`, and `packages.find` `include` adds `panels*`. Non-editable installs now ship the full code.
- **`.app` license metadata aligned**: `setup_app.py` `NSHumanReadableCopyright` updated from the stale `MIT License` to `Copyright © 2025-2026 lollapalooza. Licensed under AGPL-3.0-only.`, matching what `pyproject.toml` declares.
- **`pricing_cache.json` path unified**: `analyzer/cost.py` now caches to `~/.claude/pricing_cache.json` (was repo root), matching `pricing.py`. A stray 1.1 MB orphan cache at repo root was removed.
- **Panel names go through i18n**: `panels/__init__.py` exposes an `i18n_key` per panel and i18n.json gains the missing keys across all 5 languages. The "Switch Panel" menu no longer mixes Chinese names into en / ja / ko UIs.
- **Status-file error messages go through i18n**: `usage_client.py`'s "status file not found" and "no quota data yet" hints now route through `_t()`, all 5 languages covered.
- **Analytics CLI read order matches the main app**: `adapters/rate_limits.py` previously only read `~/.claude/tt-status.json`; it now follows the same `usage-status.json` → `usag-status.json` → `tt-status.json` fallback chain as `usage_client.py`.
- **README documents the v0.11.0 update check + GitHub Releases as a network exception**: README.md / README.en.md both gain a new "update check" bullet and list the GitHub Releases API as the second of two network exceptions (the first remains the LiteLLM pricing table).

## [0.11.0] - 2026-05-24

### Added
- **In-app update check (Stage 1)**: On launch, usage pings GitHub Releases for a newer version (rate-limited to once per 24h so you're not nagged every time you open the app). When a newer version is found, an NSAlert shows the version + release notes with three buttons: **Download**, **Later**, **Skip this version**. "Download" opens the Release page in your default browser — manually replace the old `.app` with the new one. (Stage 2 will bring Sparkle-style auto download + replace.)
- **Two new entries in the "Switch panel" menu**:
  - **Automatically Check for Updates** (toggleable): unchecking it disables the launch-time auto check entirely; the manual entry below still works.
  - **Check for Updates Now**: manually triggers a check, bypassing the 24h cooldown and skip-version preference. If you're already up to date, an alert says so; on network error you see "Update check failed".
- Preferences are stored in the existing `~/.claude/usage-preferences.json`, with three new keys: `auto_update_check` (default true), `update_dismissed_at` (Unix timestamp), `update_skipped_version` (skipped version string).

### Changed
- `setup_app.py` now bundles `pyproject.toml` and `update_checker` into the py2app build — so the packaged `.app` can fall back to reading `pyproject.toml` when `importlib.metadata` can't resolve the version.

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
