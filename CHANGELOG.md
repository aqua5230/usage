# 變更紀錄 (Changelog)

繁體中文 · [English](CHANGELOG.en.md)

本檔記錄 usage 所有重要變更。格式參考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### 變更
- **Homebrew 安裝改用 cask 發佈**：usage 是圖形介面 App，改以 Homebrew 的 cask（給 GUI 應用程式用的格式）發佈後，會直接把 `usage.app` 放進「應用程式」資料夾，不再經過 formula 的重定位／重簽章流程——這也徹底根治了 `usage.app/usage.app` 雙路徑造成的 `Errno::ENOENT` 安裝失敗。安裝指令改為 `brew install --cask aqua5230/usage/usage`；之前用 formula 裝過的人請先 `brew uninstall usage` 再重裝。（感謝 @anatolii-maslennikov-improvado 回報 #34）

## [0.16.1] - 2026-06-07

### 修正
- **用 Homebrew 安裝不再失敗**：`brew install` 時因為壓縮檔頂層只有單一 `usage.app` 目錄，Homebrew 會自動切進該目錄而找不到要安裝的檔案，跳出 `Errno::ENOENT ... usage.app`。已修正 formula 的安裝路徑，重新安裝即可。（感謝 @teddy123434 回報 #32）
- **從 .app 安裝狀態列 hook 後，Claude Code 啟動不再報錯**：從打包的 .app 安裝時，原本會把 app 內建、離開 app 就無法獨立執行的 Python 寫進 hook 設定，導致 Claude Code 啟動時跳 `Could not find platform independent libraries`、狀態列無法顯示。現在一律改用系統的 `/usr/bin/python3`；先前已經被寫壞的設定，下次啟動或重跑安裝時會自動修正回來。（感謝 @teddy123434 回報 #32）

## [0.16.0] - 2026-06-07

### 新增
- **進度管家交接時會帶出上次未提交的改動**：開新對話時自動交接的「上次做到哪」，現在也會列出上個 session 還沒提交（commit）的檔案改動，不用自己回想。
- **燃燒率預測改用 EMA（指數移動平均）平滑**：「再過多久用完」的預估，從只看頭尾兩點的斜率改為對近期用量加權平均，對突然加速更靈敏、對單點雜訊更穩，預估更貼近當下節奏。

### 修正
- **打包後的 .app 從非終端機啟動不再閃退**：雙擊 .app 或在背景啟動時，會在開啟面板或請求通知權限的瞬間崩潰（`Argument 3 is a block, but no signature available`）。根因是 py2app 只帶了 WebKit／UserNotifications 的裸模組、漏了完整的 wrapper metadata。現在無條件註冊所需的 block 簽名，並讓打包帶齊 wrapper。
- **配額暫時沒資料時不再誤報「額度用完」**：某個額度視窗暫時沒有讀數（例如 Codex 的 5 小時視窗過期）時，原本會被當成「用完」而跳通知，並顯示殘缺的「重置 -- 後恢復」。現在只有真的達 100% 才視為用完。
- **某語系字串格式有誤時不再讓畫面崩潰**：翻譯字串的佔位符若對不上呼叫端的參數，原本會讓該段 UI 崩掉；現在會自動退回英文、再退回原始鍵，不波及其他畫面。

### 變更
- **精簡燃燒率警告文字**：移除警告紅字後面「（比均速快 N 倍／省）」的後綴——它讓整行超出面板寬度。警告現在只顯示「多久用完＋重置倒數」。

### 文件
- **開源準備：新增安全政策與授權標頭**：新增雙語 `SECURITY.md`（漏洞請走私下 email 回報，不走公開 Issue）、為所有 Python 檔加上 AGPL-3.0-only 授權標頭、`LICENSE` 版權行標明維護者的 GitHub 帳號。

## [0.15.14] - 2026-06-07

### 修正
- **進入新資料夾時 Claude Code 配額不再短暫掉成「--」**：開新對話（新 session）後第一次刷新狀態列時，Claude Code 推來的資料可能還沒包含配額；狀態列 hook 原本會把這份不完整資料整包覆寫，洗掉先前有效的配額，畫面就短暫顯示「--」與「請發送一句訊息以同步配額」，直到再發一句訊息才復原。現在寫入前若新資料的配額不完整，會沿用既有的完整配額，不再被洗白。

## [0.15.13] - 2026-06-06

### 修正
- **成本估算在價格更新後會正確重算**：先前用 fallback 價格算過的成本會被寫回並快取在用量項目上，等真實價格抓回來也不再重算，導致成本數字長期偏離（主要影響來源未附成本的項目，例如 Codex）。現在估算不再寫回項目，價格更新後會即時反映。
- **網頁面板注入持續失敗時不再無限重載**：狀態注入若反覆失敗，面板原本會一直 reload 形成循環；現在同一份資料的重載設上限，超過即停手（WebContent 程序真正崩潰時的自動復原不受影響）。

## [0.15.12] - 2026-06-06

