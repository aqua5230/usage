# Changelog

[繁體中文](CHANGELOG.zh-TW.md) · English

All notable changes to usage are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.29.23] - 2026-08-10

### Added
- **Two new panel themes: Stained Glass and Origami.** Stained Glass renders the quota cards behind irregular polygon color fields with leaded dividers and a slow light sweep; Origami folds the same layout into monochrome triangle facets that unfold once on load instead of looping like the other panels. Both are available on macOS and in the Windows tray, reuse Classic's measured panel height since their DOM structure is identical, and are picked from "Switch Panel". A regression test now asserts the Windows panel list and height table stay in sync with the macOS panel registry — nothing previously caught a new panel being added to one and not the other.
- **The contribution heatmap has a snake easter egg.** Triple-click the heatmap title within 1.5 seconds and a snake eats its way across the grid along a serpentine path, then the grid restores itself automatically. The path starts at the first week with data so an all-empty year doesn't spin uselessly, it's skipped when `prefers-reduced-motion` is set, and it's stopped and reset before any HTML/CSV/PNG export so an export can never catch the grid mid-bite.

### Fixed
- **Eight panels were silently missing the Codex stale/quota/history warnings, and five had no Install Hook button.** Extracting nine panels to a shared `panel_core.js` (see Changed) surfaced how far the independently-copied logic had drifted — averaging 200+ lines apiece — and with the drift came real feature gaps nobody had audited for: depending on which panel happened to be open, a card that should show a Codex staleness banner, a quota bar, or a history-load error sometimes just didn't. Win95's stale-state clearing also had a small bug. All nine now go through the same binding logic, so a gap in one is a gap in none.

### Changed
- **Nine card panels now share one core script instead of nine divergent copies.** `classic`, `matrix`, `win95`, `newspaper`, `cloud_observation`, `aquarium`, `prism_arcade`, `black_hole`, and `lepidoptera` all inject the same `panel_core.js` through the existing placeholder mechanism; only the genuinely panel-specific pieces stay behind — progress-bar material, project-row layout, the theme-switch button treatment, and decorative animation. A regression test now blocks a future panel from being built by copy-pasting the whole script again.
- **The public website picked up nine polish passes** — spotlight cursor tracking, scroll-triggered fade-ins, spring-eased hover states, and full keyboard navigation among them — drawn from patterns in Framer Motion, GSAP, Aceternity, Radix, and Magic UI and reimplemented in plain CSS/vanilla JS so nothing new was added as a dependency.

### Docs
- World Cup 2026's panel description no longer claims the Antigravity card and drag-to-reorder exist there — it's the one panel without either. The theme gallery gained screenshots for Classic, Cloud Observation, Prism Arcade, and Lepidoptera; every README got a quick-jump section list; and DEVELOPMENT's panel-card description now mentions Antigravity. The website nav also swapped its emoji brand mark for a hand-drawn SVG paw print, added the official GitHub icon next to the repository link, corrected wording in the five-language resume explainer (the CLI does keep a record — it just doesn't reattach automatically), and dropped four outdated feature cards along with their translation keys.

## [0.29.22] - 2026-08-10

### Fixed
- **Codex data was unreadable for anyone with a custom `CODEX_HOME`.** Every path into Codex's local data (`codex_loader.py`, `adapters/codex.py`, `session_hooks.py`, `setup_hook.py`, `fsevents_watch.py`, `menubar_state.py`, `analyzer/subscription.py`) was hardcoded to `~/.codex/...`, so anyone who set the `CODEX_HOME` environment variable — multiple accounts, containerized setups — got an empty Codex section with no explanation. All of them now resolve through a single `codex_paths.codex_home()` helper that honors `CODEX_HOME` and falls back to `~/.codex/` when it's unset.

## [0.29.21] - 2026-08-09

### Fixed
- **Windows quota panels opened taller than their content.** `wintray.py`'s `PANEL_HEIGHTS` still held the numbers from before 64a7c0b recalibrated the Mac panel heights; that commit missed the Windows fallback table, so eight panels rendered 17–24pt too tall for the brief window before the WebView reports its real content height. The numbers now match, with a comment recording where they come from so the next recalibration doesn't miss this table too.
- **Adding a new quota card silently reset everyone's saved card order.** `_valid_quota_card_order()` required the saved order's length to match the current default list exactly, so a newly added card (a fourth quota source, say) made every existing saved order look invalid and quietly fall back to default. It now only rejects duplicate or unknown ids; an order that's missing a newer card gets that card appended instead of the whole preference being discarded.

### Changed
- **The CLI status line moved to a cooler color palette.** The project name, branch, and metric labels shifted from the original green/blue/magenta mix to a teal-and-blue variant; usage-percentage colors by severity are unchanged.

## [0.29.20] - 2026-08-08

### Fixed
- **Saving a setting turned a symlinked config file into a regular one.** Every settings write goes through `_atomic_write_text()`, which writes a temporary file and then `os.replace()`s it over the target — the standard way to make sure a crash mid-write cannot leave half a file behind. `os.replace()` does not follow symlinks, though, so for anyone who manages `~/.claude/settings.json` or `~/.codex/config.toml` from a dotfiles repository, the symlink was silently replaced by a plain file: the repository copy stopped receiving updates, nothing warned, and the divergence only showed up the next time those dotfiles were deployed somewhere else. The target is now resolved to its real path before the replace, and the temporary file is created next to that real path rather than next to the link — putting it beside the link would move the rename across filesystems, which fails outright with `Invalid cross-device link` and would have traded one silent breakage for a louder one. The atomic write itself is unchanged. `statusline_settings.py` had grown its own copy of this sequence and now calls the shared helper, so `settings.json`, `config.toml` and `hooks.json` are all covered by one implementation.
- **The self-heal log could discard settings Claude Code had just written.** `_append_self_heal_log()` reads `settings.json`, appends an entry and writes the whole file back. Claude Code writes the same file, and anything it stored between that read and that write — a newly granted `permissions.allow` entry, for instance — was overwritten by the older copy still held in memory. The window is milliseconds wide, which is exactly why it would have been diagnosed as a mystery rather than as a race. The read-modify-write is now held under a `flock`, reusing the lock helper the status line already uses. It takes its own `usage-settings.lock` rather than sharing the status line's `usage-status.lock`: that one guards a different file written on every message, and sharing it would serialise two unrelated things for no benefit.
- **A short secret redacted every occurrence of its characters.** `_redact_environment_values()` masks sensitive environment values out of transcripts by substring replacement. Nothing bounded how short a value could be, so an environment variable matching the sensitive-name pattern whose value happened to be `1` turned every `1` in the message into `[REDACTED]` — timestamps, token counts, error codes. Values shorter than eight characters are now skipped; a secret that short is not one worth protecting, and treating it as one destroys the surrounding text.

### Security
- **The vendored instate CLI was bundled and executed without being verified.** `scripts/build_app.sh` downloads the binary from a release when the local `instate` project is not present, then packages it into the `.app` as-is. There was nothing to detect a substituted or corrupted download. The build now pins the expected SHA-256 in `scripts/instate-cli.sha256` and refuses to continue when the downloaded binary does not match, deleting it rather than leaving a suspect file behind for the next run to reuse. The fingerprint is committed to this repository rather than published beside the release asset on purpose: a checksum stored next to the binary can be rewritten by whoever rewrites the binary, which verifies nothing. A download that fails outright still logs a warning and continues — that is a missing panel, not a compromised one.

### Changed
- **Three passages of duplicated code were extracted.** The sharded disk caches for Claude and Codex history held sixty-three identical lines, and `codex_disk_cache.py` reached across to import `history_disk_cache.py`'s private serialisers and re-export them under its own `__all__` — a detour that made the real owner of that code impossible to see. Serialisation, shard paths and index, stale-cache removal and the payload read/write now live in `disk_cache_common.py`. The disk-cache lifecycle shared verbatim by all three loaders — the one-time seed check, the throttled flush and the best-effort flush on termination — moved to `disk_cache_lifecycle.py`. The loaders themselves are still three separate modules and stay that way; they parse three unrelated formats, and only the cache plumbing around them was ever the same. In `session_hooks.py`, three pairs of `_is_X_entry`/`_strip_X_hooks` differing only in a marker constant were parameterised, with the six original names kept as thin wrappers. `agy_disk_cache.py` was deliberately left out: it is a single JSON file with no sharding, and forcing it into the shared shape would have meant changing its behaviour to fit. Net 218 lines removed, with no behavioural change.
- **Dead constants, two unused functions and thirteen orphaned translation keys were removed.** The keys came from renames and from the AI-updates feature moving to its own repository. Finding them took more care than the count suggests: a plain text search over the source reported 159 orphans, of which 146 were false. Keys are frequently assembled at runtime rather than written out — `discussion.html` builds `discussion_status_round1_running` by lowercasing a `SessionStatus` value, and `ui/html_report.py` prepends `report_` to every key it looks up, so four live `report_wrapped_beast_*` entries appear nowhere in the source under their full names. `agy_loader.recent_input_output_tokens()` looks equally dead from inside this repository and was kept: its only caller is a script outside it.

## [0.29.19] - 2026-08-06

### Fixed
- **The app told Homebrew users to run a command that cannot work.** With no status file on disk, the popover footer said `Run python3 main.py --setup and open Claude Code once` — an instruction written for people who cloned the repo. Someone who installed the cask has no repo, so the natural next move is to look inside the bundle, and `main.py` really is in there: py2app copies it to `Contents/Resources/`. Running that copy with the system `python3` dies on `ImportError: cannot import name 'packaged_resource_path' from 'i18n'`, which points at the wrong thing entirely. The modules `main.py` imports are compiled into `lib/python313.zip`, and only the bundle's own interpreter has that on `sys.path`; with the real `i18n.py` unreachable, an unrelated PyPI package also named `i18n` in the user's site-packages answers the import instead. Both footer messages now name the "Set Up Status Line" button, which does the same job in one click and exists in every install regardless of how it was obtained. The bundled `main.py` additionally exits with an explanation when it is started without py2app's `RESOURCEPATH`, so the dead end says what it is instead of raising. (#92, reported by @kyang-06)

## [0.29.18] - 2026-08-06

### Fixed
- **The panel window oscillated between two heights.** Opening it snapped the window once, and it kept flicking back and forth afterwards. A panel's height has two sources: `popover_dimensions()` estimates it in Python from a registered base plus per-card adjustments, and the page measures itself for real once it has been laid out and reports the number back. The measurement is meant to win — it is saved to `NSUserDefaults` and read back by `resolve_panel_size()` on the next pass. It never was. `NSUserDefaults.objectForKey_()` hands PyObjC an Objective-C `__NSDictionaryI`, and `isinstance(value, dict)` on that is `False`, so the guard rejected the saved `{classic: 974}` every single time and fell back to the 1004 estimate. The write path had the same guard and therefore discarded every other panel's saved height whenever one was stored. What made this hard to see is that saving worked while loading did not: `defaults read com.lollapalooza.usage` showed the correct 974 sitting on disk the whole time, so the data looked healthy from the outside. The 30-point gap between the two values happens to equal `status_wrap_extra_height`, which is a coincidence worth ignoring — the estimate being wrong is not what caused the loop; the measurement being rejected is. Both guards now accept `collections.abc.Mapping`. The estimate is still used, but only for panels that can never report a measurement — `ErrorPanelView` has no JavaScript bridge, so waiting for one would leave it at the wrong size forever. The regression test substitutes a `MappingProxyType`, which like `NSDictionary` is a `Mapping` that is not a `dict`; a test double built from a plain `dict` passes whether or not the bug is present.
- **The Japanese and Korean locales shipped sixty-three blank labels each.** Flagged one version earlier and fixed here. Both locales carried all 489 keys, so `test_every_language_has_the_same_keys` compared key sets, found them identical, and passed — while `loading`, `no_data`, `session_title`, `col_time` and `model_breakdown` rendered as empty space for anyone running the app in either language. A present-but-empty value is invisible to a parity check by construction, which is the same blind spot that let fifty-two Simplified Chinese strings sit in the Traditional Chinese locale until last version. Two assertions now close it: no translated value may be blank, and every value's `{placeholder}` set must match English exactly. The second guards a failure the first cannot see — a translation that drops or renames a placeholder does not look wrong in the file, it raises at `format` time in front of the user. Rich markup (`[dim]`), format specs (`{m:02d}`) and command names were left in English.

