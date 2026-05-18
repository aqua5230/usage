# 貢獻指南

繁體中文 · [English](CONTRIBUTING.en.md)

歡迎開 issue / PR。這份文件只描述硬性要求，不規定流程。

## 開 Issue

- **Bug report**：用 `.github/ISSUE_TEMPLATE/bug_report.md` 模板。請附 macOS 版本、Python 版本、`git rev-parse --short HEAD`、跑哪個模式（menu bar / TUI / mock）。
- **Feature request**：用 `.github/ISSUE_TEMPLATE/feature_request.md` 模板。

## 開 PR 前的必跑檢查

```bash
source .venv/bin/activate
uv run ruff check
uv run mypy .
uv run pytest -v
```

三項都要綠才能 merge。CI 也會跑這三項（`.github/workflows/check.yml`）。

## 改 code 的方針

- **改 prod 模組請順手補測試**：`tests/` 底下挑風格最接近的檔案模仿。新增測試禁止碰 `~/.claude/` 跟 `~/.codex/` 真實檔案，請用 `monkeypatch` 改路徑常數。
- **內外名稱統一為 `usage`**：檔案路徑、設定 key、binary、env var、LaunchAgent label 都使用 `usage` 前綴。
- **menubar.py 的 UI 常數**（`CARD_HEIGHT`、`CARD_RADIUS`、`SECTION_GAP` 等）動之前先想清楚，那是 popover 視覺設計的一部分。

## CHANGELOG 與發版

- 改完一件事就把它寫進 `CHANGELOG.md` 的 `## Unreleased` 段，**同時更新 `CHANGELOG.en.md`** 對應段（這個專案的 README / CHANGELOG / release notes 全部雙語）。
- 發版由 maintainer 處理（`pyproject.toml` 版本 bump + `## Unreleased` → `## X.Y.Z — YYYY-MM-DD` + commit `Release vX.Y.Z` + tag）。

## Commit message 風格

跟現有 `git log` 一致：祈使句 + 簡短主旨，必要時加 body 解釋 why（不是 what，what 看 diff 就好）。範例：

```
Fix AttributeError: drop stale tracker.sample() call

072a088 removed UsageRateTracker.sample() but missed the lone caller in
menubar.py:435...
```