### 修正
- **修正 Codex SQLite 連線在讀取後未關閉造成的檔案描述子洩漏（#30）**：讀取 Codex 的 `logs_2.sqlite`／`state_5.sqlite` 時，連線只結束交易卻未真正關閉，長時間執行會累積開啟的檔案描述子。現在每次讀取後都確實關閉連線。
- **Codex 配額刷新改在 history 掃描前套用（#31）**：背景刷新時，Codex 配額結果現在會先同步套用到主畫面，再進行專案 history 掃描，避免畫面短暫顯示舊配額。

## [0.15.11] - 2026-06-06

### 修正
- **網頁面板在背景渲染程序崩潰後會自動復原（#29）**：WKWebView 的網頁內容程序有時會被系統單獨中止，而 app 本體仍在執行，面板就只剩空白／灰窗，得重啟整個 app 才會回來。現在偵測到內容程序中止會自動重載面板，並把上一次的資料重新套用回去復原；JavaScript 狀態注入失敗時也會重載重試。

## [0.15.10] - 2026-06-05

### 新增
- **報告新增「洞察」區塊**：在用量卡片下方，用本機規則自動點出幾條「卡片看不出來」的重點——本期 vs 上期的用量增減、最猛的單一尖峰日、模型或專案占比的明顯轉移、使用節奏，以及一條對應建議。固定最多五行、同一件事不重複。完全本機計算，不連網、不打 API、不讀對話內容。

## [0.15.9] - 2026-06-05

### 修正
- **選單列／報告遇到非英文（中文等）專案路徑時不再讀取失敗**：打包成 app 雙擊啟動時沒有設定系統語系，內部呼叫 `git` 取得專案名稱時會用 ASCII 解讀輸出，碰到含中文／日文／韓文／重音等字元的專案路徑就丟出 `UnicodeDecodeError`。此錯誤影響 `history_loader`／`codex_loader`（即時選單列）與 `persona_loader`（使用習慣），會讓報告的「使用習慣」在「今日」以外的期間空白。現在固定以 UTF-8 解讀 `git` 輸出，任何語言的路徑都正常。

## [0.15.8] - 2026-06-05

### 修正
- **Codex「Session（5 小時）」配額過期時不再空白**：5 小時視窗重置後，原本會顯示空白（`--`），與 Claude 端不一致；現在比照 Claude 顯示為 0%。同時讓終端機指令（CLI）與選單列改用同一個額度讀取來源，兩處數字不再對不上。

### 其他
- `doctor` 新增 Codex 診斷：顯示 session 紀錄最新時間、`logs_2.sqlite` 配額筆數、`state_5.sqlite` 狀態，以及目前 5h／週配額是否有資料，方便排查「抓不到」的原因。

## [0.15.7] - 2026-06-04

### 修正
- **選單列刷新失敗時不再整片變空白（#27）**：接續 #25，把本機專案用量／今日統計／狀態列的讀取移到遠端額度抓取「之前」；遠端抓取失敗時改為保留這些已載入好的本機資料，畫面不再閃成空白。另外系統彈窗（NSAlert）建立或設定圖示失敗時改用安全空殼擋住，不再中斷選單列更新。
- **專案用量「30d」報告對齊滾動 30 天（#28）**：選單列專案用量選「30d」產生報告時，原本會對應到「本月」（每月 1 號至今），與標示的「滾動 30 天」不符；現在正確對應到報告管線的 `last30`（近 30 天）。

### 文件
- 首頁（landing）主題展示圖換新、功能 icon 與英雄橫幅刷新，README 補上面板圖庫。

## [0.15.6] - 2026-06-03

### 變更
- **全新賽博龐克貓 app 圖示**：把先前的青色貓掌佔位圖換成正式的 usage 圖示（賽博龐克風格貓咪）。此版起隨 `.app` 出貨，安裝後 Dock／Finder／選單列都會顯示新圖示。
- **README 改善上手體驗**：(1) 頂部新增「快速上手」段落，把一行 Homebrew 安裝指令提到免捲動就能複製貼上的位置；(2) 文末加上 Star 成長圖表。

## [0.15.5] - 2026-06-03

### 變更
- **選單列改用 Claude／Codex 彩色品牌圖示**：原本選單列用 emoji（🐾 代表 Claude、📜 代表 Codex）標示兩家用量，現在換成 Claude 與 Codex 的官方彩色品牌圖示，深色與淺色選單列都更清楚易辨。

## [0.15.4] - 2026-06-03

### 修正
- **面板載入失敗不再變成一片啞掉的灰視窗**：點開的面板（popover 內嵌網頁）若因故載入不出來，原本只會顯示一片深灰色空視窗、使用者無從得知發生什麼事；現在會改為顯示明確的錯誤訊息與 GitHub 回報連結，並在 debug log（`USAGE_DEBUG=1`）記錄「載入失敗」或「渲染逾時」的線索，方便回報與診斷。

## [0.15.3] - 2026-06-02

