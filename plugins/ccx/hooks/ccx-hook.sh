#!/bin/sh
# UserPromptSubmit hook: brings the linked session's new progress into this one.
# Claude Code may run with a minimal PATH, so find a usable python3 ourselves.
# /usr/bin/python3 is only a stub until the Command Line Tools are installed
# (running it would pop an installer dialog), so check for them first.
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CANDIDATES="/opt/homebrew/bin/python3 /usr/local/bin/python3"
/usr/bin/xcode-select -p >/dev/null 2>&1 && CANDIDATES="$CANDIDATES /usr/bin/python3"
for py in $CANDIDATES; do
  if [ -x "$py" ] && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PYTHONPATH="$ROOT/lib" exec "$py" -m ccx.hook "$@"
  fi
done
echo "ccx needs Python 3.9+: run xcode-select --install to get the Command Line Tools." >&2
exit 1
