# 變更紀錄 (Changelog)

繁體中文 · [English](CHANGELOG.en.md)

本檔記錄 usage 所有重要變更。格式參考 [Keep a Changelog](https://keepachangelog.com/)。

## [0.6.1] - 2026-05-22

### 新增
- **駭客任務（Matrix）面板**：黑底螢光綠字 + 數位雨動畫的第二款面板。卡片標題、配額條、專案排行、footer 全部沿用 Classic 排版，差異只在配色與背景。透過 popover 上的「⇄ 更換面板」按鈕切換。
- README 補上 Matrix 面板截圖（繁中 / 英文），同時對照 Classic 面板。

### 修正
- Matrix 面板標題 `line-height: 1` 在 CJK 字符（如「專案用量」「専案使用量」）下方筆畫與 `text-shadow` 光暈會被卡片邊界裁切；改為 `1.25` 後 5 種語系標題完整顯示，與 30×30 圖示維持垂直對齊。

## [0.6.0] - 2026-05-22

### 新增
- **多語言介面（i18n）**：自動偵測 macOS 系統語言，支援繁體中文、簡體中文、英文、日文、韓文。不需任何設定，系統語言是什麼就顯示什麼。
- **`USAGE_LANG` 環境變數**：可強制指定語言（例如 `USAGE_LANG=ja`），方便開發與測試。

### 變更
- **授權從 MIT 改為 AGPL-3.0**：修改後發佈的版本必須開源，保護原作者權益。
- **popover 底部加入 attribution 小字**：`based on usage by lollapalooza`。

### 修正
- 移除 `usage_client.py` 中硬寫的中文狀態字串（「✓ 已同步」），改由 i18n 系統統一處理。

## [0.5.0] - 2026-05-21

### 新增
- **專案用量新增「月」切換**：「今日 / 7 日 / 月」三段循環，可查看近 30 天各專案的 token 用量與費用。

### 修正
- **專案用量費用正確計算**：之前因為 Claude Code 的 JSONL 沒有寫入 `costUSD` 欄位，所有專案顯示 $0.00；現在改用與「今日費用」相同的 `calculate_cost()` 計算，數字一致。
- **備援定價 Opus 修正為 $5/M**：離線時備援的 Opus 單價從 $15/M 修正為 $5/M，與 LiteLLM 實際值一致。

### 改善
- 專案用量的 SVG 圖示尺寸調整為與 Claude Code / Codex 圖示一致（30×30）。

### 移除
- 移除 Taiwan、Matrix、ECG、Minimal、Sketch 五個 PyObjC 原生面板，統一改為 HTML/CSS 架構，新面板設計中。
- 移除 Antigravity 用量追蹤（Google OAuth 憑證不應寫入原始碼；功能待架構調整後重新設計）

## [0.4.0] - 2026-05-20

### 新增
- **預設面板改為 WKWebView + HTML/CSS render**：classic 預設面板改由共用 HTML/CSS 層繪製，為後續 Windows 版本鋪路；macOS 仍透過 `NSPopover` 內嵌 `WKWebView` 呈現。
- **Antigravity 額度追蹤**：popover 現在顯示 Claude Code / Codex / Antigravity 三張卡；Antigravity 卡含目前用量（Session）與每週上限（Weekly）兩排。
- Antigravity 桶 `remainingFraction == 1.0`（未使用）時隱藏重置時間，避免 API 滾動 placeholder 顯示成永遠的「重置 ~24h」。

### 變更
- `antigravity_loader` 依重置視窗自動分流：短窗歸為 Session，長窗歸為 Weekly；Google API 補上週 bucket 時 Weekly 會自動填值。
- WKWebView 整合加入 JS bridge（refresh / quit / switch）、預先載入與深色 layer，減少開啟時白閃；切換面板時會 teardown 以解除 retain cycle。
- 面板按鈕加入點擊壓深 + 微縮反饋。
- 新增依賴：`pyobjc-framework-WebKit`、`pyobjc-framework-Quartz`。

### 移除
- 移除 `panels/classic.py` CoreGraphics 版本，改由 `HTMLPanel` 取代。

### 內部
- `codex_loader` / `history_loader._as_int` 型別精確化為 `max(0, int(value))`。
- 改用 Quartz `CGColorCreateGenericRGB` 建立 `CGColorRef`，消除啟動時的 `ObjCPointerWarning`。

## 0.3.3 — 2026-05-19

### 新增
- **Minimal 面板**：深色簡約風格，Linear / Raycast 設計語言。近黑底色（`#0A0A0C`）、圓角卡片、accent 色進度條（Claude 暖橘 / Codex 青色）。每張卡各有 Session（大字 26pt）與 Weekly（24pt）兩列，各自含標籤、百分比數字、2px 進度條、重置倒數；頁尾卡片以左標籤（muted）+ 右數值（bright）雙欄呈現速率、狀態、今日花費，列間加分隔線。三顆按鈕（立即更新 / 結束 / 切換面板）沿用 accent 漸層 + 半透明邊框設計。

## 0.3.2 — 2026-05-19

### 新增
- **ECG 心電圖面板**：醫療監視器風格面板。`ECGView` 以 `NSTimer`（80ms）驅動雙通道 ECG 波形動畫，LEAD A 對應 Claude Code、LEAD B 對應 Codex；波形振幅隨 quota 使用率縮放，速率（burn rate）越高波形節奏越激烈。文字標籤與波形區域垂直分區，互不重疊。

## 0.3.1 — 2026-05-19

### 新增
- **駭客任務面板（MatrixPanel）**：黑底綠字的 Matrix 數位雨動畫面板。`MatrixRainView` 以 `NSTimer`（80ms）驅動，每幀在每列畫一個頭字元（全亮）＋ 10 格漸暗拖尾，字元池為片假名 + 數字。卡片區改為半透明深綠底 + 綠色邊框，所有按鈕與標題改為終端機方括號風格（`[ SWITCH ]`、`[ REFRESH ]`、`[ EXIT ]`）；rate/status/today 標籤改為大寫英文前綴。

## 0.3.0 — 2026-05-19

### 新增
- **面板切換系統**：popover 右上角新增「⇄ 更換面板」按鈕，點下去出現 NSMenu 列出所有已註冊面板；選擇後立即套用最新狀態並透過 `NSUserDefaults`（key `usage.activePanelId`）持久化，下次啟動記得上次選的面板。
- **預設面板（ClassicPanel）**：保留原有兩張卡 + 速率/狀態/今日佈局，切換按鈕嵌入 Claude 卡右上角，新增 `ClassicSwitchButton` 在 light/dark 兩種外觀下都清晰可見。
- **台灣用量監控面板（TaiwanPanel）**：紅底白字主題（純 20 行 `ThemeConfig`），頂部標題列含 TAIWAN 旗 icon、「台灣用量監控」標題、切換按鈕，整體 popover 高度 574 → 672。
- 新增 `panels/` 模組：`base.py` 提供 `Panel` Protocol、`ThemeConfig` dataclass、`ThemedPanel` 通用實作與 `NSUserDefaults` helper；`classic.py` / `taiwan.py` 為具體面板；`__init__.py` 提供 panel registry（`get_panel(id)`、`all_panels()`、找不到 id 自動 fallback 到 classic）。
- 新增 `assets/taiwan.png`，並在 `setup_app.py` 的 `resources` 清單登錄，確保 `.app` bundle 內含此資源。

### 重構
- `menubar.py` 大幅縮減（1041 → 524 行）：所有 popover 視圖繪製與排版邏輯抽到 `panels/` 模組；`PopoverViewController` 改為輕量 container，依目前選的 `Panel` 動態 rebuild view；`AppDelegate` 新增 `switchPanel:` / `selectPanel:` 與 `_set_active_panel_id` 處理面板切換流程。

### 測試
- 新增 `tests/test_panels.py`（11 個 case）覆蓋：panel registry 內容、各面板 `preferred_size`、`NSUserDefaults` round-trip、找不到 id 的 fallback、`ThemeConfig` 套用、`ThemedPanel` 有無 header 的高度差。

## 0.2.1 — 2026-05-18

### 修正
- `scripts/install-hook.sh`：產生 statusLine command 時改用 `shlex.quote()` 包裹路徑，與 `setup_hook.py` 對齊，避免使用者 Python 路徑或 hook 路徑含空白時 hook 安裝失效。
- `pricing.py`：`_pricing_cache` 改記錄 source（cache / fetched / fallback）與時間，fallback 結果改成 10 分鐘短 TTL，避免離線啟動後即使網路恢復成本估算也永久卡在舊 fallback。
- `menubar.py` / `codex_loader.py`：silent except 改成 `USAGE_DEBUG=1` 時印 `logger.warning(exc_info=True)`，未設定時保持靜默；除錯時不會再看似「沒安裝 Codex」實際是解析失敗。

### 文件
- `README.md` / `README.en.md`：在價格表說明段補一句「首次啟動沒快取會同步抓一次，網路慢時可能等 ~10 秒」，避免新使用者以為當機。

### 測試
- 新增 `tests/test_main.py`（9 個）覆蓋 `parse_args` 與 `_apply_outcome` 行為。
- 新增 `tests/test_menubar.py`（14 個）覆蓋純函式：`format_human_time`、`_format_percent`、`_bar_color`、`_quota_row`、`_missing_row`、`_today_title(mock=True)`、`_empty_state`、`_error_state`、`_popover_size`。
- 新增 `tests/test_pricing.py` 4 個 case 覆蓋 fallback TTL、retry 後 fetched、fetched / cache 不重抓。
- 全測試從 63 → 90 passed。

## 0.2.0 — 2026-05-18

### 破壞性變更
- app 內部識別從 `usag` 改成 `usage`：bundle id、檔名、launchctl label、`~/.claude/` 路徑全數改名。

### 新增
- `setup_hook.py` 自動偵測並清除舊 v0.1.x `usag` 殘留：hook 腳本、settings 內 statusLine、備份 key 與 status 檔。
- `install-launchagent.sh` / `uninstall-launchagent.sh` 會自動清掉舊 LaunchAgent plist 與 label。
- `usage_client.py` 讀檔加入舊 `usag-status.json` fallback，提供升級過渡相容。

### 修正
- app 對外名稱與內部 bundle 識別統一為 `usage`。

## 0.1.11 — 2026-05-18

### 修正
- `setup_app.py` 補打包 `usag_statusline.py`，確保 `.app` 內有 hook 原始檔。
- `setup_hook.py` 在原始碼模式與 `.app` bundle 模式都能解析 hook 來源路徑。

### 介面
- popover 偵測到找不到狀態檔時新增「立即安裝 hook」一鍵救援按鈕。

## 0.1.10 — 2026-05-18

### 介面
- 進度條顏色依用量動態切換：< 50% 維持品牌色、50–80% 轉琥珀黃、≥ 80% 轉警告紅。

### 修正
- `codex_loader.py`：Codex 用量改用最後一次 token 事件時間做 `hours_back` 過濾；逐檔容錯排序，壞檔不拖垮整批讀取。
- `history_loader.py`：缺 id 時改用複合 key 去重；排除 bool 與負數 token 值。
- `usage_client.py`：`rate_limits` 子欄位非 dict 時補防衛。
- `setup_hook.py`：寫入前驗證 settings 格式；備份欄位非 dict 時安全重建。

### 文件
- README 修正三處事實錯誤：網路聲明、Codex 資料來源描述、今日成本為估算值。
- README 加入「快速開始」表格、「下載現成 App」段落、「常見問題排查」表格。

## 0.1.9 — 2026-05-18

### 介面
- 進度條顏色依用量動態切換：< 50% 維持品牌色（Claude 橘 / Codex 青）、50–80% 轉琥珀黃、≥ 80% 轉警告紅。

### 修正
- 狀態列「已同步」來源標籤從 `usag-status` 改成 `usage`，跟對外名稱一致。
- `setup_hook.py`：用 `shlex.quote()` 包 interpreter 與 hook 路徑，修復專案目錄含空格時 hook 永遠不跑的問題（PR #1，感謝 @DennisWei9898）。
- `usag_statusline.py`：把 `datetime.UTC`（Python 3.11+ 限定）改成 `timezone.utc`，相容 macOS 系統 Python 3.9（PR #1，感謝 @DennisWei9898）。
- `codex_loader.py`：Codex 用量改用最後一次 token 事件的時間做 `hours_back` 過濾，長 session 的近期 token 不再被誤排除；逐檔容錯排序，壞檔不拖垮整批讀取。
- `history_loader.py`：缺 `message_id` / `request_id` 時改用複合 key 去重，降低誤刪有效紀錄的機率；token 解析排除 bool 與負數。
- `usage_client.py`：`rate_limits` 及子欄位非 dict 時補防衛，避免 `.get()` 出錯。
- `setup_hook.py`：寫入前先驗證 `settings.json` 格式；備份 statusLine 的欄位非 dict 時安全重建。

### 文件
- README 把「打 API」「打網路 API」等大陸慣用語改成「呼叫 API」「連網路」。

## 0.1.8 — 2026-05-18

### 介面
- popover 重新設計：
  - Claude Code / Codex 卡片左上加上品牌 icon（`claude.webp` / `codex.webp`）。
  - 卡片底色與進度條改為漸層填色（`NSGradient`），accent 配色調亮（Claude 偏暖橘、Codex 偏青）。
  - 「立即更新」與「結束」按鈕改為自繪的 `ActionButton`，分主／次樣式（主按鈕走 accent 漸層、次按鈕走半透明邊框）。
  - 速率 / 狀態 / 今日花費收進獨立的第三張卡片，與上方兩張視覺一致。
  - 各 spacing、字重、字距與 muted 顏色重新校正一輪，提高深色 / 淺色模式下的對比度。

### 打包
- `setup_app.py` 把 `claude.webp` / `codex.webp` 加入 py2app `resources`，確保 `.app` bundle 帶得上 icon。
- `menubar.py` 改用 `NSBundle.mainBundle().pathForResource_ofType_` 解析 icon 路徑，dev 模式（launchagent 直接跑 `main.py`）與 `.app` bundle 兩種佈署都找得到資源檔。

## 0.1.7 — 2026-05-18

### 文件
- README 加上 5 顆 badge（CI 狀態、最新 release、Python 版本、平台、license）。
- README 「資料來源」段加上一張 mermaid 流程圖，把「Claude Code → hook → JSON 檔 → usage」這條鏈視覺化，並明確標出 `Anthropic API` 是**不會被呼叫**的（虛線斷開）。
- 新增 `CONTRIBUTING.md` / `CONTRIBUTING.en.md`（雙語）：寫清楚 issue / PR 要附什麼、merge 前必跑哪三項檢查、改 code 不能動的技術短名 / UI 常數、CHANGELOG 雙語規矩、commit message 風格。

### 測試
- 新增三個測試檔，蓋住三個高風險「I/O / parse 邊界」模組（這幾個模組原本零測試，是 0.1.2 → 0.1.3 那種「改一處漏一處」最容易爆的地方）：
  - `tests/test_usage_client.py`：`_read_status_file` 兩條路徑都不存在 / USAG_STATUS 壞 JSON / fallback；`_build_snapshot` 缺欄位 / 百分比超界 clamp；`ClaudeUsageClient` mock 跟 real mode 的 outcome。
  - `tests/test_codex_loader.py`：`load_entries` sessions dir 不存在 / valid JSONL / hours_back cutoff filter / 壞 JSON line / 缺欄位 / `_parse_timestamp` 三種 ISO 8601 變體；`load_rate_limits` 沒檔案回 None / 有檔案讀出 5h + weekly 兩段。
  - `tests/test_setup_hook.py`：`setup` 全新環境 / 已有自訂 statusLine 備份 / 重複 idempotent；`unsetup` 還原備份 / 沒裝過時的行為；`_is_usag_hook` 判斷邏輯。
- 測試全程用 `monkeypatch` 注入路徑常數，**沒碰真實 `~/.claude` 或 `~/.codex`**（有對 mtime 做 before/after 比對驗證）。
- 測試總數從 44 → 60，執行時間 0.04s → 0.08s。

## 0.1.6 — 2026-05-18

### 變更
- 對外名稱統一從 `usag` 改成 `usage`，跟 GitHub repo 名稱對齊：
  - `pyproject.toml` 的 `name` 從 `"usag"` 改成 `"usage"`（PyPI / `pip list` 看到的就是 `usage`）。
  - `README.md` / `README.en.md` 標題與 prose 都改成 `usage`。
  - `.github/ISSUE_TEMPLATE/bug_report.md` 內提到的 commit 命令也對齊。
- **不變的部分**（避免打到已安裝的使用者）：所有檔案路徑、設定 key 跟 binary 名稱仍保留 `usag` 前綴 —— `~/.claude/usag-status.json`、`~/.claude/usag-statusline.py`、`~/Library/Logs/usag/`、`com.lollapalooza.usag` (LaunchAgent label)、`usag.app` (bundle)、`USAG_DEBUG` (env var)、`settings.usag.previousStatusLine` (JSON key) 完全沒動。技術 contract 短名是 `usag`，對外名稱是 `usage`。

## 0.1.5 — 2026-05-18

### CI
- `actions/setup-python` 從 v5 升到 v6（v6 用 Node.js 24）。GitHub 之前的警告：v5 跑在 Node.js 20，2026-09-16 之後 runner 會強制升 Node 24。先升避免之後 release 流程突然壞掉。

### 文件
- `pyproject.toml` 的 `description` 從「在 macOS 終端機顯示 Claude Code 用量的繁中小工具」改成「usage — 在 macOS menu bar 顯示 Claude Code 用量的繁中小工具（也提供終端機 TUI）」。原描述只提終端機，跟現在 menu bar 主導的事實不符，也順手讓 PyPI / GitHub 上看到的專案名稱跟 repo 對齊。

## 0.1.4 — 2026-05-18

### CI
- Release workflow（`.github/workflows/release.yml`）改成 self-heal：tag 推上去之後，如果對應的 GitHub release 還沒建立，會先用 `gh release create` 補建（空 notes、target 指向 tag 對應的 ref），再上傳 `usag.app.zip`。0.1.3 發版時遇到的「workflow 假設 release 已存在所以上傳失敗」不會再發生。

### Build
- `menubar.py` 的 mypy 設定從整檔 `# mypy: ignore-errors` 收緊成 `disable-error-code="import-untyped,misc"`，只放過 PyObjC 缺 stub 跟動態基底類別這兩類錯。其餘型別錯誤現在會被 mypy 抓到（之前 `tracker.sample` AttributeError 類的事，這層本來就該擋下）。

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
