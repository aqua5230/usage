# 變更紀錄 (Changelog)

繁體中文 · [English](CHANGELOG.en.md)

本檔記錄 usage 所有重要變更。格式參考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### 修正
- **切換面板時重新定位已開啟的 popover**：使用者在 popover 開啟狀態下切換 theme/panel 時，先關閉舊 popover、重建內容與尺寸後再重新顯示，避免視圖短暫縮排或尺寸錯亂。
- **Codex 專案用量與分析報告統一算法**：同一個 Codex session 出現在多個 JSONL 檔時，改選較新的 cumulative token entry；分析報告改共用 `codex_loader.load_entries()`，Project Usage 也納入 Codex session，避免同一份資料在 app 與 report 顯示不同數字。Project Usage 的 Today 現在與底部 Today 同樣使用本地日曆日，且底部 Today 不會在呼叫端已提供 Codex entries 時重複載入 Codex。

## [0.11.4] - 2026-05-25

### 新增
- **statusLine 顯示「可更新」提示**：menubar 跑 update check 後會把結果寫進 `~/.claude/usage-preferences.json` 的 `last_update_check`；statusLine 讀這個檔，發現有新版時在 model 行末顯示 `🆕 vX.Y.Z 可更新`（青色）。尊重「跳過此版本」設定，cache 超過 30 天視為過期不顯示。新增五語言翻譯 `update_available_suffix`（zh-TW「可更新」/ zh-CN「可更新」/ en「available」/ ja「更新あり」/ ko「업데이트」）。

### 變更
- **statusLine 對話窗格式調整**：「對話窗(1.0M):[bar]」改為「對話窗:[bar] 15% / 1.0M」—— 容量上限從中間括號移到尾巴跟百分比並排，讀起來更像「15% of 1M」。
- **statusLine fast mode 顯示反轉**：以前 on/off 都顯示標籤（`⚡快速` / `/nofast`），改為只有開啟才顯示 `⚡快速`，關閉不顯示 —— 像家裡的冷氣指示燈，亮燈即表示「在運作」。
- **statusLine 百分比跟進度條同色**：之前百分比都是灰白，現在跟進度條同色（黃 / 綠 / 紅）—— 一眼看數字就知道警示級別。
- **statusLine 「(剩 X 時間)」亮度提升**：之前用 ANSI dim 在深背景下太暗，現在拿掉 dim 用正常亮度，仍靠括號表達「補充資訊」。

## [0.11.3] - 2026-05-25

### 修正
- **CLI 讀取型命令會偷偷改使用者設定**：`usage daily` / `report` / `sessions` / `dashboard` 等只讀命令會無條件呼叫 `setup()` 或 `update_hook()`，每次跑都可能改到 `~/.claude/settings.json` 或 `~/.codex/config.toml`。修正後只有 `setup` / `unsetup` 才會寫使用者設定；其他命令在 hook 未安裝時改顯示一行提示「Hook 尚未安裝。請執行：usage setup」。
- **Opus 4.6 / 4.7 離線冷啟動成本估算低 3 倍**：`pricing.py` 的 fallback 表把 Opus 寫成 `5e-6 / 25e-6`（input / output per token），Anthropic 官方是 `15e-6 / 75e-6`。受影響條件：沒有 pricing cache 且 LiteLLM 線上 fetch 失敗的離線冷啟動；連線正常或已有 cache 的使用者不受影響。
- **`adapters/codex.py` sqlite connection 漏關**：`_load_thread_models()` 用 `try / except` 包，但 `conn.close()` 在 `execute().fetchall()` 之後，中間任何例外都會留下未釋放的連線。改用 `contextlib.closing()` 確保必定釋放。
- **`~/.codex/config.toml` 寫入中斷會留下 truncated TOML**：`setup_hook.py` 的 `_setup_codex` / `_unsetup_codex` 用 `write_text()` 直接覆寫，setup 過程被 crash / kill 會壞掉 Codex 設定檔。改成 `mkstemp + os.replace` atomic write，並與 Claude settings 共用同一個 module-private helper。

