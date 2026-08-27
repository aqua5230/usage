#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Guard public docs from drifting out of sync."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
CHANGELOG_VERSION_RE = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)


@dataclass(frozen=True)
class DocGroup:
    label: str
    english: str
    translations: tuple[str, ...]


DOC_GROUPS = (
    DocGroup(
        "README",
        "README.md",
        ("docs/README.zh-TW.md", "docs/README.zh-CN.md", "docs/README.ja.md", "docs/README.ko.md"),
    ),
    DocGroup("CHANGELOG", "CHANGELOG.md", ("docs/CHANGELOG.zh-TW.md",)),
    DocGroup("CONTRIBUTING", ".github/CONTRIBUTING.md", (".github/CONTRIBUTING.zh-TW.md",)),
    DocGroup("SECURITY", ".github/SECURITY.md", (".github/SECURITY.zh-TW.md",)),
    DocGroup(
        "docs/DEVELOPMENT",
        "docs/DEVELOPMENT.md",
        ("docs/DEVELOPMENT.zh-TW.md",),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that English public docs and translations stay in lockstep."
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


def translation_language(path: str) -> str:
    language_names = {
        "zh-TW": "Traditional Chinese",
        "zh-CN": "Simplified Chinese",
        "ja": "Japanese",
        "ko": "Korean",
    }
    language_code = Path(path).stem.rsplit(".", maxsplit=1)[-1]
    return language_names.get(language_code, "translation")


def check_group(root: Path, group: DocGroup) -> list[str]:
    errors: list[str] = []
    english_path = root / group.english
    translation_paths = [(path, root / path) for path in group.translations]

    english_exists = english_path.is_file()
    if not english_exists:
        errors.append(f"{group.label}: missing English file {group.english}")

    for translation, translation_path in translation_paths:
        if not translation_path.is_file():
            errors.append(
                f"{group.label}: missing {translation_language(translation)} file {translation}"
            )

    if not english_exists:
        return errors

    english_sections = count_primary_sections(english_path)
    for translation, translation_path in translation_paths:
        if not translation_path.is_file():
            continue
        translation_sections = count_primary_sections(translation_path)
        if english_sections != translation_sections:
            errors.append(
                f"{group.label}: section count mismatch at ## headings "
                f"({group.english}={english_sections}, {translation}={translation_sections})"
            )

    if group.label == "CHANGELOG":
        english_version = latest_changelog_version(english_path)
        if english_version is None:
            errors.append(f"{group.label}: could not find a version heading in {group.english}")
        else:
            for translation, translation_path in translation_paths:
                if not translation_path.is_file():
                    continue
                translation_version = latest_changelog_version(translation_path)
                if translation_version is None:
                    errors.append(
                        f"{group.label}: could not find a version heading in {translation}"
                    )
                elif english_version != translation_version:
                    errors.append(
                        f"{group.label}: latest version mismatch "
                        f"({group.english}={english_version}, {translation}={translation_version})"
                    )

    return errors


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    errors: list[str] = []
    for group in DOC_GROUPS:
        errors.extend(check_group(root, group))

    if errors:
        print("FAIL: bilingual document parity check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: bilingual document parity check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
