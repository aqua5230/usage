from __future__ import annotations

import ast
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from installer import claude_pane as pane
from installer import setup_hook


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    from loaders import cache_quarantine

    settings = tmp_path / "claude" / "settings.json"
    monkeypatch.setattr(setup_hook, "_claude_settings_path", lambda: settings)
    monkeypatch.setattr(pane, "INSTALL_DIR", tmp_path / "installed" / "usage-dash")
    monkeypatch.setattr(cache_quarantine, "QUARANTINE_DIR", tmp_path / "quarantine")
    monkeypatch.setattr(pane, "detect_lang", lambda: "zh-TW")
    return settings


@pytest.mark.parametrize("existing", [None, "/someone/plugin", "ours", "tilde"])
def test_enable_preserves_paths(
    isolated: Path, monkeypatch: pytest.MonkeyPatch, existing: str | None
) -> None:
    path = str(pane.INSTALL_DIR)
    if existing == "tilde":
        monkeypatch.setenv("HOME", str(pane.INSTALL_DIR.parent))
        monkeypatch.setenv("USERPROFILE", str(pane.INSTALL_DIR.parent))
        existing = "~/usage-dash"
    elif existing == "ours":
        existing = path
    before: dict[str, object] = {"other": {"keep": True}}
    if existing is not None:
        before["env"] = {pane.PLUGIN_DIRS_KEY: existing, "OTHER": "keep"}
    setup_hook._save_settings(before)
    assert pane.enable_claude_pane() == 0
    result = setup_hook._load_settings()
    value = result["env"][pane.PLUGIN_DIRS_KEY]
    assert value == (
        existing
        if existing in (path, "~/usage-dash")
        else os.pathsep.join(filter(None, [existing, path]))
    )
    assert result["other"] == before["other"]
    if existing is not None:
        assert result["env"]["OTHER"] == "keep"
    assert pane.is_claude_pane_enabled()
    assert not list(pane.INSTALL_DIR.rglob("*.test.ts"))
    assert not (pane.INSTALL_DIR / ".claude-plugin" / "types").exists()


@pytest.mark.parametrize("others", [True, False])
@pytest.mark.parametrize("keep_env", [True, False])
def test_disable_only_ours(isolated: Path, others: bool, keep_env: bool) -> None:
    pane.enable_claude_pane()
    env = {
        pane.PLUGIN_DIRS_KEY: os.pathsep.join(
            ["/other", str(pane.INSTALL_DIR), "/another"] if others else [str(pane.INSTALL_DIR)]
        )
    }
    if keep_env:
        env["OTHER"] = "keep"
    setup_hook._save_settings({"env": env, "other": "keep"})
    assert pane.disable_claude_pane() == 0
    result = setup_hook._load_settings()
    assert result["other"] == "keep"
    if others:
        assert result["env"][pane.PLUGIN_DIRS_KEY] == os.pathsep.join(["/other", "/another"])
    elif keep_env:
        assert result["env"] == {"OTHER": "keep"}
    else:
        assert "env" not in result
    assert not pane.INSTALL_DIR.exists()
    assert not pane.is_claude_pane_enabled()


def test_tilde_disable_and_reinstall(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(pane.INSTALL_DIR.parent))
    monkeypatch.setenv("USERPROFILE", str(pane.INSTALL_DIR.parent))
    pane.enable_claude_pane()
    old = pane.INSTALL_DIR / "old.txt"
    old.write_text("obsolete")
    (pane.INSTALL_DIR / "hooks" / "quota.ts").write_text("modified")
    pane.enable_claude_pane()
    assert not old.exists()
    assert "modified" not in (pane.INSTALL_DIR / "hooks" / "quota.ts").read_text(encoding="utf-8")
    setup_hook._save_settings({"env": {pane.PLUGIN_DIRS_KEY: "~/usage-dash/"}})
    assert pane.is_claude_pane_enabled()
    pane.disable_claude_pane()
    assert setup_hook._load_settings() == {}


