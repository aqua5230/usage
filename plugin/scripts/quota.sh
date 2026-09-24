#!/bin/sh
# Prints `usage status --json`, preferring an installed usage CLI over a uvx run.
if command -v usage >/dev/null 2>&1; then
  exec usage status --json
fi
if command -v uvx >/dev/null 2>&1; then
  exec uvx --quiet --from usage-cli usage status --json
fi
echo "usage-cli not found. Install it with: uv tool install usage-cli"
