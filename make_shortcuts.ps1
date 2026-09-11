# make_shortcuts.ps1 - installs the built Narrowgate.exe to a normal
# Windows-local folder and creates a Desktop + Start Menu shortcut for it.
#
# Run this AFTER build.ps1 has produced dist\Narrowgate.exe. Safe to
# re-run any time (e.g. after a rebuild) -- it just overwrites the same
# copy and shortcuts.

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$builtExe = Join-Path $scriptDir "dist\Narrowgate.exe"

if (-not (Test-Path -LiteralPath $builtExe)) {
    Write-Host "dist\Narrowgate.exe not found -- run build.ps1 first."
    exit 1
}

# Copy the exe into a normal Windows-local folder instead of pointing the
# shortcut straight at the WSL-mounted project path. \\wsl.localhost\...
# only resolves while the WSL VM is running, so a shortcut left pointing
# there can hang or fail to launch if WSL has shut down in the background.
# Re-run this script after every rebuild to refresh this copy.
$installDir = Join-Path $env:LOCALAPPDATA "Narrowgate"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
$exePath = Join-Path $installDir "Narrowgate.exe"
Copy-Item -LiteralPath $builtExe -Destination $exePath -Force

$shell = New-Object -ComObject WScript.Shell

function New-AppShortcut([string]$path) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = $installDir
    $shortcut.IconLocation = "$exePath,0"
    $shortcut.Description = "Narrowgate"
    $shortcut.Save()
    Write-Host "Created: $path"
}

$desktop = [Environment]::GetFolderPath("Desktop")
New-AppShortcut (Join-Path $desktop "Narrowgate.lnk")

$startMenu = [Environment]::GetFolderPath("StartMenu")
$programsDir = Join-Path $startMenu "Programs"
New-AppShortcut (Join-Path $programsDir "Narrowgate.lnk")

Write-Host "Installed to: $exePath"
Write-Host "Done -- launch Narrowgate from your Desktop or Start Menu."
