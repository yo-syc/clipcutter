# Build the Windows app folder and installer.
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#   -> dist\ClipCutter\ (app folder) and dist\ClipCutter-<version>-windows-x64-setup.exe
# Needs: uv, MSYS2 (for libfribidi, preinstalled on GitHub runners), Inno Setup 6 (choco install innosetup).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$version = $env:CLIPCUTTER_VERSION
if (-not $version) { $version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value }
$env:CLIPCUTTER_VERSION = $version

# libfribidi (Hindi text shaping): MSYS2 package
$fribidi = "C:\msys64\mingw64\bin\libfribidi-0.dll"
if (-not (Test-Path $fribidi)) {
    & C:\msys64\usr\bin\bash.exe -lc "pacman -S --noconfirm --needed mingw-w64-x86_64-fribidi"
    if ($LASTEXITCODE -ne 0) { throw "could not install fribidi with MSYS2" }
}

uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
if (-not (Test-Path packaging\vendor\bin\ffmpeg.exe)) {
    uv run --no-project python packaging\fetch_vendor.py --fribidi $fribidi
    if ($LASTEXITCODE -ne 0) { throw "fetch_vendor failed" }
}
uv run python packaging\make_icons.py
if ($LASTEXITCODE -ne 0) { throw "make_icons failed" }

Remove-Item -Recurse -Force build\pyinstaller, dist\ClipCutter -ErrorAction SilentlyContinue
uv run --with "pyinstaller>=6.10" pyinstaller packaging\clipcutter.spec --noconfirm --distpath dist --workpath build\pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "$env:ProgramFiles\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { choco install innosetup -y --no-progress; $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $iscc "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem dist\*.exe
