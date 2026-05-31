from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import main
import setup_hook
import usage_statusline_forwarder


def _patch_setup_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    hook_target = claude_dir / "usage-statusline.py"
    forwarder_target = claude_dir / "usage-statusline-forwarder.py"
    hook_source = tmp_path / "usage_statusline.py"
    forwarder_source = tmp_path / "usage_statusline_forwarder.py"
    hook_source.write_text("print('usage')\n", encoding="utf-8")
    forwarder_source.write_text("print('forwarder')\n", encoding="utf-8")

    monkeypatch.setattr(setup_hook, "CLAUDE_SETTINGS", settings)
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", hook_target)
    monkeypatch.setattr(setup_hook, "FORWARDER_TARGET", forwarder_target)
    monkeypatch.setattr(setup_hook, "STATUS_FILE", claude_dir / "usage-status.json")
    monkeypatch.setattr(setup_hook, "CODEX_CONFIG", tmp_path / ".codex" / "config.toml")
    monkeypatch.setattr(setup_hook, "CODEX_BACKUP", tmp_path / ".codex" / "usage-backup.json")
    monkeypatch.setattr(setup_hook, "_resolve_hook_source", lambda: hook_source)
    monkeypatch.setattr(setup_hook, "_resolve_forwarder_source", lambda: forwarder_source)
    monkeypatch.setattr("setup_hook.shutil.which", lambda _: "/usr/bin/python3")
    return settings, hook_target, forwarder_target


def test_install_when_no_existing_statusline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, hook_target, forwarder_target = _patch_setup_paths(monkeypatch, tmp_path)

    assert setup_hook.setup() == 0
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data["statusLine"]["command"] == f"/usr/bin/python3 {hook_target}"
    assert hook_target.exists()
    assert not forwarder_target.exists()


def test_install_when_tt_statusline_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, hook_target, forwarder_target = _patch_setup_paths(monkeypatch, tmp_path)
    legacy_name = "tt" + "-statusline.py"
    external = {"type": "command", "command": f"python3 ~/.claude/{legacy_name}"}
    settings.write_text(json.dumps({"statusLine": external}), encoding="utf-8")

    assert setup_hook.setup() == 0
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data["statusLine"]["command"] == f"/usr/bin/python3 {forwarder_target}"
    assert data["usage"]["previousStatusLine"] == external
    assert hook_target.exists()
    assert forwarder_target.exists()


def test_install_when_forwarder_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _, forwarder_target = _patch_setup_paths(monkeypatch, tmp_path)
    existing = {"type": "command", "command": f"/usr/bin/python3 {forwarder_target}"}
    settings.write_text(json.dumps({"statusLine": existing}), encoding="utf-8")

    assert setup_hook.setup() == 0
    data = json.loads(settings.read_text(encoding="utf-8"))

    assert data == {"statusLine": existing}


def test_forwarder_calls_all_hooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("a-statusline.py", "b-statusline.py", "c-statusline.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "usage-statusline-forwarder.py").write_text("", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(cmd)
        assert kwargs["input"] == '{"x": 1}'
        assert kwargs["timeout"] == usage_statusline_forwarder.TIMEOUT_SECONDS
        return SimpleNamespace(stdout=Path(cmd[1]).name + "\n")

    monkeypatch.setattr(usage_statusline_forwarder, "HOOK_DIR", str(tmp_path))
    monkeypatch.setattr("usage_statusline_forwarder.subprocess.run", fake_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"x": 1}'))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    usage_statusline_forwarder.main()

    assert {Path(call[1]).name for call in calls} == {
        "a-statusline.py",
        "b-statusline.py",
        "c-statusline.py",
    }
    assert stdout.getvalue() == "a-statusline.py\nb-statusline.py\nc-statusline.py\n"


def test_forwarder_ignores_failed_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ok = tmp_path / "ok-statusline.py"
    bad = tmp_path / "bad-statusline.py"
    ok.write_text("import sys\nsys.stdout.write('ok')\n", encoding="utf-8")
    bad.write_text("raise SystemExit(2)\n", encoding="utf-8")

    monkeypatch.setattr(usage_statusline_forwarder, "HOOK_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    usage_statusline_forwarder.main()

    assert stdout.getvalue() == "ok"


def test_health_check_triggers_repair_when_displaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, hook_target, _ = _patch_setup_paths(monkeypatch, tmp_path)
    settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "python3 other.py"}}),
        encoding="utf-8",
    )
    hook_target.write_text("print('installed')\n", encoding="utf-8")
    monkeypatch.setattr(main, "PREFERENCES_FILE", tmp_path / "usage-preferences.json")
    monkeypatch.setattr(main, "_show_repair_dialog", lambda: "repair")
    calls: list[bool] = []

    def fake_setup(*, force_forwarder: bool = False) -> int:
        calls.append(force_forwarder)
        return 0

    monkeypatch.setattr(setup_hook, "setup", fake_setup)

    main.health_check()

    assert calls == [True]


def test_save_preferences_is_atomic_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefs_file = tmp_path / "usage-preferences.json"
    prefs_file.write_text('{"existing": true}\n', encoding="utf-8")
    monkeypatch.setattr(main, "PREFERENCES_FILE", prefs_file)

    def fail_replace(src: str, dst: str | os.PathLike[str]) -> None:
        _ = src, dst
        raise OSError("replace failed")

    monkeypatch.setattr("main.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        main._save_preferences({"existing": False})

    assert prefs_file.read_text(encoding="utf-8") == '{"existing": true}\n'
    assert list(tmp_path.glob("*.tmp")) == []