### 修正
- **刷新出錯時 Codex 額度不再閃成空白（#25）**：接續 #24，刷新流程後段（讀取歷史用量）若出錯，原本會把 Codex 的 session／每週兩列重設成空白，蓋掉刷新一開始就已經載入好的額度數字；現在出錯時會保留這些已載入的 Codex 額度，畫面不再閃一下變空。

## [0.15.2] - 2026-06-02

### 修正
- **背景刷新更穩定**：檔案變動觸發的刷新一律切回主執行緒處理，並在刷新流程最外層加上保險，避免極少數情況下刷新狀態卡住、之後再也不更新。

### 效能
- **session 變多時刷新更輕**：歷史用量的變動偵測從掃描整個 `~/.claude` 收斂到實際會讀的 `~/.claude/projects`；Codex 最近 session 的列舉改用日期資料夾結構只掃必要範圍（並自動略過 `.DS_Store` 之類隱藏檔），不再每次刷新都掃整棵目錄樹。
- **首次啟動／離線時成本不卡頓**：價格表的網路下載移到背景進行，計算成本時一律先用本機快取或內建預設值，下載完成後再自動刷新一次；長時間開著的 app 在快取過期後也會自行在背景更新。

## [0.15.1] - 2026-06-02

### 修正
- **Codex 額度顯示更即時、更準（#24）**：(1) 選單列的 Codex 額度在每次刷新一開始就先更新，不必等較慢的歷史解析跑完；(2) SQLite 與 JSONL 兩來源改成「逐視窗（5 小時／每週）合併」而非整份二選一，額度剛見底（100%）時不會被舊快照蓋回 80%；(3) 小額用量顯示小數百分比，不再四捨五入成 0%；(4) 刷新間隔改用設定值（原本寫死 300 秒）；(5) FSEvents 觸發的刷新若正忙會排隊而非丟棄；(6) 刷新中途若 Claude Code 端讀取失敗，已先載入的 Codex 百分比會保留，不再閃一下又消失。
- **升級後選單列的「🆕 可更新」標籤不再殘留**：原本清快取只在更新檢查流程內跑，原地升級後標籤會一直掛到重開 app；改成每次計時器刷新都比對已安裝版本，已是最新即清。

## [0.15.0] - 2026-06-01

### 新增
- **配額用量通知（opt-in，預設關）**：用量接近門檻、見底、或恢復時，發一則 macOS 系統通知（「快用完囉 / 額度用完啦 / 額度回來了」）。涵蓋 Claude Code 與 Codex 的 session 與每週兩種額度，每個門檻只提醒一次、重置後自動解鎖再提醒。選單一個開關控制；通知文字走 `i18n.json` 五語系。沿用既有的磁碟用量快照觸發，**不連網、不呼叫 API**。打包版（`.app`）已納入 UserNotifications framework 確保通知可送達。
- **配速指示器**：在「照目前速度，X 後見底」這行燃燒警告後面，補一句你目前比個人均速「快幾倍」或「更省」，一眼看出此刻是不是燒得比平常兇。

### 修正
- **忽略 Codex 回音式的額度查詢（#23）**：某些情況下 Codex 會把先前的額度查詢原樣回拋（echo），舊版會把這些回音也當成新訊息塞進視窗、灌爆顯示。改成辨識並略過回音查詢。

## [0.14.2] - 2026-06-01

### 變更
- **HTML 報告「你的訂閱」與「工具用量」合併為「你的工具」**：原本兩塊分開陳述同一組 Claude Code / Codex 工具，現在每個工具一張卡——方案徽章與訂閱起始日，和占比／tokens／花費並列在同一個共用表頭下，少掉一塊重複資訊。
- **頂部 KPI 卡片重新配比**：TOKENS 欄位拿到最寬，確保完整數字（如 `2,364,752,661`）在任何視窗寬度都不被截斷或溢出；數字改用 `tabular-nums` 對齊更整齊。

### 文件
- **README 重整（中英）**：隱私／系統需求與快速上手置頂、安裝方式三選一對等呈現、精簡功能條列與標點，開發者指南移至 `docs/DEVELOPMENT`。

## [0.14.1] - 2026-06-01

### 修正
- **Codex 額度卡在舊值**：`load_rate_limits()` 原本只要 SQLite（`logs_2.sqlite`）撈到資料就直接回傳，不再比對 `~/.codex/sessions/*.jsonl` 裡更新的 `rate_limits`，導致選單列卡在前一天的舊額度。改成同時讀 SQLite 與 JSONL 兩個來源，依 `updated_at` 挑最新有效的那筆；時間相同時維持原本偏好 SQLite 的行為。

## [0.14.0] - 2026-06-01

### 新增
- **HTML 報告新增「使用習慣」區塊**：純本地、零 API。在分析報告中以滿版 24 小時長條圖呈現你的活躍時段，標出最高峰並附一句白話總結（「你最常在 X 點和 Y 點與 AI 協作」）。資料取自本機 Claude Code 對話紀錄的訊息時間（僅計 user / assistant 訊息），**不讀對話內文**；解析邏輯獨立於 `persona_loader.py`，附 300 秒 TTL 快取。
- **Codex 卡片「資料過期」提示**：當本機 Codex 用量快照超過 15 分鐘，classic 面板的 Codex 卡會顯示「約 N 分鐘前」標籤與一個 ⓘ 說明氣泡。Codex 不像 Claude Code 有即時回報的狀態列 hook，其用量來自偶爾才寫入的 session 紀錄、可能落後實際帳號；氣泡同時說明「維持離線是為了不多耗你的 token」。資料取自既有 `rate_limits.updated_at`，**不連網、不呼叫 API**。

