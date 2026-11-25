# SPDX-License-Identifier: AGPL-3.0-only

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "build_redirects", Path(__file__).parents[1] / "scripts" / "build_redirects.py"
)
assert _spec is not None and _spec.loader is not None
redirects = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(redirects)


@pytest.mark.parametrize(
    ("page", "route"),
    [
        ("index.html", "/"),
        ("ja/index.html", "/ja/"),
        ("blog/what-is-cli/index.html", "/blog/what-is-cli/"),
        ("zh-TW/blog/what-is-cli/index.html", "/zh-TW/blog/what-is-cli/"),
    ],
)
def test_index_redirect(tmp_path: Path, page: str, route: str) -> None:
    assert redirects.build_redirects(tmp_path, check=False) == 0

    html = (tmp_path / page).read_text(encoding="utf-8")
    target = f"https://getusage.app{route}"
    assert f'<meta http-equiv="refresh" content="0; url={target}">' in html
    assert f'<link rel="canonical" href="{target}">' in html
    assert '<meta name="robots" content="noindex">' in html
    assert f'location.replace("{target}" + location.search + location.hash);' in html
    assert f'<a href="{target}">' in html


def test_404_redirect(tmp_path: Path) -> None:
    assert redirects.build_redirects(tmp_path, check=False) == 0

    html = (tmp_path / "404.html").read_text(encoding="utf-8")
    assert r'location.pathname.replace(/^\/usage(?=\/|$)/, "") || "/"' in html
    assert " + location.search + location.hash);" in html
    assert '<a href="https://getusage.app/">' in html


def test_check_detects_missing_and_changed_pages_without_writing(tmp_path: Path) -> None:
    assert redirects.build_redirects(tmp_path, check=False) == 0
    assert redirects.build_redirects(tmp_path, check=True) == 0

    missing = tmp_path / "ko" / "index.html"
    missing.unlink()
    changed = tmp_path / "404.html"
    changed.write_text("edited", encoding="utf-8")

    assert redirects.build_redirects(tmp_path, check=True) == 1
    assert not missing.exists()
    assert changed.read_text(encoding="utf-8") == "edited"
