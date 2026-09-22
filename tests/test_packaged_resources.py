# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {"tests", "build", "dist", ".venv", "__pycache__", "scripts"}
DataFileReference = tuple[Path, str]


def _is_local_data_path(value: str) -> bool:
    return bool(value) and not value.endswith(".py") and not value.startswith(("/", "~"))


def _source_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.name != "setup_app.py" and EXCLUDED_DIRS.isdisjoint(path.relative_to(root).parts)
    )


def _path_file_call(node: ast.AST) -> bool:
    match node:
        case ast.Call(func=ast.Name(id="Path"), args=[ast.Name(id="__file__")]):
            return True
    return False


def _parent_count(node: ast.AST) -> int | None:
    if _path_file_call(node):
        return 0
    match node:
        case ast.Call(func=ast.Attribute(attr="resolve", value=value)) if _path_file_call(value):
            return 0
        case ast.Attribute(attr="parent", value=value):
            count = _parent_count(value)
            return count + 1 if count is not None else None
    return None


def _literal_division(node: ast.AST) -> tuple[ast.AST, list[str]] | None:
    parts: list[str] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        if not isinstance(node.right, ast.Constant) or not isinstance(node.right.value, str):
            return None
        parts.append(node.right.value)
        node = node.left
    parts.reverse()
    return node, parts


def _from_division(node: ast.AST, source: Path, root: Path) -> str | None:
    result = _literal_division(node)
    if result is None:
        return None
    base_node, parts = result
    count = _parent_count(base_node)
    value = "/".join(parts)
    if count is None or not _is_local_data_path(value):
        return None
    base = source
    for _ in range(count):
        base = base.parent
    return str((base / value).relative_to(root))


def _from_with_name(node: ast.AST, source: Path, root: Path) -> str | None:
    match node:
        case ast.Call(
            func=ast.Attribute(attr="with_name", value=path_call),
            args=[ast.Constant(value=str() as value)],
        ) if _path_file_call(path_call):
            if _is_local_data_path(value):
                return str((source.parent / value).relative_to(root))
    return None


def find_local_data_file_references(root: Path = ROOT) -> list[DataFileReference]:
    references: list[DataFileReference] = []
    for source in _source_files(root):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            resource = _from_with_name(node, source, root) or _from_division(node, source, root)
            if resource is not None and (root / resource).is_file():
                references.append((source.relative_to(root), resource))
    return references


def parse_setup_app_resources(root: Path = ROOT) -> set[str]:
    tree = ast.parse((root / "setup_app.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        match node:
            case ast.Assign(value=ast.Dict(keys=keys, values=values), targets=targets) if any(
                isinstance(target, ast.Name) and target.id == "OPTIONS" for target in targets
            ):
                for key, value in zip(keys, values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "resources"
                        and isinstance(value, ast.List)
                    ):
                        return {
                            item.value
                            for item in value.elts
                            if isinstance(item, ast.Constant) and isinstance(item.value, str)
                        }
    raise AssertionError('setup_app.py does not define OPTIONS["resources"] as a list literal')


def _is_declared(resource: str, resources: set[str]) -> bool:
    path = Path(resource)
    return resource in resources or any(
        (ROOT / entry).is_dir() and path.is_relative_to(entry) for entry in resources
    )


def test_parse_setup_app_resources() -> None:
    resources = parse_setup_app_resources()

    assert "i18n.json" in resources
    assert "assets/windows" in resources


def test_local_data_files_are_declared_as_py2app_resources() -> None:
    resources = parse_setup_app_resources()
    missing = [
        ref for ref in find_local_data_file_references() if not _is_declared(ref[1], resources)
    ]

    assert not missing, "\n".join(
        f"{resource} is read by {source}, but is not listed in setup_app.py resources"
        for source, resource in missing
    )
