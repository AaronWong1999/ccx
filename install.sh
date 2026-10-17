#!/bin/sh
# ccx - claudecodex installer (macOS).
#
#   curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh
#
# Puts ccx in ~/Library/Application Support/ccx, installs the ccx plugin into
# the Claude and Codex desktop apps (through the CLIs those apps bundle), and
# builds the menu bar icon locally (so no Developer ID signature is needed).
# Nothing needs sudo. Re-run any time to repair; `ccx update` updates;
# `ccx uninstall` removes.
set -e
REPO="aaronwong1999/ccx"
DEST="$HOME/Library/Application Support/ccx/src"
BIN="$HOME/.local/bin"

say() { printf '%s\n' "$*"; }

[ "$(uname)" = "Darwin" ] || { say "ccx supports macOS only."; exit 1; }
MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[ "$MAJOR" -ge 13 ] 2>/dev/null || say "Note: ccx is tested on macOS 13 and later; you have $(sw_vers -productVersion)."

# Developer install from a checkout: ./install.sh --dev
if [ "${1:-}" = "--dev" ]; then
  HERE="$(cd "$(dirname "$0")" && pwd)"
  exec "$HERE/plugins/ccx/bin/ccx" setup --dev
fi

# --- which desktop apps are here -------------------------------------------
app() { [ -d "/Applications/$1.app" ] || [ -d "$HOME/Applications/$1.app" ]; }
HAS_CLAUDE=0; HAS_CODEX=0
app Claude && HAS_CLAUDE=1
{ app ChatGPT || app Codex; } && HAS_CODEX=1
if [ $HAS_CLAUDE = 0 ] && [ $HAS_CODEX = 0 ]; then
  say "ccx connects the Claude and Codex desktop apps, and neither is installed yet."
  say "  Claude:  https://claude.com/download   (then open it once and click Code)"
  say "  Codex:   https://openai.com/codex      (the Codex / ChatGPT desktop app)"
  say "Install at least one (ideally both), then run this command again. Nothing was changed."
  exit 1
fi

# --- Apple's Command Line Tools (git, python3, swiftc) ----------------------
if ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
  say "ccx needs Apple's Command Line Tools (git, python3, swiftc)."
  say "A macOS window is opening: click Install and accept the license (about 5-10 minutes)."
  say "When it finishes, run this install command again."
  /usr/bin/xcode-select --install >/dev/null 2>&1 || true
  exit 1
fi

say "Installing ccx - claudecodex. What you may see:"
say "  • a macOS notice \"Background Items Added\" — that's the menu bar icon starting at login; keep it on;"
say "  • later, a request to allow notifications — allow it to see sync results;"
say "  • in Codex, \"Trust this folder?\" the first time ccx opens a project there — that's Codex's own check."
say ""

# --- download / update the code (the newest release, never untagged commits) -
export GIT_TERMINAL_PROMPT=0
# git ignores the Mac's system proxy (System Settings → Network, set by apps like
# Clash); use it unless a proxy is already set in the environment.
if [ -z "${https_proxy:-}${HTTPS_PROXY:-}${all_proxy:-}${ALL_PROXY:-}" ]; then
  P="$(/usr/sbin/scutil --proxy 2>/dev/null)"
  for kind in HTTPS HTTP SOCKS; do
    if printf '%s' "$P" | grep -q "${kind}Enable : 1"; then
      host="$(printf '%s' "$P" | awk -v k="${kind}Proxy" '$1==k {print $3}')"
      port="$(printf '%s' "$P" | awk -v k="${kind}Port" '$1==k {print $3}')"
      scheme=http; [ "$kind" = SOCKS ] && scheme=socks5h
      [ -n "$host" ] && export https_proxy="$scheme://$host:${port:-80}" http_proxy="$scheme://$host:${port:-80}" all_proxy="$scheme://$host:${port:-80}" && break
    fi
  done
fi
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch --quiet --force --tags origin || { say "Could not reach github.com/$REPO (no network?). Try again later."; exit 1; }
else
  mkdir -p "$(dirname "$DEST")"
  rm -rf "$DEST"
  git clone --quiet "https://github.com/$REPO.git" "$DEST" ||
    { say "Could not download ccx from github.com/$REPO (no network, or the repository isn't reachable)."; exit 1; }
fi
TAG="$(git -C "$DEST" tag -l 'v[0-9]*' --sort=-v:refname | head -n 1)"
[ -n "$TAG" ] || { say "No ccx release found yet at github.com/$REPO."; exit 1; }
git -C "$DEST" checkout --quiet --force "$TAG"

# --- the `ccx` command on PATH ----------------------------------------------
case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    PROFILE="$HOME/.zprofile"
    case "${SHELL:-}" in */bash) PROFILE="$HOME/.bash_profile" ;; esac
    if ! grep -qs '.local/bin' "$PROFILE"; then
      printf '\n# added by ccx installer\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$PROFILE"
      say "Added ~/.local/bin to your PATH in $PROFILE (new terminal windows pick it up)."
    fi
    ;;
esac

[ $HAS_CLAUDE = 0 ] && say "Note: the Claude desktop app isn't installed; ccx sets up Codex now. Install Claude later and ccx finishes setup by itself (or run: ccx setup)."
[ $HAS_CODEX = 0 ] && say "Note: the Codex desktop app isn't installed; ccx sets up Claude now. Install Codex later and ccx finishes setup by itself (or run: ccx setup)."
exec "$DEST/plugins/ccx/bin/ccx" setup
