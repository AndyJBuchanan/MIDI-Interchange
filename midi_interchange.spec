# PyInstaller spec: pyinstaller midi_interchange.spec
# Produces dist/MIDI Interchange.app (macOS) or dist/MIDI Interchange/ (Windows).
import os
import sys

# Single source of the app version. See docs/RELEASING.md before changing it.
# Feeds the macOS Info.plist, the Windows exe version resource, the Windows installer and every
# artifact file name (build_macos.sh reads it back from Info.plist; build_windows.ps1 reads this line
# with a regex, so keep it a plain "MAJOR.MINOR.PATCH" literal).
# Numbers only: macOS and Windows both reject suffixes such as "-pre". Pre-release labels go on the
# git tag / GitHub release instead (e.g. VERSION "0.1.0" is released as tag v0.1.0-pre).
VERSION = "0.2.0"

import re as _re
if not _re.fullmatch(r"\d+\.\d+\.\d+", VERSION):
    raise SystemExit(f'midi_interchange.spec: VERSION must be MAJOR.MINOR.PATCH digits only, got "{VERSION}". '
                     "Put labels like -pre on the git tag, not here (docs/RELEASING.md).")

# Set by scripts/build_macos.sh from scripts/signing.local.env; unset = ad-hoc signing.
codesign_identity = os.environ.get("CODESIGN_IDENTITY") or None
entitlements_file = os.environ.get("ENTITLEMENTS_FILE") or None

block_cipher = None
version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32 import versioninfo as vi
    _v = tuple(int(x) for x in VERSION.split(".")) + (0,)
    version_info = vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=_v, prodvers=_v),
        kids=[vi.StringFileInfo([vi.StringTable("040904B0", [
                  vi.StringStruct("ProductName", "MIDI Interchange"),
                  vi.StringStruct("FileDescription", "MIDI Interchange"),
                  vi.StringStruct("InternalName", "MIDI Interchange"),
                  vi.StringStruct("OriginalFilename", "MIDI Interchange.exe"),
                  vi.StringStruct("FileVersion", VERSION),
                  vi.StringStruct("ProductVersion", VERSION)])]),
              vi.VarFileInfo([vi.VarStruct("Translation", [0x0409, 1200])])])

excluded = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
            "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "tkinter"]

# Icon files are made from assets/icon/icon.png by tools/make_icons.py.
ICON_ICNS = os.path.join("assets", "icon", "MIDI Interchange.icns")
ICON_ICO = os.path.join("assets", "icon", "MIDI Interchange.ico")

a = Analysis(["main.py"], pathex=["."], binaries=[],
             datas=[(os.path.join("midi_interchange", "resources", "*.png"), os.path.join("midi_interchange", "resources"))],
             hiddenimports=[],
             excludes=excluded, noarchive=False)
pyz = PYZ(a.pure, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MIDI Interchange",
          console=False, argv_emulation=False, target_arch=None,
          codesign_identity=codesign_identity, entitlements_file=entitlements_file,
          version=version_info, icon=ICON_ICO if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MIDI Interchange")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="MIDI Interchange.app", bundle_identifier="com.midiinterchange.app",
                 icon=ICON_ICNS,
                 info_plist={
                     "NSHighResolutionCapable": True,
                     "CFBundleShortVersionString": VERSION,
                     "CFBundleVersion": VERSION,
                     "CFBundleDocumentTypes": [{
                         "CFBundleTypeName": "Standard MIDI File",
                         "CFBundleTypeRole": "Editor",
                         "LSItemContentTypes": ["public.midi-audio"],
                         "CFBundleTypeExtensions": ["mid", "midi", "smf"],
                     }],
                 })
