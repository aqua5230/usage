# usage

繁體中文 · [English](README.en.md)

[![CI](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![Latest Release](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![License](https://img.shields.io/github/license/aqua5230/usage)](LICENSE)

`usage` 是一個 macOS menu bar（螢幕右上角的選單列）小工具，把 **Claude Code 跟 Codex** 的用量同時釘在你的螢幕右上角。點開可以看到這 5 小時用了多少、這 7 天用了多少、今天總共花了幾塊美金。

不打 Anthropic / OpenAI 的 API（接口）、也不讀 Keychain（macOS 內建的密碼保險箱），所以不會發生「自己每分鐘 ping 一次也算用量」這種事。

<p align="center">
  <img src="docs/popover.png" alt="usage popover 展開時的樣子" width="320">
</p>

## 它怎麼拿到你的用量數字

usage **不打網路 API**。資料來源是 Claude Code 跟 Codex 在你本機留下的檔案。

### Claude Code 用量

usage 會幫你裝一個小腳本，這個小腳本叫做 **statusLine hook**（hook 就是「事件觸發點」，每次 Claude Code 刷新狀態列就會自動跑一次的小程式）。流程是這樣：

1. Claude Code 每次更新狀態列時，會把「這 5 小時用了百分之幾、這 7 天用了百分之幾」這類資訊整理成 JSON
2. 透過標準輸入（stdin）餵給 hook
3. hook 把 JSON 寫進 `~/.claude/usag-status.json` 這個檔
4. usage 主程式去讀這個檔

因為兩邊看的是同一份資料，**數字跟 Claude Code 自己看到的完全一樣**。

```mermaid
flowchart LR
    A[Claude Code 主程式] -->|每次刷新狀態列<br/>把 JSON 透過 stdin 餵給 hook| B[usag-statusline.py<br/>hook 腳本]
    B -->|寫入| C[(~/.claude/<br/>usag-status.json)]
    D[usage menu bar / TUI] -->|讀取| C
    D -->|顯示| E[macOS menu bar]
    F((Anthropic API)) -.x.- D
    style F stroke:#c0392b,stroke-dasharray:5 5
```

讀檔的優先順序：

1. `~/.claude/usag-status.json` —— usage 自己 hook 寫的
2. `~/.claude/tt-status.json` —— 備援；如果你也裝過 [token-tracker](https://github.com/stormzhang/token-tracker)，usage 會直接共用它的狀態檔

### Codex 用量

Codex CLI 沒有 statusLine hook 這種機制，所以 usage 採另一條路：直接掃 Codex CLI 留下的對話紀錄檔（`~/.codex/sessions/` 底下的 `*.jsonl`），從裡面挖出每次對話用了多少 token（語言模型的計費單位），反推這 5 小時跟這 7 天的用量。

沒裝 Codex 或沒這個資料夾的話，這部分會自動隱藏，不會影響 Claude Code 那邊的顯示。

## 你需要的東西

- macOS
- Python 3.13
- 已經裝好、登入過 Claude Code（Codex 是可選的）

## 拿到原始碼

```bash
git clone https://github.com/aqua5230/usage.git
cd usage
```

不熟 git 也可以到 [GitHub 專案頁](https://github.com/aqua5230/usage) 點右上角綠色的 **Code → Download ZIP**，解壓縮後 `cd` 進那個資料夾。

## 建環境

下面這幾行會幫你開一個**獨立的 Python 環境**（venv，virtual environment 的縮寫，就像幫這個專案開一個專用的抽屜，跟系統 Python 分開，互不干擾），然後把 usage 跟它需要的套件裝進去：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

`source .venv/bin/activate` 是「進入這個抽屜」的意思 —— 跑完之後你 terminal 提示字元前面會多一個 `(.venv)`，代表現在 Python 指令會在這個獨立環境裡跑。

## 跟 Claude Code 對接（首次安裝）

這個指令會做兩件事：把 usage 的 hook 腳本複製到 `~/.claude/` 裡，再去改 Claude Code 的設定檔，讓它每次刷新狀態列時去叫這個 hook。

```bash
source .venv/bin/activate
python3 main.py --setup
```

**跑完後請重開一次 Claude Code**，這樣它才會重新讀 `~/.claude/settings.json` 並刷新一次狀態列（資料這時候才會落到磁碟）。

setup 具體做了什麼：

- 把 `usag_statusline.py` 複製到 `~/.claude/usag-statusline.py`
- 在 `~/.claude/settings.json` 把 `statusLine` 指向這個 hook
- 如果你本來就有自訂的 statusLine，會自動備份到 `settings.usag.previousStatusLine`，不會被蓋掉

要卸載：

```bash
python3 main.py --unsetup
```

unsetup 會把原本的 statusLine 還原回去、刪掉 hook 跟 `~/.claude/usag-status.json`。

## 跑起來

### Menu bar 模式（預設、推薦）

啟動後會在 macOS 右上角的選單列常駐，平常只顯示一行小小的百分比；點下去就會展開完整的 popover（彈出小視窗）。

```bash
source .venv/bin/activate
python3 main.py
```

- **選單列那行字長這樣**：`🐾 37%`；如果同時有 Codex 用量，會變成 `🐾 37% · 📜 10%`：

  <img src="docs/menubar.png" alt="menu bar 上方顯示樣式" width="240">

- **點一下會展開 popover**，分三塊：
  1. 上面兩張卡片分別是 Claude Code 跟 Codex，每張各有 Session（這 5 小時）跟 Weekly（這 7 天）兩條進度條，旁邊標重置倒數
  2. 最下面那張小卡是目前速率、同步狀態、今日總花費（美金 + token 數）
  3. 兩顆按鈕：「立即更新」、「結束」
- **權限提醒**：第一次啟動時，macOS 可能會問你要不要讓它在背景跑，點「允許」就好。

### 終端機 TUI 模式

如果你比較喜歡留在終端機，可以用 TUI（Text-based UI，文字版的圖形介面）模式，畫面會帶一個 Claude 的像素藝術動畫。

```bash
source .venv/bin/activate
python3 main.py --tui
```

## 開機自動啟動

LaunchAgent 是 macOS 內建的背景服務管理器（負責「使用者登入後要幫忙啟動哪些程式」），可以讓 usage 在你登入時自動跑起來，不用每次手動啟動。

1. **安裝**：
   ```bash
   ./scripts/install-launchagent.sh
   ```
   這個指令會在 `~/Library/LaunchAgents/` 底下放一份設定檔，然後立刻把 usage 載入起來。

2. **手動啟動（測試用）**：
   ```bash
   launchctl start com.lollapalooza.usag
   ```

3. **查看 log**（log 就是這個服務跑的時候的「日誌」，裡面有訊息跟錯誤紀錄）：
   - 一般訊息：`~/Library/Logs/usag/usag.log`
   - 錯誤訊息：`~/Library/Logs/usag/usag.err.log`

4. **移除**：
   ```bash
   ./scripts/uninstall-launchagent.sh
   ```

## 想先看看 UI 長什麼樣（預覽模式）

還沒裝 hook、或者只想看看介面長什麼樣，可以用假資料（mock data）跑一次：

```bash
# Menu bar 預覽
python3 main.py --mock

# TUI 預覽
python3 main.py --tui --mock
```

## 全部可用參數

- `--setup` / `--unsetup`：安裝 / 卸載 Claude Code statusLine hook。
- `--tui`：強制使用終端機 TUI 模式（不開 menu bar）。
- `--interval N`：UI 多久重新讀一次狀態檔（秒）。最小值 30，預設 60。
- `--mock`：用假資料跑，不讀任何狀態檔。
- `--force-group {0,1,2,3}`：強制指定速率分組（只有 TUI 模式有效）。

## 除錯

想看 usage 內部有沒有吞掉什麼錯誤（例如 OSError，作業系統相關錯誤），啟動時加環境變數：

```bash
USAG_DEBUG=1 python3 main.py
```

## 一些行為說明

- usage 只讀 `~/.claude/usag-status.json` 跟 `~/.claude/tt-status.json`（還有 Codex 那邊的 session 檔）。**不打網路、也不讀 Keychain**。
- Claude Code 沒在跑的時候，狀態檔不會更新；但因為實際用量也不會變（除非重置時間到了），所以顯示的數字仍然是有效的；重置時間過了會自動歸零。
- 如果狀態檔超過 6 小時沒被更新過，會在狀態訊息標註「狀態檔已 N 分鐘未更新，數字可能過時」。

## 打包成 .app（不開終端機就能跑）

想要雙擊圖示就跑、不開終端機，可以打包成 macOS 原生 App（.app 就是 macOS 看到的圖示，本質是一個目錄，裡面把程式跟資源打包在一起）：

```bash
./scripts/build_app.sh
```

跑完產物會在 `dist/usag.app`。雙擊或 `open dist/usag.app` 就能跑。

⚠️ 因為沒有 Apple Developer 簽章，**第一次開啟時 macOS Gatekeeper（系統的「擋陌生程式」保全機制）會擋下來**。
解法：在 Finder 找到 `dist/usag.app` → 按住 Ctrl 點右鍵 → 選「打開」→ 再確認一次「打開」。之後就能直接雙擊。

每次發 GitHub Release（push 一個 `v*` 開頭的 tag 時），CI 會自動 build 並把 `usag.app.zip` 附加到 Release 頁面，使用者可以直接從 Release 下載，不用自己 build。
