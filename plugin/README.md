# usage — Claude Code plugin

Adds `/usage:quota` to Claude Code. It shows how much of your Claude Code and Codex 5-hour and weekly quota is used, and when each window resets.

It runs `usage-cli status --json` from [usage-cli](https://pypi.org/project/usage-cli/), which reads local files only. It never calls a model API and never spends quota.

## Install

```
/plugin marketplace add aqua5230/usage
/plugin install usage@usage
```

The plugin uses an installed `usage-cli` command if you have one (`uv tool install usage-cli`). Otherwise it runs usage-cli through `uvx`, which needs [uv](https://docs.astral.sh/uv/).

For the macOS menu bar app, see the [main README](../README.md).
