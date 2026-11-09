#!/usr/bin/env bash
# Builds dist/MIDI Interchange.app and a distributable DMG next to it.
#
# Signing and notarisation are configured in scripts/signing.local.env (git-ignored;
# template: scripts/signing.env.example). Without it, the build is ad-hoc signed only.
#
# Environment overrides:
#   PYTHON=python3.13      interpreter used to create .venv-build
#   SIGNING_ENV=<path>     alternative signing config file
#   SKIP_NOTARIZE=1        sign but don't submit to Apple (faster local test builds)
set -euo pipefail
cd "$(dirname "$0")/.."

APP="dist/MIDI Interchange.app"
SIGNING_ENV="${SIGNING_ENV:-scripts/signing.local.env}"
CODESIGN_IDENTITY="${CODESIGN_IDENTITY:-}"
NOTARY_KEYCHAIN_PROFILE="${NOTARY_KEYCHAIN_PROFILE:-}"
if [ -f "$SIGNING_ENV" ]; then
  # shellcheck disable=SC1090
  source "$SIGNING_ENV"
  echo "Signing config: $SIGNING_ENV"
fi

if [ -n "$CODESIGN_IDENTITY" ]; then
  if ! security find-identity -v -p codesigning | grep -q "$CODESIGN_IDENTITY"; then
    echo "Signing identity '$CODESIGN_IDENTITY' not found in the keychain." >&2
    echo "Run: security find-identity -v -p codesigning" >&2
    exit 1
  fi
  export CODESIGN_IDENTITY
  export ENTITLEMENTS_FILE="$PWD/scripts/entitlements.plist"
else
  echo "WARNING: no CODESIGN_IDENTITY; building ad-hoc signed (other Macs will block it)." >&2
  unset ENTITLEMENTS_FILE || true
fi

# --- build the .app ---------------------------------------------------------
PY="${PYTHON:-python3.12}"
"$PY" -m venv .venv-build
.venv-build/bin/pip install -q -r requirements.txt -r requirements-dev.txt
.venv-build/bin/pyinstaller --noconfirm --clean midi_interchange.spec
echo "Built: $APP"

if [ -n "$CODESIGN_IDENTITY" ]; then
  codesign --verify --deep --strict --verbose=2 "$APP"
  SIGINFO="$(codesign -dvv "$APP" 2>&1)"
  for want in "Authority=Developer ID Application" "flags=0x10000(runtime)" "Timestamp="; do
    grep -qF "$want" <<<"$SIGINFO" || { echo "App signature is missing: $want" >&2; echo "$SIGINFO" >&2; exit 1; }
  done
  grep -E "^Authority=Developer ID Application|^TeamIdentifier|^Timestamp" <<<"$SIGINFO"
fi

# --- package the DMG --------------------------------------------------------
VERSION="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$APP/Contents/Info.plist")"
ARCH="$(uname -m)"
DMG="dist/MIDI-Interchange-${VERSION}-macOS-${ARCH}.dmg"
RW="build/dmg-rw.dmg"
MNT="build/dmg-mount"
rm -rf "$DMG" "$RW" "$MNT" build/dmg-staging
# `hdiutil create -srcfolder` regularly fails with "Resource busy" right after a build (the
# fresh bundle is being scanned by the system). Instead: blank read-write image -> attach ->
# ditto the app in -> detach -> convert to compressed read-only.
APP_MB="$(du -sm "$APP" | cut -f1)"
hdiutil create -size "$((APP_MB + 40))m" -fs HFS+ -volname "MIDI Interchange" -ov "$RW"
mkdir -p "$MNT"
hdiutil attach "$RW" -nobrowse -noverify -noautoopen -mountpoint "$MNT"
ditto "$APP" "$MNT/MIDI Interchange.app"
ln -s /Applications "$MNT/Applications"
for attempt in 1 2 3 4 5; do
  hdiutil detach "$MNT" && break
  [ "$attempt" = 5 ] && { hdiutil detach "$MNT" -force; break; }
  echo "detach busy (attempt $attempt), retrying..." >&2
  sleep 2
done
hdiutil convert "$RW" -format UDZO -imagekey zlib-level=9 -o "$DMG"
rm -rf "$RW" "$MNT"
hdiutil verify "$DMG"

# --- sign, notarise and staple the DMG --------------------------------------
if [ -n "$CODESIGN_IDENTITY" ]; then
  codesign --force --timestamp --sign "$CODESIGN_IDENTITY" "$DMG"
  codesign --verify --verbose=2 "$DMG"

  if [ "${SKIP_NOTARIZE:-0}" = 1 ]; then
    echo "SKIP_NOTARIZE=1: DMG is signed but NOT notarised." >&2
  elif [ -z "$NOTARY_KEYCHAIN_PROFILE" ]; then
    echo "WARNING: no NOTARY_KEYCHAIN_PROFILE; DMG is signed but NOT notarised." >&2
  else
    echo "Submitting to Apple notary service (profile: $NOTARY_KEYCHAIN_PROFILE)..."
    OUT="$(xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_KEYCHAIN_PROFILE" \
            --wait --output-format json)" || true
    echo "$OUT"
    STATUS="$(printf '%s' "$OUT" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)"
    SUB_ID="$(printf '%s' "$OUT" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)"
    if [ "$STATUS" != "Accepted" ]; then
      echo "Notarisation failed (status: ${STATUS:-unknown})." >&2
      [ -n "$SUB_ID" ] && xcrun notarytool log "$SUB_ID" --keychain-profile "$NOTARY_KEYCHAIN_PROFILE" >&2 || true
      exit 1
    fi
    # The DMG's ticket also covers the app inside it; staple both.
    xcrun stapler staple "$DMG"
    xcrun stapler staple "$APP"
    xcrun stapler validate "$DMG"
    spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
    spctl --assess --type execute --verbose=2 "$APP"
  fi
fi

shasum -a 256 "$DMG"
echo "Built: $DMG"
