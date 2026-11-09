# PyInstaller spec: pyinstaller midi_interchange.spec
# Produces dist/MIDI Interchange.app (macOS) or dist/MIDI Interchange/ (Windows).
import os
import sys

# Set by scripts/build_macos.sh from scripts/signing.local.env; unset = ad-hoc signing.
codesign_identity = os.environ.get("CODESIGN_IDENTITY") or None
entitlements_file = os.environ.get("ENTITLEMENTS_FILE") or None

block_cipher = None
excluded = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
            "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "tkinter"]

a = Analysis(["main.py"], pathex=["."], binaries=[], datas=[], hiddenimports=[],
             excludes=excluded, noarchive=False)
pyz = PYZ(a.pure, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MIDI Interchange",
          console=False, argv_emulation=False, target_arch=None,
          codesign_identity=codesign_identity, entitlements_file=entitlements_file)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MIDI Interchange")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="MIDI Interchange.app", bundle_identifier="com.midiinterchange.app",
                 info_plist={
                     "NSHighResolutionCapable": True,
                     "CFBundleShortVersionString": "0.1.0",
                     "CFBundleVersion": "0.1.0",
                     "CFBundleDocumentTypes": [{
                         "CFBundleTypeName": "Standard MIDI File",
                         "CFBundleTypeRole": "Editor",
                         "LSItemContentTypes": ["public.midi-audio"],
                         "CFBundleTypeExtensions": ["mid", "midi", "smf"],
                     }],
                 })
