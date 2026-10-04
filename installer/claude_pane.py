"""Install the opt-in Claude Code pane without changing other plugins."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from i18n import t as _t
from installer import setup_hook
from usage_common.usage_lang import detect_lang

INSTALL_DIR = Path.home() / ".usage" / "claude-pane" / "usage-dash"
PLUGIN_DIRS_KEY = "CLAUDE_CODE_PLUGIN_DIRS"


def _same_path(left: str, right: str) -> bool:
    return os.path.normpath(os.path.expanduser(left)) == os.path.normpath(os.path.expanduser(right))


def _add_path(value: str, path: str) -> str:
    parts = value.split(os.pathsep) if value else []
    if not any(part and _same_path(part, path) for part in parts):
        parts.append(path)
    return os.pathsep.join(parts)


def _remove_path(value: str, path: str) -> str:
    parts = [part for part in value.split(os.pathsep) if not (part and _same_path(part, path))]
    return os.pathsep.join(parts) if any(parts) else ""


def _resolve_source() -> Path:
    paths = [
        Path(__file__).resolve().parent.parent / "claude_pane" / "usage-dash",
        Path(sys.executable).resolve().parent.parent / "Resources" / "claude_pane" / "usage-dash",
    ]
    for path in paths:
        if path.is_dir():
            return path
    raise SystemExit(_t("claude_pane_source_missing", tried=", ".join(map(str, paths))))


def _status_argv() -> list[str]:
    if getattr(sys, "frozen", False):
        resources = str(Path(sys.executable).resolve().parent.parent / "Resources")
        major, minor = sys.version_info[:2]
        bootstrap = (
            f"import sys;sys.path[:0]=[{resources!r}+'/lib/python{major}{minor}.zip',"
            f"{resources!r}+'/lib/python{major}.{minor}',"
            f"{resources!r}+'/lib/python{major}.{minor}/lib-dynload',{resources!r}];"
            "import usage_cli;sys.argv=['usage','status','--json'];usage_cli.main()"
        )
        return [
            "/usr/bin/env",
            f"PYTHONHOME={resources}",
            f"RESOURCEPATH={resources}",
            sys.executable,
            "-c",
            bootstrap,
        ]
    return [
        sys.executable,
        str(Path(__file__).resolve().parent.parent / "usage_cli.py"),
        "status",
        "--json",
    ]


def _write_sidecar() -> None:
    from i18n import I18N_PATH

    bundle = json.loads(I18N_PATH.read_text(encoding="utf-8"))
    english = bundle["en"]
    table = bundle.get(detect_lang(), english)
    strings = {
        key: table.get(key) or value
        for key, value in english.items()
        if key.startswith("claude_pane_")
    }
    setup_hook._atomic_write_text(
        INSTALL_DIR / "usage-pane.json",
        json.dumps(
            {"strings": strings, "status_argv": _status_argv()}, ensure_ascii=False, indent=2
        )
        + "\n",
    )


def _env(settings: dict[str, object]) -> dict[str, str]:
    env = settings.get("env", {})
    if not isinstance(env, dict) or not isinstance(env.get(PLUGIN_DIRS_KEY, ""), str):
        raise SystemExit(_t("claude_pane_invalid_env"))
    return env


def enable_claude_pane() -> int:
    source = _resolve_source()
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
    shutil.copytree(source, INSTALL_DIR, ignore=shutil.ignore_patterns("*.test.ts"))
    _write_sidecar()
    settings = setup_hook._load_settings()
    env = _env(settings)
    env[PLUGIN_DIRS_KEY] = _add_path(env.get(PLUGIN_DIRS_KEY, ""), str(INSTALL_DIR.absolute()))
    settings["env"] = env
    setup_hook._save_settings(settings)
    return 0


def disable_claude_pane() -> int:
    settings = setup_hook._load_settings()
    env = _env(settings)
    if PLUGIN_DIRS_KEY in env:
        value = _remove_path(env[PLUGIN_DIRS_KEY], str(INSTALL_DIR.absolute()))
        if value:
            env[PLUGIN_DIRS_KEY] = value
        else:
            env.pop(PLUGIN_DIRS_KEY)
        if not env:
            settings.pop("env", None)
        setup_hook._save_settings(settings)
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
    return 0


def is_claude_pane_enabled() -> bool:
    try:
        value = _env(setup_hook._load_settings()).get(PLUGIN_DIRS_KEY, "")
    except SystemExit:
        return False
    return INSTALL_DIR.is_dir() and any(
        part and _same_path(part, str(INSTALL_DIR.absolute())) for part in value.split(os.pathsep)
    )
