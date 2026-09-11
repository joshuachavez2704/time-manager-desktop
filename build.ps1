# build.ps1 - builds Narrowgate.exe with PyInstaller.
#
# Run this from the project folder, with the venv activated
# (.\venv\Scripts\Activate.ps1). Produces dist\Narrowgate.exe.
#
# PyInstaller does not cross-compile: this has to be run on Windows to get
# a Windows .exe, and re-run any time you edit the source to rebuild it.

pip install pyinstaller | Out-Null
pyinstaller --noconfirm --clean Narrowgate.spec

if (Test-Path ".\dist\Narrowgate.exe") {
    Write-Host "Build succeeded: dist\Narrowgate.exe"
} else {
    Write-Host "Build did not produce dist\Narrowgate.exe -- check the output above for errors."
}
