#!/usr/bin/env bash
# Build assets/usage.icns from assets/usage_icon.png (1024x1024).
# Swap the PNG and re-run to update the icon — no code change needed.
set -euo pipefail

cd "$(dirname "$0")/.."
SRC="assets/usage_icon.png"
ICONSET="$(mktemp -d)/usage.iconset"
mkdir -p "$ICONSET"

for size in 16 32 64 128 256 512; do
  sips -z "$size" "$size" "$SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "$ICONSET" -o assets/usage.icns
echo "wrote assets/usage.icns"
