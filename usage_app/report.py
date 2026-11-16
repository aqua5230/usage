# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 lollapalooza <https://github.com/aqua5230>
#
# Part of "usage". Free software licensed under the GNU Affero General Public
# License v3.0 only; see the LICENSE file for full terms and the warranty disclaimer.

"""Generate and open a report in a short-lived process."""

from __future__ import annotations

import argparse
import sys
from typing import Any, cast

from adapters.registry import detect_agents
from analyzer.reporter import build_report_data
from ui.html_report import save_and_open


def main(argv: list[str]) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                cast(Any, stream).reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--period", required=True)
    parser.add_argument("--default-range")
    parser.add_argument("--language")
    args = parser.parse_args(argv)
    try:
        data = build_report_data(detect_agents(), args.period)
        options = {"language": args.language}
        if args.default_range is not None:
            options["default_range"] = args.default_range
        saved = save_and_open(data, **options)
        print(saved)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0
