"""Install the opt-in Claude Code pane without changing other plugins."""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys
from pathlib import Path

from installer import setup_hook
from usage_common.i18n import t as _t
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


def _install_dir(mod: str) -> Path:
    return INSTALL_DIR.with_name("usage-beginner") if mod == "usage-beginner" else INSTALL_DIR


def _sidecar_name(mod: str) -> str:
    return "usage-beginner.json" if mod == "usage-beginner" else "usage-pane.json"


def _resolve_source(mod: str = "usage-dash") -> Path:
    paths = [
        Path(__file__).resolve().parent.parent / "claude_pane" / mod,
        Path(sys.executable).resolve().parent.parent / "Resources" / "claude_pane" / mod,
    ]
    for path in paths:
        if path.is_dir():
            return path
    raise SystemExit(_t("claude_pane_source_missing", tried=", ".join(map(str, paths))))


def _status_argv() -> list[str]:
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return [sys.executable, "status", "--json"]
    if getattr(sys, "frozen", False):
        resources = str(Path(sys.executable).resolve().parent.parent / "Resources")
        major, minor = sys.version_info[:2]
        bootstrap = (
            f"import sys;sys.path[:0]=[{resources!r}+'/lib/python{major}{minor}.zip',"
            f"{resources!r}+'/lib/python{major}.{minor}',"
            f"{resources!r}+'/lib/python{major}.{minor}/lib-dynload',{resources!r}];"
            "from usage_app import cli;sys.argv=['usage','status','--json'];cli.main()"
        )
        return [
            "/usr/bin/env",
            f"PYTHONHOME={resources}",
            f"RESOURCEPATH={resources}",
            sys.executable,
            "-c",
            bootstrap,
        ]
    root = str(Path(__file__).resolve().parent.parent)
    return [
        sys.executable,
        "-c",
        f"import sys;sys.path.insert(0,{root!r});from usage_app import cli;"
        "sys.argv=['usage','status','--json'];cli.main()",
    ]


def _sidecar_text(mod: str = "usage-dash") -> str:
    from usage_common.i18n import I18N_PATH

    bundle = json.loads(I18N_PATH.read_text(encoding="utf-8"))
    english = bundle["en"]
    table = bundle.get(detect_lang(), english)
    strings = {
        key: table.get(key) or value
        for key, value in english.items()
        if key.startswith("claude_beginner_" if mod == "usage-beginner" else "claude_pane_")
    }
    return (
        json.dumps(
            (
                {"strings": strings, "lang": detect_lang()}
                if mod == "usage-beginner"
                else {"strings": strings, "status_argv": _status_argv()}
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def _write_sidecar(mod: str = "usage-dash") -> None:
    setup_hook._atomic_write_text(_install_dir(mod) / _sidecar_name(mod), _sidecar_text(mod))


def _copy_pane(mod: str = "usage-dash") -> None:
    source = _resolve_source(mod)
    if _install_dir(mod).exists():
        shutil.rmtree(_install_dir(mod))
    shutil.copytree(source, _install_dir(mod), ignore=shutil.ignore_patterns("*.test.ts"))
    _write_sidecar() if mod == "usage-dash" else _write_sidecar(mod)


def _installed_is_current(mod: str = "usage-dash") -> bool:
    source = _resolve_source(mod)
    shipped = {
        path.relative_to(source)
        for path in source.rglob("*")
        if path.is_file() and not path.name.endswith(".test.ts")
    }
    # Claude Code writes its own type stubs under .claude-plugin/types; they are not ours.
    generated = Path(".claude-plugin", "types")
    installed = {
        path.relative_to(_install_dir(mod))
        for path in _install_dir(mod).rglob("*")
        if path.is_file() and generated not in path.relative_to(_install_dir(mod)).parents
    } - {Path(_sidecar_name(mod))}
    if shipped != installed:
        return False
    if not all(
        filecmp.cmp(source / path, _install_dir(mod) / path, shallow=False) for path in shipped
    ):
        return False
    try:
        return (_install_dir(mod) / _sidecar_name(mod)).read_text(
            encoding="utf-8"
        ) == _sidecar_text(mod)
    except OSError:
        return False


def _env(settings: dict[str, object]) -> dict[str, str]:
    env = settings.get("env", {})
    if not isinstance(env, dict) or not isinstance(env.get(PLUGIN_DIRS_KEY, ""), str):
        raise SystemExit(_t("claude_pane_invalid_env"))
    return env


def enable_claude_pane(mod: str = "usage-dash") -> int:
    _copy_pane() if mod == "usage-dash" else _copy_pane(mod)
    settings = setup_hook._load_settings()
    env = _env(settings)
    env[PLUGIN_DIRS_KEY] = _add_path(
        env.get(PLUGIN_DIRS_KEY, ""), str(_install_dir(mod).absolute())
    )
    settings["env"] = env
    setup_hook._save_settings(settings)
    return 0


def is_fullscreen_layout() -> bool:
    return setup_hook._load_settings().get("tui") == "fullscreen"


def enable_fullscreen_layout() -> None:
    settings = setup_hook._load_settings()
    settings["tui"] = "fullscreen"
    usage = settings.get("usage")
    if not isinstance(usage, dict):
        usage = {}
        settings["usage"] = usage
    usage["claudePaneSetFullscreen"] = True
    setup_hook._save_settings(settings)


def disable_claude_pane(mod: str = "usage-dash") -> int:
    settings = setup_hook._load_settings()
    env = _env(settings)
    changed = False
    if PLUGIN_DIRS_KEY in env:
        value = _remove_path(env[PLUGIN_DIRS_KEY], str(_install_dir(mod).absolute()))
        if value:
            env[PLUGIN_DIRS_KEY] = value
        else:
            env.pop(PLUGIN_DIRS_KEY)
        if not env:
            settings.pop("env", None)
        changed = True
    usage = settings.get("usage")
    if (
        mod == "usage-dash"
        and isinstance(usage, dict)
        and usage.get("claudePaneSetFullscreen") is True
    ):
        if settings.get("tui") == "fullscreen":
            settings.pop("tui")
        usage.pop("claudePaneSetFullscreen")
        if not usage:
            settings.pop("usage")
        changed = True
    if changed:
        setup_hook._save_settings(settings)
    if _install_dir(mod).exists():
        shutil.rmtree(_install_dir(mod))
    return 0


def is_claude_pane_enabled(mod: str = "usage-dash") -> bool:
    try:
        value = _env(setup_hook._load_settings()).get(PLUGIN_DIRS_KEY, "")
    except SystemExit:
        return False
    return _install_dir(mod).is_dir() and any(
        part and _same_path(part, str(_install_dir(mod).absolute()))
        for part in value.split(os.pathsep)
    )


def refresh_claude_pane() -> None:
    """Re-copy an enabled pane whose files differ from this build's, e.g. after an app upgrade."""
    if is_claude_pane_enabled() and not _installed_is_current():
        _copy_pane()
    if is_claude_beginner_enabled() and not _installed_is_current("usage-beginner"):
        _copy_pane("usage-beginner")


def enable_claude_beginner() -> int:
    return enable_claude_pane("usage-beginner")


def disable_claude_beginner() -> int:
    return disable_claude_pane("usage-beginner")


def is_claude_beginner_enabled() -> bool:
    return is_claude_pane_enabled("usage-beginner")
