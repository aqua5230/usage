#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Generate the PyInstaller version resource for the Windows executable.

SignPath Foundation's OSS terms require every signed binary to carry an enforced
product name and product version, so `usage.exe` cannot ship without one.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'lollapalooza'),
          StringStruct('FileDescription', '{description}'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'usage'),
          StringStruct('LegalCopyright', 'AGPL-3.0-only'),
          StringStruct('OriginalFilename', 'usage.exe'),
          StringStruct('ProductName', 'usage'),
          StringStruct('ProductVersion', '{version}'),
        ],
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""


def project_version(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = data["project"]["version"]
    if not isinstance(version, str):
        raise TypeError(f"project.version is {type(version).__name__}, expected str")
    return version


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"expected a three-part version, got {version!r}")
    major, minor, patch = (int(part) for part in parts)
    return (major, minor, patch, 0)


def render(version: str, description: str) -> str:
    return TEMPLATE.format(
        version=version,
        version_tuple=version_tuple(version),
        description=description,
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} <output-path>", file=sys.stderr)
        return 2

    pyproject = REPO_ROOT / "pyproject.toml"
    version = project_version(pyproject)
    description = "Claude Code, Codex and Antigravity quota in your system tray"

    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(version, description), encoding="utf-8")
    print(f"wrote {output} for usage {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
