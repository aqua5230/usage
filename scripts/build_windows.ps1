$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $RepoRoot "dist"
$OutputDir = Join-Path $DistRoot "usage-windows"
$PyInstallerOutput = Join-Path $DistRoot "usage"
$BuildDir = Join-Path $RepoRoot "build/pyinstaller-windows"
$SpecDir = Join-Path $RepoRoot "build/pyinstaller-spec"

Remove-Item $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $PyInstallerOutput -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $BuildDir -Recurse -Force -ErrorAction SilentlyContinue

Push-Location $RepoRoot
try {
    uv run --no-sync python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name usage `
        --distpath $DistRoot `
        --workpath $BuildDir `
        --specpath $SpecDir `
        --add-data "$(Join-Path $RepoRoot 'i18n.json');." `
        --add-data "$(Join-Path $RepoRoot 'pyproject.toml');." `
        --add-data "$(Join-Path $RepoRoot 'assets');assets" `
        --hidden-import wintray `
        --hidden-import pystray `
        --hidden-import webview `
        --hidden-import webview.platforms.edgechromium `
        --hidden-import tui `
        --hidden-import session_hooks `
        --hidden-import setup_hook `
        --hidden-import adapters.registry `
        --hidden-import analyzer.reporter `
        --hidden-import ui.html_report `
        --collect-all pystray `
        --collect-all webview `
        main.py

    Move-Item $PyInstallerOutput $OutputDir
} finally {
    Pop-Location
}

$Executable = Join-Path $OutputDir "usage.exe"
if (-not (Test-Path $Executable -PathType Leaf)) {
    throw "PyInstaller did not produce $Executable"
}
