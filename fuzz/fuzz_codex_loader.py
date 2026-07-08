from __future__ import annotations

import hashlib
import importlib
import io
import sys
from pathlib import Path

import atheris  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

codex_loader = importlib.import_module("codex_loader")


def _test_one_input(data: bytes) -> None:
    provider = atheris.FuzzedDataProvider(data)
    line = provider.ConsumeUnicodeNoSurrogates(len(data)).encode("utf-8", errors="replace")
    if provider.ConsumeBool():
        line += b"\n"
    entries: list[object] = []
    codex_loader._parse_linear_jsonl_bytes(
        io.BytesIO(line),
        session_id="fuzz-session",
        models={},
        entries=entries,
        state=codex_loader._JsonlParseState(),
        digest=hashlib.blake2b(digest_size=16),
        confirmed_offset=0,
    )


def main() -> None:
    atheris.Setup(sys.argv, _test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
