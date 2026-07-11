from __future__ import annotations

import sys
from pathlib import Path

import atheris  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import history_loader  # noqa: E402


def _test_one_input(data: bytes) -> None:
    provider = atheris.FuzzedDataProvider(data)
    line = provider.ConsumeUnicodeNoSurrogates(len(data))
    history_loader._parse_line(line, "fuzz-project")


def main() -> None:
    atheris.Setup(sys.argv, _test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
