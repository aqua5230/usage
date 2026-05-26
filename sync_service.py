from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

STATUS_DIR = Path(os.path.expanduser("~/.claude"))
SETTINGS_PATH = STATUS_DIR / "settings.json"
STATE_FILE = STATUS_DIR / "sync-state.json"
COOLDOWN_SECONDS = 300  # 5 minutes


def load_remotes() -> list[str]:
    if not SETTINGS_PATH.exists():
        return []
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        remotes = data.get("usage", {}).get("remotes")
        if isinstance(remotes, list):
            return [str(r) for r in remotes if r]
    except Exception as e:
        logger.warning("Failed to load remotes from settings.json: %s", e)
    return []


def sync_devices(force: bool = False) -> tuple[bool, str]:
    """Synchronizes remote devices with the local main device.

    Returns (success, message).
    """
    remotes = load_remotes()
    if not remotes:
        return True, "No remote devices configured."

    local_hook = Path(__file__).resolve().parent / "usage_statusline.py"
    if not local_hook.exists():
        local_hook = Path(os.path.expanduser("~/.claude/usage-statusline.py"))
        if not local_hook.exists():
            return False, f"Local hook script not found: {local_hook}"

    success_hosts: list[str] = []
    failed_hosts: list[str] = []

    for host in remotes:
        try:
            # 1. Check SSH connection
            res = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", host, "echo OK"],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0 or res.stdout.strip() != "OK":
                failed_hosts.append(f"{host} (SSH unreachable)")
                continue

            # 2. Make sure remote ~/.claude directory exists
            subprocess.run(
                ["ssh", host, "mkdir -p ~/.claude"],
                check=True,
                capture_output=True,
            )

            # 3. Copy usage_statusline.py to remote
            subprocess.run(
                ["scp", str(local_hook), f"{host}:~/.claude/usage-statusline.py"],
                check=True,
                capture_output=True,
            )

            # 4. Update remote settings.json
            remote_cmd = (
                "python3 -c '\n"
                "import json, os\n"
                "p = os.path.expanduser(\"~/.claude/settings.json\")\n"
                "try:\n"
                "    with open(p) as f: d = json.load(f)\n"
                "except Exception: d = {}\n"
                "d[\"statusLine\"] = {\"type\": \"command\", "
                "\"command\": \"python3 \" + "
                "os.path.expanduser(\"~/.claude/usage-statusline.py\")}\n"
                "with open(p, \"w\") as f: json.dump(d, f, indent=2)\n"
                "'"
            )
            res = subprocess.run(
                ["ssh", host, remote_cmd],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                failed_hosts.append(
                    f"{host} (failed to update remote settings.json: {res.stderr.strip()})"
                )
                continue

            # 5. Two-way sync of projects/ directory
            # First, pull remote to local
            subprocess.run(
                [
                    "rsync",
                    "-avz",
                    "--ignore-errors",
                    "-e",
                    "ssh",
                    f"{host}:~/.claude/projects/",
                    os.path.expanduser("~/.claude/projects/"),
                ],
                check=True,
                capture_output=True,
            )
            # Second, push local to remote
            subprocess.run(
                [
                    "rsync",
                    "-avz",
                    "--ignore-errors",
                    "-e",
                    "ssh",
                    os.path.expanduser("~/.claude/projects/"),
                    f"{host}:~/.claude/projects/",
                ],
                check=True,
                capture_output=True,
            )

            # 6. Pull remote usage-status.json to local usage-status-{host}.json
            subprocess.run(
                [
                    "scp",
                    f"{host}:~/.claude/usage-status.json",
                    os.path.expanduser(f"~/.claude/usage-status-{host}.json"),
                ],
                capture_output=True,
                check=False,
            )

            success_hosts.append(host)
        except Exception as e:
            failed_hosts.append(f"{host} ({str(e)})")

    # Save last sync time
    try:
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_sync_ts": time.time()}, f)
    except Exception:
        pass

    if failed_hosts:
        msg = f"Synced: {', '.join(success_hosts)}. Failed: {', '.join(failed_hosts)}"
        return False, msg

    return True, f"Successfully synchronized devices: {', '.join(success_hosts)}"


def maybe_sync_remotes() -> None:
    """Runs sync_devices if the cooldown period has elapsed."""
    now = time.time()
    last_sync = 0.0
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
            last_sync = float(state.get("last_sync_ts", 0.0))
        except Exception:
            pass

    if now - last_sync >= COOLDOWN_SECONDS:
        logger.info("Starting background auto-sync...")
        sync_devices(force=False)
