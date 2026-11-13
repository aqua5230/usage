# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Track seen models and Antigravity quota groups across app refreshes."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loaders import agy_quota_probe, cache_quarantine
from loaders.codex_paths import codex_home
from usage_common import pricing

SCHEMA_VERSION = 1
REGISTRY_PATH = Path.home() / ".usage" / "model_registry.json"
CODEX_MODELS_CACHE_PATH = codex_home() / "models_cache.json"

logger = logging.getLogger(__name__)


def _normalize_model_key(name: str) -> str:
    return name.strip().casefold()


def _normalize_group_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _load_registry() -> tuple[dict[str, Any] | None, bool]:
    """Load the existing registry, returning ``(payload, is_baseline_run)``."""
    try:
        with REGISTRY_PATH.open(encoding="utf-8") as handle:
            payload: object = json.load(handle)
    except FileNotFoundError:
        return (None, True)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        cache_quarantine.quarantine(REGISTRY_PATH, "model registry unreadable")
        return (None, True)

    if not isinstance(payload, dict):
        cache_quarantine.quarantine(REGISTRY_PATH, "model registry schema unreadable")
        return (None, True)

    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != SCHEMA_VERSION:
        logger.warning(
            "model registry schema mismatch in %s: expected %s, got %s; rebuilding",
            REGISTRY_PATH,
            SCHEMA_VERSION,
            schema_version,
        )
        return (None, True)

    raw_items = payload.get("items")
    if not isinstance(raw_items, dict):
        cache_quarantine.quarantine(REGISTRY_PATH, "model registry items unreadable")
        return (None, True)

    return (payload, False)


def _read_codex_catalog() -> tuple[str | None, list[str]] | None:
    """Read visible models and account identity from Codex's models cache."""
    try:
        with CODEX_MODELS_CACHE_PATH.open(encoding="utf-8") as handle:
            payload: object = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        return None

    raw_identity = payload.get("identity")
    identity = raw_identity if isinstance(raw_identity, str) and raw_identity else None

    models: list[str] = []
    for entry in raw_models:
        if not isinstance(entry, dict):
            continue
        if entry.get("visibility") != "list":
            continue
        slug = entry.get("slug")
        if isinstance(slug, str):
            stripped = slug.strip()
            if stripped:
                models.append(stripped)
    return (identity, models)


def _read_agy_groups() -> list[tuple[str, list[str]]]:
    """Read Antigravity quota groups and their model lists from disk cache."""
    try:
        quota = agy_quota_probe._read_cache()
    except (OSError, UnicodeError, ValueError):
        return []
    if quota is None:
        return []

    groups: list[tuple[str, list[str]]] = []
    for group in quota.groups:
        raw_name = getattr(group, "name", None)
        if not isinstance(raw_name, str):
            continue
        name = " ".join(raw_name.split())
        if not name:
            continue
        raw_models = getattr(group, "models", ())
        models = [model for model in raw_models if isinstance(model, str) and model]
        groups.append((name, models))
    return groups


def _collect_usage_models(entries: Sequence[Any] | None) -> list[tuple[str, str, str]]:
    """Collect unique ``(normalized_model, agent, model)`` tuples from usage entries."""
    if not entries:
        return []

    seen_pairs: set[tuple[str, str]] = set()
    for entry in entries:
        raw_model = getattr(entry, "model", None)
        if not isinstance(raw_model, str):
            continue
        raw_agent = getattr(entry, "agent_id", None)
        agent = raw_agent if isinstance(raw_agent, str) else ""
        seen_pairs.add((agent, raw_model))

    by_key: dict[str, tuple[str, str]] = {}
    for raw_agent, raw_model in seen_pairs:
        model = raw_model.strip()
        if not model or model.startswith("<"):
            continue
        normalized = model.casefold()
        if normalized == "unknown" or "orchestrator" in normalized:
            continue
        agent = raw_agent.strip() or "unknown"
        existing = by_key.get(normalized)
        if existing is None or (existing[0] == "unknown" and agent != "unknown"):
            by_key[normalized] = (agent, model)

    return [(normalized, agent, model) for normalized, (agent, model) in by_key.items()]


def _write_registry(payload: dict[str, Any]) -> None:
    temporary: str | None = None
    try:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=REGISTRY_PATH.parent,
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, REGISTRY_PATH)
        temporary = None
    finally:
        if temporary is not None and os.path.exists(temporary):
            with suppress(OSError):
                os.unlink(temporary)


def update(entries: Sequence[Any] | None = None) -> None:
    """Merge models and quota groups into ``REGISTRY_PATH`` if anything changed."""
    try:
        loaded_payload, is_baseline_run = _load_registry()
        if loaded_payload is not None:
            raw_identity = loaded_payload.get("codex_identity")
            existing_identity = (
                raw_identity if isinstance(raw_identity, str) and raw_identity else None
            )
            items: dict[str, dict[str, Any]] = {
                key: dict(value)
                for key, value in loaded_payload["items"].items()
                if isinstance(key, str) and isinstance(value, dict)
            }
        else:
            existing_identity = None
            items = {}

        now_iso = datetime.now(UTC).replace(microsecond=0).isoformat()
        # A source seen for the first time (agy probed later, Codex installed later)
        # is a baseline too; otherwise its whole catalog would read as new.
        known_sources = {item.get("source") for item in items.values()}

        for item in items.values():
            if item.get("source") == "agy_group":
                continue
            if item.get("baseline") is False:
                name = item.get("name")
                if isinstance(name, str) and name:
                    item["priced"] = pricing.is_model_priced(name)

        codex_identity = existing_identity
        codex_catalog = _read_codex_catalog()
        if codex_catalog is not None:
            catalog_identity, codex_models = codex_catalog
            identity_changed = bool(catalog_identity and catalog_identity != existing_identity)
            if catalog_identity:
                codex_identity = catalog_identity
            for model_name in codex_models:
                key = f"codex_catalog:{_normalize_model_key(model_name)}"
                if key in items:
                    continue
                items[key] = {
                    "source": "codex_catalog",
                    "agent": "codex",
                    "name": model_name,
                    "first_seen": now_iso,
                    "baseline": is_baseline_run
                    or identity_changed
                    or "codex_catalog" not in known_sources,
                    "priced": pricing.is_model_priced(model_name),
                }

        for group_name, group_models in _read_agy_groups():
            key = f"agy_group:{_normalize_group_key(group_name)}"
            existing_item = items.get(key)
            if existing_item is not None:
                existing_item["models"] = list(group_models)
                continue
            items[key] = {
                "source": "agy_group",
                "agent": "antigravity",
                "name": group_name,
                "models": list(group_models),
                "first_seen": now_iso,
                "baseline": is_baseline_run or "agy_group" not in known_sources,
                "priced": None,
            }

        for normalized, agent, model_name in _collect_usage_models(entries):
            key = f"usage_log:{normalized}"
            if key in items:
                continue
            items[key] = {
                "source": "usage_log",
                "agent": agent,
                "name": model_name,
                "first_seen": now_iso,
                "baseline": is_baseline_run or "usage_log" not in known_sources,
                "priced": pricing.is_model_priced(model_name),
            }

        new_payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "codex_identity": codex_identity,
            "items": items,
        }
        if loaded_payload is None:
            if not items and codex_identity is None and not REGISTRY_PATH.exists():
                return
        elif new_payload == loaded_payload:
            return

        _write_registry(new_payload)
    except Exception:
        logger.warning("Model registry update failed", exc_info=True)
