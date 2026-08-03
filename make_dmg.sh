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

# The install guide is authored in Word. Regenerate the plain-text copy the
# disk image carries whenever the .docx is the newer of the two, so edits made
# in Word can't silently fail to reach customers.
if [ -f "$DIR/Read Me First.docx" ]; then
  if [ ! -f "$DIR/Read Me First.txt" ] || \
     [ "$DIR/Read Me First.docx" -nt "$DIR/Read Me First.txt" ]; then
    echo "regenerating Read Me First.txt from the Word document…"
    textutil -convert txt -encoding UTF-8 \
      -output "$DIR/Read Me First.txt" "$DIR/Read Me First.docx"
  fi
fi

echo "staging…"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "$DIR/LICENSES.txt" "$STAGE/Licenses.txt" 2>/dev/null || true
# the install guide is the first thing a buyer should see
# prefer the PDF the customer folder uses, falling back to plain text
cp "$HOME/Desktop/Translation Lens/READ ME.pdf" "$STAGE/READ ME.pdf" 2>/dev/null \
  || cp "$DIR/Read Me First.txt" "$STAGE/Read Me First.txt" 2>/dev/null || true

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
