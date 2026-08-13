# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "scripts" / "usage.manifest"


def test_windows_manifest_declares_per_monitor_v2_dpi_awareness() -> None:
    root = ElementTree.parse(MANIFEST_PATH).getroot()

    dpi_awareness = root.find(
        ".//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness"
    )

    assert dpi_awareness is not None
    assert dpi_awareness.text == "PerMonitorV2"


def test_windows_build_embeds_manifest() -> None:
    build_script = (REPO_ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")

    assert '$ManifestFile = Join-Path $PSScriptRoot "usage.manifest"' in build_script
    assert "--manifest $ManifestFile `" in build_script