@pytest.mark.parametrize(
    "frozen",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(sys.platform == "win32", reason="macOS .app bundle paths"),
        ),
    ],
)
def test_sidecar(isolated: Path, monkeypatch: pytest.MonkeyPatch, frozen: bool) -> None:
    import i18n

    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if frozen:
        monkeypatch.setattr(sys, "executable", "/tmp/A space's/usage.app/Contents/MacOS/usage")
        monkeypatch.setattr(sys, "version_info", (3, 14, 0))
    pane.enable_claude_pane()
    sidecar = json.loads((pane.INSTALL_DIR / "usage-pane.json").read_text(encoding="utf-8"))
    bundle = json.loads(i18n.I18N_PATH.read_text(encoding="utf-8"))
    assert sidecar["strings"] == {
        key: value for key, value in bundle["zh-TW"].items() if key.startswith("claude_pane_")
    }
    argv = sidecar["status_argv"]
    if frozen:
        resources = Path(sys.executable).resolve().parent.parent / "Resources"
        assert argv[:5] == [
            "/usr/bin/env",
            f"PYTHONHOME={resources}",
            f"RESOURCEPATH={resources}",
            sys.executable,
            "-c",
        ]
        assert len(argv) == 6
        tree = ast.parse(argv[5])
        paths = tree.body[1]
        assert isinstance(paths, ast.Assign)
        # Execute only the path expression, never the status command.
        actual = eval(compile(ast.Expression(paths.value), "bootstrap", "eval"))
        assert actual == [
            str(resources / "lib/python314.zip"),
            str(resources / "lib/python3.14"),
            str(resources / "lib/python3.14/lib-dynload"),
            str(resources),
        ]
        assert "sys.argv=['usage','status','--json'];usage_cli.main()" in argv[5]
    else:
        assert argv[0] == sys.executable
        assert argv[1:] == [
            str(Path(pane.__file__).resolve().parent.parent / "usage_cli.py"),
            "status",
            "--json",
        ]


@pytest.mark.parametrize(
    "value", ["", os.pathsep, "/other" + os.pathsep, "/pane/", "/other" + os.pathsep + "/pane/"]
)
def test_path_boundaries(value: str) -> None:
    added = pane._add_path(value, "/pane")
    assert pane._add_path(added, "/pane") == added
    removed = pane._remove_path(added, "/pane")
    assert not any(part and pane._same_path(part, "/pane") for part in removed.split(os.pathsep))
    if "/other" in value:
        assert "/other" in removed.split(os.pathsep)
    else:
        assert removed == ""


def test_bundled_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pane, "__file__", str(tmp_path / "lib/python313.zip/installer/pane.py"))
    executable = tmp_path / "usage.app/Contents/MacOS/usage"
    monkeypatch.setattr(sys, "executable", str(executable))
    source = executable.parent.parent / "Resources/claude_pane/usage-dash"
    source.mkdir(parents=True)
    assert pane._resolve_source() == source


def test_packaging_and_default_strings() -> None:
    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "setup_app.py").read_text(encoding="utf-8"))
    resources = next(
        value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "resources"
    )
    assert "claude_pane" in ast.literal_eval(resources)
    strings = (root / "claude_pane/usage-dash/hooks/strings.ts").read_text(encoding="utf-8")
    defaults = json.loads(strings.split("= ", 1)[1].split("\nlet strings", 1)[0])
    english = json.loads((root / "i18n.json").read_text(encoding="utf-8"))["en"]
    assert all(english[key] == value for key, value in defaults.items())


@pytest.mark.parametrize("env", [None, "bad", {pane.PLUGIN_DIRS_KEY: 42}])
def test_invalid_env_not_overwritten(isolated: Path, env: object) -> None:
    setup_hook._save_settings({"env": env})
    before = isolated.read_bytes()
    with pytest.raises(SystemExit):
        pane.enable_claude_pane()
    assert isolated.read_bytes() == before
    assert (pane.INSTALL_DIR / "usage-pane.json").is_file()


def test_missing_source_preserves_install(
    isolated: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pane.enable_claude_pane()
    before = isolated.read_bytes()
    monkeypatch.setattr(pane, "__file__", str(tmp_path / "absent/installer/pane.py"))
    monkeypatch.setattr(sys, "executable", str(tmp_path / "absent/app/MacOS/usage"))
    with pytest.raises(SystemExit):
        pane.enable_claude_pane()
    assert isolated.read_bytes() == before
    assert pane.INSTALL_DIR.is_dir()


def test_uses_platform_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "pathsep", ";")
    assert pane._add_path("/other;/pane/", "/pane") == "/other;/pane/"
    assert pane._remove_path("/other;/pane/", "/pane") == "/other"


def test_status_argv_uses_windows_frozen_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    executable = r"C:\\Program Files\\usage\\usage.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", executable)

    assert pane._status_argv() == [executable, "status", "--json"]


