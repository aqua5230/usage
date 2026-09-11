# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

import usage_client
from installer import setup_hook
from loaders import claude_paths


@pytest.fixture(autouse=True)
def _clear_claude_path_cache() -> Iterator[None]:
    claude_paths.cache_clear()
    yield
    claude_paths.cache_clear()


def test_environment_value_takes_priority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "configured"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(configured))
    monkeypatch.setattr(
        "loaders.claude_paths.subprocess.run",
        lambda *args, **kwargs: pytest.fail("launchctl must not run"),
    )

    assert claude_paths.claude_config_dirs() == [configured]
    assert claude_paths.claude_home() == configured


def test_comma_separated_value_strips_expands_and_drops_empty_parts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", " ~/a , , ~/b ")

    assert claude_paths.claude_config_dirs() == [tmp_path / "a", tmp_path / "b"]


def test_launchctl_value_is_used_when_environment_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "launchctl-config"
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=f"{configured}\n")

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")
    monkeypatch.setattr("loaders.claude_paths.sys.platform", "darwin")
    monkeypatch.setattr("loaders.claude_paths.subprocess.run", fake_run)

    assert claude_paths.claude_config_dirs() == [configured]
    assert calls == [
        (
            ["launchctl", "getenv", "CLAUDE_CONFIG_DIR"],
            {
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "timeout": 2,
                "stdin": subprocess.DEVNULL,
            },
        )
    ]


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout="ignored"),
        SimpleNamespace(returncode=0, stdout=""),
        SimpleNamespace(returncode=0, stdout=","),
    ],
)
def test_empty_or_failed_launchctl_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    result: SimpleNamespace,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("loaders.claude_paths.sys.platform", "darwin")
    monkeypatch.setattr(
        "loaders.claude_paths.subprocess.run", lambda *args, **kwargs: result
    )

    assert claude_paths.claude_config_dirs() == [tmp_path / ".claude"]


@pytest.mark.parametrize(
    "error",
    [OSError("launchctl failed"), subprocess.TimeoutExpired("launchctl", 2)],
)
def test_launchctl_exception_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: Exception,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("loaders.claude_paths.sys.platform", "darwin")

    def fail(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr("loaders.claude_paths.subprocess.run", fail)

    assert claude_paths.claude_config_dirs() == [tmp_path / ".claude"]


def test_non_darwin_does_not_call_launchctl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("loaders.claude_paths.sys.platform", "linux")
    monkeypatch.setattr(
        "loaders.claude_paths.subprocess.run",
        lambda *args, **kwargs: pytest.fail("launchctl must not run"),
    )

    assert claude_paths.claude_config_dirs() == [tmp_path / ".claude"]


def test_result_is_cached_until_cache_is_cleared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(first))

    assert claude_paths.claude_home() == first
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(second))
    assert claude_paths.claude_home() == first

    claude_paths.cache_clear()
    assert claude_paths.claude_home() == second


def test_claude_json_sits_inside_any_configured_dir_and_beside_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("loaders.claude_paths.sys.platform", "linux")
    assert claude_paths.claude_json_path() == tmp_path / ".claude.json"
    assert usage_client._claude_json_file() == str(tmp_path / ".claude.json")

    # Claude Code keys on whether the variable is set, not on its value.
    claude_paths.cache_clear()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    assert claude_paths.claude_json_path() == tmp_path / ".claude" / ".claude.json"

    claude_paths.cache_clear()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "custom"))
    assert usage_client._claude_json_file() == str(tmp_path / "custom" / ".claude.json")


