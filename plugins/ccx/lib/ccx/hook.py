"""UserPromptSubmit hook shared by Claude and Codex: if this conversation is
paired and the other side made progress since the last sync, inject it.

    python -m ccx.hook   (the app sends the hook JSON on stdin)

On the Claude side it also shows a short notice ("ccx brought in N updates from
Codex"), and, when only the plugin is installed (from a plugin directory), says
where to get the rest of ccx a few times. It never blocks or fails a prompt:
problems are logged and ignored.
Cost warnings belong to the ⇄ menu, at the moment someone transfers.
"""

from __future__ import annotations

import json
import sys
import time
import traceback

from . import pairs, presence
from .common import L, NAME, STATE_DIR

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
        out, notes = {}, []
        if res:
            out["hookSpecificOutput"] = {"hookEventName": "UserPromptSubmit", "additionalContext": res["context"]}
            notes.append(L(f"ccx: brought in {res['count']} new updates from {NAME[res['from']]}",
                           f"ccx：带入了 {NAME[res['from']]} 的 {res['count']} 条新进展"))
        # Claude's hook input points at its transcript under ~/.claude; only Claude shows systemMessage.
        claude_side = host == "claude" or "/.claude/" in (data.get("transcript_path") or "")
        if claude_side and presence.nudge_due():
            notes.append("ccx: " + presence.setup_hint())
        if notes and claude_side:
            out["systemMessage"] = "\n".join(notes)
        if out:
            print(json.dumps(out, ensure_ascii=False))
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
