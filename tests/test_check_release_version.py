from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_release_version",
    Path(__file__).resolve().parent.parent / "scripts" / "check_release_version.py",
)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


@pytest.mark.parametrize("published", [[], ["0.34.11"]])
def test_release_rejects_mismatched_project_version_before_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    published: list[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.34.11"\n')
    monkeypatch.setattr(check, "__file__", str(tmp_path / "scripts" / "check_release_version.py"))
    queried = []

    def versions(_repo: str) -> list[str]:
        queried.append(True)
        return published

    monkeypatch.setattr(check, "_published_versions", versions)

    assert check.main(["synthetic/repo", "v0.34.12"]) == 1
    assert capsys.readouterr().err.startswith("::error::")
    assert not queried


@pytest.mark.parametrize(("published", "expected"), [([], 0), (["0.34.11"], 0), (["0.34.12"], 1)])
def test_matching_release_version_keeps_published_version_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, published: list[str], expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.34.12"\n')
    monkeypatch.setattr(check, "__file__", str(tmp_path / "scripts" / "check_release_version.py"))
    monkeypatch.setattr(check, "_published_versions", lambda _repo: published)

    assert check.main(["synthetic/repo", "v0.34.12"]) == expected
