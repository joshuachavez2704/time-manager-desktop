# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Narrowgate desktop app.
#
# Build (from the project folder, with the venv activated and
# `pip install pyinstaller` done):
#     pyinstaller Narrowgate.spec
#
# The .exe lands in dist\Narrowgate.exe. Must be built on the OS you
# want the executable for -- PyInstaller does not cross-compile, so this
# has to be run on Windows to produce a Windows .exe.
import sys

block_cipher = None

# pystray and plyer both pick their backend at runtime based on sys.platform
# via `from . import _whatever`, which PyInstaller's static analysis can
# miss -- listing them explicitly avoids a working build that silently
# fails to show a tray icon or a notification.
hidden_imports = ["PIL._tkinter_finder"]
if sys.platform == "win32":
    hidden_imports += ["pystray._win32", "plyer.platforms.win.notification"]
elif sys.platform == "darwin":
    hidden_imports += ["pystray._darwin", "plyer.platforms.macosx.notification"]
else:
    hidden_imports += [
        "pystray._gtk", "pystray._appindicator", "pystray._xorg",
        "plyer.platforms.linux.notification",
    ]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Narrowgate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
