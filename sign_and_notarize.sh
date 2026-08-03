#!/bin/bash
# Sign, notarize and staple Translation Lens for distribution.
#
# Without this, macOS Gatekeeper blocks the app on every machine but the one
# that built it ("Apple could not verify ... is free of malware").  You need a
# paid Apple Developer account.  One-time setup:
#
#   1. Create a "Developer ID Application" certificate in the Apple Developer
#      portal and install it in your login keychain.
#   2. Create an app-specific password at appleid.apple.com.
#   3. Store the credentials once:
#        xcrun notarytool store-credentials translation-notary \
#          --apple-id you@example.com --team-id ABCDE12345 \
#          --password xxxx-xxxx-xxxx-xxxx
#
# Then:  ./sign_and_notarize.sh "Developer ID Application: Your Name (ABCDE12345)"
set -euo pipefail

IDENTITY="${1:-}"
PROFILE="${2:-translation-notary}"
[ -n "$IDENTITY" ] || { echo "usage: $0 \"Developer ID Application: …\" [keychain-profile]"; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$DIR/TranslationLens.spec")"
APP="$DIR/dist/Translation Lens.app"
DMG="$DIR/release/Translation-Lens-$VERSION.dmg"

# A Python app bundles many nested binaries; each needs signing, innermost
# first, and the hardened runtime needs an exception for the unsigned-memory
# execution CPython relies on.
cat > /tmp/translation-entitlements.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.cs.allow-jit</key><true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
  <key>com.apple.security.cs.disable-library-validation</key><true/>
</dict>
</plist>
PLIST

echo "signing nested binaries…"
find "$APP" \( -name "*.so" -o -name "*.dylib" -o -perm -u+x -type f \) -print0 |
while IFS= read -r -d '' f; do
  case "$(file -b "$f")" in
    *Mach-O*) codesign --force --timestamp --options runtime \
                --entitlements /tmp/translation-entitlements.plist \
                --sign "$IDENTITY" "$f" >/dev/null 2>&1 || true ;;
  esac
done

echo "signing the app…"
codesign --force --timestamp --options runtime \
  --entitlements /tmp/translation-entitlements.plist \
  --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "building and signing the disk image…"
"$DIR/make_dmg.sh"
codesign --force --timestamp --sign "$IDENTITY" "$DMG"

echo "notarizing (a few minutes)…"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"
spctl --assess --type open --context context:primary-signature -v "$DMG"

echo
echo "ready to ship: $DMG"
