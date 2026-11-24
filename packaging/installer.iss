; Inno Setup script for the Windows installer. Built by packaging\build_windows.ps1.
; Per-user install (no admin prompt). User data stays in %APPDATA%\ClipCutter and survives uninstall.
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6C1C7E2A-7D2B-4C3E-9C8F-C11FC077E201}
AppName=ClipCutter
AppVersion={#AppVersion}
AppPublisher=ClipCutter
AppPublisherURL=https://github.com/pandeymynk/clipcutter
DefaultDirName={localappdata}\Programs\ClipCutter
DefaultGroupName=ClipCutter
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ClipCutter-{#AppVersion}-windows-x64-setup
SetupIconFile=build\icon.ico
UninstallDisplayIcon={app}\ClipCutter.exe
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\ClipCutter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\ClipCutter"; Filename: "{app}\ClipCutter.exe"
Name: "{autodesktop}\ClipCutter"; Filename: "{app}\ClipCutter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ClipCutter.exe"; Description: "Open ClipCutter now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
