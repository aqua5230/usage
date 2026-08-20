import sys
import sysconfig
import tomllib
from pathlib import Path

from pytest import MonkeyPatch

import i18n

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_i18n_json_declared_as_wheel_data_file() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "i18n.json" in pyproject["tool"]["setuptools"]["data-files"]["share/usage"]


def test_packaged_resource_path_prefers_wheel_data_dir(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.delenv("RESOURCEPATH", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sysconfig, "get_path", lambda _name: str(tmp_path))
    source_path = tmp_path / "source" / "i18n.json"
    wheel_path = tmp_path / "share" / "usage" / "i18n.json"
    wheel_path.parent.mkdir(parents=True)
    wheel_path.write_text("{}", encoding="utf-8")

    assert i18n.packaged_resource_path("i18n.json", source_path) == wheel_path

    wheel_path.unlink()
    assert i18n.packaged_resource_path("i18n.json", source_path) == source_path