## [0.29.17] - 2026-08-06

### Fixed
- **The offline price table overcharged Opus 4.6 and 4.7 threefold, and valued Opus 5 at nothing.** `_fallback_pricing()` is what the cost estimate falls back on when the LiteLLM table cannot be downloaded or its cache has expired. It is written by hand and nothing ever reconciled it against the live table, so it drifted in silence: `claude-opus-4-6` and `claude-opus-4-7` still carried the Opus 4.1-era $15/$75 per Mtok long after Anthropic dropped Opus to $5/$25, `claude-haiku-4-5-20251001` was twenty percent low, and `claude-opus-5` was missing outright — and a missing key makes `calculate_cost()` return `0.0`, so Opus 5 usage was reported as costing nothing. The corrected figures come from reconciling against the cached LiteLLM table rather than from the changelog: Claude Code 2.1.219 announced Opus 5 at `$10/$50 per Mtok`, but that is the fast-mode price, not the standard one. What makes this class of bug worth naming is when it surfaces — only offline, which is exactly the moment nobody thinks to doubt the number on screen.
- **Fifty-two keys in the Traditional Chinese locale contained Simplified Chinese.** The TUI and report strings had been copied across from `zh-CN` without conversion, so a Traditional Chinese user opening the TUI read `检测到`, `时间`, `来源`, `项目` and `消息`. A hand-written list of Simplified characters found only some of them — it missed `来` and `项` — so every value was instead run through OpenCC's `s2twp` and the differences reviewed one by one. Nine of those differences were the converter overreaching on text that was already correct (`發送`→`傳送`, `吹回`→`吹迴`, `連接詞`→`連線詞`) and were left alone. The golden HTML snapshot was patched for the two strings that actually changed rather than regenerated, because regenerating it would also replace the frozen timestamp and version the test asserts on. The same region of `ja` and `ko` holds sixty-three empty strings each; those are missing translations rather than wrong ones and are left for a separate change.

### Changed
- **`_refresh_in_background` moved into `menubar_refresh.py`.** At 203 lines it was the largest method in `menubar.py`, which had four lines left under its ceiling — and a ceiling exists on that file precisely because it has been split apart and grown back twice. Only three lines of the method touch PyObjC, the three `performSelectorOnMainThread` calls, and those stay behind along with every selector: an AppDelegate method is bound by name, so relocating one breaks the binding. What moved is the data work between them, split into `load_sources()` and `build_result()`, with the app passed in behind a `typing.Protocol` so the new module imports no PyObjC at all — the same rule that keeps `menubar_state.py` clean. `menubar.py` goes from 2116 lines to 1934 and the ceiling was lowered to match rather than raised, since raising it to get CI green would dismantle the only thing stopping the file from growing back a third time. Behaviour is unchanged, and that was verified rather than assumed: the six `refresh_timing` stages, the fifteen state assignments on the degraded path, and the `submitted`/`finally` guard that keeps a failed refresh from wedging the app were each compared line by line against the original.

## [0.29.16] - 2026-08-02

### Added
- **The file log is bounded and rotates.** The only log on disk was whatever launchd redirected into `~/Library/Logs/usage/usage.log`, and a redirect has no size limit — for a menu bar app that stays open for months, that file only ever grows. Python now owns a log of its own beside it, capped at 2 MB with three archives kept. Building the handler is best-effort: if the directory cannot be created the app keeps its console output and starts normally, because a logging subsystem must never be the thing that stops the program from running. macOS keeps the `~/Library/Logs/usage/` convention; every other platform writes under `~/.usage/logs/` next to the disk caches, since `~/Library/Logs` means nothing on Windows and `_setup_logging()` runs before the platform branch.
- **`USAGE_DEBUG` selects subsystems instead of switching everything on.** It was a boolean, so diagnosing one loader meant turning on all forty-odd debug sites and reading the result through the noise. It now takes a comma-separated list — `USAGE_DEBUG=codex_loader,pricing` raises only those two. Prefix matching comes free from Python's logger hierarchy rather than a hand-written comparison: setting `a.b` covers `a.b.c` because that is how logger inheritance already works. `1`, `all` and `*` keep the previous global behaviour.
- **`--doctor --json` emits the report as data with stable codes.** The report was a block of text, so a user could only screenshot it and the reader had to scan by eye — nothing could compare two reports or decide programmatically which check failed. Each check now carries a fixed code (`hook_state`, `codex_sessions`, …) and one of three states, the process exits non-zero when any check is in error, and the human-readable output is unchanged to the character. Ambiguous cases resolve to `warn` rather than `error`: a false alarm that fails a health check costs more than a missed warning.

### Fixed
- **The test suite wrote into the developer's real log file.** `tests/test_main.py` exercises `main()`, whose first action is `_setup_logging()` — so the run attached a rotating file handler pointed at the actual `~/Library/Logs/usage/usage-app.log`, and every warning logged by every later test landed in it. One full run deposited 8 KB containing pytest's temporary directory paths, which is worse than noise: it makes the log untrustworthy the day someone reads it for a real diagnosis. An autouse fixture now redirects the log directory to `tmp_path`, matching the existing rule for `cache_quarantine.QUARANTINE_DIR`. Curiously the same class of bug was fixed one version earlier in the Windows tray tests.

### Changed
- **`switchPanel_` builds its items through a helper.** A dozen menu entries each repeated the same five to seven lines — allocate the item, set the target, set the state, set the tooltip, add it — and `menubar.py` had two lines left under its ceiling. `menubar_menu.build_menu_item()` absorbs that shape. It lives in a new module rather than in `menubar_state.py`, which stays free of PyObjC. `switchPanel_` itself does not move: an AppDelegate method is bound by selector, and relocating one breaks the binding. The saving is smaller than it looks — 24 lines, not the 80 the line count suggested, because keyword arguments wrap across lines and give much of it back. The gain is the removed repetition, not the arithmetic. Moving the helper out also broke a test that patched `NSMenuItem` on the `menubar` module only; the fix was to patch the helper module too, never to add module-level indirection so the old patch keeps reaching.

## [0.29.15] - 2026-08-02

### Fixed
- **Token estimates no longer undercount CJK text by a factor of four.** Six places in the waste diagnosis converted characters to tokens with `chars // 4`, which is the ASCII ratio. A CJK character is roughly one token, not a quarter of one, so every figure the diagnosis reported for a Chinese, Japanese or Korean file — wasted tokens and the cost derived from them — came out at a quarter of the truth. This project reads its own `i18n.json`, `CLAUDE.md` and `README.zh-TW.md` often enough to hit this on itself. The estimate now counts CJK codepoints as one token each and everything else at four characters per token. No tokenizer dependency was added: this is an offline tool, and pulling in a model-specific tokenizer to chase rounding-level accuracy is not a trade worth making.
- **A corrupt disk cache is preserved instead of being deleted outright.** All three caches — Antigravity, Codex and history — dealt with an unreadable file by removing it and recomputing. That is the right recovery, but it also destroys the only evidence of what went wrong, so a later report of "my numbers look off" has nothing left to inspect. A damaged file is now moved to `~/.usage/quarantine/` first, named with a millisecond timestamp so a second failure cannot overwrite the first, capped at ten files and 5 MB each. A stale `schema_version` is *not* quarantined: that is an ordinary upgrade, and with 32 shards per cache one version bump would flush the whole budget and push the real evidence out. The quarantine helper swallows every error it can hit — it is a side service and must never take the caller down with it.
- **`--doctor` no longer reports a missing file that the current mode does not use.** The report listed fourteen checks as one flat list, so `forwarder script: [missing]` read as a fault even when the installed mode never needs that script. It is now grouped into `[core]`, `[hook]` and `[optional]`, and the forwarder line says `[not needed in <state> mode]` when that is the case. None of the check logic changed.
- **Two Windows tray tests wrote into the real `~/.claude/usage-preferences.json`.** Both call `switch_panel()`, which persists through `_save_active_panel_id()`, and neither patched `prefs.PREFERENCES_FILE` — so running the suite silently changed the developer's own active panel.

### Changed
- **The documentation parity check covers Simplified Chinese, Japanese and Korean.** `check_doc_parity.py` only compared English against Traditional Chinese, leaving the other three README translations unwatched; `CLAUDE.md` had to carry a note to sync them by hand. Each translation is now compared on its own and the failure message names the file that drifted. The comparison is still a count of `##` headings rather than their text — matching text would force translators to mirror English headings word for word, which is what makes translated docs read badly.
- **`scripts/install_local.sh` replaces the hand-typed steps for installing a build locally.** Releasing does not touch `/Applications`: the tag drives CI, and the local copy keeps running whatever was already there. That last step lived only in a checklist, and the menu bar once ran a stale build for six versions before anyone noticed. The script checks the build exists, prints both versions, waits for the running app to exit, swaps it, and verifies the installed version matches.

## [0.29.14] - 2026-08-02

### Fixed
- **The panel no longer creeps downward every time you open and close it.** Dragging it into place used to hold for one cycle at most: each reopen landed it a little lower than the last. Two anchors disagreed. The saved position was the window's bottom-left corner, but `setContentSizeKeepingTopLeft_` — added in 0.29.9 precisely so the panel would not appear to jump while resizing — holds the *top* edge. To hold that edge it calls `setFrameOrigin_`, and macOS posts `NSWindowDidMoveNotification` for a programmatic move just as it does for a drag, so `windowDidMove_` recorded a resize as though the user had dragged the window. Every open re-measured the content height, the bottom-left corner dropped by the difference, and that drop was saved as the new position. The anchor is now the top edge on both sides, so resizing cannot change the stored value. Positions saved by earlier versions are read through a migration path and are not reset.
- **Opening the panel no longer starts short and then stretches.** Two height systems were computing the same number and disagreeing: `popover_dimensions` estimates from a panel's base height by arithmetic (subtract a card when Claude or Codex is hidden, subtract a row when Codex has no data, add for a wrapped status line or an install button), while the script in `panels/dynamic_height.py` measures the rendered content and reports it back. The window opened at the estimate and jumped to the measurement. The gap was widest with cards hidden, where the most terms are subtracted. The measured height is now remembered per panel and used on open, leaving the estimate as a fallback for a panel that has never been measured. The arithmetic constants were deliberately left alone — tuning them is whack-a-mole, since every new UI element needs another adjustment. The panel still adjusts once when the content genuinely changes size.
- **A state file corrupted into non-UTF-8 bytes no longer raises instead of degrading.** `_load_preferences`, `_load_ping_state` and `_load_last_ping` each catch `OSError` and `json.JSONDecodeError` around a `read_text(encoding="utf-8")` — but a file containing invalid UTF-8 raises `UnicodeDecodeError`, which is a sibling of `JSONDecodeError` under `ValueError`, not a subclass of it. All three are contracted to fall back quietly when their file is unusable, and a half-written or damaged file broke that contract by propagating the exception.

### Changed
- **The macOS notification bridge moved out of `menubar.py` into `menubar_notify.py`.** The six module-level functions that talk to `UNUserNotificationCenter` had no reason to live in a 2230-line file. They were not folded into `usage_notifications.py`, which stays free of PyObjC so its decision logic remains testable without the ObjC runtime — these functions call `objc.registerMetaDataForSelector`. The update-dismissal cooldown joined `update_gate.py`, where the other update-timing constants already were. `menubar.py` is down to 2139 lines and its ceiling followed.
- **`jsonl_utils` and `time_utils` gained direct unit tests.** Both are shared by several loaders and had only incidental coverage through the modules above them. The JSONL reader's tolerance for blank lines, malformed rows and non-object values is now pinned, including the deliberate choice to raise on invalid UTF-8 when no `errors` argument is given — that decision belongs to the caller.