### 變更
- **`analyzer/cost.py` 退場**：原本是 `pricing.py` 的劣化複製品 —— 寬鬆雙向子字串模型比對會誤配、無 cache TTL、SSL 憑證錯誤時自動關閉驗證重抓（對成本資料是安全風險）。`analyzer/{aggregator,blocks,reporter}` 改用 `pricing.calculate_cost`；後者改接 `typing.Protocol`，同時支援 `history_loader.UsageEntry` 與 `adapters.types.UsageEntry`。整體淨減 76 行重複實作。

## [0.11.2] - 2026-05-25

### 修正
- **`usage_cli.py` 第一次執行必 crash**（感謝 @will30-blockchain 的 [#7](https://github.com/aqua5230/usage/pull/7)）：`setup(auto=True)` 傳了不存在的參數給 `setup_hook.setup()`，導致 fresh 安裝或 `unsetup` 後第一次跑 `usage_cli.py` 就噴 `TypeError`。已裝過 hook 的使用者不受影響。修正：拿掉多餘的 `auto=True`。

### 效能
- **JSONL 增量解析**：`history_loader` 與 `codex_loader` 新增 module-level mtime+size 快取，僅在檔案內容變動時重新解析，大幅減少每次 UI 刷新的磁碟 I/O。
- **Hook 並行轉發**：`usage_statusline_forwarder` 改用 `ThreadPoolExecutor` 同時執行所有 hook，單一 hook 逾時不再阻塞其他 hook，最壞情況從 `n × 5s` 降為 `5s`。
- **多 session 寫入保護**：`usage_statusline.py` 的 `save()` 加入 `fcntl.LOCK_EX` 檔案鎖，防止多個 Claude Code session 同時寫入時資料互蓋。
- **Python 路徑優先順序**：`setup_hook` 安裝 hook 時改用 `_find_system_python()`，優先選 `.app` 內建 Python，其次 `/usr/bin/python3`，避免 Xcode 更新後 `shutil.which("python3")` 指到壞掉的 stub。
- **FSEvents 事件驅動 UI 更新**：`menubar` 改用 CoreServices `FSEventStream`（ctypes）監聽 `~/.claude/`，`usage-status.json` 一有變動立即觸發 `_refresh()`，更新延遲從最多 60 秒降至毫秒；`NSTimer` 降為 300 秒 fallback，CoreServices 不可用時自動降級。

## [0.11.1] - 2026-05-24

### 修正
- **[P0] 已發佈 .app 在 macOS Sequoia / arm64 一開就閃退**（感謝 @cmhcm 的 [#6](https://github.com/aqua5230/usage/pull/6)）：v0.10.0 / v0.10.1 / v0.11.0 三個 release 都受影響。Root cause 是 `i18n.py` 在 py2app 打包後會被壓進 `lib/python313.zip`，但 `i18n.json` 是放在 `Contents/Resources/`；舊版用 `Path(__file__).with_name("i18n.json")` 拼路徑，會變成「穿過 zip 檔的無效路徑」，第一次讀就 `NotADirectoryError` 炸掉。修正：新增 `i18n.packaged_resource_path()` helper，優先讀 py2app 啟動時注入的 `RESOURCEPATH` 環境變數（指向 `Contents/Resources/`），找不到再退回原本的 source-mode 路徑。四個讀打包資源的 call site 全部換新（`i18n.py` / `tui.py` / `main.py` / `menubar.py`），原始碼模式跑法完全不受影響。

### 變更
- **打包設定補齊**：`pyproject.toml` 的 `py-modules` 補上之前漏掉的 `burn_rate` / `update_checker` / `tips_loader` / `usage_lang` / `usage_statusline_forwarder`，`packages.find` include 補上 `panels*`；非 editable 安裝才能拿到完整程式碼。
- **`.app` License metadata 對齊**：`setup_app.py` 的 `NSHumanReadableCopyright` 從舊的 `MIT License` 更新成 `Copyright © 2025-2026 lollapalooza. Licensed under AGPL-3.0-only.`，與 `pyproject.toml` 宣告一致。
- **`pricing_cache.json` 路徑統一**：`analyzer/cost.py` 的快取路徑從專案根目錄改為 `~/.claude/pricing_cache.json`，與 `pricing.py` 同步；移除 repo 根目錄一顆 1.1 MB 的孤兒快取檔。
- **面板名稱走 i18n**：`panels/__init__.py` 九款面板的顯示名稱改用 `i18n_key`，i18n.json 五語言補齊；英 / 日 / 韓系統的「更換面板」選單不再混入中文面板名。
- **狀態檔錯誤訊息走 i18n**：`usage_client.py` 的「找不到狀態檔」和「狀態檔尚無配額」兩段提示走 `_t()`，五語言齊全。
- **analytics CLI 讀檔順序對齊主程式**：`adapters/rate_limits.py` 之前只讀 `~/.claude/tt-status.json`，現在改成 `usage-status.json` → `usag-status.json` → `tt-status.json` 三路 fallback，與 `usage_client.py` 一致。
- **README 補 v0.11.0 更新檢查說明 + GitHub Releases 網路例外**：README.md / README.en.md 都加上「更新檢查」段落、把 GitHub Releases API 明列為第二個網路例外（第一個仍是 LiteLLM 價格表）。

## [0.11.0] - 2026-05-24

### 新增
- **App 內檢查更新（Stage 1）**：開 app 時自動到 GitHub Releases 查最新版（24 小時最多檢查一次，避免每次開都被打擾）；發現新版會跳出視窗顯示版本號＋ release notes，三顆按鈕「前往下載 / 稍後再說 / 跳過此版本」。「前往下載」會用預設瀏覽器打開 Release 頁，你手動下載新版蓋掉舊版即可（Stage 2 才會做 Sparkle 全自動下載＋替換）。
- **「更換面板」選單新增兩條**：
  - **自動檢查更新**（可勾選）：取消勾選後完全關閉啟動時的自動檢查，只保留手動入口。
  - **立刻檢查更新**：手動觸發一次檢查，忽略 24h cooldown 與「跳過此版本」設定；沒新版也會跳視窗告知「已是最新版本」，網路錯誤時跳「檢查更新失敗」。
- 偏好設定沿用既有 `~/.claude/usage-preferences.json`，新增三個 key：`auto_update_check`（預設 true）、`update_dismissed_at`（Unix 時間戳）、`update_skipped_version`（被跳過的版本號）。

### 變更
- `setup_app.py` 把 `pyproject.toml` 與 `update_checker` 一併納入 py2app 打包——讓 .app 版在 `importlib.metadata` 抓不到版本時可 fallback 讀 `pyproject.toml`。

## [0.10.1] - 2026-05-24

### 修正
- **Weekly burn-rate 警告誤報**：對 7 天 weekly quota 套用最近 10 分鐘的燒率外推會過度激進（例：56% 已用 → 預測 5h50m 用完 → 顯示「剩 5h50m 用完(重置還要 4d6h)」），實際使用者不會 24/7 維持那速度。修正方式：`_quota_row` 新增 `warning_max_seconds` 參數，weekly 三處呼叫傳入 24h 上限——預測用完時間超過 24 小時就不再警告。session 警告行為完全不變。

## [0.10.0] - 2026-05-24

### 新增
- **HTML 報告「分享」按鈕**：報告右上角新增分享按鈕，點開後可選「另存一份 .html」或「複製檔案路徑」，把報告透過 AirDrop / Mail / Slack / 訊息傳給同事或主管；對方用瀏覽器打開即可閱讀，手機電腦皆支援。
- **下載時可隱藏專案名稱**：分享 modal 內含「隱藏專案名稱」勾選框（預設打勾，隱私優先），勾選後另存的 HTML 會把所有專案名稱替換成 `Project 1 / Project 2 / ...`，不影響當前螢幕顯示。
- **HTML 報告 sponsor 區重做**：兩個 Ko-fi 徽章夾住品牌標語 `No cloud. No tracking. Just yours.`（五語言統一不翻譯），標語帶輕微晃動動畫吸引目光；下方新增 GitHub repo 連結（github.com/aqua5230/usage）。

### 變更
- **statusLine 第二行（累計問答 / 快取 / 花費）移除**：簡化視覺，主要監控資訊集中在第一行（5h / 7d / Context window）與第三行（會話時長、模型）。
- **HTML 報告 KPI 卡片寬度調整**：tokens / cost 兩張較寬，sessions / messages / active days 三張較窄（grid 比例 1.5fr 1.4fr 1fr 1fr 1fr），避免 9 位數 token 數字換行。

### 移除
- HTML 報告底部 `usage · 本機分析 · 資料不離本機` footer 行 —— 由 sponsor 區的 GitHub 連結取代。

## [0.9.1] - 2026-05-23

### 修正
- **TUI 模式輪詢失效**：`poll_usage` 函式內 `continue` 導致每次 timeout 後直接跳回迴圈頂端，狀態永遠停在初始那次 fetch，之後不再更新。改為 `pass` 使輪詢邏輯正常執行。
- **環境變數名稱不一致**：`USAG_FORCE_GROUP`（v0.1.x 舊前綴）改為 `USAGE_FORCE_GROUP`，與專案其他環境變數統一命名。
- **每次 refresh 重複掃 filesystem**：`_refresh_in_background` 原本對 `history_loader.load_entries` 呼叫 4 次（24h × 2、168h × 1、720h × 1），現改為一次性讀取 720h 超集並向下傳遞，省去重複 I/O。

### 變更
- `pricing.py` User-Agent 從過期的 `usage/0.2` 更新為 `usage/0.9`。
- `--setup` 執行時不再多印「無需 migration」訊息（全新安裝環境下的無意義輸出）。

## [0.9.0] - 2026-05-22

### 新增
- **新增「世界盃 2026」面板**：FIFA 電視轉播 HUD 風格。鮮綠球場俯視圖（草皮條紋＋白色場線、中圈、禁區、角弧），深色廣播記分板顯示 Claude / Codex Session 大號數字（38px），雙向對戰條（Claude←中線→Codex）取代傳統單向進度條，Canvas 動畫：一顆五邊形足球在下半區滾動，兩隊各 6 個棒人球員緩慢跑位，距球最近的球員以 0.8 px/frame 追球並踢球改變方向（各隊冷卻 60 frames），底部 MATCH STATS 積分榜，用量 ≥ 85% 時觸發黃金進球彩蛋。

## [0.8.0] - 2026-05-22

### 新增
- **新增「稜鏡街機」面板**：深紫黑底，Canvas conic 彩虹光暈緩慢旋轉，幾何稜鏡碎片（三角形/菱形）隨機漂移，彩色光點粒子閃爍，卡片採全息漸層邊框（CSS background-clip 技巧），進度條全光譜 rainbow gradient + 掃光。
- **新增「黑洞視界」面板**：純黑宇宙背景，Canvas 2D 繪製星場（120 顆含閃爍星）、旋轉吸積盤（橙黃白漸層橢圓，都卜勒左亮右暗）、光子環、事件視界藍紫光暈，橙色粒子沿橢圓軌道流動，琥珀色玻璃卡片。

### 修正
- **修正三個面板底部多餘空隙**：水族箱、稜鏡街機、黑洞視界的 `.projects-card` 補上 `flex: 1`，內容現在正確撐滿面板高度。
- **三個動畫面板卡片透明度調低**：水族箱、稜鏡街機、黑洞視界卡片 background opacity 從 0.5–0.75 降至 0.14–0.28，背景動畫透出更多。

## [0.7.0] - 2026-05-22

### 新增
- **新增「午夜水族箱」面板**：第六款內建面板，深海動畫主題 —— Canvas 2D 氣泡上升（42 顆，隨機漂移）、4 隻 CSS 水母（上下浮動＋青色發光）、生物發光粒子點綴背景。玻璃感卡片搭配 backdrop-filter blur，進度條帶掃光動效。新增 i18n key `panel_aquarium`（5 語齊全）。
- **修正 .app 語言偵測**：改用 `NSLocale.preferredLanguages()` 取代 `currentLocale().localeIdentifier()`，讓 bundle 內語言不再被 `CFBundleDevelopmentRegion = English` 覆寫，繁中使用者點 .app 後正確顯示中文。

## [0.6.9] - 2026-05-22

### 新增
- **新增「雲圖觀測」面板**：第五款內建面板，氣象風視覺 —— 淡藍天空漸層、白色雲層（feGaussianBlur 柔邊）、淡藍等高線、半透明玻璃卡片。整體淺色調，搭配 backdrop-filter 讓雲透出。新增 i18n key `panel_cloud_observation`（5 語齊全）。

## [0.6.8] - 2026-05-22

### 修正
- **修正 .app 啟動時找不到 i18n.json**：py2app 打包資源清單補上 `i18n.json`，menu bar 與 Web panel 載入多語系檔案時會優先讀取 `.app` bundle 的 `Contents/Resources/i18n.json`，再 fallback 到原始碼路徑，避免 v0.6.0 以上版本啟動即發生 `FileNotFoundError`。

## [0.6.7] - 2026-05-22

### 修正
- **燃燒速度警告誤判**：v0.6.6 上線後實測發現,在 app 剛重啟、樣本還不夠的情況下,即使百分比只用了 1% / 14% / 36% 也會跳紅色警告。原因是 2 點斜率只用 2-3 個樣本太不穩,而且低百分比時剩餘緩衝大、根本沒有緊迫性。修正方式加兩道安全閥:預估只在「最近 10 分鐘內樣本 ≥ 5 個、跨度 ≥ 5 分鐘」時才生效;警告只在「當下百分比 ≥ 50%」時才替換 reset 文案。其他情況一律維持原本的「重置 X」顯示。

## [0.6.6] - 2026-05-22

### 新增
- **燃燒速度警告**：當 app 預估你照目前用法會在額度重置前先用完時，原本「重置 X 分鐘」那行會自動換成紅色警告：「⚠ 剩 X 分用完（重置還要 Y 分）」。沒事的時候面板長得跟原本一樣，完全不打擾。覆蓋 Claude Code Session / Weekly 與 Codex Session / Weekly 共 4 個額度，4 款面板（Classic / Matrix / Newspaper / Win95）各自配對應主題的紅色。內部用 15 分鐘滾動樣本 + 最近 10 分鐘斜率推估，重置時自動清掉舊樣本避免誤報。

## [0.6.5] - 2026-05-22

### 新增
- **「開機自動啟動」開關**：popover 的「更換面板」選單新增一條可勾選的「開機自動啟動」項目，勾選後 usage 會在你下次登入時自動啟動，不必每次手動開。.app 版與原始碼版會各自產生對應的 LaunchAgent 設定檔；取消勾選只移除設定檔，不會關掉正在執行的 app。

### 變更
- README「開機自動啟動」章節補上 popover 開關說明（繁中 / 英文）。

## [0.6.4] - 2026-05-22

### 新增
- **「復古報紙」面板**：第四款內建面板，重現舊報紙頭版風格 —— 米黃報紙底、明體油墨字、雙線版心框、報紙欄頭式標題、細墨線分隔、暖墨實心進度條。卡片排版與資料邏輯沿用 Classic，差異只在 CSS 樣式。

### 修正
- **繁體中文系統被誤判為簡體中文**：`_detect_language()` 原本讀 `NSLocale.languageCode`，它只回傳不帶地區的 `"zh"`，繁中系統因此被正規化成簡體。改讀保留地區資訊的 `localeIdentifier`（如 `zh_TW`），繁中系統現在正確顯示繁體中文。

### 變更
- README 面板章節更新為四款面板並列截圖（繁中 / 英文）。

## [0.6.3] - 2026-05-22

### 新增
- **「視窗 95」面板**：第三款內建面板，重現 Windows 95 經典桌面介面 —— teal 桌布、寶藍漸層標題列、灰色 3D outset 視窗、chunked 分格進度條、凸起塑膠按鈕、Tahoma 字體。
- **面板可指定專屬視窗尺寸**：`HTMLPanel` 新增 `width` / `height` 參數，每款面板能依內容量使用合身的 popover 尺寸（預設仍為 364×812）。視窗 95 內容較精簡，使用 364×768。

### 變更
- README 面板章節更新為三款面板並列截圖（繁中 / 英文）。

## [0.6.2] - 2026-05-22

### 修正
- **駭客任務面板「專案用量」資料夾圖示消失**：三張卡片 inline `style="--accent: var(--accent)"` 是自我參考的 cyclic CSS variable，依 CSS 規範會被判 invalid 並 unset，導致 inline SVG 的 `stroke="var(--accent)"` 取不到顏色變透明。Claude / Codex 卡用 `<img>` 不受影響，但 projects 卡的 SVG 資料夾圖示因此失蹤。`--accent` 已在 `:root` 定義並會 inherit，三個 cyclic inline style 是無意義的覆寫，移除後圖示正常顯示。

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
