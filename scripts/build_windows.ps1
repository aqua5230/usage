$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $RepoRoot "dist"
$OutputDir = Join-Path $DistRoot "usage-windows"
$PyInstallerOutput = Join-Path $DistRoot "usage"
$BuildDir = Join-Path $RepoRoot "build/pyinstaller-windows"
$SpecDir = Join-Path $RepoRoot "build/pyinstaller-spec"
$ManifestFile = Join-Path $PSScriptRoot "usage.manifest"

Remove-Item $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $PyInstallerOutput -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $BuildDir -Recurse -Force -ErrorAction SilentlyContinue

Push-Location $RepoRoot
try {
    $VersionFile = Join-Path $SpecDir "usage-version-info.txt"
    uv run --no-sync python scripts/make_version_file.py $VersionFile

    uv run --no-sync python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name usage `
        --icon "$(Join-Path $RepoRoot 'assets/usage.ico')" `
        --version-file $VersionFile `
        --manifest $ManifestFile `
        --distpath $DistRoot `
        --workpath $BuildDir `
        --specpath $SpecDir `
        --add-data "$(Join-Path $RepoRoot 'i18n.json');." `
        --add-data "$(Join-Path $RepoRoot 'pyproject.toml');." `
        --add-data "$(Join-Path $RepoRoot 'assets');assets" `
        --add-data "$(Join-Path $RepoRoot 'usage_statusline.py');." `
        --add-data "$(Join-Path $RepoRoot 'usage_statusline_agy.py');." `
        --add-data "$(Join-Path $RepoRoot 'usage_statusline_grok.py');." `
        --add-data "$(Join-Path $RepoRoot 'usage_statusline_forwarder.py');." `
        --add-data "$(Join-Path $RepoRoot 'usage_session_resume.py');." `
        --add-data "$(Join-Path $RepoRoot 'usage_terse_mode.py');." `
        --add-data "$(Join-Path $RepoRoot 'usage_terse_reminder.py');." `
        --hidden-import wintray.app `
        --hidden-import pystray `
        --hidden-import webview `
        --hidden-import webview.platforms.edgechromium `
        --hidden-import tui.app `
        --hidden-import installer.session_hooks `
        --hidden-import installer.setup_hook `
        --hidden-import adapters.registry `
        --hidden-import analyzer.reporter `
        --hidden-import ui.html_report `
        --collect-all pystray `
        --collect-all windows_toasts `
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

# The exe existing is not proof it works: v0.29.34-36 shipped bundles whose
# hidden-import names still pointed at pre-refactor top-level modules, so the
# packages collected nothing and the app died on launch. Assert the two
# dynamically imported entry modules are actually inside the archive.
$RequiredModules = @('wintray.app', 'tui.app')
$ArchiveToc = uv run --no-sync python -m PyInstaller.utils.cliutils.archive_viewer -l -r $Executable
foreach ($Module in $RequiredModules) {
    if (-not ($ArchiveToc | Select-String -SimpleMatch -Quiet "'$Module'")) {
        throw "packaged exe is missing module: $Module"
    }
}