## [0.29.13] - 2026-08-02

### Fixed
- **Removing the Codex status line no longer deletes one that `usage` never installed.** `_unsetup_codex()` only checked whether a `tui.status_line` existed at all, not whether it was ours. Anyone who had configured their own status line and then ran the removal lost it. Worse, a corrupt backup file made the restore path overwrite the config with an empty list and then delete the only backup, losing both at once. Removal now acts only when the status line matches `CODEX_STATUS_LINE` exactly, and an unreadable or wrong-typed backup leaves both the config and the backup untouched.
- **A corrupt `~/.codex/hooks.json` is no longer treated as an empty one.** `_load_codex_hooks()` returned `{}` for "file missing" and "file exists but won't parse" alike; terse mode then rebuilt from that empty dict and wrote it back, permanently erasing every Codex hook the user had, with no backup and no message. Codex writing that file while `usage` reads it is enough to trigger this. The unreadable case now aborts before anything is copied or written, so a failed run can no longer leave a half-installed state either.

## [0.29.12] - 2026-08-02

### Added
- **The AI Talent Market gained 25 engineering roles across seven new packs.** Frontend, backend, cloud ops, quality, AI, code maintenance and app development — React and Next.js specialists, API designers, SQL and Python pros, cloud architects, Docker and DevOps engineers, Swift and Electron experts, refactoring and dependency specialists, prompt engineers, and more. Every role ships the full zh-TW/zh-CN/en/ja/ko persona set. Two existing packs also absorbed a role each: SEO into marketing, payment integration into ecommerce.

### Changed
- **Hiring a role is now one click instead of two.** A role card used to show "Install", and only after that did it turn into "Launch" — but installing is an implementation detail (writing one `.md` file into `~/.claude/agents/`) that no one needed to see. Every card now shows "Launch" directly; if the role isn't installed yet, it gets installed first and then starts. A failed install stops there and reports the error rather than opening an empty terminal. The "Restore" button for hand-edited roles is unchanged.

## [0.29.11] - 2026-08-01

### Added
- **The report and the terminal's session list now show what each conversation was about.** Claude Code names every conversation and writes that name into its transcript. `usage` had been parsing those names all along and carrying them into the report payload, where the renderer ignored them — the snapshot fixture still read `"Ignore in current renderer"`. The HTML report gained a "What you worked on" section under the contribution heatmap, and the TUI's recent-session table gained a column, so three rows from the same project are no longer indistinguishable. Titles carry `data-mask`, so the existing project-name masking covers them before a report is shared. Sessions without a title stay blank rather than falling back to the project name, which would read as a title that isn't one.

### Fixed
- **A rate-limited Antigravity quota probe now waits as long as the server asked, instead of retrying every five minutes.** That probe is the only external API call in the project. It and the token refresh both folded `HTTPError` into the same `except` clause as connection failures, so a 429 reached the caller as a bare `None` — the status code and the `Retry-After` header were discarded together, and the next cache expiry sent another request at a server that had already said to wait. Each now catches `HTTPError` separately, reads `Retry-After` in either the seconds or the HTTP-date form, and holds off until it elapses. A missing or unparseable header falls back to sixty seconds, and the delay is capped at an hour so an oversized value cannot strand the card.
- **The last minute before a quota resets no longer reads "0m".** Under sixty seconds the countdown's minute arithmetic rounds to zero, and the already-expired case printed the same string, so one line meant both "forty seconds left" and "the window has already turned". The card now reads "Reset imminent", in all five languages. The fix sits at the call site rather than in the shared duration formatter, which also renders the "will run out in" half of the burn warning — changing it there would have produced "will run out in reset imminent".

## [0.29.10] - 2026-07-31

### Changed
- **Nothing changes on screen in this release — it is housekeeping on the menu bar code.** `menubar.py` had reached 2485 lines, creeping past 2000 for the third time after being split apart twice. The icon and alert helpers moved into a new `menubar_chrome.py`, and the state constructors joined `menubar_state.py`, taking the file down to 2230. Only module-level functions moved: PyObjC binds `AppDelegate` methods by selector name, so relocating one would silently stop the matching control from working. `_popover_size` was split rather than moved, because it ends in `NSMakeSize` and `menubar_state.py` has to stay importable without the ObjC runtime for its projections to be unit-testable — the arithmetic moved as `popover_dimensions()` and a three-line shell stayed behind.
- **The growth policy behind that cleanup is now enforced by CI rather than by discipline.** `scripts/check_file_size.py` fails the build when a guarded file passes its ceiling. The rule had been written in CLAUDE.md all along; nothing checked it, and the file grew back twice. Lower a ceiling when a cut lands, never raise it to go green.
- **CLAUDE.md's module map lists only modules with a gotcha.** Half its rows restated what opening the file would tell you, and three separate rows repeated the same stdlib-only constraint. It went from 24 rows to 12.

## [0.29.9] - 2026-07-29

### Changed
- **The panel can now be placed anywhere on screen**: it was an `NSPopover`, which AppKit anchors to the status item and dismisses the moment focus moves elsewhere, so where it sat was never yours to choose. It is now a borderless floating panel: drag it from any empty spot, and it reopens where you left it. It stays put when another app takes focus — a second click on the menu bar icon, or Escape, closes it. Rounded corners and the drop shadow came free with the popover and are now drawn by the window itself. Dragging travels over the existing JS bridge: an injected script reports a mousedown that landed outside any interactive or scrollable element, and the window hands the gesture to `performWindowDragWithEvent:` so the system drives it. Resizing pins the top-left corner, because a window's origin is its bottom-left and the panel would otherwise appear to jump every time its height tracked a fresh content measurement.

### Fixed
- **The AI Talent Market panel no longer collapses into a squashed strip**: the panel intermittently opened at roughly the height of its own header, cutting off the team list. The dynamic content-height probe releases the layout's height constraints before measuring, and this panel builds its list as an absolutely positioned layer inside a `flex: 1` body — with the constraints released, that body collapsed to zero and the probe reported little more than the header, which the clamp then rounded up to the minimum panel height. Whether it happened came down to measurement timing, hence the intermittency. Panels now carry a switch for the probe, and this one — a fixed-height design that scrolls internally and never needed measuring — opts out.
- **Dismissing the switch-panel menu no longer closes the panel**: opening "Switch Panel" and then clicking the panel itself, pressing Escape, or clicking away closed the whole panel. A transient popover was already gone by the time the menu took focus, so closing it was merely cleanup; the floating panel survives the menu, which turned the same cleanup into a mistouch that threw the panel away.

## [0.29.8] - 2026-07-29

### Fixed
- **The Windows panel no longer snaps back to the primary monitor on every panel switch**: dragging the popover onto a second display and then switching panel style (or theme) forced it right back onto the primary monitor. Windows' `SPI_GETWORKAREA` API only ever reports the *primary* monitor's work area, and the window was clamped against that single rectangle on every reposition regardless of which monitor it actually lived on — so a window dragged onto a secondary display got clamped straight back onto the primary one the next time the panel reloaded. Placement now looks up the work area of whichever monitor the window's current (or saved) position falls on via `MonitorFromPoint`/`GetMonitorInfoW`, so a window on a secondary display stays there across panel switches. A related issue on a single monitor is fixed alongside it: switching panels reset the remembered content height to `None`, so the window was briefly clamped against each panel's near-fullscreen placeholder height (`PANEL_HEIGHTS`) before its real height was measured, which could shove a dragged window toward the top of the screen; the previous panel's measured height is now kept as the transitional estimate instead.

## [0.29.7] - 2026-07-29

### Fixed
- **The panel no longer leaves an empty strip at the bottom**: panel height came from a fixed per-panel constant, so any layout that rendered shorter than the registered value left dead space below the footer. The common trigger is Codex reporting only a weekly window with no 5-hour data, which drops a quota row from the card. The panel now measures its own natural height after each refresh and the window resizes to match, clamped to the usable screen area; the registered constants stay as the pre-measurement default and as the fallback when a measurement is unusable. A panel that deliberately leaves room for a full-window backdrop — World Cup's pitch is the only one — marks that region so it keeps its designed height instead of collapsing while the measurement releases the layout's height constraints.

## [0.29.6] - 2026-07-29

### Fixed
- **Claude Code panel no longer stays blank forever on Windows**: the installer picked whichever `python`/`py` `shutil.which()` found on `PATH` without checking it actually ran, so on any Windows machine without a real Python install, it silently wired the statusLine hook to Windows' non-functional "App Execution Alias" stub (the placeholder `python.exe`/`python3.exe` that Windows 10/11 ships by default to prompt a Microsoft Store install). The hook then failed silently on every refresh, `usage-status.json` was never written, and the Claude Code panel showed `--` permanently — not a first-run loading state. The installer now actually runs each candidate with `--version` before trusting it, and skips any that don't execute.

## [0.29.5] - 2026-07-27

### Changed
- **AI Council spends less Claude quota per turn**: `claude -p` calls without an attached project folder used to omit `--tools` entirely, so Claude Code loaded its full built-in toolset — Bash, Edit, Write, and the rest — into every turn's input even though the council prompt already tells participants not to call tools. Calls now pass `--tools ""` when no project folder is attached, and every Claude call adds `--exclude-dynamic-system-prompt-sections` to keep the system prompt prefix byte-stable across turns for a better shot at Anthropic's automatic prompt caching. Codex and Antigravity participants are unaffected.

## [0.29.4] - 2026-07-26

### Added
- **Steer the council mid-discussion**: an opt-in "guidance between rounds" toggle pauses the session before every round after the first, so you can react to what you just heard — "we're single-host, no cluster" — instead of watching a debate run off in the wrong direction or stopping and restarting from scratch. The pause waits up to 5 minutes and is skipped automatically if left blank; the round then proceeds exactly as it did before.
- **See who disagreed, not just how many**: the consensus tally under the moderator's summary now lists each participant by name next to their stance, with dissenting and alternative positions colored so they stand out, instead of a bare "2 agree, 1 alternative" that meant scrolling back through the transcript to find out who.
- **The five debate tones now explain themselves**: a one-line plain-language hint appears under the tone picker — devil's advocate, for instance, now reads "the AIs will deliberately argue the opposite side to test whether a plausible conclusion holds up" — so a first-time user isn't left guessing how "adversarial" differs from "devil's advocate."

## [0.29.3] - 2026-07-25

### Fixed
- **The menu bar critters no longer cost a third of a CPU core**: the phoenix, dragon and lion each drove their own timer, and every single frame re-sent the whole status item title to AppKit — which re-typesets the entire string through CoreText and re-measures the item's width, asking the system for its preferred languages along the way. With all three animating at full speed that came to 60 full relayouts a second, measured at 30–33% of a core with the popover closed; the cost arrived precisely when you were busiest, since the critters only animate while you are burning tokens. They now share a single timer, the fastest frame interval widens from 0.05s to 0.10s (indistinguishable on an 18px sprite), and a tick where no critter advances skips the redraw entirely. The burn-rate lookup that used to sit on the animation path — stat-ing 2,858 history files on the main thread every time its 30-second cache expired — moved to the background refresh, and the menu bar's text and sprite fragments are now cached instead of rebuilt per frame. Same animation, measured 4.2–5.9%.

### Changed
- **A service alert the provider forgot to clear no longer sticks around**: a status page can leave a component marked as degraded long after the incident is over, and the panel had no way to tell that apart from a live problem. Two rules now retire such an alert, both limited to the mildest *degraded performance* level so a partial or major outage is never hidden. First, if every unresolved incident on the page has sat in *monitoring* — the provider's own word for "the fix is in, we are watching it" — for more than four hours, the alert is suppressed until something changes. Second, a status observed unchanged for more than 24 hours is treated as residue. The second rule times what usage itself has seen rather than trusting the page's own timestamps: on OpenAI's page all 25 components, the operational ones included, share one timestamp from over two weeks earlier, so that field records when a component was defined, not when its status last moved.

## [0.29.2] - 2026-07-25

