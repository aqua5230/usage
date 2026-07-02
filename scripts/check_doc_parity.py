#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Guard bilingual public docs from drifting out of sync."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
CHANGELOG_VERSION_RE = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)


@dataclass(frozen=True)
class DocPair:
    label: str
    english: str
    traditional_chinese: str


DOC_PAIRS = (
    DocPair("README", "README.md", "README.zh-TW.md"),
    DocPair("CHANGELOG", "CHANGELOG.md", "CHANGELOG.zh-TW.md"),
    DocPair("CONTRIBUTING", "CONTRIBUTING.md", "CONTRIBUTING.zh-TW.md"),
    DocPair("SECURITY", "SECURITY.md", "SECURITY.zh-TW.md"),
    DocPair("docs/DEVELOPMENT", "docs/DEVELOPMENT.md", "docs/DEVELOPMENT.zh-TW.md"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that English public docs and Traditional Chinese translations "
            "stay in lockstep."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to inspect (default: current working directory).",
    )
    return parser.parse_args()


def count_primary_sections(path: Path) -> int:
    return len(HEADING_RE.findall(path.read_text(encoding="utf-8")))


def latest_changelog_version(path: Path) -> str | None:
    match = CHANGELOG_VERSION_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        return None
    return match.group(1)


def check_pair(root: Path, pair: DocPair) -> list[str]:
    errors: list[str] = []
    english_path = root / pair.english
    chinese_path = root / pair.traditional_chinese

    english_exists = english_path.is_file()
    chinese_exists = chinese_path.is_file()
    if not english_exists or not chinese_exists:
        if not english_exists:
            errors.append(f"{pair.label}: missing English file {pair.english}")
        if not chinese_exists:
            errors.append(
                f"{pair.label}: missing Traditional Chinese file {pair.traditional_chinese}"
            )
        return errors

    english_sections = count_primary_sections(english_path)
    chinese_sections = count_primary_sections(chinese_path)
    if english_sections != chinese_sections:
        errors.append(
            f"{pair.label}: section count mismatch at ## headings "
            f"({pair.english}={english_sections}, {pair.traditional_chinese}={chinese_sections})"
        )

    if pair.label == "CHANGELOG":
        english_version = latest_changelog_version(english_path)
        chinese_version = latest_changelog_version(chinese_path)
        if english_version is None:
            errors.append(f"{pair.label}: could not find a version heading in {pair.english}")
        if chinese_version is None:
            errors.append(
                f"{pair.label}: could not find a version heading in {pair.traditional_chinese}"
            )
        if (
            english_version is not None
            and chinese_version is not None
            and english_version != chinese_version
        ):
            errors.append(
                f"{pair.label}: latest version mismatch "
                f"({pair.english}={english_version}, {pair.traditional_chinese}={chinese_version})"
            )

    return errors


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    errors: list[str] = []
    for pair in DOC_PAIRS:
        errors.extend(check_pair(root, pair))

    if errors:
        print("FAIL: bilingual document parity check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: bilingual document parity check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
