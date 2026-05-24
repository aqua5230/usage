"""Regression tests for ``i18n.packaged_resource_path``.

These cover the fix for the py2app launch crash where
``Path(__file__).with_name("i18n.json")`` resolved into
``lib/python313.zip/i18n.json`` and raised ``NotADirectoryError`` at first
read. The fix prefers the ``RESOURCEPATH`` env var py2app injects at
launch (pointing at ``Contents/Resources/``) and only falls back to the
source-adjacent path when running outside a bundle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from i18n import packaged_resource_path


def test_prefers_RESOURCEPATH_when_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "Resources"
    bundle.mkdir()
    (bundle / "i18n.json").write_text("{}", encoding="utf-8")

    source_path = tmp_path / "source" / "i18n.json"
    source_path.parent.mkdir()
    source_path.write_text('{"different": {}}', encoding="utf-8")

    monkeypatch.setenv("RESOURCEPATH", str(bundle))
    resolved = packaged_resource_path("i18n.json", source_path)

    assert resolved == bundle / "i18n.json"


def test_falls_back_to_source_path_when_RESOURCEPATH_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RESOURCEPATH", raising=False)
    source_path = tmp_path / "i18n.json"
    source_path.write_text("{}", encoding="utf-8")

    resolved = packaged_resource_path("i18n.json", source_path)
    assert resolved == source_path


def test_falls_back_when_RESOURCEPATH_set_but_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RESOURCEPATH exists but does not contain the file → fall through."""
    bundle = tmp_path / "Resources"
    bundle.mkdir()
    # deliberately do NOT create bundle/i18n.json

    source_path = tmp_path / "source" / "i18n.json"
    source_path.parent.mkdir()
    source_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("RESOURCEPATH", str(bundle))
    resolved = packaged_resource_path("i18n.json", source_path)

    assert resolved == source_path


def test_falls_back_when_RESOURCEPATH_empty_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty RESOURCEPATH is treated as unset (defensive)."""
    monkeypatch.setenv("RESOURCEPATH", "")
    source_path = tmp_path / "i18n.json"
    source_path.write_text("{}", encoding="utf-8")

    resolved = packaged_resource_path("i18n.json", source_path)
    assert resolved == source_path


def test_simulated_py2app_zipfile_path_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end repro of the original crash.

    Pre-fix: the source-mode path was the only option, and inside py2app
    it resolved to ``lib/python313.zip/i18n.json`` — an invalid path through
    the zipfile that raised ``NotADirectoryError`` on read. This test
    reconstructs the same shape: a path that points inside a regular file
    (simulating the zip) and asserts that packaged_resource_path returns
    the bundled copy instead of the broken zip-internal path.
    """
    resources = tmp_path / "Resources"
    resources.mkdir()
    (resources / "i18n.json").write_text('{"en": {}}', encoding="utf-8")

    fake_zip = resources / "lib" / "python313.zip"
    fake_zip.parent.mkdir()
    fake_zip.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # minimal empty-zip footer
    # this is what Path(__file__).with_name resolves to when __file__ is inside the zip
    crashing_source_path = fake_zip / "i18n.json"

    monkeypatch.setenv("RESOURCEPATH", str(resources))
    resolved = packaged_resource_path("i18n.json", crashing_source_path)

    # Must NOT return the crashing path
    assert resolved != crashing_source_path
    # Must return the real, readable file
    assert resolved == resources / "i18n.json"
    assert resolved.read_text() == '{"en": {}}'
