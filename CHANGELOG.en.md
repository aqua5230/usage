# Changelog

[繁體中文](CHANGELOG.md) · English

All notable changes to usage are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- **Homebrew now ships as a cask**: usage is a GUI app, so it's now distributed via Homebrew's cask format — it drops `usage.app` straight into your Applications folder and skips the formula relocation/re-signing pass, which also fully fixes the earlier `usage.app/usage.app` doubled-path `Errno::ENOENT` install failure. Install with `brew install --cask aqua5230/usage/usage`; if you previously installed via the formula, run `brew uninstall usage` first, then reinstall. (Thanks @anatolii-maslennikov-improvado for reporting #34)

## [0.16.1] - 2026-06-07

### Fixed
- **Homebrew install no longer fails**: because the release zip had a single top-level `usage.app` directory, Homebrew would auto-`chdir` into it and then fail to find the file to install, raising `Errno::ENOENT ... usage.app`. The formula's install path is fixed — just reinstall. (Thanks @teddy123434 for reporting #32)
- **Claude Code no longer errors on startup after installing the status-line hook from the .app**: installing from the packaged .app used to write the app's bundled Python — which can't run standalone outside the bundle — into the hook config, so Claude Code threw `Could not find platform independent libraries` on startup and the status line wouldn't show. It now always uses the system `/usr/bin/python3`, and any previously corrupted config is repaired automatically on next launch or re-run of setup. (Thanks @teddy123434 for reporting #32)

## [0.16.0] - 2026-06-07

### Added
- **Progress Concierge now surfaces last session's uncommitted changes**: the automatic "where you left off" handoff on a new conversation also lists the file changes the previous session hadn't committed yet, so you don't have to recall them.
- **EMA-smoothed burn-rate forecast**: the "time until empty" estimate now uses an exponential moving average over recent interval rates instead of a single first-to-last slope, making it more responsive to sudden acceleration and steadier against single-point noise.

### Fixed
- **Packaged .app no longer crashes on a non-terminal launch**: double-clicking the .app or launching it in the background could crash the moment it opened the panel or requested notification permission (`Argument 3 is a block, but no signature available`), because py2app shipped the bare WebKit/UserNotifications modules without their full wrapper metadata. The required block signatures are now registered unconditionally and the wrappers are bundled.
- **Missing quota data no longer triggers a false "quota empty" alert**: when a quota window temporarily has no reading (e.g. an expired Codex 5-hour window), it was treated as depleted — firing a notification with a broken "back after --" body. Depletion now requires an actual 100%.
- **A malformed locale string can no longer crash the UI**: if a translated string's placeholder doesn't match the call site's arguments, the lookup now falls back to English, then to the raw key, instead of raising.

### Changed
- **Shorter burn-rate warning**: removed the "(N× faster than / under average pace)" suffix that pushed the red warning line past the panel width. The warning now shows only time-to-empty and the reset countdown.

### Docs
- **Open-source prep: security policy and license headers**: added a bilingual `SECURITY.md` (vulnerabilities go to a private email, not public Issues), an AGPL-3.0-only header on every Python file, and the maintainer's GitHub handle on the `LICENSE` copyright line.

## [0.15.14] - 2026-06-07

### Fixed
- **Claude Code quota no longer briefly drops to "--" when entering a new folder**: on the first status-line refresh of a new session, the data Claude Code sends may not yet include rate limits; the hook used to overwrite the status file wholesale with this incomplete data, wiping out the previously valid quota and briefly showing "--" plus "send a message to sync your quota" until you sent another message. The hook now preserves the existing complete quota when the incoming data is incomplete.

## [0.15.13] - 2026-06-06

### Fixed
- **Estimated cost now recomputes after a pricing update**: a cost computed with fallback prices was written back and cached onto usage entries, so it was never recomputed once real prices loaded — leaving cost figures persistently off (mainly for entries without a source cost, e.g. Codex). The estimate is no longer written back, so it reflects updated prices immediately.
- **Web panel no longer reloads endlessly when injection keeps failing**: if state injection failed repeatedly the panel would loop reloading; reloads per payload are now capped (WebContent-process crash recovery is unaffected).

## [0.15.12] - 2026-06-06

### Fixed
- **Fixed a file-descriptor leak from Codex SQLite connections not being closed after reads (#30)**: reading Codex's `logs_2.sqlite` / `state_5.sqlite` only ended the transaction without actually closing the connection, accumulating open file descriptors over long runs. Connections are now properly closed after every read.
- **Codex quota refresh is now applied before the history scan (#31)**: during background refresh, the Codex quota result is now applied to the main view synchronously before the project history scan runs, avoiding a brief display of stale quota.

## [0.15.11] - 2026-06-06

### Fixed
- **Web panel now recovers automatically after its render process crashes (#29)**: the WKWebView's web content process can be terminated on its own while the app itself keeps running, leaving the panel blank/grey until the whole app is restarted. The panel now detects content-process termination, reloads, and re-applies the last payload to recover; it also reloads and retries when JavaScript state injection fails.

## [0.15.10] - 2026-06-05

### Added
- **New "Insights" section in the report**: below the usage cards, a few local-rule highlights that the raw cards don't show — period-over-period change, the single heaviest spike day, a notable shift in model/project share, your pace, and one matching suggestion. At most five lines, with no fact repeated. Computed entirely on-device: no network, no API, no reading of conversation content.

## [0.15.9] - 2026-06-05

### Fixed
- **Menu bar / report no longer fail on non-ASCII (e.g. Chinese) project paths**: a .app launched by double-click has no locale set, so resolving project names via `git` decoded its output as ASCII and raised `UnicodeDecodeError` on paths containing Chinese/Japanese/Korean/accented characters. This affected `history_loader`/`codex_loader` (live menu bar) and `persona_loader` (Usage Habits), leaving the report's "Usage Habits" section blank for non-today ranges. `git` output is now always decoded as UTF-8, so paths in any language work.

## [0.15.8] - 2026-06-05

### Fixed
- **Codex "Session (5h)" quota no longer blanks out when the window expires**: after the 5-hour window resets, the session used to show blank (`--`), inconsistent with the Claude side; it now shows 0% like Claude. The CLI and menu bar now read rate limits from the same source, so their numbers no longer disagree.

### Other
- `doctor` now reports Codex diagnostics: latest session-log age, `logs_2.sqlite` rate-limit row count, `state_5.sqlite` status, and whether 5h / weekly quota data is currently available — making "why isn't it detected" easy to diagnose.

## [0.15.7] - 2026-06-04

### Fixed
- **Menu bar no longer blanks out when a refresh fails (#27)**: follow-up to #25. Local project usage / today's stats / the status line are now loaded *before* the remote quota fetch, and preserved when that fetch fails, so the view no longer flashes empty. Alert (NSAlert) creation or icon-setup failures now fall back to a safe no-op instead of interrupting the menu bar update.
- **Project Usage "30d" report aligns with a rolling 30 days (#28)**: generating a report from the menu bar's "30d" Project Usage range previously mapped to "this month" (1st of the month to today), which didn't match the labeled rolling 30-day range. It now maps to the report pipeline's `last30` (the last 30 days).

### Docs
- Landing page theme showcase refreshed, feature icons and hero banner updated, and a panel gallery added to the READMEs.

## [0.15.6] - 2026-06-03

### Changed
- **New cyberpunk-cat app icon**: replaces the teal-paw placeholder with the real usage icon (a cyberpunk-style cat). It ships with the `.app` starting this release, so the new icon shows in the Dock / Finder / menu bar after install.
- **README onboarding improvements**: (1) a top-level Quick Start that lifts the one-line Homebrew install up to where you can copy-paste it without scrolling; (2) a Star History chart at the bottom.

## [0.15.5] - 2026-06-03

### Changed
- **Color Claude / Codex brand icons in the menu bar**: the menu bar previously marked each service's usage with emoji (🐾 for Claude, 📜 for Codex). It now shows the official Claude and Codex brand icons in color, which read more clearly on both light and dark menu bars.

## [0.15.4] - 2026-06-03

### Fixed
- **Panel load failures no longer degrade to a silent grey window**: when the popover's embedded web panel fails to load, it previously fell back to a blank dark window with no explanation. It now shows a native error view with the error detail and a GitHub report link, and logs navigation failures / render timeouts under `USAGE_DEBUG=1` for easier diagnosis.

## [0.15.3] - 2026-06-02

### Fixed
- **Codex quota no longer blanks out on refresh errors (#25)**: follow-up to #24. When the later refresh stage (history parsing) failed, the error state reset the Codex session/weekly rows to blank, overwriting the quota that had already been loaded at the start of the refresh. The error path now preserves those already-loaded Codex rows, so they no longer flash empty.

## [0.15.2] - 2026-06-02

### Fixed
- **Steadier background refresh**: file-change–triggered refreshes are now always marshalled to the main thread, and the refresh routine has an outer guard so it can't get stuck in a state where it never refreshes again.

### Performance
- **Lighter refresh when sessions pile up**: history change-detection narrowed from scanning all of `~/.claude` to the `~/.claude/projects` it actually reads; Codex recent-session enumeration now walks the dated folder structure and scans only what's needed (skipping hidden files like `.DS_Store`) instead of rglob-ing the whole tree on every refresh.
- **No stall on first launch / offline**: the pricing-table download moved to the background; cost calculation always uses the local cache or built-in fallback first and auto-refreshes once the download lands. A long-running app also refreshes pricing in the background after the cache expires.

## [0.15.1] - 2026-06-02

### Fixed
- **Codex quota shows fresher, more accurate numbers (#24)**: (1) the menu-bar Codex quota now updates at the very start of each refresh instead of waiting for the slower history pass; (2) SQLite and JSONL sources are merged per window (5-hour / weekly) instead of picking one whole source, so a just-hit 100% limit is no longer overwritten by an older 80% snapshot; (3) small usage shows a fractional percentage instead of rounding to 0%; (4) the refresh timer uses the configured interval instead of a hard-coded 300s; (5) FSEvents-triggered refreshes queue instead of being dropped while one is in flight; (6) if the Claude Code read fails mid-refresh, the already-loaded Codex percentage is preserved instead of flickering away.
- **Stale "🆕 update available" badge no longer lingers after upgrading**: the cache cleanup previously ran only inside the update-check path, so the badge stuck until the app restarted; it now compares the installed version on every timer refresh and clears as soon as you're current.

## [0.15.0] - 2026-06-01

### Added
- **Quota usage notifications (opt-in, off by default)**: fires a macOS system notification when usage approaches a threshold, runs out, or recovers ("Almost out / Quota is empty / Quota is back"). Covers both session and weekly quotas for Claude Code and Codex; each threshold alerts once and re-arms after the quota resets. Controlled by one menu toggle; notification text is localized across all five languages in `i18n.json`. Triggered from the existing on-disk usage snapshot — **no network, no API calls**. The packaged `.app` now bundles the UserNotifications framework so alerts are delivered.
- **Pace indicator**: the burn-rate warning line ("at current pace, empty in X") now appends whether you're running some multiple faster than your personal average, or under it — so you can tell at a glance if you're burning hotter than usual.

### Fixed
- **Ignore echoed Codex quota queries (#23)**: in some cases Codex echoes a prior quota query verbatim; older versions treated these echoes as new messages and let them flood the window. They're now detected and skipped.

## [0.14.2] - 2026-06-01

### Changed
- **HTML report merges "Your subscription" and "By tool" into "Your tools"**: the two panels used to describe the same Claude Code / Codex tools separately. Now there's one card per tool — the plan badge and subscription start date sit alongside the share / tokens / cost stats under a single shared header, dropping the duplicate block.
- **Top KPI cards rebalanced**: the TOKENS column now gets the widest slot so the full number (e.g. `2,364,752,661`) never truncates or overflows at any window width, with `tabular-nums` for cleaner digit alignment.

### Docs
- **README overhaul (EN/繁中)**: privacy / requirements and quick start moved to the top, the three install methods presented on equal footing, feature bullets and punctuation trimmed, and the developer guide moved to `docs/DEVELOPMENT`.

## [0.14.1] - 2026-06-01

### Fixed
- **Codex quota stuck on stale values**: `load_rate_limits()` returned as soon as SQLite (`logs_2.sqlite`) had any data, never comparing the newer `rate_limits` in `~/.codex/sessions/*.jsonl`, so the menu bar stayed pinned to the previous day's quota. It now reads both SQLite and JSONL and picks the newest valid entry by `updated_at`, keeping the prior SQLite-preferred behavior when timestamps are equal.

## [0.14.0] - 2026-06-01

### Added
- **"Usage Habits" section in the HTML report**: fully local, zero API. The analysis report now shows a full-width 24-hour activity histogram of when you work, highlighting your peak hour with a plain-language summary ("You most often work with AI around HH:00 and HH:00"). Data comes from the message timestamps in your local Claude Code logs (user / assistant messages only) — **never the conversation content**. Parsing lives in a standalone `persona_loader.py` with a 300s TTL cache.
- **"Stale data" hint on the Codex card**: when the local Codex usage snapshot is older than 15 minutes, the classic panel's Codex card shows an "about N minutes ago" tag plus an info (ⓘ) tooltip. Unlike Claude Code, Codex has no live status-line hook, so its usage numbers come from session logs it writes only intermittently and can lag your real account; the tooltip also explains that staying offline is a deliberate choice so it never burns your tokens. Built from the existing `rate_limits.updated_at` — **no network, no API**.

## [0.13.0] - 2026-05-31

### Added
- **"Progress Concierge" feature** (menu label: "Resume Last Session"): fully local, zero API. When you open a new Claude Code session (`startup` / `/clear`), it automatically hands your last progress to the AI — no need to re-explain. A single menu toggle (off by default, opt-in) installs a Claude Code SessionStart hook (`usage_session_resume.py`, stdlib-only so it runs under macOS's bundled Python 3.9) that reads the project's previous session for **your last request + the commits made + any unfinished todos (if TodoWrite was used)**, assembles a resume prompt, injects it at the start of the new session, and asks Claude to open with "🐾 Picked up where you left off — let's keep going!" so you know it took effect. Wording lives in `i18n.json` (written to a sidecar at install time so the hook stays single-sourced); `setup_hook` handles install/remove/backup/self-heal. The menu item carries a tooltip with the full explanation.
- **Dedicated app icon**: replaces py2app's default rocket; NSAlert dialogs now use the brand icon too (via `setIcon_`).

### Changed
- **Slimmer menu**: the 9 panel themes are collapsed into a "Panel theme" submenu, so the menu is no longer dominated by a long inline list.

### Fixed
- **Broad robustness hardening**: systematically hardened every entry point that reads user files on disk against bad UTF-8, bad JSON, and type drift (numeric strings, non-dict, non-str fields) — covering `setup_hook`, `codex_loader`, the Codex / Claude / rate-limit adapters, the statusline, the history loader, subscription reads and JWT decoding, and the tips loader.
- **WebKit panel fallback**: registered the missing `evaluateJavaScript` block signature on the `loadBundle` fallback path.

## [0.12.1] - 2026-05-29

### Changed
- **File-level cache for the HTML report loaders**: `adapters/claude.py` and `adapters/codex.py` gain an `mtime`+`size`-keyed LRU cache (matching `history_loader`), so generating a report no longer re-parses every JSONL log on each run; the Codex adapter shares one cache between `load_entries` and `load_rate_limits`. Whole-file `OSError` / `PermissionError` / `sqlite3.Error` are now printed to stderr when `USAGE_DEBUG=1` (per-line `JSONDecodeError` stays silent).
- **mypy `--strict` now covers the whole codebase**: removed the mypy exclude for `adapters/`, `analyzer/`, `ui/` and `usage_cli.py` (a ~35% type-checking blind spot), added the missing generics and function annotations, and switched `_group_by_agent` to a PEP 695 type parameter. `mypy --strict` now checks all 70 source files.
- **Three cross-module functions in `adapters/claude.py` are now public API**: `get_claude_dirs`, `extract_project_from_dir`, `parse_jsonl` (previously underscore-private), dropping the matching `# type: ignore[attr-defined]` in `analyzer/reporter.py`.

### Fixed
- Removing the mypy exclude surfaced and fixed a few latent issues: a redundant `parsed_entries` re-annotation left over from the cache change in `adapters/claude.py`, the `agent` loop variable reused with two different types in `analyzer/reporter.py` (inner accumulator renamed `agent_totals`), and a redundant `cast` in `menubar.py`.

### Tests
- Added coverage for `_apply_sort` with the `"time"` sort key (which maps to `None` and is handled per-command).
- Added an i18n key-parity test asserting all five `i18n.json` language sections share the same key set, so a forgotten translation fails CI instead of silently falling back to English.

## [0.12.0] - 2026-05-29

### Added
- **"Your subscription" section in the HTML report**: auto-detects Claude (plan + subscription start date) and Codex (ChatGPT plan + subscription start date) from the local OAuth account files. Only the plan name and start date are read — tokens, emails and other secrets are never touched. When sharing the report, the subscription date is masked together with the "Hide project names" toggle. Adds the `subscription.py` module and its tests.
- **Project-share donut chart in the HTML report**: pure-SVG (zero external deps) breakdown of token share per project; the top 6 projects get their own colour, the rest fold into "Other", and the centre shows the total.
- **"Claude vs Codex" comparison section in the HTML report**: surfaces the per-agent usage (tokens / share / cost) that `build_report_data` already computed but never displayed.

### Fixed
- **Double-counted report cost**: `build_report_data` summed cost once over all entries and then recomputed it per entry inside the loop — effectively doubling the work on large datasets. Now accumulated once inside the loop.
- **Duplicated clipboard code in the report's "copy command" button**: the tip-copy button now reuses the shared `copyText()` helper instead of re-implementing the legacy-browser fallback.
- **Hard-coded TWD rate**: the USD→TWD estimate in the report is now a named `_USD_TO_TWD` constant with a note that it is a display estimate, not a live FX rate.

## [0.11.19] - 2026-05-29

### Added
- **"Hide Codex Section" menu toggle**: the menubar gained a "Hide Codex Section" option that collapses the Codex card across all 9 HTML panels and shrinks popover height per-panel. The preference persists via `NSUserDefaults` so it survives restarts. i18n keys added for all 5 locales. (PR #19, thanks @RayCHWong for the first-time contribution)

### Fixed
- **`HTMLPanel.codex_card_height` is now a required keyword-only argument with no default**: previously the parameter had a `192.0` default, so a new panel that forgot to set its height in `panels/__init__.py` would silently fall back to the default — the Codex card would render at a height that doesn't match the rest of the panel without raising any error. Now declared as `*, codex_card_height: float` (keyword-only, no default), so any missing call site raises `TypeError` at import. All 9 existing panels already pass it by keyword and are unaffected; added `test_html_panel_requires_explicit_codex_card_height` to lock the contract.

## [0.11.18] - 2026-05-28

### Changed
- **Statusline progress bar visual refresh**: progress bar characters switched from `█░` to `■□` (filled / hollow squares), and the color palette moved from standard ANSI green/yellow/red (32/33/31) to 256-color teal/orange/dark-red (42/214/160) for stronger contrast around the 50% threshold — safe / warning / danger states are now distinguishable at a glance. Changes confined to `usage_statusline.py` (`progress_bar()` and `color_by_pct()`); HTML reports and the TUI progress bars are unaffected.

### Docs
- **Traditional Chinese default panel screenshot refreshed**: `docs/繁體中文面板.png` updated to reflect the latest UI (new "Report / Terminal" toggle, per-project cost display, footer attribution).

## [0.11.16] - 2026-05-27

### Fixed
- **Codex usage panel no longer falls back to `--` after a burst of short sessions**: `codex_loader.load_rate_limits()` only scanned the 5 most recent jsonl files via `_recent_jsonl_files()` to find rate_limits. Codex CLI (observed on 0.134.0) writes `payload.rate_limits == null` for short or interrupted sessions (a quick `codex exec` run, Ctrl-C, etc.); when the latest 5 sessions all fall into that bucket, the genuinely-valid prior session gets evicted from the lookup window and the entire Codex block in the popover / TUI renders as `--`. The scan window is widened from 5 to 30 (covers a typical 1–2 day usage range); the first non-null result still early-returns, and the `primary.used_percent` / `secondary.used_percent` parsing path is unchanged. The new Codex CLI 0.134.0 schema fields (`limit_id`, `limit_name`, `credits`, `plan_type`, `rate_limit_reached_type`) are deliberately not parsed — UI doesn't use them. Three new tests cover the "5 null then 6th valid", "all 30 null returns None", and "pick most recent valid" scenarios.

### Fixed
- **Dashed Claude Code project names now decode correctly**: `history_loader._project_from_path` previously replaced every `-` in the encoded directory name with `/`, so `Desktop-claude-tutorial-video` would become `/Desktop/claude/tutorial/video` — a non-existent path. `resolve_project_name`'s fallback then took the last segment, mis-labeling the project as `"video"` instead of `"claude-tutorial-video"`. The decoder now tries the all-slash candidate first; on miss, it DFS-walks the segments, joining adjacent ones with `-` and preferring whichever variant actually exists on disk. When nothing matches, the encoded name (minus the leading `-`) is kept as-is so dashes round-trip (`plain-project` stays `plain-project`). For most users, the JSONL `cwd` field already overrides the project name, so this primarily fixes older entries that lack `cwd`.
- **TUI language detection routed through `usage_lang.detect_lang`**: `tui.py` had its own detector that only returned `zh-TW` or `en` (treating simplified Chinese, Japanese, and Korean as English), and ignored `USAGE_LANG` / `TT_LANG` / `LANG` entirely. The menubar already used `usage_lang.detect_lang()`, so the same machine could show Japanese in the menubar and English in the TUI. The TUI now shares the same detector — all five languages render consistently.

### Internal improvements
- **LRU cap on history / codex loader caches**: `_file_cache` and `_jsonl_cache` were unbounded module-level dicts. As `~/.claude/projects/` and `~/.codex/sessions/` accumulated more jsonl files over time, the menubar's resident memory grew without bound — parsed `UsageEntry` lists never got released. Both caches are now `OrderedDict`s with a 512-entry ceiling: cache hits `move_to_end` to mark MRU, inserts on a full cache `popitem(last=False)` the oldest. The mtime/size invalidation logic and codex_loader's `entry.model` rebind on cache hit are unchanged.

### Development
- **Significantly expanded test coverage**: previously undercovered modules `setup_app` / `ui/tables` / `usage_cli` now have direct unit tests; the suite grew from 234 to 363 tests. No production code was changed.

## [0.11.14] - 2026-05-27

### Fixed
- **Stale update badge clears immediately after upgrading**: `usage_statusline.py:_read_update_hint` only compared the cached `current_version` against `latest_version` without consulting the actual running version. The menubar app's 24h dismiss cooldown returned early before refreshing the cache, so a user already on v0.11.13 would keep seeing "v0.11.5 available" until cooldown expired. `_check_update_in_background` now refreshes `current_version` in the cache on startup (even during cooldown), and if the running version has caught up to `latest_version`, both fields are leveled so the badge disappears immediately.

### Changed (community contributions)
- **Codex usage bucketed by token_count deltas (@ericweichun, #11)**: `analyzer/reporter.py`'s fast path previously parsed Codex `.jsonl` files to extract a cumulative snapshot keyed by session-start timestamp, which diverged from the popover (which uses `codex_loader.load_entries` with per-event delta logic). The reporter now shares the same loader, so today/week/month reports match the popover exactly. Added a reporter-layer test exercising a cross-day cumulative Codex session to verify only the current-day delta is counted.
- **All-Time reports tied to the project range selector (@ericweichun, #15)**: v0.11.6's analyze-bridge refactor left out the All-Time period, so clicking All-Time showed 720h cached data instead of true all-time. The bridge now maps `projectRange === "all"` through `_analysis_period_from_project_range("all") → "all"`, and project history loads with `hours_back=0` for true all-time data. All 9 panels gained a `projectRange === "all"` branch; `project_range_all` i18n keys added across all 5 locales.
- **Manual refresh button queues while busy (@ericweichun, #12)**: previously, pressing refresh while one was already running silently dropped the second request. Now a single follow-up is queued, and the completion `finally` block runs in order: `codex_model = result.get("codex_model", "unknown")`, web language injection, clear the busy flag, then drain one queued refresh.
- **Setup guidance made agent-neutral (@ericweichun, #16)**: the setup button previously gated on `~/.claude/` existence, hiding it from Codex-only users. The check is now "any status-line target available" (`~/.claude/` or `~/.codex/config.toml`); the existing `setup_hook.setup()` flow already auto-detects which agent to configure. Both README variants (zh-TW + en) reworded to agent-neutral phrasing; ja/ko `hook_not_installed` translations filled in.

## [0.11.13] - 2026-05-27

### Changed
- **Removed Codex model footer from popover**: the "· model: gpt-5.5" suffix added in v0.11.6 (`menubar.py:868-870`) misled users into thinking the model was being used *right now*, when in fact it reflects the model of the most recent Codex session with rate_limits data — possibly hours old. Without a timestamp context, this information is noise that can't be acted on. TUI model displays (`ui/tables.py:818,857`) are kept since they live inside different contexts (active session block / idle panel). The `model_label` i18n key and `CodexRateLimits.model` field are preserved; only the popover footer concatenation is removed.

## [0.11.12] - 2026-05-27

### Changed
- **Hook self-heal: broken installs fix themselves, silently**: every startup now runs `setup_hook.self_heal()`, which silently repairs three clearly-safe scenarios: (1) first-run (`is_setup()==False` and no `statusLine` key in settings) → invokes `setup()`; (2) hook script version is out of date (`needs_update()==True`) → `update_hook()`; (3) settings points to a missing hook file with state `us-direct`/`us-forwarder` → re-runs `_copy_hook_script()` + `_copy_forwarder_script()`. When state is `external`/`legacy-tt`, all three skip (no silent override of third-party tools). Each action appends to `settings["usage"]["selfHealLog"]` (FIFO, 20 entries). Failures are swallowed; stderr is printed only when `USAGE_DEBUG=1`.
- **Coexistence prompt consolidated**: when an external statusLine tool is detected, usage shows a single NSAlert with two buttons ("Enable Coexistence Mode" / "Keep Current Setup"). Either button sets `settings["usage"]["forwarderModePromptDismissed"]=True` and the prompt never appears again. Replaces the previous three-button repair dialog in `main.py:health_check()`; the "remind me later (24h cooldown)" path is removed. Users who previously chose "Do Not Ask Again" on the old dialog will be re-prompted once (one click resolves it).
- **`--doctor` hidden CLI flag**: `python3 main.py --doctor` prints a plain-text diagnostic report (English-only for easier GitHub issue searches) covering hook state, version, script file status, status file mtime, external hook detection (recognizes `ccusage` / `lord-kali` keywords), forwarder prompt ack state, last 5 self-heal log entries, and Codex sessions scan count. Hidden from `--help` via `argparse.SUPPRESS` so it doesn't distract typical users. New `doctor.py` renderer module.

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
