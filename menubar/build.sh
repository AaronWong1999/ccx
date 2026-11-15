#!/bin/sh
# Build the ccx menu bar app.  Usage: build.sh <app path> <ccx command path> <version>
# Built locally from source, so it needs no Developer ID signature or notarization.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-$HOME/Applications/ccx.app}"
CCX="${2:-$(cd "$HERE/.." && pwd)/plugins/ccx/bin/ccx}"
VERSION="${3:-0.0.0}"
mkdir -p "$(dirname "$APP")"
TMP="$(mktemp -d "$(dirname "$APP")/.ccx-build.XXXXXX")"
cleanup() {
  # Compile/sign before touching the installed app. Restore it if the final
  # same-filesystem rename fails or the update is interrupted normally.
  if [ ! -e "$APP" ] && [ -d "$TMP/previous.app" ]; then
    mv "$TMP/previous.app" "$APP"
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
mkdir -p "$TMP/ccx.app/Contents/MacOS" "$TMP/ccx.app/Contents/Resources"
swiftc -O -swift-version 5 -o "$TMP/ccx.app/Contents/MacOS/ccx" "$HERE/main.swift" -framework AppKit
cp "$HERE/AppIcon.icns" "$TMP/ccx.app/Contents/Resources/AppIcon.icns"
cat > "$TMP/ccx.app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>io.github.aaronwong1999.ccx</string>
  <key>CFBundleName</key><string>ccx</string>
  <key>CFBundleDisplayName</key><string>ccx - claudecodex</string>
  <key>CFBundleExecutable</key><string>ccx</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSDesktopFolderUsageDescription</key><string>ccx needs access to project folders on your Desktop to continue tasks between your coding apps.</string>
  <key>NSDocumentsFolderUsageDescription</key><string>ccx needs access to project folders in Documents to continue tasks between your coding apps.</string>
  <key>NSDownloadsFolderUsageDescription</key><string>ccx needs access to project folders in Downloads to continue tasks between your coding apps.</string>
  <key>CCXPath</key><string>$CCX</string>
</dict></plist>
PLIST
codesign --force -s - "$TMP/ccx.app" >/dev/null 2>&1 || true
if [ -e "$APP" ]; then mv "$APP" "$TMP/previous.app"; fi
mv "$TMP/ccx.app" "$APP"
echo "$APP"
