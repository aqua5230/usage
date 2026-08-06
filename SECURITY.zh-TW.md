# 安全政策

> English version: [SECURITY.md](SECURITY.md)

## 回報安全漏洞

如果你發現 usage 的安全漏洞，**請勿開公開 Issue**。請改用私下管道回報：

📧 **aqua5230@gmail.com**

回報時請盡量包含：

- 受影響的版本（或 commit）
- 重現步驟，或概念驗證（PoC）
- 你評估的影響範圍

本專案為單人維護，我會盡力在合理時間內回覆並處理。修復釋出後會在 release notes 中致謝（除非你希望匿名）。

## 支援版本

usage 採滾動發布，安全修復只針對**最新發布版**。回報前請先確認你使用的是 [最新 release](https://github.com/aqua5230/usage/releases/latest)。

## 安全設計

usage **不呼叫任何 LLM API**——看額度這件事本身永遠不會消耗你的 token，這是本專案的核心設計原則。usage 也不上傳、不追蹤、不把你的用量資料外送：你的提示詞、對話內容與用量數字都不會離開你的電腦。

**Claude Code 與 Codex** 的數字完全來自你本機磁碟上既有的檔案——Claude Code 的狀態列 hook 寫入的狀態檔，以及 Codex 的 session log。讀取這些數字完全不需要連網。

**Antigravity** 不一樣，這點要講明白：它的額度不在你的磁碟上，所以 usage 會透過網路取得。詳見下表。

### 所有對外連線

| 用途 | 端點 | 時機 |
|---|---|---|
| Antigravity 額度 | `https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary` | app 執行期間定期取得，且僅在 Antigravity 已登入時 |
| Antigravity token 更新 | `https://oauth2.googleapis.com/token` | 本機存的 access token 過期時 |
| 服務狀態警示 | `https://status.claude.com/api/v2/summary.json`<br>`https://status.openai.com/api/v2/summary.json` | 每 5 分鐘 |
| Token 價目表 | `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | 首次需要時，之後每 7 天 |
| 更新檢查 | `https://api.github.com/repos/aqua5230/usage/releases/latest` | 最多每 24 小時一次，可從選單關閉 |

以上沒有任何一項會夾帶你的用量資料、提示詞或對話內容。狀態、價目表與更新檢查這三個端點都是不帶驗證的單純 GET。

### 憑證存取

為了讀取 Antigravity 額度，usage 會讀取 Antigravity CLI 本來就存在你電腦上的 OAuth 憑證——macOS 存在 **Keychain（鑰匙圈）**，Windows 存在 **認證管理員（Credential Manager）**。這個存取是唯讀的：usage 不會寫入或修改該憑證，也不會把它送到 Google 自己的 token 與額度端點以外的任何地方——跟 Antigravity CLI 本身的做法完全一樣。如果你沒有使用 Antigravity，usage 永遠不會讀取任何憑證。

Claude Code 與 Codex 則完全不需要任何憑證存取。

### 關於原始碼裡的 OAuth client 常數

`agy_quota_probe.py` 裡以明文寫著 Antigravity 安裝型應用的 OAuth client ID 與 client secret。這是刻意的，而且它不是外洩的憑證：

- 依 [RFC 8252](https://datatracker.ietf.org/doc/html/rfc8252)，安裝型應用本來就無法保密 client secret。這種 secret 不構成安全邊界，OAuth 規範直接把這類 client 視為公開（public client）。
- 它**不是你的憑證**，本身也不授予任何存取權。真正的授權來自你電腦上既有的 OAuth token，那個只有你有。
- 自動掃描工具看到 `GOCSPX-` 前綴就會告警。在這裡出現這種告警是預期內的。

如果 Google 之後輪替或撤銷這組常數，`usage` 只會停止顯示 Antigravity 額度——token 請求失敗、探測回傳空值，Claude Code、Codex 與其他所有功能都照常運作。
