"""UserPromptSubmit hook shared by Claude and Codex: if this conversation is
paired and the other side made progress since the last sync, inject it.

    python -m ccx.hook   (the app sends the hook JSON on stdin)

Two extras, Claude side only:
- a short notice the person can see ("ccx brought in N updates from Codex");
- a one-time stop before a huge, long-idle linked conversation is resumed: its
  prompt cache has expired, so the next message re-reads the whole context
  (hundreds of thousands of tokens). Sending the message again goes ahead.

Apart from that one deliberate stop it never blocks or fails a prompt: problems
are logged and ignored.
"""

from __future__ import annotations

import json
import sys
import time
import traceback

from . import claude, pairs
from .common import L, NAME, STATE_DIR, clip, setting

LOG = STATE_DIR / "hook.log"
GUARD = STATE_DIR / "resume-guard.json"
BIG_CONTEXT = 250_000      # tokens
CACHE_EXPIRED = 55 * 60    # seconds idle after which the prompt cache is gone


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        sid = data.get("session_id") or data.get("thread_id") or ""
        # Session ids never collide between the two apps, so look the id up on both sides.
        host = next((t for t in ("claude", "codex") if sid and pairs.find(t, sid)), None)
        if host == "claude" and guard(sid, data):
            sys.exit(0)
        res = pairs.pull(host, sid) if host else None
        if host:
            _log(f"{host} session={sid} injected={res['count'] if res else 0}")
        if res:
            out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": res["context"]}}
            if host == "claude":
                out["systemMessage"] = L(f"ccx: brought in {res['count']} new updates from {NAME[res['from']]}",
                                         f"ccx：带入了 {NAME[res['from']]} 的 {res['count']} 条新进展")
            print(json.dumps(out, ensure_ascii=False))
    except Exception:
        _log(traceback.format_exc())
    sys.exit(0)


def guard(sid: str, data: dict) -> bool:
    """Stop once before re-reading a huge conversation whose cache has expired."""
    if not setting("warn_long_resume"):
        return False
    s = claude.find(sid)
    if not s:
        return False
    tokens, last = claude.context_state(s.path)
    idle = time.time() - last
    if tokens < BIG_CONTEXT or idle < CACHE_EXPIRED:
        return False
    try:
        warned = json.loads(GUARD.read_text())
    except (OSError, ValueError):
        warned = {}
    if warned.get(sid) == last:
        return False  # already warned about this resume: the person chose to go ahead
    warned[sid] = last
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    GUARD.write_text(json.dumps(warned))
    k, hours = round(tokens / 1000), round(idle / 3600, 1)
    prompt = clip(data.get("prompt") or "", 600)
    reason = L(
        f"ccx paused this message to save your usage. This conversation is about {k}k tokens and has been idle "
        f"for {hours} h, so its cache has expired and continuing here re-reads all {k}k tokens.\n\n"
        f"• Send the same message again to continue here anyway.\n"
        f"• Or run /compact first to shrink this conversation.\n"
        f"• Or start a new conversation in this folder and say “continue from Codex”: it brings over the "
        f"condensed progress (about 20k tokens) and stays linked.\n\n"
        f"Your message:\n{prompt}\n\n(Turn this off in the ⇄ menu: “Warn before resuming long conversations”.)",
        f"ccx 先拦下了这条消息，帮你省额度。这个对话大约 {k}k token，已经闲置 {hours} 小时，缓存已过期，"
        f"在这里继续会把这 {k}k token 全部重新读一遍。\n\n"
        f"• 再发一次同样的消息，就照常在这里继续；\n"
        f"• 或者先运行 /compact 压缩这个对话；\n"
        f"• 或者在这个目录新开一个对话，说「接着 codex 继续」：只带压缩后的进展（约 2 万 token），并保持关联。\n\n"
        f"你的消息：\n{prompt}\n\n（可在 ⇄ 菜单里关闭：「继续超长对话前提醒」）")
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    _log(f"claude session={sid} paused resume: {k}k tokens idle {hours}h")
    return True


def _log(line: str):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%m-%d %H:%M:%S ") + line.strip() + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    main()