### Fixed
- **The council consensus tally no longer drops opinions**: stance labels were only matched at the very start of a turn's first line, so a rebuttal that reached its label a few words in — or ended its first line with one — counted as unparsed and vanished from the count. The whole first line is now scanned, and a turn must name exactly one distinct label to be counted; a turn quoting several stays unparsed instead of having one guessed for it.
- **Every selected participant shows its check mark**: the "✓" marking a participant as joining the discussion is drawn as a CSS `::after` overlay, which never renders on a replaced element. It therefore appeared only on the seat whose avatar falls back to an inline SVG (Antigravity) and stayed invisible on the seats drawn from an image icon (Claude, Codex), making a fully selected line-up look half-selected. All three now host the overlay on a wrapper element.

### Changed
- **The disabled *start discussion* button says why it is disabled**: a line under the button now names what is missing — no topic, no participant selected, or a discussion already running — instead of leaving a greyed-out button and no explanation. The reason is tied to the button with `aria-describedby` and lives in a status region, so keyboard and screen-reader users get it too, not only whoever hovers.
- **The moderator star is tellable apart**: all three stars carried the same accessible name, so a screen reader could not say which seat was moderating. Each star now exposes its pressed state, and its tooltip reads *current moderator* or *set as moderator* to match.
- **Agreeing in a council rebuttal requires reasons**: a participant opening with the agreement stance must state what it reviewed, why it agrees, and what concerns remain, so consensus cannot be reached by rubber-stamping.
- Bumped `setuptools` to 83.0.0.

## [0.29.1] - 2026-07-25

### Added
- **Council participants can wear a persona from the AI Talent Market**: every seat now has a role picker next to its model picker, listing the specialists from your installed talent packs (contract review, front-end, security audit, and the rest). The role's expertise is injected as a prompt prefix, so the same CLI can sit in two seats wearing two different hats. Roles are grouped by talent pack in a collapsible picker — collapsed it shows only the pack names, so a 50-role list no longer scrolls off the screen. Role text is fetched from the talent-market CLI at runtime and is never bundled into usage itself.
- **Five debate styles for a council**: pick the tone every participant takes from the second round on — constructive consensus-seeking, adversarial fault-finding, collaborative gap-filling, Socratic questioning of assumptions, or devil's advocate. The stance label each participant must open with is preserved under every style.
- **Council consensus is counted, and can end the discussion early**: the stance labels participants open their rebuttals with are now tallied and shown above the summary. Turn on *end on consensus* and a discussion stops as soon as every participant in a round agrees, instead of burning through the rounds you budgeted for. A round where anyone failed to finish never counts as consensus.

### Changed
- **The moderator no longer sees who said what**: the transcript handed to the moderator is anonymized, so it cannot favor the answers its own CLI wrote. Participant names are restored before the summary reaches your screen and the exported Markdown, so you still read "Claude argued…" rather than "Participant A argued…". Participants' own words are passed through untouched — a discussion *about* Claude or Codex stays readable.

## [0.29.0] - 2026-07-25

### Added
- **AI Council**: a new menu-bar window that runs a multi-round discussion between Claude Code, Codex, and Antigravity (agy) on a topic you give it. Pick which CLIs join and which model each one uses (Opus / Sonnet / Haiku for Claude, Terra / Luna / Sol for Codex, a choice of Gemini models for Antigravity), set 1–5 rounds, and optionally have one participant write a closing summary as moderator. The setup panel collapses into a status bar once a discussion starts, so the transcript and summary panes get the full window height.
- **Council cost stays visible before you commit to it**: the estimate shown before starting now includes a token total, not just a CLI-call count, and turns amber with a plain multiple-of-two-rounds comparison once 3+ rounds are selected — every extra round costs more than the last, since each participant re-reads the whole transcript so far.
- **Council supports image attachments and an optional read-only project folder**: drag-and-drop or paste (Cmd+V) images into the topic box, and each participating CLI gets read access to them; a working directory can be attached so participants can reference real project files without write access.

## [0.28.21] - 2026-07-24

### Added
- **Service-status banners for Claude Code, Claude API, and Codex API incidents.** `usage` reads the public Claude and Codex Statuspage.io status pages and shows an orange-red warning banner at the bottom of a panel only when an affected service has an outage or degraded performance. It never calls an LLM usage API.
- **Service-status banners work across every panel with a footer.** Each panel uses warning colors matched to its own theme, and a banner for a tool is not shown when that tool's card is hidden.
- **Service-status banner text is available in all five UI languages.** Antigravity is not supported because it has no usable public status page.

### Changed
- **Rate and status information now sit side by side in the footers of all eight themed panels.** They now match the default panel instead of being stacked vertically.

### Fixed
- **Live usage-rate categories can distinguish heavy use again.** Heavy users previously remained permanently in Heavy because burn rate counted `cache_read`—a near-free prompt-cache reread that reflects conversation length rather than usage intensity—in its numerator. It now excludes `cache_read`, and the Idle / Normal / Active / Heavy thresholds have been recalibrated from 50 / 250 / 1000 to 500 / 2500 / 6000 tokens per minute.
- **Popover height now accounts for the service-status banner.** When the banner appears, the panel grows enough to contain it instead of squeezing its content.

## [0.28.20] - 2026-07-24

### Fixed
- **Auto-start 5-hour Session stopped firing at all after its first ping.** 0.28.17 swapped the keeper's elapsed-time throttle for reset-boundary deduplication, which only holds up while the boundary keeps moving — and it doesn't. The ping runs `claude -p` headless, which never triggers Claude Code's statusLine hook, so `usage-status.json` goes on reporting the boundary that was already handled and the keeper wedges permanently. One machine went 23 hours with no auto-opened window while the cooldown-based Antigravity keeper kept working normally. The boundary check stays, since it is what catches a real rollover the moment it happens; a 5h5m cooldown is added alongside it as a second, independent way to re-arm once the payload has gone stale. Every existing gate is untouched, so a live window still never draws a spurious ping.
- **Orphaned temp files piled up in `~/.usage/`.** Every atomic write unlinks its `mkstemp` file in a `finally` block, and that block never runs when the app is SIGKILLed or crashes mid-write. One install had collected 40 MB of them over twelve days, dominated by the large JSONL caches whose slow writes are the likeliest to be interrupted. Startup now sweeps `~/.usage` and its direct `*.d` children, deleting only regular files that match the `mkstemp` name shape and have gone untouched for 24 hours — long enough that a second usage process cannot lose a temp file it is still writing. Symlinks and directories are skipped no matter how well their name matches.

## [0.28.19] - 2026-07-23

### Added
- **Windows tray now has the same "Auto-start 5-hour session" toggle macOS has had.** Wires the existing `window_keeper` auto-ping logic into `wintray.py`, firing after each refresh; the toggle is in both the tray menu and the HTML panel menu, with Windows-specific enable instructions (Settings → Power & battery) across all five languages. Also adds real-world Windows install-path fallbacks for the `claude`/`agy` binaries.

## [0.28.18] - 2026-07-22

### Fixed
- **Antigravity quota showed a stuck, wrong percentage since the CLI's 1.1.5 update.** The Antigravity CLI moved its OAuth credential from a plain file on disk into the macOS Keychain (`security` service `gemini`, account `antigravity`, `go-keyring-base64:`-wrapped JSON) and switched its quota backend from `cloudcode-pa.googleapis.com` to `daily-cloudcode-pa.googleapis.com`. The card kept reading the now-abandoned token file, which silently refreshed against a stale grant and returned numbers that no longer matched the CLI's own `/quota` output. It now reads the Keychain entry first (falling back to the legacy file), and posts to the current backend.

## [0.28.17] - 2026-07-21

### Fixed
- **Classic popover no longer clips the Claude card when the footer status wraps to two lines.** Long status warnings (e.g. hook broken/restart) push the footer status pill onto a second line, adding roughly 30px the fixed popover height never accounted for; flex then squeezed the overflow-hidden Claude card and clipped its weekly reset row.
- **Auto-start 5-hour Session could silently skip a reset boundary.** The keeper's fixed 5-hour self-throttle was measured from the last ping's own timestamp, which could drift out of sync with the real quota reset boundary and occasionally skip a ping entirely — leaving the next window to start only once you talked to Claude yourself. It now dedupes by the actual reset boundary instead of elapsed time, so drift can no longer cause a miss.

## [0.28.16] - 2026-07-21

### Improved
- **Idle CPU and disk I/O cut significantly across the board.** History scanning now uses FSEvents-reported paths to stat only changed files instead of re-walking and stat'ing every Claude/Codex session JSONL (thousands of files) on every refresh tick; a full rescan still runs periodically as a safety net. Startup no longer unconditionally re-downloads the pricing table or checks for updates — both now respect their existing cache freshness windows. Codex rate-limit reads reuse the same file index instead of re-scanning session directories, and SQLite reads (thread metadata, rate limits) are skipped entirely when the underlying database file hasn't changed. The on-disk parse cache is now sharded into 32 buckets so a single active session only rewrites its own shard instead of the whole multi-megabyte cache file.

## [0.28.15] - 2026-07-19

### Changed
- **Auto-start is now one shared switch for Claude and Antigravity.** It starts both keepers together; users who previously enabled either individual switch are automatically treated as having both enabled.

### Fixed
- **Antigravity auto-start never fired, and the card showed a phantom countdown.** The Antigravity quota API reports a *sliding* reset time (always "in ~5 hours") while a 5-hour window is still untouched at 100% remaining. The 0.28.14 auto-start gate treated any reported countdown as "a window is already running", so it never pinged; it now treats 100% remaining itself as "no active window" (the 5-hour self-throttle still applies). The card likewise stopped rendering that placeholder as a live countdown — at 100% remaining it now shows "Quota full" until a real window starts.

## [0.28.14] - 2026-07-19

### Added
- **Antigravity can now auto-start its next 5-hour session.** A new opt-in menu toggle watches fresh, non-mock agy quota results and, when the selected model group's session is fully reset with no countdown running, dispatches one background `agy -p ok --model 'Gemini 3.5 Flash (Low)'`. It is off by default, self-throttles for five hours, uses only the local agy CLI, and shows the same Mac sleep warning as the Claude window keeper when enabled.

## [0.28.13] - 2026-07-18

### Fixed
- **Auto-start 5-hour Session now actually fires**: the `claude` CLI resolution list was missing `~/.local/bin/claude` (where the native installer puts it), so inside the `.app` bundle's narrow `PATH` the ping silently found nothing to run and gave up. Also hardened against a false "expired" read: the reset-time check now only trusts the live statusLine hook data source (fallback sources can default a missing `resets_at` to parse time, which the next refresh would misread as already-expired) and requires the expiry to be at least 2 minutes old before firing, filtering out that false positive without meaningfully delaying a real away-from-keyboard ping. Dialog copy from 0.28.12 also simplified — leads with "pauses on sleep, resumes on wake, nothing to manage" and routes the sleep-setting instructions through System Settings search (the exact pane/wording varies by Mac model and macOS version) with a fallback suggestion to ask Claude Code to walk through it.

## [0.28.12] - 2026-07-18

### Added
- **New opt-in menu toggle: Auto-start 5-hour Session.** When enabled, usage detects that your Claude 5-hour quota window has just reset and no session is currently running, then fires a single `claude -p ok --model haiku` in the background to immediately start the next window — useful if you're stepping away and want the next 5 hours counting down before you're back. Off by default; sends at most once per 5-hour window (self-throttled), never touches the Anthropic quota API, and silently no-ops if the `claude` CLI can't be found. Enabling it shows a one-time dialog explaining that it needs usage (and the Mac) to stay awake to fire — closing the lid always sleeps the Mac regardless of this setting.

## [0.28.11] - 2026-07-18

