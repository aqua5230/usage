"""Publish the CLI's local-only quota payload for standalone hooks."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

SNAPSHOT_PATH = Path.home() / ".usage/quota_snapshot.json"
logger = logging.getLogger(__name__)


def write_snapshot() -> None:
    from quota.status_payload import _status_payload

    temporary = None
    try:
        payload = _status_payload()
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=SNAPSHOT_PATH.parent, suffix=".tmp", delete=False
        ) as handle:
            temporary = handle.name
            json.dump(payload, handle)
        os.replace(temporary, SNAPSHOT_PATH)
    except (OSError, ValueError):
        logger.warning("Quota snapshot write failed", exc_info=True)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
