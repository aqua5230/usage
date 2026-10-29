#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$BASH_SOURCE")/.."
rm -rf build dist
uv sync --group build
uv run python3 setup_app.py py2app
if [[ -d dist/main.app && ! -d dist/usage.app ]]; then
  mv dist/main.app dist/usage.app
fi
# Prune build artifacts the runtime never reads: py2app's bytecode caches
# (recompiled below), and Resources/include, which only matters at compile time.
APP=dist/usage.app
echo "Size before prune: $(du -sh "$APP" | cut -f1)"
find "$APP" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$APP" -type f -name '*.opt-1.pyc' -delete
rm -rf "$APP/Contents/Resources/include"
# Without precompiled caches, Python writes __pycache__ into the bundle on
# first launch, which breaks its seal and leaves tampering undetectable.
# unchecked-hash caches load without comparing source timestamps, so nothing
# is written at runtime.
uv run python3 -m compileall -q -j 0 --invalidation-mode unchecked-hash "$APP/Contents/Resources/lib/python3.13"
echo "Size after prune: $(du -sh "$APP" | cut -f1)"
# py2app signed the bundle before the prune, so its seal still lists the
# deleted files; re-sign ad hoc and verify, or the bundle fails codesign.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
echo "Built: dist/usage.app"
