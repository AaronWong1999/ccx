#!/bin/sh
# Build ClaudeCodex.app (menu bar) and install it to ~/Applications.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
APP="$HOME/Applications/ClaudeCodex.app"
mkdir -p "$APP/Contents/MacOS"
swiftc -O -swift-version 5 -o "$APP/Contents/MacOS/ClaudeCodex" "$HERE/main.swift" -framework AppKit -framework ServiceManagement
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.claudecodex.menubar</string>
  <key>CFBundleName</key><string>ClaudeCodex</string>
  <key>CFBundleExecutable</key><string>ClaudeCodex</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.3.0</string>
  <key>CFBundleVersion</key><string>3</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>CCXPath</key><string>$ROOT/plugins/claudecodex/bin/ccx</string>
</dict></plist>
PLIST
codesign --force -s - "$APP" >/dev/null 2>&1 || true
echo "$APP"
