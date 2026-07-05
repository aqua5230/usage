#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$BASH_SOURCE")/.."
rm -rf build dist
uv sync --group build
# Build + vendor the instate CLI (separate ~/Developer/instate project) so the
# talent-market panel has its data source in the shipped .app. On machines
# without that project (e.g. community contributors) this is skipped silently —
# setup_app.py only bundles vendor/instate-cli when it exists, and the panel
# shows its empty state otherwise.
if [[ -d /Users/lollapalooza/Developer/instate ]]; then
  (cd /Users/lollapalooza/Developer/instate && bun run build:cli) || \
    echo "warning: instate CLI build failed, talent market panel will show empty state"
  mkdir -p vendor
  cp /Users/lollapalooza/Developer/instate/dist-cli/instate-cli vendor/instate-cli 2>/dev/null || true
  if [[ -n "${INSTATE_CLI_TOKEN:-}" ]]; then
    GH_TOKEN="$INSTATE_CLI_TOKEN" gh release upload latest vendor/instate-cli \
      --repo aqua5230/instate-cli-dist --clobber || \
      GH_TOKEN="$INSTATE_CLI_TOKEN" gh release create latest vendor/instate-cli \
        --repo aqua5230/instate-cli-dist --title "instate-cli" \
        --notes "auto-published by build_app.sh" || \
      echo "warning: instate CLI publish failed, continuing with local vendor binary only"
  fi
elif [[ -n "${INSTATE_CLI_TOKEN:-}" ]]; then
  mkdir -p vendor
  GH_TOKEN="$INSTATE_CLI_TOKEN" gh release download latest \
    --repo aqua5230/instate-cli-dist --pattern instate-cli \
    --dir vendor --clobber || \
    echo "warning: instate CLI download failed, talent market panel will show empty state"
fi
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
