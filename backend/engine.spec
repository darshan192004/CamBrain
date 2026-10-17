# PyInstaller spec for the packaged engine (plan T5, D6-1 packaged layout).
#
# ONEDIR, deliberately not onefile: a one-file engine extracts its whole
# payload (~200 MB) to %TEMP% on every boot -- slow, fills the user's system
# drive, and dies with "No space left on device" exactly at the worst time.
# The onedir layout ships plain files next to the exe and boots in seconds.
#
# Build:  pyinstaller --clean --noconfirm backend/engine.spec
# Output: dist/cambrian-engine/ (cambrian-engine.exe + _internal/)
# Ship:   copy the whole folder's contents into src-tauri/resources/engine/

a = Analysis(
    ["scripts/engine_entry.py"],
    pathex=["."],
    binaries=[],
    # Migrations run on startup from disk (DATABASE §1) and D6-4 bootstrap
    # reads the pinned manifest + legal notice from the bundle; the weights
    # themselves download into app data. The spec runs from backend/, so
    # repo-root paths need ../.
    datas=[
        ("migrations/env.py", "migrations"),
        ("migrations/script.py.mako", "migrations"),
        ("migrations/versions", "migrations/versions"),
        ("../models/manifest.json", "models"),
        ("../models/LICENSE-MODEL-NOTICE", "models"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cambrian-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="cambrian-engine",
)