## [0.13.0] - 2026-05-31

### 新增
- **「進度管家」功能（Progress Concierge）**：純本地、零 API，選單名「接著上次做」。開新 Claude Code 對話（`startup` / `/clear`）時，自動把上次的進度交給 AI——不用再跟它重講一次。選單一個開關（預設關、opt-in），啟用後安裝 Claude Code 的 SessionStart hook（`usage_session_resume.py`，stdlib-only、可於 macOS 內建 Python 3.9 執行）：讀出該專案上一個 session 的「你上次的請求 + 完成的 commit + 未完成待辦（若有用 TodoWrite）」，組成接續提示詞注入新對話開場，並請 Claude 第一句回「🐾 已接回上次進度，繼續吧！」讓你知道已生效。文案走 `i18n.json`（安裝時寫入 sidecar 供 hook 讀，維持單一來源）；`setup_hook` 負責安裝/移除/備份/self-heal。滑鼠停留選單項顯示完整說明。
- **專屬 App 圖示**：以自製圖示取代 py2app 預設的火箭圖；NSAlert 對話框也改用品牌圖示（透過 `setIcon_`）。

### 變更
- **選單瘦身**：9 個面板主題收進「面板主題」子選單，選單不再被長長一排佔滿。

### 修正
- **大規模健壯性硬化**：系統性強化所有「讀使用者磁碟檔」的入口，對抗壞 UTF-8、壞 JSON、型別漂移（數字字串、非 dict、非 str 欄位）——涵蓋 `setup_hook`、`codex_loader`、Codex / Claude / rate-limit adapter、statusline、history loader、subscription 讀取與 JWT 解碼、tips loader。
- **WebKit 面板 fallback**：修正 `loadBundle` fallback 路徑未註冊 `evaluateJavaScript` block 簽名的問題。

## [0.12.1] - 2026-05-29

### 變更
- **HTML 報告載入器加上檔案快取**：`adapters/claude.py` 與 `adapters/codex.py` 補上以 `mtime`+`size` 為鍵的 LRU 快取（與 `history_loader` 一致），產生報告時不再每次重新解析整批 JSONL；Codex 端的 `load_entries` 與 `load_rate_limits` 共用同一份快取。整檔級的 `OSError` / `PermissionError` / `sqlite3.Error` 現在會在 `USAGE_DEBUG=1` 時輸出到 stderr（逐行的 `JSONDecodeError` 維持靜默）。
- **mypy `--strict` 全面覆蓋**：移除 `adapters/`、`analyzer/`、`ui/`、`usage_cli.py` 的 mypy 排除設定（約 35% 程式碼的型別盲區），補齊泛型參數與函式型別標註，`_group_by_agent` 改用 PEP 695 型別參數。`mypy --strict` 現涵蓋全部 70 個原始檔。
- **`adapters/claude.py` 三個跨模組函式改為公開 API**：`get_claude_dirs`、`extract_project_from_dir`、`parse_jsonl`（原為底線私有），並移除 `analyzer/reporter.py` 對應的 `# type: ignore[attr-defined]`。

### 修正
- 拔除 mypy 排除後抓出並修正數個潛在問題：`adapters/claude.py` 快取改動殘留的 `parsed_entries` 重複標註、`analyzer/reporter.py` 把 `agent` 迴圈變數重用為兩種型別（內層改名 `agent_totals`）、`menubar.py` 一個多餘的 `cast`。

### 測試
- 新增 `_apply_sort` 對 `"time"` 排序鍵（對應 `None`、由各指令自行處理）分支的測試。
- 新增 i18n key parity 測試：斷言 `i18n.json` 五個語言區塊的 key 集合一致，漏翻譯會在 CI 直接失敗，而非默默回退英文。

## [0.12.0] - 2026-05-29

### 新增
- **HTML 報告「你的訂閱」區塊**：自動從本地 OAuth 帳號檔偵測 Claude（方案＋訂閱起始日）與 Codex（ChatGPT 方案＋訂閱起始日）。只讀取方案名稱與訂閱日期，不觸碰 token、email 等機密欄位。分享報告時，訂閱日會隨「隱藏專案名稱」一併遮罩。新增 `subscription.py` 模組與對應測試。
- **HTML 報告專案佔比圓環圖**：以純 SVG（零外部依賴）呈現各專案 token 佔比，前 6 大專案分色、其餘併為「其他」，中心顯示總量。
- **HTML 報告「Claude vs Codex」對比區塊**：把原本已在 `build_report_data` 計算、卻從未顯示的 per-agent 用量（token／占比／成本）實際呈現在報告中。