### Changed
- **The HTML usage report looks less like a template and reads more cleanly**: gold is no longer a blanket accent — it's now reserved for four focal points (headline tail, primary KPI number, the Wrapped kicker badge, the terminal cursor), with the contribution heatmap and donut chart moved to a cohesive teal/mauve palette instead. Fixed three alignment bugs: the KPI card grid now keeps a consistent rhythm across all six cards, the Wrapped section's total-token figure no longer overlaps the phoenix illustration at high digit counts, and the trailing metric card in that section no longer orphans onto its own row. Also cleans up several small "obviously AI-generated" tells: `transition: all` rules now list only the properties that actually animate, card/section borders read at a clearer contrast in both color schemes, disabled/active button states are now styled instead of falling back to defaults, motion respects `prefers-reduced-motion`, and the three share-dialog emoji icons are now matched-stroke SVGs.

## [0.28.10] - 2026-07-18

### Fixed
- **Switching panels no longer stalls the UI with a beachball**: cold-rebuilding a panel view (evicted from the small LRU cache) reread and reassembled its HTML from disk every time — now the assembled markup is cached per panel and only built once. Selecting a panel no longer forces `NSUserDefaults.synchronize()` on the main thread. Unchanged panel state is no longer redundantly re-serialized and re-injected when a switch triggers two refresh passes back to back. Evicting an old cached panel view from the LRU cache is now deferred off the click's run-loop turn instead of running inline with the new panel's setup.

## [0.28.9] - 2026-07-17

