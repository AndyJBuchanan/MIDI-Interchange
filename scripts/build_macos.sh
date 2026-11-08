#!/usr/bin/env bash
# Builds dist/MIDI Interchange.app and a distributable DMG next to it.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3.12}"
"$PY" -m venv .venv-build
.venv-build/bin/pip install -q -r requirements.txt -r requirements-dev.txt
.venv-build/bin/pyinstaller --noconfirm --clean midi_interchange.spec
echo "Built: dist/MIDI Interchange.app"

VERSION="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "dist/MIDI Interchange.app/Contents/Info.plist")"
ARCH="$(uname -m)"
DMG="dist/MIDI-Interchange-${VERSION}-macOS-${ARCH}.dmg"
STAGE="build/dmg-staging"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
ditto "dist/MIDI Interchange.app" "$STAGE/MIDI Interchange.app"
ln -s /Applications "$STAGE/Applications"
# hdiutil intermittently fails with "Resource busy" while Spotlight/XProtect scan a fresh bundle; retry.
for attempt in 1 2 3 4 5; do
  if hdiutil create -volname "MIDI Interchange" -srcfolder "$STAGE" -ov -format UDZO "$DMG"; then break; fi
  [ "$attempt" = 5 ] && { echo "hdiutil create failed after $attempt attempts" >&2; exit 1; }
  echo "hdiutil create failed (attempt $attempt), retrying..." >&2
  sleep 3
done
hdiutil verify "$DMG"
shasum -a 256 "$DMG"
echo "Built: $DMG"
