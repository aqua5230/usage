#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Refuse to release a version that isn't strictly newer than any published release."""

from __future__ import annotations

import json
import subprocess
import sys

from updates.checker import compare_versions


def _published_versions(repo: str) -> list[str]:
    result = subprocess.run(
        ["gh", "release", "list", "--repo", repo, "--limit", "200", "--json", "tagName,isDraft"],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    releases = json.loads(result.stdout)
    versions = []
    for release in releases:
        if release.get("isDraft"):
            continue
        tag = release["tagName"]
        versions.append(tag[1:] if tag.startswith("v") else tag)
    return versions


def _latest(versions: list[str]) -> str | None:
    latest: str | None = None
    for candidate in versions:
        try:
            if latest is None or compare_versions(candidate, latest) > 0:
                latest = candidate
        except ValueError:
            continue  # malformed historical tag; don't let it block a release
    return latest


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_release_version.py <repo> <tag>", file=sys.stderr)
        return 2
    repo, tag = argv
    version = tag[1:] if tag.startswith("v") else tag

    latest = _latest(_published_versions(repo))
    if latest is None:
        print("No published releases yet; nothing to compare against.")
        return 0

    try:
        result = compare_versions(version, latest)
    except ValueError:
        print(
            f"::error::Tag {tag!r} isn't MAJOR.MINOR.PATCH — "
            f"can't verify it's newer than {latest}.",
            file=sys.stderr,
        )
        return 1

    if result <= 0:
        print(
            f"::error::Tag {tag!r} ({version}) is not newer than the latest published "
            f"release ({latest}). Refusing to publish a non-monotonic version.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {version} is newer than latest published release {latest}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
