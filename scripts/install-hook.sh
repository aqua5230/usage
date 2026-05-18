#!/usr/bin/env bash
# 一鍵把 usage 的 Claude Code statusLine hook 裝起來。
# 給只有下載 usage.app、沒有原始碼的使用者用：
#   bash <(curl -fsSL https://raw.githubusercontent.com/aqua5230/usage/main/scripts/install-hook.sh)
#
# 做的事：
#   1. 下載 usage_statusline.py 到 ~/.claude/usage-statusline.py
#   2. 把 ~/.claude/settings.json 的 statusLine 指向它
#   3. 如果原本有自訂 statusLine，備份到 settings.usage.previousStatusLine
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/aqua5230/usage/main"
CLAUDE_DIR="${HOME}/.claude"
HOOK_PATH="${CLAUDE_DIR}/usage-statusline.py"
SETTINGS_PATH="${CLAUDE_DIR}/settings.json"

mkdir -p "${CLAUDE_DIR}"

echo "↓ 下載 hook 腳本到 ${HOOK_PATH}"
curl -fsSL "${REPO_RAW}/usage_statusline.py" -o "${HOOK_PATH}"
chmod +x "${HOOK_PATH}"

PYTHON_BIN="$(command -v python3 || echo /usr/bin/python3)"

echo "✎ 更新 ${SETTINGS_PATH}"
HOOK_PATH="${HOOK_PATH}" SETTINGS_PATH="${SETTINGS_PATH}" PYTHON_BIN="${PYTHON_BIN}" \
"${PYTHON_BIN}" - <<'PY'
import json, os

settings_path = os.environ["SETTINGS_PATH"]
hook_path = os.environ["HOOK_PATH"]
python_bin = os.environ["PYTHON_BIN"]

data = {}
if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        data = json.load(f)
if not isinstance(data, dict):
    raise SystemExit(f"❌ {settings_path} 不是 JSON object，請手動處理")

existing = data.get("statusLine")
if isinstance(existing, dict) and "usage-statusline" not in str(existing.get("command", "")):
    data.setdefault("usage", {})["previousStatusLine"] = existing
    print(f"ℹ 已備份原 statusLine 到 settings.usage.previousStatusLine")

data["statusLine"] = {"type": "command", "command": f'{python_bin} {hook_path}'}

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY

echo
echo "✓ 安裝完成"
echo "→ 請完全結束 Claude Code（Cmd+Q）再重新打開一次，"
echo "  然後在 usage 視窗按一下「立即更新」，數字就會跑出來。"
