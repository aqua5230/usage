#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$BASH_SOURCE")/.."
rm -rf build dist
uv sync --group build
uv run python3 setup_app.py py2app
if [[ -d dist/main.app && ! -d dist/usage.app ]]; then
  mv dist/main.app dist/usage.app
fi

# Post-build fix for conda/homebrew dynamic libraries
uv run python3 -c "
import os, sys, shutil
prefix_lib = os.path.join(sys.base_prefix, 'lib')
dest_dir = 'dist/usage.app/Contents/Frameworks'
os.makedirs(dest_dir, exist_ok=True)
for lib in ['libffi.8.dylib', 'libsqlite3.dylib']:
    src = os.path.join(prefix_lib, lib)
    if os.path.exists(src):
        shutil.copy2(src, dest_dir)
        print(f'Bundled {lib} into App Frameworks')
"

echo "Built: dist/usage.app"