### 修正
- **報告成本重複計算**：`build_report_data` 原本先全量加總一次成本、迴圈內又逐筆重算，資料量大時形同雙倍計算；改為僅在迴圈內單次累加。
- **報告「複製指令」按鈕的重複剪貼簿程式碼**：tip 複製鈕改用既有的共用 `copyText()`，移除重抄一份的舊瀏覽器備援邏輯。
- **台幣匯率硬編碼**：報告中 USD→TWD 的估算匯率抽成具名常數 `_USD_TO_TWD` 並加註說明（僅供顯示估算，非即時匯率）。

## [0.11.19] - 2026-05-29

### 新增
- **「隱藏 Codex 區塊」選單開關**：menubar 多了一個「隱藏 Codex 區塊」選項，可把所有 9 個 HTML 面板裡的 Codex 卡片收起，popover 高度也會依每個面板的設定縮減。設定透過 `NSUserDefaults` 持久保存，重啟後仍有效。五國語言 i18n key 同步補上。（PR #19，感謝 @RayCHWong 第一次貢獻）

### 修正
- **`HTMLPanel.codex_card_height` 改為強制 keyword-only、無預設值**：之前該參數有 `192.0` 預設，新增面板若忘了在 `panels/__init__.py` 設高度，會默默使用預設值；該面板的 Codex 卡片高度跟其他面板對不齊但完全不會報錯。現在改成 `*, codex_card_height: float`（無預設、強制 keyword 傳入），漏設 import 階段就會 `TypeError`。9 個既有面板已全用 `codex_card_height=...` 形式呼叫，不受影響；新增 `test_html_panel_requires_explicit_codex_card_height` 鎖定契約。

## [0.11.18] - 2026-05-28

### 變更
- **狀態列進度條外觀更新**：進度條字符從「█░」改成「■□」（黑底實心方塊／白底空心方塊），顏色從標準 ANSI 綠／黃／紅（32／33／31）換成 256 色青綠（42）／暖橘（214）／暗紅（160），讓 50% 臨界附近的色差更明顯，掃一眼就分得出安全／警告／危險三段。改動侷限在 `usage_statusline.py` 的 `progress_bar()` 與 `color_by_pct()`；HTML 報告與 TUI 進度條不受影響。

### 文件
- **繁體中文預設面板截圖更新**：`docs/繁體中文面板.png` 換成包含近期 UI 改動的版本（新「報告／終端」切換按鈕、per-project 成本顯示、底部 attribution 等）。

## [0.11.16] - 2026-05-27

### 修正
- **Codex 用量區塊在連續開短 session 時整段顯示 `--`**：`codex_loader.load_rate_limits()` 透過 `_recent_jsonl_files()` 只取最新 5 個 jsonl 找 rate_limits。Codex CLI（觀察到的版本 0.134.0）在「短 session」或「被中斷的 session」會寫 `payload.rate_limits == null`；只要最近 5 個 session 剛好全是這種情況（連續跑幾個 `codex exec`、Ctrl-C 中斷等），上一個真正有資料的 session 就會被擠出 lookup window，popover / TUI 整段 Codex 用量都顯示 `--`。掃描範圍從 5 提高到 30、覆蓋 1~2 天 typical 使用範圍；找到第一筆非 null 仍 early-return，`primary.used_percent` / `secondary.used_percent` 解析路徑不動。Codex CLI 0.134.0 新增的 `limit_id` / `limit_name` / `credits` / `plan_type` / `rate_limit_reached_type` 欄位刻意不解析（UI 沒用到）。新增 3 個測試覆蓋「前 5 個 null 第 6 個有效」「全 30 個 null 回 None」「挑最新有效」三種 case。

### 修正
- **含 dash 連字號的 Claude Code 專案名解碼修正**：`history_loader._project_from_path` 之前的解碼邏輯把目錄名所有 `-` 全換成 `/`，例如 `Desktop-claude-tutorial-video` 變成 `/Desktop/claude/tutorial/video`，路徑不存在 → `resolve_project_name` 走 fallback 取最後一段 → 專案被誤標為 `"video"` 而不是 `"claude-tutorial-video"`。現在先試「全 slash」候選，不存在則對 path segments 做 DFS 嘗試合併連續段、用 fs 上實際存在的目錄定錨；都找不到時保留原 dash 形式（`plain-project` → `plain-project`）。多數情境下 JSONL 內的 `cwd` 欄位已經會覆寫 project name，這條修正主要保護沒有 `cwd` 欄位的舊 entry。
- **TUI 語言偵測統一走 `usage_lang.detect_lang`**：先前 `tui.py` 自寫一份偵測，只認 zh / en（簡中、日韓全部被當英文），且完全沒讀 `USAGE_LANG` / `TT_LANG` / `LANG` 環境變數。結果同一台機器 menubar 顯示日文、TUI 顯示英文。現在 TUI 跟 menubar 共用同一個 `detect_lang()`，五國語言一致。

