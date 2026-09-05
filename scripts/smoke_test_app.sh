#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Launch the built app's TUI and fail if it does not render.
#
# The bundle checks that run before this one only assert that files exist, so
# a bundle that cannot start still shipped: v0.30.7 went out with rich's
# Unicode width tables missing and crashed on the first table it drew (#125).
# Nothing before this ran the app, so the reporter was the first to execute it.
#
# Usage: scripts/smoke_test_app.sh [path/to/usage.app]

set -euo pipefail

APP="${1:-dist/usage.app}"
BIN="$APP/Contents/MacOS/usage"
TIMEOUT=60

if [[ ! -x "$BIN" ]]; then
  echo "Missing app binary: $BIN"
  exit 1
fi

LOG=$(mktemp)
cleanup() {
  pkill -f "$BIN --mock --tui" 2>/dev/null || true
}
trap cleanup EXIT

# --mock keeps the run off the user's real Claude and Codex files, and script(1)
# hands the TUI a pty so rich renders instead of falling back to plain output.
# The bundle this runs against is the one about to be zipped, so the run must
# leave nothing behind: py2app already declines to write bytecode, and
# PYTHONDONTWRITEBYTECODE keeps it that way if that ever changes.
PYTHONDONTWRITEBYTECODE=1 script -q /dev/null "$BIN" --mock --tui >"$LOG" 2>&1 </dev/null &
# Killing the run is how this script always ends, so drop the job from the
# shell's table and keep "Terminated: 15" out of the CI log.
disown

for _ in $(seq "$TIMEOUT"); do
  sleep 1
  if grep -qE 'Traceback|ModuleNotFoundError|ImportError' "$LOG"; then
    break
  fi
  # The rounded top-left corner of the TUI's outer panel: rich only emits it
  # once a full frame has been measured and drawn.
  if grep -q '╭' "$LOG"; then
    break
  fi
done

cleanup

if grep -qE 'Traceback|ModuleNotFoundError|ImportError' "$LOG"; then
  echo "The bundled app raised an exception on launch:"
  sed -e $'s/\033\\[[0-9;?]*[a-zA-Z]//g' "$LOG" | tail -40
  exit 1
fi

if ! grep -q '╭' "$LOG"; then
  echo "The bundled app drew no TUI frame within ${TIMEOUT}s:"
  sed -e $'s/\033\\[[0-9;?]*[a-zA-Z]//g' "$LOG" | tail -40
  exit 1
fi

echo "TUI rendered from $APP with no exception."