def test_setup_without_config_dir_writes_default_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixed_dir = tmp_path / ".claude"
    fixed_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("loaders.claude_paths.sys.platform", "linux")
    hook_source = tmp_path / "hook-source.py"
    hook_source.write_text("print('hook')\n", encoding="utf-8")
    hook_target = fixed_dir / "usage-statusline.py"
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", hook_target)
    monkeypatch.setattr(
        setup_hook, "FORWARDER_TARGET", fixed_dir / "usage-statusline-forwarder.py"
    )
    monkeypatch.setattr(setup_hook, "STATUS_FILE", fixed_dir / "usage-status.json")
    monkeypatch.setattr(setup_hook, "LEGACY_HOOK_TARGET", fixed_dir / "usag-statusline.py")
    monkeypatch.setattr(setup_hook, "LEGACY_STATUS_FILE", fixed_dir / "usag-status.json")
    monkeypatch.setattr(setup_hook, "LEGACY_TT_HOOK_TARGET", fixed_dir / "tt-statusline.py")
    monkeypatch.setattr(setup_hook, "_resolve_hook_source", lambda: hook_source)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/python3")

    assert setup_hook.setup() == 0

    settings = json.loads((fixed_dir / "settings.json").read_text(encoding="utf-8"))
    command = settings["statusLine"]["command"]
    # Windows quotes the path with backslashes or writes it with forward slashes.
    assert str(hook_target) in command or hook_target.as_posix() in command


def test_setup_uses_relocated_settings_but_usage_reads_fixed_status_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_home = tmp_path / "home"
    fixed_dir = user_home / ".claude"
    relocated_dir = tmp_path / "claude-personal"
    fixed_dir.mkdir(parents=True)
    relocated_dir.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(relocated_dir))
    claude_paths.cache_clear()

    hook_source = tmp_path / "hook-source.py"
    hook_source.write_text("print('hook')\n", encoding="utf-8")
    hook_target = fixed_dir / "usage-statusline.py"
    status_file = fixed_dir / "usage-status.json"
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", hook_target)
    monkeypatch.setattr(
        setup_hook, "FORWARDER_TARGET", fixed_dir / "usage-statusline-forwarder.py"
    )
    monkeypatch.setattr(setup_hook, "STATUS_FILE", status_file)
    monkeypatch.setattr(setup_hook, "LEGACY_HOOK_TARGET", fixed_dir / "usag-statusline.py")
    monkeypatch.setattr(setup_hook, "LEGACY_STATUS_FILE", fixed_dir / "usag-status.json")
    monkeypatch.setattr(setup_hook, "LEGACY_TT_HOOK_TARGET", fixed_dir / "tt-statusline.py")
    monkeypatch.setattr(setup_hook, "_resolve_hook_source", lambda: hook_source)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/python3")

    assert setup_hook.setup() == 0

    settings_path = relocated_dir / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert hook_target.as_posix() in settings["statusLine"]["command"]
    assert not (fixed_dir / "settings.json").exists()

    status_file.write_text(
        json.dumps(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 12},
                    "seven_day": {"used_percentage": 34},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(usage_client, "STATUS_FILE", str(status_file))
    monkeypatch.setattr(
        usage_client, "LEGACY_STATUS_FILE", str(fixed_dir / "usag-status.json")
    )
    monkeypatch.setattr(usage_client, "TT_STATUS_FILE", str(fixed_dir / "tt-status.json"))

    loaded = usage_client._read_status_file()
    assert loaded is not None
    assert loaded[0]["rate_limits"]["five_hour"]["used_percentage"] == 12


def test_setup_does_not_create_a_missing_configured_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_home = tmp_path / "home"
    fixed_dir = user_home / ".claude"
    relocated_dir = tmp_path / "missing-config"
    fixed_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(relocated_dir))
    claude_paths.cache_clear()
    monkeypatch.setattr(setup_hook, "HOOK_TARGET", fixed_dir / "usage-statusline.py")
    monkeypatch.setattr(
        setup_hook, "LEGACY_HOOK_TARGET", fixed_dir / "usag-statusline.py"
    )
    monkeypatch.setattr(setup_hook, "LEGACY_STATUS_FILE", fixed_dir / "usag-status.json")

    assert setup_hook.setup() == 1
    assert not relocated_dir.exists()
