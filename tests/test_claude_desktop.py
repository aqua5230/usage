from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loaders import claude_desktop as desktop

NOW = 2_000_000_000.0


def _history(path: Path, samples: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "samples": samples}), encoding="utf-8")


def _sample(age: float = 0, org: str = "org-a", **usage: object) -> dict[str, Any]:
    return {"t": (NOW - age) * 1000, "org": org, "u": usage or {"fh": 8, "sd": 0}}


def test_reads_latest_observation_not_array_order(tmp_path: Path) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, [_sample(fh=11, sd=0), _sample(age=900, fh=8, sd=0)])
    quota = desktop._read_history(path, NOW)
    assert quota == desktop.DesktopQuota(11, 0, NOW)


def test_org_switch_never_fills_window_from_previous_org(tmp_path: Path) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, [_sample(age=10, sd=99), _sample(org="org-b", fh=12)])
    assert desktop._read_history(path, NOW) == desktop.DesktopQuota(12, None, NOW)


def test_invalid_latest_org_does_not_restore_previous_org(tmp_path: Path) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, [_sample(age=10), _sample(org="org-b", fh="invalid")])
    assert desktop._read_history(path, NOW) is None


def test_equal_timestamps_use_last_org_observation(tmp_path: Path) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, [_sample(org="a", fh=99), _sample(org="b", fh=12)])
    assert desktop._read_history(path, NOW) == desktop.DesktopQuota(12, None, NOW)


def test_missing_or_unreadable_history_does_not_crash(tmp_path: Path) -> None:
    assert desktop._read_history(tmp_path / "missing.json", NOW) is None
    assert desktop._read_history(tmp_path, NOW) is None


@pytest.mark.parametrize("value", [True, False, -1, 101, "8", None, float("nan"), float("inf")])
def test_invalid_utilization_is_not_a_quota(tmp_path: Path, value: object) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, [_sample(fh=value)])
    assert desktop._read_history(path, NOW) is None


@pytest.mark.parametrize("age", [desktop.MAX_AGE_SECONDS + 1, -61])
def test_expired_or_future_observation_is_rejected(tmp_path: Path, age: float) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    _history(path, [_sample(age=age)])
    assert desktop._read_history(path, NOW) is None


@pytest.mark.parametrize("raw", [b'{"version":', b"\xff", b"[]", b'{"version":3,"samples":[]}'])
def test_incomplete_or_unknown_format_is_read_only(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    path.write_bytes(raw)
    assert desktop._read_history(path, NOW) is None
    assert path.read_bytes() == raw


def test_file_size_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    path.write_bytes(b" " * 33)
    monkeypatch.setattr(desktop, "MAX_FILE_BYTES", 32)
    assert desktop._read_history(path, NOW) is None


@pytest.mark.parametrize("version", [1, 2])
def test_supported_desktop_history_versions(tmp_path: Path, version: int) -> None:
    path = tmp_path / desktop.HISTORY_NAME
    path.write_text(json.dumps({"version": version, "samples": [_sample()]}), encoding="utf-8")
    assert desktop._read_history(path, NOW) == desktop.DesktopQuota(8, 0, NOW)


def test_polls_replacement_and_chooses_newest_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "regular.json", tmp_path / "store.json"
    monkeypatch.setattr(desktop, "desktop_history_paths", lambda: (first, second))
    _history(first, [_sample(age=900)])
    _history(second, [_sample(fh=11, sd=0)])
    assert desktop.load_desktop_quota(NOW) == desktop.DesktopQuota(11, 0, NOW)
    _history(second, [_sample(age=-1, fh=25, sd=1)])
    assert desktop.load_desktop_quota(NOW + 1) == desktop.DesktopQuota(25, 1, NOW + 1)
    assert desktop.load_desktop_quota(NOW + desktop.MAX_AGE_SECONDS + 2) is None


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_standard_install_paths(
    platform: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("loaders.claude_desktop.sys.platform", platform)
    for key in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(desktop, "desktop_history_paths", _REAL_PATHS)
    if platform == "win32":
        store = tmp_path / "AppData/Local/Packages/Claude_test/LocalCache/Roaming/Claude"
        store.mkdir(parents=True)
        assert desktop.desktop_history_paths() == (
            tmp_path / "AppData/Roaming/Claude" / desktop.HISTORY_NAME,
            store / desktop.HISTORY_NAME,
        )
    elif platform == "darwin":
        assert desktop.desktop_history_paths() == (
            tmp_path / "Library/Application Support/Claude" / desktop.HISTORY_NAME,
        )
    else:
        assert desktop.desktop_history_paths() == (
            tmp_path / ".config/Claude" / desktop.HISTORY_NAME,
        )


_REAL_PATHS = desktop.desktop_history_paths


def test_windows_appdata_environment_and_store_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roaming, local = tmp_path / "roaming", tmp_path / "local"
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr("loaders.claude_desktop.sys.platform", "win32")
    monkeypatch.setattr(desktop, "desktop_history_paths", _REAL_PATHS)
    package = local / "Packages/Claude_test"
    package.mkdir(parents=True)
    (local / "Packages/Other_app").mkdir()
    assert desktop.desktop_history_paths() == (
        roaming / "Claude" / desktop.HISTORY_NAME,
        package / "LocalCache/Roaming/Claude" / desktop.HISTORY_NAME,
    )


def test_linux_xdg_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("loaders.claude_desktop.sys.platform", "linux")
    monkeypatch.setattr(desktop, "desktop_history_paths", _REAL_PATHS)
    assert desktop.desktop_history_paths() == (tmp_path / "Claude" / desktop.HISTORY_NAME,)
