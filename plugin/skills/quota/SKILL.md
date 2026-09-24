---
name: quota
description: Show how much of the Claude Code and Codex 5-hour and weekly quota is used and when each window resets.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/quota.sh)
---

Quota snapshot from `usage-cli status --json`:

!`${CLAUDE_PLUGIN_ROOT}/scripts/quota.sh`

Report this snapshot to the user in their language, one short line per agent:

- Name the agent (`claude-code` → Claude Code, `codex` → Codex) and its `model`.
- Give `five_hour.used_percent` and `seven_day.used_percent`. A `null` percent means unknown; say so instead of guessing.
- Turn each window's `resets_in_seconds` into "resets in Xh Ym" (or "Xd Yh" past a day). If it is `null` or absent, say the reset time is unknown.
- If `age_seconds` is over 3600, say the numbers may be stale. For Claude Code, the built-in `/usage` command is the live source.
- If an agent has `"available": false`, say it has no local data.

If the snapshot says usage-cli is not found, tell the user to run `uv tool install usage-cli`, or install the menu bar app with `brew install --cask aqua5230/usage/usage` (https://github.com/aqua5230/usage).

Do not run any other command.
