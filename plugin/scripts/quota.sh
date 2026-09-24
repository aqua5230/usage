#!/bin/sh
# Prints `usage-cli status --json`, preferring an installed usage-cli over a uvx run.
# `usage-cli` rather than `usage`: other tools (e.g. jdx/usage) also install a `usage` binary.
if command -v usage-cli >/dev/null 2>&1; then
  exec usage-cli status --json
fi
if command -v uvx >/dev/null 2>&1; then
  exec uvx --quiet --from usage-cli usage-cli status --json
fi
echo "usage-cli not found. Install it with: uv tool install usage-cli"
