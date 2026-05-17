# 變更紀錄 (Changelog)

繁體中文 · [English](CHANGELOG.en.md)

本檔記錄 usag 所有重要變更。格式參考 [Keep a Changelog](https://keepachangelog.com/)。

## 0.1.3 — 2026-05-18

### 變更
- Popover 改版：Claude / Codex 兩段改用淡色內嵌卡片包起來，群組感更明確；間距、字重、footer 字色一併重整。卡片填色會跟著系統 Dark / Light 自動切換。
- `docs/popover.png` 換成新版的截圖。

### 修正
- Popover 不再顯示「狀態：錯誤 (AttributeError)」、Claude 兩條 quota 不再卡在 `--`。`menubar.py` 還有一行 `self.tracker.sample(...)` 是 0.1.2 移除 `UsageRateTracker.sample()` 時漏掉的呼叫站，每次成功刷新都會丟 `AttributeError`、被外層 try/except 吞成錯誤狀態；這次拿掉了。`tracker.group()` 本來就會自己讀歷史 entries，不需要被餵 sample。

## 0.1.2 — 2026-05-17

### 變更
- `pricing.py`：pricing cache 從套件目錄搬到 `~/.claude/pricing_cache.json`，讓唯讀的 `.app` bundle 也能刷新快取。
- 全專案套用 `ruff format`（純格式化，沒動邏輯）。

### 移除
- `UsageRateTracker.sample()` 死碼（原本是空操作，從 `main._apply_outcome` 被呼叫）。

### Build
- `.gitignore` 新增排除 `*.egg-info/` 跟 `.pytest_cache/`。

## 0.1.1 — 2026-05-17

### 新增
- py2app `.app` bundle 打包設定（`setup_app.py`、`build_app.sh`），使用者不用開終端機就能跑 usag。
- GitHub Actions release workflow（`release.yml`）自動 build `usag.app.zip`，每次 tag release 都會自動掛上去。
- 英文版 README（`README.en.md`），兩份 README 頂部都加了語言切換。

## 0.1.0 — 2026-05-17

GitHub 首次公開 release。

### 新增
- `tests/` 底下的 pytest 測試套件，涵蓋 `pricing`、`history_loader`、`usage_rate`（44 個測試、89% 行覆蓋率）。
- CI 跑完 ruff 跟 mypy 之後會再跑 `pytest -v`。
- GitHub Actions CI 會在 push 到 main 或開 PR 時跑 `ruff check` 跟 `mypy`（macos-latest runner、uv 管依賴）。
- `USAG_DEBUG=1` 環境變數可開 warning level log，原本靜默的 OSError 站點會吐訊息。
- `.github/` 底下放了 issue templates（bug report、feature request）跟 PR template。

### 變更
- `menubar.py`：I/O 從 AppKit 主執行緒搬到背景（`threading.Thread` + `performSelectorOnMainThread_withObject_waitUntilDone_`），消掉每次刷新時 UI 會凍一下的問題。`_refresh_in_flight` flag 防止重入。
- `usage_rate.py`：`group()` 加 30 秒 TTL 快取；不會每次 TUI tick 都重掃過去一小時的 JSONL。
- `menubar.py`：provider 區塊之間的分隔線重新置中（first_y=178、second_y=352）。「今日」狀態列字級回到 12pt，跟 footer 其他行一致。
- README：改用 `python3` 而不是 `python`（uv venv 只裝了 `python3` symlink）；補了 `USAG_DEBUG` 的說明。

### 修正
- `setup_hook.py` 跟 `pricing.py` 改用 atomic write（`tempfile.mkstemp` + `os.replace`）；寫到一半 crash 不會再弄壞 `~/.claude/settings.json` 或 `pricing_cache.json`。
- `install-launchagent.sh` 改用 `BASH_SOURCE` 算出專案目錄；之前從非專案根目錄執行會壞掉。
- `uninstall-launchagent.sh` 改成清 `~/Library/Logs/usag/` 底下的 log（實際位置），不是專案目錄。
- `pricing_cache.json` 用 mtime 7 天過期，避免模型降價後還在用舊價。
- `pricing.py`、`codex_loader.py`、`history_loader.py` 裡 7 個原本靜默的 `except OSError` 站點，現在會先 log warning 再吞錯。

### 移除
- `blocks.py` — 未使用的死碼。
