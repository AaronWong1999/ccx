#!/bin/sh
# Build the ccx menu bar app.  Usage: build.sh <app path> <ccx command path> <version>
# Built locally from source, so it needs no Developer ID signature or notarization.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-$HOME/Applications/ccx.app}"
CCX="${2:-$(cd "$HERE/.." && pwd)/plugins/ccx/bin/ccx}"
VERSION="${3:-0.0.0}"
TMP="$(mktemp -d)"
mkdir -p "$TMP/ccx.app/Contents/MacOS" "$TMP/ccx.app/Contents/Resources"
swiftc -O -swift-version 5 -o "$TMP/ccx.app/Contents/MacOS/ccx" "$HERE/main.swift" -framework AppKit
cat > "$TMP/ccx.app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>io.github.aaronwong1999.ccx</string>
  <key>CFBundleName</key><string>ccx</string>
  <key>CFBundleDisplayName</key><string>ccx</string>
  <key>CFBundleExecutable</key><string>ccx</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>CCXPath</key><string>$CCX</string>
</dict></plist>
PLIST
codesign --force -s - "$TMP/ccx.app" >/dev/null 2>&1 || true
mkdir -p "$(dirname "$APP")"
rm -rf "$APP"
mv "$TMP/ccx.app" "$APP"
rm -rf "$TMP"
echo "$APP"
