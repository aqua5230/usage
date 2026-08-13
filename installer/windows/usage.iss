#ifndef AppVersion
  #error AppVersion must be supplied by the build script
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by the build script
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by the build script
#endif
#ifndef RepoRoot
  #error RepoRoot must be supplied by the build script
#endif

[Setup]
AppId={{5B469EB3-1018-4ACB-B137-E45606C13448}
AppName=Usage
AppVersion={#AppVersion}
AppPublisher=lollapalooza
AppPublisherURL=https://github.com/aqua5230/usage
AppSupportURL=https://github.com/aqua5230/usage/issues
DefaultDirName={localappdata}\Programs\Usage
DefaultGroupName=Usage
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#RepoRoot}\LICENSE
SetupIconFile={#RepoRoot}\assets\usage.ico
UninstallDisplayIcon={app}\usage.exe
OutputDir={#OutputDir}
OutputBaseFilename=UsageSetup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"
Name: "autostart"; Description: "Start Usage when I sign in to Windows"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Usage"; Filename: "{app}\usage.exe"
Name: "{autodesktop}\Usage"; Filename: "{app}\usage.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Usage"; ValueData: "{app}\usage.exe"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\usage.exe"; Description: "Launch Usage"; Flags: nowait postinstall skipifsilent