### 內部改進
- **history / codex loader cache 加 LRU 上限**：`_file_cache` 與 `_jsonl_cache` 之前是無上限的 module-level dict，menubar app 駐留越久、`~/.claude/projects/` 與 `~/.codex/sessions/` 累積越多 jsonl，parsed `UsageEntry` list 全卡在記憶體永遠不釋放。改用 `OrderedDict` + 各自 512 entry 上限；cache hit `move_to_end` 標 LRU、insert 滿了 `popitem(last=False)` evict 最舊。mtime/size 失效邏輯不動、codex_loader 的 `entry.model` rebind 也保留。

### 開發
- **測試覆蓋大幅擴張**：`setup_app` / `ui/tables` / `usage_cli` 三個原本欠覆蓋的模組補上單元測試，整體測試數從 234 增加到 363。沒有改動 production code。

## [0.11.14] - 2026-05-27

### 修正
- **升級後底部狀態列不再殘留舊版本提示**：`usage_statusline.py:_read_update_hint` 只比較快取裡的 `current_version` 與 `latest_version`，沒對照「現在實際在跑的版本」。menubar app 又會在 24 小時冷卻期間直接 return、不更新快取，導致使用者已經升到 v0.11.13 卻一直看到「v0.11.5 可更新」直到冷卻結束。現在 `_check_update_in_background` 啟動就先把目前版本寫回快取，若已追上 `latest_version` 就把它一起拉平，badge 立刻消失。

### 變更（社群 contributor 修補）
- **Codex 用量改用 delta 桶計算（@ericweichun, #11）**：`analyzer/reporter.py` 的 fast path 之前自己 parse Codex `.jsonl` 拿 cumulative snapshot + session-start 時間戳，跟 popover 用的 `codex_loader.load_entries` 走兩條路、結果會分歧。現在 reporter 統一走 shared loader，token_count delta 按 event timestamp 入桶，今日/本週/本月報表跟 popover 完全一致。新增跨日 cumulative session 測試確保只計當日 delta。
- **All Time 報表跟著 project range 一起切換（@ericweichun, #15）**：v0.11.6 重整 analyze bridge 時漏掉 All Time 這個區段，使用者點 All Time 看到的是 720h 快取資料而非真正全期。現在 `_analysis_period_from_project_range("all") → "all"`，project 資料載入改 `hours_back=0` 真的拉全部。9 個 panel HTML 都加 `projectRange === "all"` 分支；五語 i18n 補齊 `project_range_all`。
- **手動重整按鈕在 busy 期間改成排隊（@ericweichun, #12）**：之前 refresh 正在跑時再按一次會直接被丟掉。現在改成排隊一次，refresh 完成的 finally block 依序：先 `codex_model = result.get("codex_model", "unknown")`、再注入 web 語言、再清 busy 旗標、再 drain 一筆 queued refresh。
- **setup 指引改為 agent-neutral（@ericweichun, #16）**：之前 setup 按鈕只看 `~/.claude/` 存不存在當顯示條件，Codex-only 使用者看不到。現在改成「status-line target 任一存在即可」（`~/.claude/` 或 `~/.codex/config.toml`），既有 `setup_hook.setup()` 路徑已會自動偵測 agent。README（繁中 + 英文）同步改成 agent-neutral 措辭；補齊 ja/ko `hook_not_installed` 翻譯。

## [0.11.13] - 2026-05-27

### 變更
- **拿掉 popover footer 的 Codex 模型顯示**：v0.11.6 加進去的「· 模型: gpt-5.5」拼接（`menubar.py:868-870`）會讓使用者誤以為「現在這一秒正在用 gpt-5.5」，但實際語意是「Codex 最近一個有 rate_limits 紀錄的 session 用的模型」——可能是好幾小時前。在沒有時間戳脈絡的情況下，這個資訊「看得到但不知道怎麼用」，純粹噪音。TUI 那邊的 model 顯示（`ui/tables.py:818,857`）脈絡不同（active session 區塊內 / idle panel），保留不動。`model_label` i18n key 與 `CodexRateLimits.model` 欄位皆保留，僅移除 popover footer 的拼接。

## [0.11.12] - 2026-05-27

### 變更
- **hook 自癒：壞了自己修，使用者無感**：每次 usage 啟動會跑一輪 `setup_hook.self_heal()`，在三種「明確安全」的情境下默默修復：(1) 首次安裝（`is_setup()==False` 且 settings 沒有 `statusLine` 鍵）→ 呼叫 `setup()`；(2) hook script 版本過舊（`needs_update()==True`）→ `update_hook()`；(3) settings 指向的 hook 檔案不存在但 state 為 `us-direct`/`us-forwarder` → 重新 `_copy_hook_script()` + `_copy_forwarder_script()`。state 為 `external`/`legacy-tt` 時三段都跳過（不會默默覆蓋第三方工具）。每筆動作寫入 `settings["usage"]["selfHealLog"]`（FIFO 20 筆）。失敗全 swallow，僅 `USAGE_DEBUG=1` 時印 stderr。
- **共存模式提示整合**：偵測到外部 statusLine 工具時跳一次 NSAlert 兩按鈕（「啟用共存模式」/「保留現狀」），按任一鍵後寫 `settings["usage"]["forwarderModePromptDismissed"]=True` 永不再跳。取代原本 `main.py:health_check()` 的三按鈕修復對話框；舊的「稍後 24h 冷卻」機制移除。舊使用者若已選過「不要再問」會被視為未 ack，更新後會再跳一次（按一下即解決）。
- **`--doctor` 隱藏 CLI 指令**：`python3 main.py --doctor` 印純文字診斷報告（全英文，方便 GitHub issue 搜尋），包含 hook state、版本、script 檔案狀態、status file mtime、外部 hook 偵測（識別 `ccusage` / `lord-kali` 關鍵字）、forwarder prompt ack 狀態、最近 5 筆 self-heal log、Codex sessions 掃描數。`argparse.SUPPRESS` 隱藏於 `--help`，預設不打擾一般使用者。新增 `doctor.py` renderer。

