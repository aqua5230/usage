"""Guard the pip-install path: every top-level module must ship in the wheel.

`[project.scripts] usage` imports `usage_cli`, which pulls in most of the
top-level modules. `[tool.setuptools] py-modules` is an explicit allowlist, so a
new module that nobody adds there is missing from an installed copy and the
console script dies with ModuleNotFoundError — while every test still passes,
because tests import from the source tree.
"""

import pathlib
import tomllib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_py_modules_covers_every_top_level_module() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    listed = set(pyproject["tool"]["setuptools"]["py-modules"])
    on_disk = {path.stem for path in REPO_ROOT.glob("*.py")}

    missing = sorted(on_disk - listed)
    assert not missing, f"add these to [tool.setuptools] py-modules: {missing}"

    stale = sorted(listed - on_disk)
    assert not stale, f"these py-modules no longer exist: {stale}"
