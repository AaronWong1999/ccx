#!/bin/sh
# ccx installer (macOS).
#
#   curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh
#
# Puts ccx in ~/Library/Application Support/ccx, installs the ccx plugin into
# the Claude and Codex desktop apps (through the CLIs those apps bundle), and
# builds the menu bar icon locally (so no Developer ID signature is needed).
# Re-run any time to repair; `ccx update` updates; `ccx uninstall` removes.
set -e
REPO="aaronwong1999/ccx"
DEST="$HOME/Library/Application Support/ccx/src"

[ "$(uname)" = "Darwin" ] || { echo "ccx 目前只支持 macOS"; exit 1; }

# Developer install from a checkout: ./install.sh --dev
if [ "${1:-}" = "--dev" ]; then
  HERE="$(cd "$(dirname "$0")" && pwd)"
  exec "$HERE/plugins/ccx/bin/ccx" setup --dev
fi

if ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
  echo "ccx 需要「命令行开发者工具」（提供 git、python3、swiftc，约几分钟装完）。"
  echo "正在打开安装窗口；装好后请重新运行这条安装命令。"
  /usr/bin/xcode-select --install >/dev/null 2>&1 || true
  exit 1
fi

if [ ! -d /Applications/Claude.app ] && [ ! -d /Applications/ChatGPT.app ] && [ ! -d /Applications/Codex.app ]; then
  echo "提示：没找到 Claude 或 Codex 桌面版。ccx 会先装好，装了桌面版后运行 ccx setup 即可。"
fi

if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only --quiet
else
  mkdir -p "$(dirname "$DEST")"
  git clone --quiet "https://github.com/$REPO.git" "$DEST"
fi
exec "$DEST/plugins/ccx/bin/ccx" setup