### 變更
- **本週燒率警告不再被瞬間高使用激動**：之前用最近 10 分鐘樣本線性外推到整週剩餘額度，使用者跑一個大 prompt 就會看到「剩 8 小時用完」之類嚇人數字，但其實休息一下警告就消失。本週警告現在改看 30 分鐘窗口、要求至少 30 分鐘樣本跨距，需要使用者**持續高燒率半小時以上**才會觸發；session 警告維持原本 10 分鐘窗口（session reset 較頻繁，不能太嚴）。`burn_rate.ROLLING_WINDOW_SECONDS` 從 15 分鐘拉到 60 分鐘讓樣本能保留更久。
- **燒率警告文字明說「按目前速度」**：5 國語言的警告文字統一加上「按目前速度 / At current pace / 现在のペース / 현재 속도」，把「這只是瞬間外推、不是穩定預測」的責任明說推給使用者，不再讓人誤以為系統在預言未來。

## [0.11.10] - 2026-05-27

### 修正
- **「開機啟動」開關立刻生效，不用重開機**：`login_item.enable()` / `disable()` 現在會在寫/刪 `~/Library/LaunchAgents/com.lollapalooza.usage.plist` 之外，呼叫 `launchctl bootstrap gui/<uid> <plist>` / `launchctl bootout gui/<uid>/<label>`，讓 launchd 當下就知道狀態變了。先前只動 plist 檔，launchd 守護程式不會接到通知，使用者點完開關要等下次重開機才會生效，關掉時還會留下 KeepAlive 孤兒程序清不掉。`launchctl` 的「已 bootstrapped」(exit 17) 與「未 bootstrapped」(exit 113) 視為成功；其他失敗只記 warning，plist 操作結果不受影響（簽名維持 `() -> None`）。

## [0.11.9] - 2026-05-27

### 修正
- **TUI session 表遇 `cost_usd=None` 不再崩潰**：`ui/tables.py` 的 `_fmt_cost` 簽名擴成 `float | None`，Codex 端可能寫入 None 的紀錄現在會顯示 `--`，與 popover 側 `panels/web_panel.py` 行為一致。先前直接 `>=` 比較會丟 `TypeError`，整張表渲染失敗。
- **更新檢查支援預發布版號**：`update_checker._parse_version` 改用 regex 切預發布後綴，`0.11.0-beta.1` / `0.11.0+build.5` 不再回 `None`、不再讓 `compare_versions` 報錯，beta tester 也能正常收到更新提示。沒有新增任何套件依賴。
- **離線時退回過期 pricing 快取**：`pricing.py` 的 fallback 順序改成 fresh cache → 線上抓取 → stale cache → 硬編 fallback。先前快取過 7 天又斷網會直接掉到硬編值，導致成本估算大偏移；現在會優先用過期但真實的歷史快取。

## [0.11.8] - 2026-05-27

### 變更
- **git worktree 自動合併到主專案**：在 worktree（同一個 repo 的副本資料夾）內跑 Claude Code 或 Codex 時，HTML report 與 TUI 排行不再把 `usage` 與 `usage-fix-bug` 算成兩個專案，而是合併歸到主 worktree 的資料夾名底下。新增 `project_resolver.py` 共用模組（純 stdlib、3 秒 timeout、查不到 git 就退回原本的 basename 行為），`history_loader.py` 與 `codex_loader.py` 統一走它。第一次升級看到歷史排行數字合併屬於預期行為。

## [0.11.7] - 2026-05-27

### 變更
- **pricing 快取改放在 `~/.usage/`**：把 LiteLLM 計費快取從 `~/.claude/pricing_cache.json` 搬到 `~/.usage/pricing_cache.json`，符合「usage 自己的狀態走自己的目錄」原則；舊路徑保留唯讀 fallback，遷移無感。感謝 @ericweichun。

### 修正
- **`usage report --help` 與未知參數行為明確化**：先前 CLI 子命令對未知參數沉默忽略、`--help` 仍會跑 agent 偵測；現在 `--help` 直接回幫助文字並結束，未知參數明確報錯。感謝 @ericweichun。

## [0.11.6] - 2026-05-27