### Fixed
- **The Claude Code statusLine hook now works end-to-end on Windows**: four fixes land together. `setup_hook` now prefers an all-ASCII `python.exe` path (falling back to system PATH when the venv path isn't ASCII), since Claude Code on Windows fails to spawn statusLine commands whose path contains non-ASCII characters; `--setup` migrates existing non-ASCII commands. All five hook scripts now read stdin via `sys.stdin.buffer` and decode UTF-8 explicitly (and the forwarder pins `encoding=utf-8` on its subprocess fan-out), since Windows otherwise decodes the piped session JSON with the locale codepage, turning a cwd like `GitHub專案` into mojibake and silently breaking `usage-status.json` writes. Hooks now fall back to `GetUserDefaultUILanguage` when no `LANG`-style env var is set (the Windows norm), matching the tray's existing language detection. `get_width()` now probes the real console width via `CONOUT$` + `GetConsoleScreenBufferInfo` instead of always falling back to a fixed 116 columns, restoring the `(left)` reset-time suffix on wide terminals. Non-Windows behavior is unchanged.

## [0.28.8] - 2026-07-17

### Fixed
- **The Windows tray no longer falls back to a stale quota cache when the hook already has live data**: a complete statusLine payload from the hook could still be overridden by the `.claude.json` fallback snapshot whenever its cached timestamp looked newer, even though that cache might describe a different or expired session; the tray now always prefers a complete hook payload, and the "complete" check itself is now stricter — malformed non-numeric percentages in the hook payload no longer count as complete, so a broken payload can't silently blank the quota by skipping the cache.
- **Windows tray history scanning no longer re-scans every Codex/Claude session log on each refresh tick**: `history_source_scan()` results are now cached for 30 seconds, removing the main source of UI jank in the tray.

## [0.28.7] - 2026-07-17

### Fixed
- **Claude quota now shows on Windows even when the statusLine hook never fires**: a Claude Code regression stops the hook from being invoked on some Windows setups, leaving the Claude quota card permanently blank. `usage_client.py` now falls back to reading `cachedUsageUtilization` straight out of Claude Code's own `~/.claude.json` when no `usage-status.json` exists, so the card still populates.
- **Session hooks no longer break on non-ASCII (CJK) project paths on Windows**: the resume, terse-mode, and terse-reminder hook commands could point into the project or app-bundle source path, which failed to execute on Windows when that path contained Chinese/Japanese/Korean characters. Self-heal now normalizes these commands to their canonical `~/.claude/` targets, and the migration is idempotent — it no longer rewrites `settings.json` and appends a duplicate self-heal log entry on every restart once the command is already correct.

## [0.28.6] - 2026-07-17

### Fixed
- **Windows hook and setup output now uses UTF-8**: statusLine bars keep their intended Unicode glyphs when Claude Code reads a pipe, and `--setup` / `--unsetup` no longer fail in legacy cp950 consoles when localized messages contain characters such as ✓.
- **Windows panel controls now fit and follow the macOS grouping**: Change Panel and Hide Sections expand in place inside a scrollable menu instead of opening clipped side submenus; the panel menu now ends with only Refresh Now, avoiding duplicate update, position-reset, and quit actions.
- **Windows quota-card empty areas now drag the panel rather than reorder cards**: the Windows shim temporarily marks only non-interactive card presses as native drag regions, retaining saved card order while buttons and links remain clickable.

### Added
- **Windows panel switch buttons now open a focused controls menu**: clicking a panel's built-in Switch Panel button opens a localized HTML overlay for panel, visibility, refresh, notification, and workflow controls; tray-only update, position-reset, and quit actions stay out of the panel menu.
- **Windows tray panels can now be repositioned**: a subtle top drag handle and quota-card empty areas move frameless panels with grab/grabbing cursors; the position is restored on the next open, clamped to the current work area, and can be reset from the tray menu.
- **Windows tray menu parity for daily updates and workflow controls**: the Windows system tray now links to AI Update Daily, offers a Hide Sections submenu for Claude, Codex, and Antigravity, supports quota-alert notifications at the same thresholds as macOS, and exposes Resume Last Session and Token Saver toggles. Changes to visible sections are injected into an open panel immediately; quota alerts use native Windows tray notifications. The macOS-only AI Talent Market remains unavailable on Windows.

## [0.28.5] - 2026-07-16

### Fixed
- **The Claude quota card now explains why it shows no data for desktop-app/headless-only users**: the quota card depends entirely on the statusLine hook, which Claude Code only invokes when rendering an interactive terminal. Users whose usage happens exclusively through the desktop app or other non-TUI surfaces never trigger it, so the card stayed on a generic "status file not found" message even while the hook was correctly installed and Claude Code transcripts kept growing. The card now distinguishes this case — hook installed, transcripts actively updating, status file still missing — and shows a targeted hint that a terminal session needs to run once to sync, instead of the setup-focused message meant for users who never installed the hook at all.

## [0.28.4] - 2026-07-16

### Fixed
- **Windows panel card order now follows across themes**: reloading a theme after dragging a quota card now rereads the shared saved order before state injection, so every draggable panel opens with the same Claude, Codex, and Antigravity card order.
- **The tray panel no longer appears as an empty white/dark rectangle at launch**: pywebview's `resize()` and `move()` call `SetWindowPos` with `SWP_SHOWWINDOW`, and the tray placed its still-hidden window as soon as the panel document loaded — dragging the unrendered panel onto the screen on every start. The window is now placed right before it is shown; after a visible panel switch the placement is re-applied as before.
- **Launching the Windows tray twice no longer leaves a blank white window**: a second instance fought the first over the shared WebView2 user-data directory, so its panel failed to initialize and lingered on screen as a bare white rectangle. The tray now holds a named mutex for its lifetime; a second launch shows an "already running" notice (localized) and exits instead.
- **The status line no longer drops quota data when two Claude Code instances refresh at once on Windows**: the hook's file lock was blocking on POSIX (`fcntl.flock(LOCK_EX)`) but non-blocking on Windows (`msvcrt.locking(LK_NBLCK)`), and a contended lock raised `OSError` that was swallowed — leaving the `rate_limits` carry-forward read-modify-write in `save()` completely unsynchronized. Windows now polls the lock until it is acquired (10s deadline), matching POSIX semantics; genuinely unsupported locking still falls back to the atomic write alone. Measured over 200 concurrent hook pairs: `rate_limits` were lost 21 times before, 0 times after.
- **The Claude Code hook no longer crashes on macOS**: a constant introduced by the Windows lock fix above referenced `errno.EDEADLOCK`, which doesn't exist on macOS — importing `usage_statusline.py` failed immediately for every macOS user. Now falls back to `errno.EDEADLK` when `EDEADLOCK` isn't defined.

## [0.28.3] - 2026-07-16

### Fixed
- **Antigravity quota probing now reads the current Windows CLI OAuth credential**: when the legacy token file is missing or unusable, usage falls back read-only to the `gemini:antigravity` Windows Credential Manager entry. The quota request's user agent now also identifies the actual host platform instead of always claiming Darwin/arm64.
- **Claude Code quota collection now works with Git Bash on Windows**: status-line commands were written with Windows backslashes, but Claude Code runs them through Git Bash when it is installed, where those backslashes escape the path and prevent the Python hook from launching. New commands use portable forward slashes; startup self-heal migrates existing usage-owned commands, and `--doctor` identifies the legacy form and the recovery step.

## [0.28.2] - 2026-07-15

### Fixed
- **Switching panels on Windows no longer risks a blank white window**: the panel-switch action reloaded the document synchronously from inside the pywebview JS-API callback, which could destroy the in-flight JavaScript Promise callback for that call and leave Edge WebView blank. The reload is now deferred until the bridge call has returned to JavaScript, with a pending-switch guard so rapid double-clicks recompute the target panel instead of reusing a stale one. The Windows PyInstaller bundle also now includes the status-line and session-hook source files that the setup and self-heal paths copy at runtime, which it previously omitted.
- **The Windows tray window no longer flashes white regardless of theme**: pywebview's window background defaults to white, which bled through the frameless window's rounded corners (and any unpainted first frame) even when the active panel's CSS was rendering its dark variant. The window background now reads the system's light/dark theme setting and matches the panel's background color.

## [0.28.1] - 2026-07-15

### Added
- **Windows auto-detects the interface language**: with no `USAGE_LANG`/`TT_LANG`/`LANG` set, language detection only knew how to ask macOS (`NSLocale`) and always fell back to English on Windows. It now maps `GetUserDefaultUILanguage()` through `locale.windows_locale`, so a zh-TW / zh-CN / ja / ko Windows UI gets the matching interface out of the box. Environment variables still take precedence.

### Changed
- **mypy now runs on the Windows CI job too**: the `check-windows` job previously skipped type checking, which is how several Windows-only defects (including the tray-startup crash surface) went unnoticed. The platform-conditional code paths (`termios`/`msvcrt` key readers, `os.getuid`, `time.tzset`, pywebview's `Window | None`) are now typed so that `mypy .` is clean on both macOS and Windows.

### Fixed
- **The Windows tray now actually starts**: importing the tray pulled in the `panels` package, whose `__init__` eagerly imported the PyObjC-backed `panels.web_panel`; on Windows this raised `ModuleNotFoundError: No module named 'objc'`, and because the TUI fallback in `main.py` only recognized a missing `wintray` module, the windowed build exited silently with nothing on screen. The panel registry now imports `web_panel` lazily inside `all_panels()` (macOS behavior unchanged), and the fallback degrades to the TUI whenever any module in the tray's import chain is missing, printing the missing module's name.
- **The tray menu and JS bridge no longer break at startup**: pystray rejects menu actions whose lambda carries an extra defaulted positional parameter, so building the panel-switch submenu raised `ValueError` before the icon ever appeared; and pywebview serializes every public attribute of the `js_api` object into the JS bridge, so exposing the tray controller on it recursed through the WinForms window graph until the recursion limit. The panel-id binding is now keyword-only, and the bridge holds the controller in a private attribute.
- **Project names derive correctly from POSIX-style cwds on Windows**: `usage_session_resume._project_from_cwd` and `adapters.claude.project_from_cwd` split paths on `os.sep` only, so a transcript cwd recorded with forward slashes (or a `C:/...`-style path) kept the whole path as the "project" on Windows. Both now normalize separators on Windows before splitting; POSIX behavior is unchanged, since backslashes are legal in POSIX filenames.
- **The test suite collects and passes on Windows**: the `check-windows` CI job had been red since it was introduced. Five test modules that import PyObjC-backed code at module level are now skipped outside macOS via `collect_ignore`; timezone pinning that relied on `TZ` + `time.tzset()` (unavailable on Windows) now pins the conversion points directly; setup-hook tests no longer hardcode `/usr/bin/python3` or `/bin/sh`; and the Codex adapter/consistency tests now sandbox `ARCHIVED_SESSIONS_DIR` and the JSONL disk cache, which previously leaked real `~/.codex` history on any machine with usage data — regardless of OS.
- **Encoded project-path decoding now works on Windows**: `project_from_encoded_path` reconstructed a project's real directory from its dash-encoded name by searching from the filesystem root, but a bare Windows `\` has no drive letter and never matches a real path, so decoding always fell back to the raw encoded string. It now anchors at the drive root (e.g. `C:\`) when the encoded name starts with one; POSIX behavior is unchanged.

## [0.28.0] - 2026-07-15

### Added
- **Full Windows support**: `usage` now runs natively on Windows, including the TUI, Claude Code status-line hook, and Codex history parsing.
- **Windows system tray UI**: a dynamic tray icon shows the Claude quota percentage; its tooltip summarizes Claude and Codex windows. Left-click opens the same 11 HTML theme panels used on macOS through WebView2, while the right-click menu offers panel switching, refresh, launch at login, update checks, and quit.
- **Portable Windows release**: GitHub Releases now include `usage-windows.zip`, containing `usage.exe` for unzip-and-run use. It requires the Microsoft Edge WebView2 Runtime, which is normally already present on Windows 10 and 11.

### Changed
- Windows packaging and CI now use PyInstaller and `windows-latest` for both checks and release artifacts. The optional `windows` extra installs pystray, pywebview, and Pillow; macOS-only PyObjC dependencies are guarded by a Darwin platform marker.
- Status-line hook file locking and generated hook-command quoting are platform-aware, so they work on Windows as well as macOS.

## [0.27.4] - 2026-07-15

### Fixed
- **Codex card no longer leaves a blank gap (and clips the projects list) on four panels**: the "Cloud Observation", "Aquarium", "Prism Arcade", and "Black Hole" panels pinned every quota card at a fixed two-row height. When Codex reports weekly-only rate limits, the session row correctly hides but these four panels kept the card at its full height while the popover window itself had already shrunk by one row, leaving a blank band inside the Codex card and cutting off the projects card at the bottom. The card now collapses along with the missing row, matching the other five panels; the two-row layout is unchanged when both rows are present.

## [0.27.3] - 2026-07-15

### Changed
- **Report generation is much faster, especially on repeat clicks**: generating the "Today"/"Last 7 days" HTML report used to re-open and re-parse every Antigravity conversation database and re-scan Codex's OTel trace log from scratch every time, and recomputed the same entry's local date and working-directory-to-project-name mapping repeatedly within a single report build. All three now cache appropriately (file-level caching for the SQLite sources, in-memory caching scoped to each report build), so a repeat click of the same period is dramatically faster with no change in the numbers shown.

## [0.27.2] - 2026-07-15

### Fixed
- **Opening the popover no longer stutters**: clicking the menu bar icon used to kick off a data refresh whose UI apply raced the popover's first frame on the main thread, and every open re-injected the full state JSON into the panel even when nothing changed. The refresh now starts only after the popover is fully shown, and state injection is skipped when the payload is identical to the last one (still force-reinjected after a WebKit process reload, so recovery is unaffected).

## [0.27.1] - 2026-07-14

### Fixed
- **Antigravity card no longer misreads as maxed out**: the card used to show whichever of the two quota groups (Gemini, or Claude/GPT) was most depleted, so an exhausted Claude/GPT five-hour window read as "100% used" even while the Gemini group the account actually runs on still had plenty left. The card now always tracks the Gemini group (falling back to the most-depleted group only if Gemini is ever absent from the API response).

## [0.27.0] - 2026-07-13

### Added
- **AI Update Daily** — clicking this menu item opens the public [web page](https://aqua5230.github.io/ai-updates/) in your default browser. The page auto-updates every day, covers Claude Code, Codex, and Antigravity, and keeps the full update history; reviewed updates show a plain-language summary in all five UI languages, while unreviewed ones show the official source text.

### Changed
- **HTML report's "AI Tool Update Digest" section removed** — the digest has graduated into its own dedicated web page, so the HTML deep report no longer duplicates it.

## [0.26.1] - 2026-07-13

### Fixed
- **Codex card no longer shows an untitled "--" row**: mid-day on 2026-07-13, OpenAI's server-side rate-limit payload switched to weekly-only (the 5-hour window vanished with the CLI version unchanged), and the loader — which mapped fields by position — shoved the weekly number into the session slot, leaving a blank row behind. Rate-limit windows are now classified by their duration, a window the server no longer reports is hidden entirely (the card shrinks by one row), and the menu-bar Codex percentage falls back to the weekly value while the 5-hour limit is absent. If OpenAI brings the 5-hour window back, both rows return automatically.
- **Antigravity reset countdowns tick down live** instead of freezing at the last-fetched value until the next refresh.

### Changed
- **Antigravity quota now comes straight from the official quota API**: usage reads the sign-in token the Antigravity CLI already stores on your machine (strictly read-only — the file is never modified) and queries the official quota endpoint directly, replacing the background `/quota` CLI probe. Numbers refresh every ~5 minutes instead of 15, countdowns are exact, no helper process is spawned, and the call reads quota metadata only — it never consumes your model quota. Any fetch failure still falls back to the cached snapshot with the usual stale badge. The data-source description in all five README languages is updated to match.
- **Less idle disk I/O**: the JSONL scan caches are flushed to disk at most once per 5 minutes (with a final flush on quit), rapid file-event bursts coalesce into a single refresh, and the four per-project ranking windows are aggregated in one pass over history.
- Antigravity token rows in the HTML report are labeled "Antigravity" instead of "unknown".

## [0.26.0] - 2026-07-13

### Added
- **Antigravity (Gemini) support** — usage now watches a third AI tool alongside Claude Code and Codex:
  - **Quota card in every panel**: session + weekly limits appear as a third card in the classic panel and all nine themed quota panels, each styled in its host theme's visual language, with the same stale-data badge and hide toggle as the other two tools.
  - **Official numbers, no API poking**: quota is read by periodically running the Antigravity CLI's own `/quota` command in the background (15-minute cache) — identical to typing it yourself. No OAuth-token scraping, no internal API calls.
  - **Menu bar segment**: the Antigravity mark and session percentage join the menu bar, complete with a **lion spirit companion** whose animation speed follows Antigravity's own token burn rate — the phoenix (Claude) and dragon (Codex) finally have a third packmate.
  - **HTML report integration**: Antigravity token usage from local logs feeds the deep report.
- **Drag to reorder quota cards**: press and drag the Claude / Codex / Antigravity cards in any panel to swap their order. The arrangement is validated, persisted, shared across all themes, and survives restarts.

### Fixed
- **Antigravity quota probe hardening**: the probe no longer hangs on Antigravity CLI 1.1.1's new workspace-trust prompt, and the stale-data tooltip now describes the probe behavior accurately.
- Fuzz harness imports are static so PyInstaller bundles the parser modules (CI fuzzing only; no user-facing impact).

### Changed
- README now ships in five languages (English, Traditional Chinese, Simplified Chinese, Japanese, Korean) with a cleaned-up presentation.
- AI Tool Update Digest refreshed (Claude Code 2.1.206 / Codex 0.144.1 / Antigravity 1.1.1).

## [0.25.4] - 2026-07-11

### Changed
- **AI Talent Market: full role-library refresh** — all 69 role prompts are restructured (XML-tagged sections, explicit tool guidance, contrastive good/bad examples) for noticeably more reliable in-conversation behavior, across the now 22 packs / 69 roles. The library ships inside the .app bundle, so this update is the way to get it.
- **The menu bar polls less when you're not looking**: the fallback refresh timer stretches from 60s to 300s while the popover is closed, and snaps back (with an immediate refresh) the moment it opens. File-change-driven updates are untouched, so the pinned numbers stay just as live — this only cuts idle CPU wakeups.
- **HTML report density polish**: tighter stat tiles, table rows, and trend rows.

## [0.25.3] - 2026-07-10

### Added
- **Token Saver now holds up in long conversations**: enabling it also installs a per-message reminder hook (`usage_terse_reminder.py`, UserPromptSubmit) that re-injects a one-line terse nudge with every message you send. In an A/B test on real Claude sessions the start-of-session instruction alone drifted badly — late-conversation replies grew +84% (603 → 1108 chars) — while the tail reminder held them steady (538 → 674), keeping late replies ~40% shorter. Existing installs pick the new hook up automatically via self-heal. Claude Code only (Codex CLI has no UserPromptSubmit equivalent).

### Changed
- **"Terse Mode" is renamed "Token Saver"** in the menu across all five languages — the name now states the benefit instead of the mechanism.
- **Spirit critters are now always on**: the phoenix/dragon animation lives permanently beside the percentages; the "Summon Spirits / Dismiss Spirits" toggle is gone.

## [0.25.2] - 2026-07-10

### Fixed
- **Phoenix menu-bar animation was nearly static in 0.25.1**: that release accidentally replaced all 5 menu-bar animation frames with near-identical high-res art meant only for the Year Wrapped report card, so the animation barely changed between frames. The menu-bar frames are restored to the original animated set, and the Wrapped report card now reads from its own dedicated `wrapped.png` asset per critter so the two no longer share a file.

## [0.25.1] - 2026-07-10

### Changed
- **Sharper phoenix critter sprites**: the Claude-side menu-bar critter animation now ships 216×216 source art (up from 54×54) for crisper rendering on Retina displays; the template-image alpha masking is unchanged.

## [0.25.0] - 2026-07-10

### Added
- **Save the report as a .png image**: the share dialog gains a third button next to .html/.csv. It renders the report with a vendored html-to-image v1.11.13 (MIT) — fully offline, no network, and it honors the "hide project names" toggle so a masked screenshot is one click.

### Changed
- **Report visual redesign (warm glassmorphism)**: warm ink background with amber/jade glows, frosted-glass cards over a subtle noise texture, and a gold/jade/coral accent palette replacing the old blue/purple. The contribution heatmap turns gold, the base type scale grows to 17.5px with a clearer size hierarchy, and headings/body adopt Grenette/Styrene font stacks (system-font fallbacks; no font files embedded or fetched).
- **Share dialog copy is audience-neutral**: the "Send to a colleague / manager" heading is now "Share a copy" across all five locales.

### Security
- CI hardening while closing out this cycle's supply-chain checklist: ClusterFuzzLite + Atheris fuzzing for the JSONL parsers (base image pinned by digest), CodeQL actions bumped to v4, and routine action bumps (setup-python 6.3.0, setup-uv 8.3.2) — all dependabot PRs merged and both OpenSSF Scorecard alerts triaged.

## [0.24.11] - 2026-07-08

### Fixed
- **AI Tool Update Digest went blank after upgrading from 0.24.9 or earlier**: the new versions-array schema introduced in 0.24.10 caused `_normalize_payload` to return an empty list (not `None`) when reading a pre-0.24.10 cache file, which `load_ai_updates` then treated as a valid "fresh" empty result instead of refetching from GitHub — hiding the section for up to 24h (the cache TTL) on every machine that had used an older version. Legacy-schema caches now correctly trigger a refetch.

## [0.24.10] - 2026-07-08

### Added
- **AI Tool Update Digest now keeps history**: previously each refresh of `ai_updates.json` overwrote the prior period, so older updates were lost. The digest now stores every tool's updates as a versions array (newest first) and the report adds a "View update history" collapsible section beneath each card so older periods stay browsable.

### Changed
- **AI Tool Update Digest content refreshed**: Claude Code 2.1.202, Codex 0.143.0-alpha.38, Antigravity 1.0.16 (covering 2026-07-01~07-08).

## [0.24.9] - 2026-07-08

### Fixed
- **Analysis report occasionally failed with `ZipImportError: bad local file header`**: `analyzer/reporter.py` imported three single-file modules (`persona_loader.py`, `subscription.py`, `ai_updates_loader.py`) that lived outside the package directories py2app already unzips, so they still loaded through `python313.zip` — the same failure mode the earlier adapters/analyzer/ui packaging fix was meant to close. Moved all three under `analyzer/` so the entire report pipeline is now free of zipimport.

## [0.24.8] - 2026-07-07

### Changed
- **AI Talent Market catalog expanded**: the bundled `instate-cli` was rebuilt from upstream to add 3 new roles — Technical Writer and UX Researcher (extending the solo-software-studio and solo-product-consultant packs to 4 roles each) and AI Visual Production (extending the content-creator pack to 4 roles) — plus a rename of every role's persona name to a real singer's given name across all five locales for easier recall. No usage code changed; this is a vendored-content refresh.

## [0.24.7] - 2026-07-07

### Fixed
- **Black hole panel: the black hole was barely visible behind the cards**: card surface opacity (0.28 → 0.14) and backdrop blur (4px → 1.5px) were heavy enough to bury the accretion disk and event horizon drawn on the background canvas. Both were lowered so the black hole stays clearly visible through the cards.
- **Midnight aquarium panel: fish and jellyfish were hidden behind the cards**: same treatment as the black hole panel — card surface opacity (0.22/0.28 → 0.13/0.17) and backdrop blur (12px → 2.5px) lowered so the aquarium life stays visible while text remains readable.

### Docs
- **README overhauled in both languages**: restructured along conventions surveyed from well-maintained open-source developer tools, with a complete inventory of current features.

## [0.24.6] - 2026-07-07

### Changed
- **AI Talent Market code-reviewer role strengthened**: the bundled `instate-cli` was rebuilt from upstream — the code-reviewer role now carries a security/boundary-condition checklist and flags over-engineering, folded into the existing persona rather than added as overlapping new roles. No usage code changed; this is a vendored-content refresh.

## [0.24.5] - 2026-07-06

### Changed
- **AI Talent Market catalog expanded**: the bundled `instate-cli` was rebuilt from upstream to add 4 new role packs (12 new roles) — content creator, event planner, translation/localization, and personal finance advisor. No usage code changed; this is a vendored-content refresh.

## [0.24.4] - 2026-07-05

### Changed
- **AI Talent Market catalog expanded**: the bundled `instate-cli` was rebuilt from upstream to add 11 new role packs (33 new roles) — customer support, virtual assistant, ecommerce operator, career coach, data analyst consultant, sales, game studio, HR recruiting, project management, paid media, and product consulting — plus a guardrail line each on the contract-review, tax-filing-prep, and design-proposal-quote roles covering unauthorized-practice and IP-assignment risk. No usage code changed; this is a vendored-content refresh.

## [0.24.3] - 2026-07-05

### Fixed
- **AI Talent Market panel always showed pack/role names in Chinese**: `talent_market_bridge.list_state()` called the bundled `instate-cli` without a language argument, so it always fell back to its default locale even though the CLI now supports five-language translations (`zh-TW`/`zh-CN`/`en`/`ja`/`ko`) for pack and role names. usage's already-detected UI language is now passed through, so the panel matches the rest of the app instead of being locked to Chinese.

## [0.24.2] - 2026-07-05

### Fixed
- **Session-resume handoff could surface skill-expansion noise and duplicate the same request**: `usage_session_resume.py`'s `_parse_session` collected every `type: "user"` transcript entry as a candidate "recently working on" request without checking Claude Code's `isMeta` flag, so skill/command expansions injected into the transcript (e.g. a full `SKILL.md` body) could show up as if they were a real request. Dedup also only compared against the immediately preceding request, so the same request separated by one of these injected entries counted twice, wasting handoff slots that are capped at 3. `isMeta: true` entries are now skipped, and dedup checks against every request seen so far, not just the last one. (Reported in #46 by @apple8409.)

## [0.24.1] - 2026-07-05

### Fixed
- **Menu bar could peg a full CPU core after launch on machines with unpriced models in their history**: `pricing.py`'s model-to-price lookup ran a full linear scan of the entire LiteLLM pricing table for every history entry whose model wasn't in it, with no caching of the "not found" result — so every refresh re-scanned the same unresolvable models (e.g. sessions logged by a non-Anthropic/OpenAI backend) from scratch, thousands of times per refresh on machines with a lot of that history. The lookup is now memoized per pricing-table generation, so a given unresolvable model is only scanned once.
- **Claude Code history reparsed from scratch on every relaunch**: `history_loader.py`'s per-file JSONL parse cache only lived in memory, unlike the matching Codex-side cache added in 0.24.0, so every app restart — including auto-launch at login — paid the full history reparse again (measured 5+ seconds on a long-lived install). It now persists to disk the same way the Codex loader already does.

## [0.24.0] - 2026-07-05

### Added
- **AI Talent Market**: a new menu-bar panel for installing curated teams of Claude Code subagent personas — organized by scenario (a one-person law practice, a solo software studio, and more) — straight into `~/.claude/agents/`; once installed, call a persona by name in any Claude Code conversation. Search or browse by team, drill into a role for a full write-up and one-click launch into a new Terminal session, and pick which folder each launch targets instead of it being guessed for you. Runs fully local through a bundled companion CLI — no account, no network call.

### Fixed
- **Menu bar refresh could take 17+ seconds on long-running installs**: the Claude Code / Codex history loaders cached parsed JSONL files behind a 512-entry LRU, too small once a machine has accumulated more sessions than that — every refresh evicted and fully re-parsed files that had just been cached the tick before. Both loaders now parse incrementally from the last confirmed byte offset instead of re-reading whole files, the cache is sized to hold a real working set, and a redundant title update that forced a full relayout on every critter-animation frame has been removed too.

## [0.23.2] - 2026-07-04

### Fixed
- **Matrix panel's countdown and footer text was too dim to read**: `--muted` opacity was bumped up and a subtle glow (matching the card titles) added to the reset countdown and footer status lines.
- **Black Hole panel's signature animation was barely visible**: the accretion-disk scene was drawn directly behind the cards, and their 16px frosted-glass blur was smearing it into a faint blob; the blur is now much lighter so the disk, event horizon, and particle stream actually show through.
- **Newspaper and Win95 panels could clip the last project row**: both panels' outer layout was missing the `flex: none` / `flex: 1` split every other panel uses to absorb variable content height, so with 3 projects showing, the bottom of the list (and sometimes the footer) got silently cut off by `overflow: hidden`. Layout fixed and registered panel heights recalibrated to the real measured minimum for each panel (Win95 800→870, others tightened after also trimming row spacing).
- **Newspaper panel's row spacing was looser than every other panel**: track height, line-heights, and card padding are now in line with Classic's proportions, so the panel isn't noticeably taller without needing extra clipping-avoidance padding.

### Changed
- **Newspaper panel now leans into the "aged paper" look**: deeper amber tone, a faint compass-rose watermark, ink-shadowed titles, and a double-line decorative border.

### Added
- **Terse Mode now covers Codex CLI too**: the same menu-bar toggle installs a matching SessionStart hook for Codex when it's detected on the machine, using Codex's native hooks system (`[features] hooks = true` plus a `~/.codex/hooks.json` entry). No separate switch — one toggle, both tools. Turning it off only removes usage's own hook entry; it leaves the `hooks` feature flag and any other hooks you've installed for Codex untouched.

## [0.23.0] - 2026-07-04

### Added
- **Terse Mode**: a new menu-bar toggle that asks Claude Code to answer more tersely for the whole session — cutting hedging, filler, and repeated preamble while keeping code, commands, file paths, and error messages byte-exact. Fully local (just a SessionStart hook, no API calls), off by default, and announces itself at the start of your first reply — merged into the Progress Concierge's greeting when both are on, or on its own line otherwise. Like any style instruction, it's a request rather than a hard constraint: on a very long conversation it can gradually fade and drift back to Claude's normal verbosity, at which point a one-line reminder brings it back.

## [0.22.14] - 2026-07-03

### Fixed
- **Archived Codex sessions could show stale data**: usage counted `~/.codex/archived_sessions/` when computing totals but didn't watch it for changes, so edits there might not refresh the menu bar until an unrelated refresh happened; the archived folder is now included in the same change-detection that drives live updates.
- **A broken usage-data hook no longer causes constant background rescanning**: when Claude Code's status hook goes stale, usage now caches the "is there recent activity" check briefly instead of rescanning your entire `~/.claude/projects` tree on every poll.

### Added
- **A small warning badge appears if local usage history can't be read**: previously, a failed read silently fell back to the last known data with no visible sign anything was wrong; the Project Usage card now shows a brief note (hover for detail) so you can tell "no new data" apart from "something broke."

### Performance
- **Faster per-refresh history scans**: each refresh previously walked the Claude/Codex session directories multiple times (once to detect changes, again per data source); it's now scanned once and reused.

## [0.22.13] - 2026-07-02

### Added
- **HTML report gets an "Avg per Message" KPI card**: a sixth summary card shows total tokens divided by message count, giving a quick read on how much each message burns (this includes cache tokens, so it reflects burn per message rather than literal message length).

## [0.22.12] - 2026-07-01

### Fixed
- **New model pricing refreshes as soon as usage sees an unknown model**: fresh cached pricing could hide newly-added models until the 7-day TTL expired, temporarily rendering them as $0.00/unknown. A pricing miss now triggers a debounced background refresh, and Claude Sonnet 5 has an offline fallback price so first-run or offline usage still estimates cost.

## [0.22.11] - 2026-06-27

### Fixed
- **Usage charts group days by your local time, not UTC**: the daily/weekly/monthly aggregates bucketed each entry by its UTC calendar day, so usage in the local pre-dawn hours (e.g. 00:00–08:00 at UTC+8) was credited to the previous day; timestamps are now converted to local time before bucketing, matching the HTML report.
- **Archived Codex sessions are no longer undercounted**: usage now scans `~/.codex/archived_sessions/` alongside `~/.codex/sessions/`, so Codex sessions that have been archived still count toward your totals (no change when that directory doesn't exist).

## [0.22.10] - 2026-06-24

### Added
- **The AI tool updates bulletin now ships in five languages**: each bulletin item previously carried only Traditional Chinese and English, so Simplified Chinese, Japanese, and Korean readers fell back to English; every item now includes zh-CN/ja/ko translations that keep each technical term's plain-language gloss and everyday metaphor in the reader's own language. The bulletin content was also refreshed to Claude Code 2.1.187, Codex 0.142.0, and Antigravity 1.0.11.

## [0.22.9] - 2026-06-24

### Added
- **World Cup panel: each team's squad size now reflects its usage**: a side using more of its session quota fields more players (5–8) and presses its formation toward midfield, sharing the same session-percent signal that already drives the ball drift.

### Fixed
- **Models with no pricing data show "—" instead of a misleading $0.00**: the cost column rendered unknown models as $0.00, which reads as free rather than unknown; unavailable costs now render as "—" in both the HTML report and the CSV export.
- **Codex quota rows are labelled by window length**: the free-plan 30-day window no longer shows as "Session" — each row's label now comes from the window length Codex reports (≈ Session / Weekly / Monthly).
- **World Cup quota bars now fill their whole half**: the duel bars used auto-margins that bunched both fills against the centre line, leaving the outer ends blank so a 100% side never reached the track edge; each fill is now anchored to the centre and extended outward.

### Performance
- **Faster Codex log parsing**: unchanged session files are no longer re-read on every poll, and a versioned on-disk cache lets a fresh launch reuse prior parse results instead of re-scanning all history cold.

## [0.22.8] - 2026-06-23

### Fixed
- **A panel that fails to load is no longer pinned to its error screen until restart**: the panel caching added in 0.22.7 stored whatever `build_view` returned — including the `ErrorPanelView` fallback shown when a panel's HTML can't be read — so once a load failed, switching back kept showing the error even after the file was available again. usage now caches only successfully-built web views; a failed build is shown but left uncached and rebuilt on the next switch, so a transient read failure recovers on its own.

## [0.22.7] - 2026-06-23

### Fixed
- **Switching panels no longer flickers**: every switch tore down the WKWebView and reloaded its HTML, exposing the dark backing layer until the load finished — a visible flicker, plus the popover closed and reopened. usage now caches each panel's web view (lazily, capped at 6 with LRU eviction) inside a container view and switches by toggling visibility and re-injecting the latest state, so a previously-opened panel reappears instantly with no reload. The first build of a panel fades in from a same-color overlay that is removed on the first successful paint (or after a 1.5s safety timeout). The popover no longer closes and reopens on switch.

## [0.22.6] - 2026-06-23

### Fixed
- **Annual Wrapped and the 52-week contribution heatmap no longer lose history when source logs are pruned**: the year view recomputed everything from whatever Claude Code / Codex session logs still existed on disk, so once those logs were rotated away it could only ever show the last ~2 months. usage now persists a daily ledger (`~/.usage/year_ledger.json`) that accumulates over time — each rebuild merges the currently-available days in (overwriting a stored day only when the fresh total is at least as large, so a partially-pruned day can't shrink the record) and trims entries beyond the 53-week window. The heatmap, streaks, active days, and Wrapped totals are all computed from the merged ledger, so coverage fills toward a full year from here on.

## [0.22.5] - 2026-06-22

### Fixed
- **Panel no longer goes permanently blank after a context-menu "Reload"**: the popover panel loads its HTML via `loadHTMLString` with no base URL, so the WKWebView system context-menu Reload reloaded `about:blank` and left the panel blank with no obvious way to recover (#42). usage now strips navigation items (Reload/back/forward/open/download) from the panel's context menu, and internal reloads re-inject the original HTML instead of calling `reload()` — which also fixes panel recovery after the web-content process is terminated.

## [0.22.4] - 2026-06-22

### Fixed
- **Analysis report no longer crashes with "bad local file header" inside the packaged .app**: the report modules (`analyzer`/`adapters`/`ui`) were compiled into the bundle's `python313.zip` and loaded lazily via `zipimport`, so a single corrupt zip entry surfaced as a `ZipImportError` the moment a report was generated. They are now unzipped into the bundle as real directories (py2app `packages`), bypassing `zipimport` entirely. The bundle's `python313.zip` also no longer ships CPython's test suite, pytest, or setuptools, shrinking it from 1665 to 819 entries and cutting the surface for a corrupt entry. This deepens the packaged-report fix from 0.22.2.

## [0.22.3] - 2026-06-22

### Added
- **Warns when the status line stops updating while you're still working**: the menu bar percentage comes only from the file the status line hook writes, so if that hook gets unwired (another tool rewrites `settings.json`) or stops firing, the pinned number would silently freeze. usage now detects this — when the status file hasn't updated for 30 minutes but your `~/.claude/projects` logs show recent activity — and shows an actionable warning telling you to re-run `--setup` or restart Claude Code. The last known percentage is kept, never fabricated, and there is still no network call.

## [0.22.2] - 2026-06-21

### Fixed
- **HTML report no longer fails inside the packaged .app**: the year-in-review spirit images (phoenix/dragon) were resolved with a source-tree path that doesn't exist in the py2app bundle, so generating any report raised `FileNotFoundError`. They are now resolved through the bundle's resource path, with the source-tree path kept as a fallback for source/CLI runs.

## [0.22.1] - 2026-06-21

### Fixed
- **Idle menu-bar refreshes no longer react to unrelated agent state writes**: FSEvents now watches Claude and Codex usage-history directories instead of their entire data roots, and unchanged status titles no longer trigger redundant AppKit layout work.

## [0.22.0] - 2026-06-21

### Added
- **Year in review in the HTML report**: two new sections that turn a year of local usage into one glance. A GitHub-style 52-week contribution heatmap shades each day by how many tokens you burned, with your current and longest active streaks and your busiest day called out beside it. A "Wrapped" card sums up the year — total tokens, cost, active days, longest streak, and your most-used model and project — and crowns you with the spirit you leaned on most: a phoenix if you ran more Claude, a dragon if you ran more Codex. All computed from local files, no network.
- **Reports stay fast on huge histories**: the year of data behind those sections is cached to disk and served instantly on repeat opens, only recomputed once it goes stale — so the report opens quickly even when your logs are enormous.

## [0.21.1] - 2026-06-20

### Added
- **AI Tool Update Digest in the HTML report**: a new section that sums up recent updates to the AI coding tools you use — Claude Code, Codex, and Antigravity — rewritten in plain, layperson-friendly language as one-idea cards, each keeping the official changelog verbatim underneath. The content is fetched from a small JSON file on GitHub, so it stays current without an app update and makes no other network calls.

## [0.21.0] - 2026-06-20

### Added
- **Summon Spirits — an animated companion in your menu bar**: a new "Summon Spirits" menu item toggles a small white silhouette that runs next to your usage percentages — a phoenix for Claude, a dragon for Codex. It animates faster the harder you burn tokens (idle -> paused, heavy -> sprinting), driven entirely by your local burn rate. Off by default; the on/off state is remembered. No network, like everything else.
- **`usage export` command**: dump your usage totals to CSV straight from the terminal.
- **CSV download in the HTML report**: the report's share dialog can now export the project/model breakdown as a CSV file (replacing the old copy-file-path action).

## [0.20.3] - 2026-06-18

### Fixed
- **Forked Codex conversations no longer replay parent history as new usage**: Codex can embed a timestamp-rewritten copy of the parent conversation in a fork JSONL. The loader now matches and excludes that replay while retaining both the original parent usage and new post-fork usage. (#40, by @ericweichun)
- **Codex reasoning tokens are no longer charged twice**: `reasoning_output_tokens` is already included in Codex's `output_tokens`, so JSONL and SQLite usage readers now price the output total once. (#40, by @ericweichun)

## [0.20.2] - 2026-06-16

### Fixed
- **Codex model attribution now falls back to turn context**: newer Codex sessions can store the model in `turn_context.payload.model`, while `state_5.sqlite` may not have a matching thread row yet. The reader still prefers SQLite when available, but now uses the turn context as a fallback so cost estimates and model distribution no longer collapse to unknown or $0. (#38, by @ericweichun)
- **Animated quota rows no longer restart on every panel refresh**: panels with animated quota tracks, including Prism Arcade, Black Hole, and Aquarium, now mount each quota row once and update it in place instead of rebuilding the markup on every status update. This prevents the CSS animation flicker during normal refreshes. (#39, by @ericweichun)

## [0.20.1] - 2026-06-14

### Changed
- **Context-window nudge reframed around quality, and fires earlier (≥70%)**: the status line reminder added in 0.20.0 was framed around cost, but Claude Code (and Codex) auto-compact at ~80% and prompt caching makes resent context cheap — so the cost angle added little. What actually degrades as a conversation grows is quality: models lose the middle of long inputs well before the window fills. The nudge now triggers at 70% — ahead of the lossy automatic compaction — and suggests taking control yourself: `/clear` when switching tasks, or `/compact` to keep the focus you choose. The dollar figure was dropped.

## [0.20.0] - 2026-06-13

### Added
- **Status line nudges `/clear` when the context window goes heavy (≥80%)**: once a Claude Code conversation fills its context window past the red zone, the status line appends a one-line reminder. Past that point every turn resends a heavy context — pricier turns and a faster rate-limit burn, both of which `/clear` resets. The nudge shows the context % and, when available, the session cost, in all five languages.

### Fixed
- **Codex 5h quota no longer goes stale on long-lived sessions**: the rate-limit reader scanned Codex session files newest-date-directory first and stopped at a scan limit, which could skip the file that was *actually* modified most recently when a long session keeps appending to an older creation-date directory. It now sorts all visible session files by modification time, so the menu bar always reflects the newest snapshot. (#37, by @ericweichun)

## [0.19.1] - 2026-06-12

### Fixed
- **Hidden Claude Code section no longer leaks a setup error**: Codex-only users who hid the Claude Code section still saw a "status file not found — run `python3 main.py --setup`" message in the popover footer, plus an "Install Hook" button. Both are Claude Code-specific and are now suppressed while the section is hidden; the footer falls back to a neutral synced status. (#36, reported by @ilss0902)

## [0.19.0] - 2026-06-11

### Added
- **Hide Claude Code section**: a new "Hide Sections ▸" submenu in the Switch Panel menu lets you hide Claude Code and Codex independently, so Codex-only users can hide the Claude Code card from every panel theme and the Claude Code percentage from the menu bar (Codex then leads the readout). Every panel keeps its "Switch Panel" button reachable — when the Claude Code card is hidden, the button moves to the next visible card. (#35, requested by @ilss0902)

### Changed
- **Hiding a provider now also hides its percentage from the menu bar** (previously "Hide Codex Section" only hid the popover card). With both providers hidden, the paw icon stays in the menu bar as the click target.
- **Shorter settings menu**: the "Automatically Check for Updates" row is gone — update checks simply stay on by default (still honored if disabled in `~/.claude/usage-preferences.json`), and the two hide toggles are consolidated into the "Hide Sections ▸" submenu.

## [0.18.0] - 2026-06-11

### Added
- **Health-check diagnosis on every new conversation**: usage now runs a background diagnosis engine against your Claude Code session logs and, when it finds meaningful waste, quietly appends a one-line reminder to the Progress Concierge's opening handoff. Say "show me" and the model reads the full snapshot (`~/.claude/usage-diagnosis.json`) and explains findings with specific suggestions. The reminder is suppressed for 7 days once a fingerprint is seen, re-surfaces when the diagnosis changes, and is skipped entirely when the snapshot is stale (>48 h).
- **Five-rule diagnosis engine** (`analyzer/diagnoser.py`): detects repeated file reads, polluter directories (node_modules, .venv, dist, …), anomalous session sizes, noisy Bash output, and repeated Bash commands. Findings are ranked by estimated token waste so the most actionable finding is always surfaced first.
- **Daily diagnosis snapshot** (`usage_diagnosis_snapshot.py`): the menu-bar app refreshes `~/.claude/usage-diagnosis.json` once per day in the background so the cost estimate is always fresh when you open a new conversation.

### Fixed
- **Anomaly-session waste estimates are no longer inflated ~9×**: the engine previously counted the entire token total of an anomalous session as waste and priced every token at the full $3/MTok input rate. Long sessions are dominated by cache reads billed at a tenth of that ($0.30/MTok), and the work done in the session isn't waste at all — only the excess over the project baseline is. Cost is now split by token type and scaled to the excess share (real-data result: $254 → $27).

## [0.17.1] - 2026-06-10

### Fixed
- **Lepidoptera panel no longer shifts when the project list is empty**: the panel was vertically centered, so with no project data the cards floated to the middle of the popover and jumped when projects appeared. It now top-aligns like the other panels, with the project card absorbing the extra height, so the layout stays stable whether or not projects are listed.

## [0.17.0] - 2026-06-10

### Added
- **New "Lepidoptera" panel theme**: a cyanotype blueprint plate inspired by the Fable 5 launch — deep Prussian-blue ground with a cyan engineering grid, the Claude Code and Codex logos mounted in cyan registration frames, monospace engineering readouts, corner crop marks, and white technical line-art butterflies drawn as schematics (construction circles, centerlines, wingspan dimensions) that drift and beat their wings across the panel. Pick it from "Switch Panel". Honors `prefers-reduced-motion`.

## [0.16.3] - 2026-06-10

### Changed
- **Cleaner project list on more panels**: removed the redundant row separators on the Matrix, Newspaper, and Windows 95 panels — each already shows a per-project usage bar, so projects are now divided by that bar alone, matching the default panel. (Panels that rely on separators instead of a usage bar are unchanged.)

## [0.16.2] - 2026-06-10

### Changed
- **Homebrew now ships as a cask**: usage is a GUI app, so it's now distributed via Homebrew's cask format — it drops `usage.app` straight into your Applications folder and skips the formula relocation/re-signing pass, which also fully fixes the earlier `usage.app/usage.app` doubled-path `Errno::ENOENT` install failure. Install with `brew install --cask aqua5230/usage/usage`; if you previously installed via the formula, run `brew uninstall usage` first, then reinstall. (Thanks @anatolii-maslennikov-improvado for reporting #34)
- **Sharper, cleaner default panel**: the default menu-bar panel now renders text with crisper font smoothing and standard font weights, shows project rankings as filled number badges (top project highlighted in green), brightens the active tab, drops the redundant row separators, and fixes the slightly clipped top edge on the project token counts.

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
