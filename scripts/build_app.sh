#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$BASH_SOURCE")/.."
rm -rf build dist
uv sync --group build
uv run python3 setup_app.py py2app
if [[ -d dist/main.app && ! -d dist/usage.app ]]; then
  mv dist/main.app dist/usage.app
fi
# Prune build artifacts the runtime never reads: bytecode caches are
# regenerated on demand, and Resources/include only matters at compile time.
APP=dist/usage.app
echo "Size before prune: $(du -sh "$APP" | cut -f1)"
find "$APP" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$APP" -type f -name '*.opt-1.pyc' -delete
rm -rf "$APP/Contents/Resources/include"
echo "Size after prune: $(du -sh "$APP" | cut -f1)"
echo "Built: dist/usage.app"