### 新增
- **Codex 模型顯示在 popover footer**：底部現在會顯示目前偵測到的 Codex 模型；沒有資料時顯示 `unknown`，避免空白狀態讓人誤以為讀取失敗。

### 變更
- **分析報告期間跟隨 Project Usage 範圍**：「分析報告」按鈕現在會依照 project range 切換輸出區間，1d 對應 today、7d 對應 week、30d 對應 month；不新增 UI，沿用現有範圍控制。

### 修正
- **日文 / 韓文 Codex 模型標籤補完**：補上 `model_label` 的 ja / ko 翻譯，讓 footer 的模型資訊在日韓介面不再空白。

### 效能
- **Codex today / week / month 報告改走尾端掃描**：session 很多的使用者按報告時不再需要等待完整歷史掃描，today 報告從約 7 秒降到 0.03 秒等級，week / month 也受益於相同路徑。

## [0.11.5] - 2026-05-26

### 新增
- **「終端」按鈕開啟狀態變色**：之前只有勾勾「終端 ✓」表示 statusLine 開關狀態，現在按鈕底色也會跟著變（每個面板用自己的主色），一眼看出開還是關。

### 變更
- **按鈕名稱對非工程師更直觀**：「分析」→「報告」、「CLI」→「終端」/ Terminal / ターミナル / 터미널 / 终端，五國語言同步。
- **所有按鈕都有 hover 反饋**：原本只有「立即更新」滑鼠移上去會變色，「結束」「更換面板」「今日」「報告」「終端」全沒反應像 disabled。現在 hover 都有對應視覺回饋，強度按 primary > secondary > switch 階層遞減。
- **classic 面板大幅視覺精修**：往「macOS 系統工具」風格調 —— 卡片圓角 18→8、間距收緊、進度條加 inset 軌道凹陷感與外發光、排行榜加相對佔比比例條（前 3 名比例橫條，第一名強調）、底部狀態變 chip pill、左邊加品牌色細條、brand icon 加底色與光暈。
- **6 個面板套同樣 UX 三件套**（matrix / win95 / newspaper / aquarium / cloud_observation / prism_arcade / black_hole）：比例條、終端開啟變色、按鈕 hover；各面板完整保留自己原本的主題視覺（駭客綠 / 像素 / 報紙 / 水紋 / 雲 / 彩虹 / 橘漸層）。
- **landing page panel 展示從 6 個擴成 9 個**：新增 aquarium / prism_arcade / black_hole 三個；classic 改用專屬截圖（之前借用 popover.png）。
- **更新 9 個面板的中英文截圖**：README 與 https://aqua5230.github.io/usage/ 上的展示截圖全部換成最新版。

### 修正
- **分析報告語言跟隨 menu bar 浮窗**：按下「報告」時 HTML 報告改用 menu bar 目前語言，避免 LaunchAgent 未設 `LANG` 時 fallback 成英文。
- **切換面板時重新定位已開啟的 popover**：popover 開啟狀態下切 theme/panel，先關舊 popover、重建內容尺寸再顯示，避免短暫排版錯亂。
- **Codex 專案用量與分析報告統一算法**：同一個 Codex session 出現在多個 JSONL 檔時改選較新的 cumulative token entry；分析報告改共用 `codex_loader.load_entries()`，Project Usage 也納入 Codex session。Project Usage 的 Today 與底部 Today 同步用本地日曆日，底部 Today 不會在呼叫端已提供 Codex entries 時重複載入。
- **9 個面板「專案用量」標題不再被按鈕擠斷**：classic 與 matrix 由 @ericweichun 補上（#9），這次補完剩 6 個面板（win95 / newspaper / aquarium / cloud_observation / prism_arcade / black_hole），全部改成 2 列 grid 版型（icon+標題在上、三顆按鈕等寬排在下），配合英文「Project Usage」與日韓較長字串。
- **macOS 開啟分析報告改用 `/usr/bin/open`**：以前 `webbrowser.open()` 走 `file://` URI 對含空格或中文字路徑可能失敗，改用 `/usr/bin/open` 更穩。感謝 @ericweichun（#9）。
- **matrix 面板 footer 被截**：加 ASCII 邊框與雨滴背景後內容變高，預設 panel height 812 裝不下「立即更新 / 結束」按鈕。改成 880。
- **win95 / newspaper 面板「重置 X天 X小時」貼下邊框**：win95 panel height 768 → 800、newspaper → 850，並對 Claude/Codex 卡的 `.row:last-child` 加 padding-bottom 緩衝。
- **4 個 grid 面板（aquarium / cloud_observation / prism_arcade / black_hole） Projects row 排版重構**：原 row 是有 border 的小卡片設計跟新加的比例條跨欄行為打架，改為 row 之間用 border-top 分隔（同 classic 風格），保留各面板主題色在 rank chip 與背景。同時拆掉這 4 個面板的比例條（grid + row 卡片化 + bar 跨欄三者本質衝突，ROI 過低），其他 4 個面板（classic / matrix / win95 / newspaper）的比例條保留。

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
