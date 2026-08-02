#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Install the freshly built dist/usage.app over /Applications/usage.app.
#
# Releasing does not update the local install: the tag drives CI, and the copy
# in /Applications keeps running whatever was there before. That last step was
# manual and undocumented outside a checklist, so the menu bar ran a stale
# build for six versions before anyone noticed. Run this after build_app.sh,
# and after the CI release finishes if a tag was just pushed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_APP="$REPO_ROOT/dist/usage.app"
TARGET_APP="/Applications/usage.app"

if [[ ! -d "$SOURCE_APP" ]]; then
    echo "error: $SOURCE_APP is missing — run ./scripts/build_app.sh first" >&2
    exit 1
fi

version_of() {
    defaults read "$1/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "unknown"
}

NEW_VERSION="$(version_of "$SOURCE_APP")"
OLD_VERSION="none"
[[ -d "$TARGET_APP" ]] && OLD_VERSION="$(version_of "$TARGET_APP")"
echo "installing $NEW_VERSION over $OLD_VERSION"

osascript -e 'quit app "usage"' 2>/dev/null || true
for _ in $(seq 1 20); do
    pgrep -x usage >/dev/null || break
    sleep 0.5
done
pkill -x usage 2>/dev/null || true

rm -rf "$TARGET_APP"
ditto "$SOURCE_APP" "$TARGET_APP"
open "$TARGET_APP"

INSTALLED="$(version_of "$TARGET_APP")"
if [[ "$INSTALLED" != "$NEW_VERSION" ]]; then
    echo "error: installed $INSTALLED but expected $NEW_VERSION" >&2
    exit 1
fi
echo "running $INSTALLED"
