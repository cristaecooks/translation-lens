#!/bin/bash
# Build "Translation Lens.app".
#
# The interpreter is copied *inside* the bundle on purpose.  macOS ties the
# Screen Recording permission to the binary that actually runs, so a launcher
# that exec'd the venv python directly would show up in System Settings as a
# nameless "python3.11".  With the interpreter in Contents/MacOS, the grant
# attaches to Translation Lens and survives rebuilds.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/Translation Lens.app"
VENV="$DIR/.venv"
PYVER="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
SITE="$VENV/lib/python$PYVER/site-packages"

"$VENV/bin/python" "$DIR/make_icon.py"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" \
         "$APP/Contents/lib/python$PYVER/site-packages"

cp "$DIR/AppIcon.icns" "$APP/Contents/Resources/"
cp "$VENV/bin/python$PYVER" "$APP/Contents/MacOS/python"

# Make the in-bundle interpreter resolve to this venv: pyvenv.cfg sets
# sys.prefix to Contents/, and the .pth adds the real site-packages.
sed "s|^command = .*|command = bundled|" "$VENV/pyvenv.cfg" > "$APP/Contents/pyvenv.cfg"
echo "$SITE" > "$APP/Contents/lib/python$PYVER/site-packages/_translation.pth"

cat > "$APP/Contents/MacOS/translation-lens" <<SH
#!/bin/bash
# keep a log so problems are diagnosable after the fact
exec "\$(dirname "\$0")/python" "$DIR/lens.py" "\$@" >>"$DIR/data/lens.log" 2>&1
SH
chmod +x "$APP/Contents/MacOS/translation-lens"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>Translation Lens</string>
  <key>CFBundleDisplayName</key>       <string>Translation Lens</string>
  <key>CFBundleIdentifier</key>        <string>local.translation.lens</string>
  <key>CFBundleVersion</key>           <string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleExecutable</key>        <string>translation-lens</string>
  <key>CFBundleIconFile</key>          <string>AppIcon</string>
  <key>NSHighResolutionCapable</key>   <true/>
  <key>LSMinimumSystemVersion</key>    <string>12.0</string>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP"
touch "$APP"
echo "built: $APP"