def test_missing_sidecar_language_falls_back(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import i18n

    monkeypatch.setattr(pane, "detect_lang", lambda: "missing")
    pane.enable_claude_pane()
    strings = json.loads((pane.INSTALL_DIR / "usage-pane.json").read_text(encoding="utf-8"))[
        "strings"
    ]
    assert (
        strings["claude_pane_title"]
        == json.loads(i18n.I18N_PATH.read_text(encoding="utf-8"))["en"]["claude_pane_title"]
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS menu action")
@pytest.mark.parametrize("enabled,code", [(False, 0), (True, 0), (False, 1), (True, 1)])
def test_toggle_reports_result(monkeypatch: pytest.MonkeyPatch, enabled: bool, code: int) -> None:
    from menubar import actions

    class App:
        language = "en"

        def performSelectorOnMainThread_withObject_waitUntilDone_(
            self, selector: str, result: object, wait: bool
        ) -> None:
            assert selector == "_finishClaudePane:"
            assert result == {"ok": code == 0, "enabled": not enabled, "output": ""}
            assert wait is False

    calls: list[str] = []

    def enable() -> int:
        calls.append("enable")
        return code

    def disable() -> int:
        calls.append("disable")
        return code

    monkeypatch.setattr(pane, "is_claude_pane_enabled", lambda: enabled)
    monkeypatch.setattr(pane, "enable_claude_pane", enable)
    monkeypatch.setattr(pane, "disable_claude_pane", disable)
    actions.toggle_claude_pane_in_background(App())
    assert calls == ["disable" if enabled else "enable"]


def test_enable_installs_before_loading_settings(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pane.INSTALL_DIR.mkdir(parents=True)
    calls = Mock()
    for owner, name in [
        (shutil, "rmtree"),
        (shutil, "copytree"),
        (pane, "_write_sidecar"),
        (setup_hook, "_load_settings"),
        (setup_hook, "_save_settings"),
    ]:
        wrapped = Mock(wraps=getattr(owner, name))
        calls.attach_mock(wrapped, name)
        monkeypatch.setattr(owner, name, wrapped)
    assert pane.enable_claude_pane() == 0
    order = [call[0] for call in calls.mock_calls]
    assert order[0] == "rmtree"
    assert order[1:-3] and all(name == "copytree" for name in order[1:-3])
    assert order[-3:] == ["_write_sidecar", "_load_settings", "_save_settings"]


def test_disable_saves_before_removing_install(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pane.enable_claude_pane()
    calls = Mock()
    for owner, name in [
        (setup_hook, "_load_settings"),
        (setup_hook, "_save_settings"),
        (shutil, "rmtree"),
    ]:
        wrapped = Mock(wraps=getattr(owner, name))
        calls.attach_mock(wrapped, name)
        monkeypatch.setattr(owner, name, wrapped)
    assert pane.disable_claude_pane() == 0
    assert [call[0] for call in calls.mock_calls] == ["_load_settings", "_save_settings", "rmtree"]


def test_refresh_skips_when_disabled(isolated: Path) -> None:
    pane.refresh_claude_pane()
    assert not pane.INSTALL_DIR.exists()


def test_refresh_leaves_current_install_alone(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pane.enable_claude_pane()
    generated = pane.INSTALL_DIR / ".claude-plugin" / "types" / "claude-code" / "index.d.ts"
    generated.parent.mkdir(parents=True)
    generated.write_text("// written by Claude Code\n")
    rmtree = Mock()
    monkeypatch.setattr(shutil, "rmtree", rmtree)
    pane.refresh_claude_pane()
    rmtree.assert_not_called()
    assert generated.exists()


@pytest.mark.parametrize("change", ["edited", "extra", "missing", "language"])
def test_refresh_recopies_stale_install(
    isolated: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    pane.enable_claude_pane()
    register = pane.INSTALL_DIR / "hooks" / "register.tsx"
    expected = register.read_bytes()
    if change == "edited":
        register.write_text("// old build\n")
    elif change == "extra":
        (pane.INSTALL_DIR / "hooks" / "removed.ts").write_text("// dropped upstream\n")
    elif change == "missing":
        register.unlink()
    else:
        monkeypatch.setattr(pane, "detect_lang", lambda: "ja")
    pane.refresh_claude_pane()
    assert register.read_bytes() == expected
    assert not (pane.INSTALL_DIR / "hooks" / "removed.ts").exists()
    assert pane._installed_is_current()


def test_update_check_survives_pane_refresh_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import usage_diagnosis_snapshot
    from menubar import update as menubar_update

    def fail() -> None:
        raise SystemExit("source missing")

    monkeypatch.setattr(usage_diagnosis_snapshot, "maybe_schedule_refresh", Mock())
    monkeypatch.setattr(pane, "refresh_claude_pane", fail)
    app = Mock()
    menubar_update.maybe_check_update_in_background(app)
    app._check_update_in_background.assert_called_once()
