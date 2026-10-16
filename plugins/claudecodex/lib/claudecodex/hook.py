"""UserPromptSubmit hook: if this session is paired and the other side made
progress since the last sync, inject that progress into this turn.

    python -m claudecodex.hook   (hook JSON on stdin; same hook for Claude and Codex)

Never blocks or fails the user's prompt: any problem is logged and ignored.
"""

from __future__ import annotations

import json
import sys
import time
import traceback

from . import pairs


def main():
    log = pairs.STATE_DIR / "hook.log"
    try:
        data = json.loads(sys.stdin.read() or "{}")
        sid = data.get("session_id") or data.get("thread_id") or ""
        # Session ids never collide between the two apps, so look the id up on both sides.
        host = next((t for t in ("claude", "codex") if sid and pairs.find(t, sid)), None)
        res = pairs.pull(host, sid) if host else None
        _log(log, f"{host or '-'} {data.get('hook_event_name')} session={sid} injected={res['count'] if res else 0}")
        if res:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": res["context"],
            }}, ensure_ascii=False))
    except Exception:
        _log(log, traceback.format_exc())
    sys.exit(0)


def _log(path, line: str):
    try:
        pairs.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%m-%d %H:%M:%S ") + line.strip() + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    main()
