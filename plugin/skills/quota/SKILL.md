---
name: quota
description: Show how much of the Claude Code and Codex 5-hour and weekly quota is used and when each window resets. Use when the user asks about remaining quota, rate limits, or usage for Claude Code or Codex.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/quota.sh), Bash(date +%s)
---

Quota snapshot from the usage CLI (`usage status --json`):

!`${CLAUDE_PLUGIN_ROOT}/scripts/quota.sh`

Current Unix time: !`date +%s`

Report this snapshot to the user in their language, one short line per agent:

- Name the agent (`claude-code` → Claude Code, `codex` → Codex) and its `model`.
- Give `five_hour.used_percent` and `seven_day.used_percent`. A `null` percent means unknown; say so instead of guessing.
- For each `resets_at` (Unix seconds), subtract the current Unix time above and say "resets in Xh Ym" (or "Xd Yh" past a day). Skip it when `resets_at` is `null`.
- If `updated_at` is more than an hour old, say the numbers may be stale. For Claude Code, the built-in `/usage` command is the live source.
- If an agent has `"available": false`, say it has no local data.

If the snapshot says usage-cli is not found, tell the user to run `uv tool install usage-cli`, or install the menu bar app with `brew install --cask aqua5230/usage/usage` (https://github.com/aqua5230/usage).

Do not run any other command.
