# agy 額度卡：第三階段 b（classic）

## 結論

完成並通過真實 `.app` 驗證。Antigravity 額度資料只接入 classic 面板；選單列標題與圖示未變。

## 改動

- `menubar_agy.py`：背景安全的 `load_quota()` 接線、卡片投影、最吃緊組選擇、已用百分比／倒數／滿額／20 分鐘陳舊判斷。
- `menubar_state.py`：新增 agy 卡片狀態與完整型別。
- `menubar.py`：既有背景刷新內呼叫葉模組，結果沿既有 main-thread refresh 派發；無新增或改名 selector。
- `panels/web_panel.py`：新增 `agy`、`hideAgy` DOM payload。
- `assets/panels/classic.html`：新增第三張 Antigravity 卡、SVG、深淺色強調色、陳舊 tooltip、隱藏規則與 DOM 更新。額度群組仍供後端選擇，但不顯示在卡片標題旁。
- `i18n.json`：五語言新增滿額與陳舊字串。
- `tests/test_menubar_agy.py`、`tests/test_web_panel_payload.py`：新增投影與 payload 測試；更新既有尺寸／刷新測試。

## 資料流

既有 `_refresh()` 背景執行緒 → `menubar_agy.load_refresh_result()` → `agy_quota_probe.load_quota(max_age_minutes=15)` → `build_popover_state()` → 既有 `_applyRefreshResult:` main-thread UI 更新 → classic 的 `usageApplyState()` DOM 更新。

關閉時既有慢速刷新每 5 分鐘會讀取一次；`load_quota` 的 15 分鐘快取使真正探測最多每 15 分鐘一次。popover 開啟也會走既有背景刷新，快取過期時不阻塞 UI。

## `.app` 問題與修正

- GUI App 找不到 `agy`：加入 `~/.local/bin`、Homebrew 常見位置的執行檔備援。
- 子行程缺少工具路徑：探測環境補入 `agy` 所在目錄與常見安裝位置。
- 啟動探測期間卡片消失：只要已安裝 `agy`，初始狀態就先保留卡片，背景結果完成後再填入額度。
- 真實 PTY `/quota` 輸出解析成功，正式刷新回傳 `hide_agy=False`，並寫入 `~/.usage/agy_quota_cache.json`。
- 重建並啟動 `dist/usage.app` 後，classic 面板已顯示 Antigravity 額度。

## 驗證

- `.venv/bin/ruff check`：通過。
- `.venv/bin/mypy .`：通過，133 個來源檔。
- agy 相關與 menubar 測試：94 passed。
- 全量 `.venv/bin/pytest -v -k 'not test_build_view_falls_back_to_error_panel_on_failure'`：759 passed、1 skipped、1 deselected；7 個既有失敗皆因沙盒禁止寫入 `~/.claude` lock／tmp，與本改動無關。
- 未排除時，`test_build_view_falls_back_to_error_panel_on_failure` 會因無 Window Server 的 AppKit `NSTextField` 建構直接 abort；同樣非本改動。
- `uv` 無法讀取 `~/.cache/uv/sdists-v9/.git`，故改用 `.venv`。

## 自我審查

| 項目 | 結果 | 說明 |
| --- | --- | --- |
| 最吃緊組／百分比／滿額／陳舊 | 通過 | 純函式測試覆蓋。 |
| 背景探測 | 通過 | 只從既有背景刷新呼叫；測試 mock `load_quota`。 |
| main-thread UI | 通過 | 沿用既有 `_applyRefreshResult:`。 |
| classic-only 面板 | 通過 | 只改 `assets/panels/classic.html`。 |
| 禁區 | 通過 | 未改 `agy_quota_probe.py`、`tui.py`、圖示／標題程式；未改既有 selector。 |
| 五語言 | 通過 | parity 測試通過。 |
| commit／push／網路／真 agy | 通過 | 均未執行。 |
