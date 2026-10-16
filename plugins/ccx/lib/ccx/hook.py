"""UserPromptSubmit hook shared by Claude and Codex: if this conversation is
paired and the other side made progress since the last sync, inject it.

    python -m ccx.hook   (the app sends the hook JSON on stdin)

It never blocks or fails the user's prompt: problems are logged and ignored.
"""

from __future__ import annotations

import json
import sys
import time
import traceback

from . import pairs
from .common import STATE_DIR

LOG = STATE_DIR / "hook.log"


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        sid = data.get("session_id") or data.get("thread_id") or ""
        # Session ids never collide between the two apps, so look the id up on both sides.
        host = next((t for t in ("claude", "codex") if sid and pairs.find(t, sid)), None)
        res = pairs.pull(host, sid) if host else None
        if host:
            _log(f"{host} session={sid} injected={res['count'] if res else 0}")
        if res:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                     "additionalContext": res["context"]}}, ensure_ascii=False))
    except Exception:
        _log(traceback.format_exc())
    sys.exit(0)


def _log(line: str):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%m-%d %H:%M:%S ") + line.strip() + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    main()
