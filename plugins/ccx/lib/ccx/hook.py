"""The sync hook shared by Claude, Codex and Antigravity: if this conversation
is linked and another app made progress since the last sync, inject it.

    python -m ccx.hook                 (Claude and Codex: UserPromptSubmit)
    python -m ccx.hook --antigravity   (Antigravity: PreInvocation)

The app sends the hook JSON on stdin. On the Claude side it also shows a short
notice ("ccx brought in N updates from Codex"), and, when only the plugin is
installed (from a plugin directory), says where to get the rest of ccx a few
times. It never blocks or fails a prompt: problems are logged and ignored.
Cost warnings belong to the ⇄ menu, at the moment someone transfers.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import traceback

from . import pairs, presence
from .common import L, STATE_DIR, names

LOG = STATE_DIR / "hook.log"
SEEN = STATE_DIR / "antigravity-hook.json"


def _note(res: dict) -> str:
    src = names(res.get("sources") or [res["from"]])
    return L(f"ccx: brought in {res['count']} new updates from {src}", f"ccx：带入了 {src} 的 {res['count']} 条新进展")


def main():
    if "--antigravity" in sys.argv[1:]:
        return antigravity_main()
    try:
        data = json.loads(sys.stdin.read() or "{}")
        sid = data.get("session_id") or data.get("thread_id") or ""
        # Session ids never collide between the apps, so look the id up on every side.
        host = next((t for t in ("claude", "codex") if sid and pairs.find(t, sid)), None)
        res = pairs.pull(host, sid) if host else None
        if host:
            _log(f"{host} session={sid} injected={res['count'] if res else 0}")
        out, notes = {}, []
        if res:
            out["hookSpecificOutput"] = {"hookEventName": "UserPromptSubmit", "additionalContext": res["context"]}
            notes.append(_note(res))
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


def _new_turn(data: dict) -> bool:
    """Antigravity runs the hook before every model call, several times per
    message. Sync once per message: on the turn's first call (invocationNum 0).
    Should a version not say, fall back to the first call after the user's input
    changed (or after ten minutes, for the same words said again)."""
    if data.get("invocationNum") is not None:
        return str(data["invocationNum"]) == "0"
    cid = data.get("conversationId") or ""
    key = hashlib.sha256((data.get("lastUserInput") or "").encode()).hexdigest()[:16]
    try:
        seen = json.loads(SEEN.read_text())
    except (OSError, ValueError):
        seen = {}
    last = seen.get(cid) or ["", 0]
    if last[0] == key and time.time() - last[1] < 600:
        return False
    seen = {k: v for k, v in seen.items() if time.time() - v[1] < 7 * 86400}
    seen[cid] = [key, time.time()]
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SEEN.write_text(json.dumps(seen))
    except OSError:
        pass
    return True


def antigravity_main():
    out = {}
    try:
        data = json.loads(sys.stdin.read() or "{}")
        cid = data.get("conversationId") or ""
        if cid and pairs.find("antigravity", cid) and _new_turn(data):
            res = pairs.pull("antigravity", cid)
            _log(f"antigravity session={cid} injected={res['count'] if res else 0}")
            if res:
                # Only this exact shape: Antigravity's hook runner rejects anything richer
                # (a `metadata` object makes it fail, and the progress would be lost).
                out["injectSteps"] = [{"systemMessage": {"systemMessage": res["context"]}}]
    except Exception:
        _log(traceback.format_exc())
    print(json.dumps(out, ensure_ascii=False))
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
