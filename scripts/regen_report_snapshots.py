"""Regenerate the golden HTML report snapshots in tests/fixtures/html_report_snapshots/.

Any change to the report's CSS or markup breaks the byte-exact snapshot test.
Run this, then eyeball the regenerated HTML — a passing snapshot test after a
regen only proves the output matches itself, not that the layout is right.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_html_report_snapshot import (  # type: ignore[import-not-found]  # noqa: E402
    SNAPSHOT_DIR,
    _empty_report_data,
    _FixedDateTime,
    _full_report_data,
)

from ui import html_report  # noqa: E402


def main() -> int:
    html_report.datetime = _FixedDateTime  # type: ignore[attr-defined]
    html_report._version = lambda: "0.15.8"
    for name, data, language in (
        ("full_zh_tw", _full_report_data(), "zh-TW"),
        ("full_en", _full_report_data(), "en"),
        ("empty_zh_tw", _empty_report_data(), "zh-TW"),
    ):
        (SNAPSHOT_DIR / f"{name}.html").write_text(
            html_report.generate_html(data, language=language), encoding="utf-8"
        )
        print(f"wrote {name}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
