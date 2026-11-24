# ClipCutter setup for Windows 10/11. Safe to run again.
# Run:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Say($m) { Write-Host "`n==> $m" -ForegroundColor Green }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

if (-not (Have "winget")) {
    Write-Host "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again."
    exit 1
}

$tools = @(
    @{ cmd = "uv";     id = "astral-sh.uv" },
    @{ cmd = "ffmpeg"; id = "Gyan.FFmpeg" },
    @{ cmd = "node";   id = "OpenJS.NodeJS.LTS" }
)
foreach ($t in $tools) {
    if (-not (Have $t.cmd)) {
        Say "Installing $($t.cmd)"
        winget install --id $t.id -e --accept-source-agreements --accept-package-agreements
    }
}

# pick up PATH changes from the installs without reopening the terminal
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

if (-not (Have "uv") -or -not (Have "ffmpeg")) {
    Write-Host "`nTools were installed. Close this window, open a new PowerShell, and run this script again."
    exit 0
}

Say "Installing Python packages (uv sync)"
uv sync

Say "Checking everything"
uv run clipcutter doctor

Write-Host "`nStart the app with:`n`n    uv run clipcutter serve`n`nthen open http://localhost:8787"
