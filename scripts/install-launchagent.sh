#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python3"
PLIST_NAME="com.lollapalooza.usage.plist"
TARGET_PLIST="${HOME}/Library/LaunchAgents/${PLIST_NAME}"
LEGACY_LABEL="com.lollapalooza.usag"
LEGACY_PLIST="${HOME}/Library/LaunchAgents/${LEGACY_LABEL}.plist"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "錯誤：找不到虛擬環境中的 Python ($VENV_PYTHON)"
    exit 1
fi

if launchctl print "gui/$(id -u)/${LEGACY_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/${LEGACY_LABEL}" 2>/dev/null || true
fi
rm -f "${LEGACY_PLIST}"

mkdir -p "${HOME}/Library/Logs/usage"

echo "正在生成設定檔..."
sed -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    -e "s|__VENV_PYTHON__|${VENV_PYTHON}|g" \
    -e "s|__HOME__|${HOME}|g" \
    "${SCRIPT_DIR}/${PLIST_NAME}" > "${TARGET_PLIST}"

echo "正在載入 LaunchAgent..."
launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
launchctl load "${TARGET_PLIST}"

echo "ℹ 已清掉舊 ${LEGACY_LABEL} LaunchAgent（如果有）"
echo "✓ 已安裝，下次登入會自動啟動。手動測試：launchctl start com.lollapalooza.usage"
