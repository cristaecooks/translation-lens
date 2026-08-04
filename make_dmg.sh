#!/bin/bash
# Build dist/Translation-Lens-<version>.dmg from dist/Translation Lens.app.
#
# The disk image is the drag-to-install kind: it contains the app plus an
# Applications shortcut, so the user drags one onto the other.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$DIR/TranslationLens.spec")"
APP="$DIR/dist/Translation Lens.app"
DMG="$HOME/Desktop/Translation-Lens-$VERSION.dmg"
STAGE="$(mktemp -d)"


[ -d "$APP" ] || { echo "build the app first: python -m PyInstaller TranslationLens.spec"; exit 1; }

echo "staging…"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "$DIR/LICENSES.txt" "$STAGE/Licenses.txt" 2>/dev/null || true
# the install guide is the first thing a buyer should see
# the install guide that ships with the app
cp "$DIR/READ ME.pdf" "$STAGE/READ ME.pdf"

rm -f "$DMG"
# ULMO (LZMA) is markedly smaller than the default zlib: 50 MB vs 78 MB.
# It needs macOS 10.15+ to mount, and this app requires 12 anyway.
hdiutil create -volname "Translation Lens" -srcfolder "$STAGE" \
  -ov -format ULMO -fs HFS+ "$DMG" >/dev/null
rm -rf "$STAGE"

echo "built: $DMG  ($(du -h "$DMG" | cut -f1))"
echo
echo "NOTE: unsigned. On another Mac, Gatekeeper will refuse to open it."
echo "Run ./sign_and_notarize.sh once you have an Apple Developer ID."
