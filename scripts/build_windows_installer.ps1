$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SourceDir = Join-Path $RepoRoot "dist/usage-windows"
$OutputDir = Join-Path $RepoRoot "dist/installer"
$InstallerScript = Join-Path $RepoRoot "installer/windows/usage.iss"
$ProjectFile = Join-Path $RepoRoot "pyproject.toml"

& (Join-Path $PSScriptRoot "build_windows.ps1")

$VersionLine = Select-String -LiteralPath $ProjectFile -Pattern '^version\s*=\s*"([^"]+)"$'
if ($null -eq $VersionLine) {
    throw "Could not read the project version from $ProjectFile"
}
$AppVersion = $VersionLine.Matches[0].Groups[1].Value

$CompilerCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs/Inno Setup 6/ISCC.exe"),
    "C:/Program Files (x86)/Inno Setup 6/ISCC.exe",
    "C:/Program Files/Inno Setup 6/ISCC.exe"
)
$Compiler = $CompilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($null -eq $Compiler) {
    throw "Inno Setup 6 is required. Install it with: winget install JRSoftware.InnoSetup"
}

Remove-Item $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $OutputDir | Out-Null

& $Compiler `
    "/DAppVersion=$AppVersion" `
    "/DSourceDir=$SourceDir" `
    "/DOutputDir=$OutputDir" `
    "/DRepoRoot=$RepoRoot" `
    $InstallerScript

$Installer = Join-Path $OutputDir "UsageSetup-$AppVersion.exe"
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "Inno Setup did not produce $Installer"
}

Write-Output $Installer
