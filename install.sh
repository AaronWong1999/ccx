#!/bin/sh
# Install claudecodex into Claude Code and Codex as local plugins (no store review),
# plus the `ccx` terminal command.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

CODEX=/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex
[ -x "$CODEX" ] || CODEX="$(command -v codex || true)"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"

if [ -x "$CLAUDE" ]; then
  "$CLAUDE" plugin marketplace add "$ROOT" >/dev/null 2>&1 || "$CLAUDE" plugin marketplace update claudecodex >/dev/null 2>&1 || true
  "$CLAUDE" plugin install claudecodex@claudecodex
  echo "✓ Claude Code 插件已安装（新开的会话里生效）"
else
  echo "! 没找到 claude 命令，跳过 Claude 插件"
fi

if [ -n "$CODEX" ]; then
  "$CODEX" plugin marketplace add "$ROOT" >/dev/null 2>&1 || true
  "$CODEX" plugin add claudecodex@claudecodex
  echo "✓ Codex 插件已安装（新开的线程里生效）"
else
  echo "! 没找到 Codex，跳过 Codex 插件"
fi

mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/plugins/claudecodex/bin/ccx" "$HOME/.local/bin/ccx"
echo "✓ 终端命令 ccx → ~/.local/bin/ccx"

if command -v swiftc >/dev/null 2>&1; then
  APP="$("$ROOT/menubar/build.sh")"
  pkill -x ClaudeCodex 2>/dev/null || true
  open "$APP"
  echo "✓ 菜单栏图标 ⇄ 已启动（$APP；菜单里可以勾选「登录时自动启动」）"
else
  echo "! 没有 swiftc（xcode-select --install 可装），跳过菜单栏图标"
fi
