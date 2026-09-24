# usage — Claude Code 外掛

在 Claude Code 加上 `/usage:quota` 指令，顯示 Claude Code 與 Codex 的 5 小時、每週額度用了多少，以及各自何時重置。

它執行 [usage-cli](https://pypi.org/project/usage-cli/) 的 `usage status --json`，只讀本機檔案，不呼叫任何模型 API，也不消耗額度。

## 安裝

```
/plugin marketplace add aqua5230/usage
/plugin install usage@usage
```

有裝 `usage` 指令（`uv tool install usage-cli`）就直接用它；沒有的話改用 `uvx` 執行 usage-cli，需要先裝 [uv](https://docs.astral.sh/uv/)。

macOS 選單列 App 請見[主 README](../docs/README.zh-TW.md)。
