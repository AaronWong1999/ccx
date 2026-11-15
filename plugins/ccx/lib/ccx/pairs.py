"""Paired sessions and incremental sync.

A pair links two conversations of the same task in two different apps (Claude,
Codex, Antigravity). A conversation can be in one pair per other app, so a task
that lives in all three is three pairs: every app's progress reaches the other
two, each exactly once.

Each side of a pair has a cursor: how many of that side's units have already
been delivered to the other side. Syncing never edits a live session; the
other side's new units are injected into the receiving conversation (by the
UserPromptSubmit hook, or returned from the continue_here tool), and the
cursor moves on, so every piece of progress is delivered exactly once.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import List, Optional, Tuple

from . import antigravity, claude, cloud, codex
from .common import NAME, OTHER, PLAN, STATE_DIR, TAG, TOOLS, Session, clip, est_tokens, folder_note, git_snapshot

PAIRS = STATE_DIR / "pairs.json"
HOOK_BUDGET = 24_000   # chars injected automatically with a prompt
FULL_BUDGET = 60_000   # chars for a first "continue from that session"


# ------------------------------------------------------------------ storage

def load() -> List[dict]:
    try:
        return json.loads(PAIRS.read_text())
    except (OSError, ValueError):
        return []


def save(pairs: List[dict]):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PAIRS.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(pairs, ensure_ascii=False, indent=1))
    os.replace(tmp, PAIRS)


def tools_of(p: dict) -> List[str]:
    return [t for t in TOOLS if t in p]


def partner_tool(p: dict, tool: str) -> str:
    return next(t for t in tools_of(p) if t != tool)


def find_all(tool: str, sid: str) -> List[dict]:
    """Every pair `tool`'s session is in: at most one per other app."""
    return [p for p in load() if tool in p and p[tool]["id"] == sid]


def find(tool: str, sid: str, other: Optional[str] = None) -> Optional[dict]:
    """The session's pair with `other` (any pair when not given; the usual
    partner app first)."""
    ps = [p for p in find_all(tool, sid) if other is None or other in p]
    return next((p for p in ps if OTHER[tool] in p), ps[0] if ps else None)


def link(a: dict, b: dict, tools: Tuple[str, str] = ("claude", "codex")) -> dict:
    """Pair two sessions (of the two `tools`, in that order), replacing any pair
    between those two apps either one was in.
    Each side: {"id", "cwd", "cursor"} (+ "size" for Codex)."""
    ta, tb = tools
    pairs = [p for p in load() if not (ta in p and tb in p and (p[ta]["id"] == a["id"] or p[tb]["id"] == b["id"]))]
    p = {ta: a, tb: b, "linked_at": time.time(), "synced_at": time.time()}
    save(pairs + [p])
    return p


def unlink(tool: str, sid: str, other: Optional[str] = None) -> List[dict]:
    """Forget the pairs `tool`'s session is in (only the one with `other`, when
    given), with their cursors; every conversation stays as it is. Returns the
    pairs it removed."""
    pairs = load()
    gone = [p for p in pairs if tool in p and p[tool]["id"] == sid and (other is None or other in p)]
    if gone:
        save([p for p in pairs if not any(p is g for g in gone)])
    return gone


def _update(pair: dict, tool: str, **fields):
    """Move one side of a pair on (cursor, and what detects the next change)."""
    a, b = tools_of(pair)
    pairs = load()
    for p in pairs:
        if a in p and b in p and p[a]["id"] == pair[a]["id"] and p[b]["id"] == pair[b]["id"]:
            p[tool].update({k: v for k, v in fields.items() if v is not None})
            p["synced_at"] = time.time()
    save(pairs)


def lookup(tool: str, sid: str) -> Optional[Session]:
    try:
        if tool == "claude":
            return claude.find(sid)
        if tool == "codex":
            return codex.find(sid)
        return antigravity.find(sid) if antigravity.installed() else None
    except RuntimeError:
        return None  # that app isn't installed


def locate(sid: str, among=TOOLS) -> Optional[Session]:
    """The session with this id, whichever app it belongs to (ids never collide)."""
    for t in among:
        s = lookup(t, sid)
        if s:
            return s
    return None


def close_triangle(a_tool: str, a_id: str, b_tool: str, b_id: str):
    """`a` and `b` were just linked. When `a` is also linked to a conversation in
    the third app, link that one to `b` too, so all three stay in sync. It owes
    `b` exactly the progress it still owes `a`."""
    third = next((t for t in TOOLS if t not in (a_tool, b_tool)), None)
    pa = find(a_tool, a_id, third) if third else None
    if not pa or cloud.is_claude(pa[third]["id"]) or cloud.is_codex(pa[third]["id"]):
        return
    if find(third, pa[third]["id"], b_tool) or find(b_tool, b_id, third):
        return
    try:
        b_side = side(b_tool, b_id)
    except RuntimeError:
        return
    link(dict(pa[third]), b_side, tools=(third, b_tool))


# --------------------------------------------------------------------- goal

def goal(tool: str, sid: str) -> Optional[dict]:
    """A session's /goal, read from the app itself (never set by ccx)."""
    if tool == "codex":
        return codex.goal(sid)
    if tool == "antigravity":
        return None
    s = claude.find(sid)
    return claude.goal(s.path) if s and s.path else None


def goal_note(g: Optional[dict], tool: str) -> str:
    if not g:
        return ""
    state = "completed" if g["status"] == "complete" else g["status"]
    return (f"The user's /goal in {NAME[tool]} ({state}): \u201c{g['objective']}\u201d. Goals don't transfer between "
            f"the apps by themselves; if the user sets it here with /goal, work toward it.\n\n")


def _goal_key(g: Optional[dict]) -> str:
    return f"{g['status']}:{g['objective']}" if g else ""


# -------------------------------------------------------------------- units

def session_units(tool: str, sid: str, include_imported: bool = False) -> Tuple[Optional[Session], List]:
    if tool == "claude":
        s = cloud.refresh_claude(sid) if cloud.is_claude(sid) else claude.find(sid)
        return s, (claude.units(s.path, include_imported) if s else [])
    if tool == "antigravity":
        s = antigravity.find(sid)
        return s, (antigravity.units(antigravity.steps(s.id), include_imported) if s else [])
    s = codex.find(sid)
    return s, (codex.units(codex.items(sid)) if s else [])


def side(tool: str, sid: str) -> dict:
    """A pair side positioned at the session's current end (nothing pending)."""
    s, us = session_units(tool, sid)
    if not s:
        raise RuntimeError(f"{NAME[tool]} session {sid} not found")
    d = {"id": s.id, "cwd": s.cwd, "cursor": len(us)}
    if tool == "codex":
        d["size"], d["updated_at"] = codex.size_of(s), s.mtime
    return d


# ------------------------------------------------------------------- deltas

def render(items: List[Tuple[str, str]], src_tool: str, budget: int) -> str:
    """Readable transcript of units, keeping the newest within budget. The latest
    task list is always kept in full, and a turn cut off mid-step is called out."""
    who = {"user": "[user] ", "assistant": f"[{NAME[src_tool]}] "}
    plan = next((t for _, t in reversed(items) if t.startswith(PLAN)), None)
    lines = [who[r] + t.strip() for r, t in items if not (t.startswith(PLAN) and t is not plan)]
    kept, size = [], 0
    for line in reversed(lines):
        if size + len(line) > budget and kept:
            break
        kept.append(line)
        size += len(line)
    kept.reverse()
    head = []
    dropped = len(lines) - len(kept)
    if dropped:
        shown = set(kept)
        asks = [clip(t, 200) for r, t in items if r == "user" and who["user"] + t.strip() not in shown]
        head.append(f"({dropped} earlier entries omitted. The user had asked: " + " | ".join(asks[-15:]) + ")")
    if plan and not any(plan.strip() in k for k in kept):
        head.append(f"Latest task list:\n{plan[len(PLAN):].strip()}")
    tail = []
    last = items[-1][1].lstrip().lower() if items else ""
    if items and items[-1][0] == "assistant" and last.startswith((
            "[tool", "[ran", "[result", "[edited", "[output", "you've hit your", "you have hit your",
            "api error: 429", "已达到会话限额", "已达到用量上限")):
        tail.append(f"NOTE: {NAME[src_tool]} stopped in the middle of a step (for example it ran out of usage). "
                    "Check its last edits and test results, then resume the unfinished step; "
                    "do not restart work that is already complete.")
    return "\n\n".join(head + kept + tail)


def wrap(body: str, src: Session, here_cwd: str, first: bool) -> str:
    what = "whole conversation (condensed)" if first else "progress since the last sync"
    note = folder_note(here_cwd, src.cwd, src.tool)
    return (
        f"<{TAG} from=\"{src.tool}\" session=\"{src.id}\" title=\"{src.title}\">\n"
        f"Below is this task's {what} in {NAME[src.tool]}. Treat it as work you already did and carry on "
        f"from it; the files on disk are the source of truth for code. A line like [image: /path] is an image "
        f"the user shared: open that file if you need to see it.\n" + (f"\n{note}\n" if note else "") +
        f"\n{body}\n\ngit status here:\n```\n{git_snapshot(here_cwd or src.cwd)}\n```\n</{TAG}>"
    )


def pull(here_tool: str, here_id: str, budget: int = HOOK_BUDGET) -> Optional[dict]:
    """The partners' progress since the last sync, or None. Advances the cursors.
    Serialized across processes, so two copies of the hook (e.g. a plugin from a
    directory next to the script-installed one) never deliver the same updates twice."""
    import fcntl
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "sync.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _pull(here_tool, here_id, budget)


def _pull(here_tool: str, here_id: str, budget: int) -> Optional[dict]:
    got, updates = [], []
    for pair in find_all(here_tool, here_id):
        try:
            d = _delta(pair, here_tool, budget, updates)
        except antigravity.Unavailable:
            continue  # Antigravity is closed: its progress comes with a later prompt
        if d:
            got.append(d)
    # Commit only after every source rendered successfully. A failure in source
    # two must not consume source one before the hook can deliver its context.
    for pair, other, fields in updates:
        _update(pair, other, **fields)
    if not got:
        return None
    return {"from": got[0]["from"], "sources": [d["from"] for d in got], "session": got[0]["session"],
            "count": sum(d["count"] for d in got), "context": "\n\n".join(d["context"] for d in got)}


def _delta(pair: dict, here_tool: str, budget: int, updates: list) -> Optional[dict]:
    """One partner's new progress; moves that partner's cursor on."""
    other = partner_tool(pair, here_tool)
    o = pair[other]
    # Rollout size is not a valid change detector for paginated history (new items
    # may live in the history DB). The thread's updatedAt is: skip the full read
    # when it hasn't moved since the last sync (and isn't from the last few seconds).
    if other == "codex" and cloud.is_codex(o["id"]):
        return _pull_codex_task(pair, here_tool, updates)
    if other == "codex":
        s = codex.find(o["id"])
        if not s:
            return None
        if o.get("updated_at") == s.mtime and time.time() - s.mtime > 5:
            return None
        us = codex.units(codex.items(s.id))
    elif other == "antigravity":
        s = antigravity.find(o["id"])
        if not s or s.steps <= o["cursor"]:
            return None  # read from Antigravity's summary table: no need for the app to run
        us = antigravity.units(antigravity.steps(s.id))
    else:
        s, us = session_units(other, o["id"])
        if not s:
            return None
    new = [u for u in us[o["cursor"]:] if u]
    g = goal(other, s.id) if new else None
    note = goal_note(g, other) if new and _goal_key(g) != o.get("goal_sent", "") else ""
    # Prepare all context before consuming the delta. If rendering fails, the
    # hook logs and skips this run; the next prompt must still receive it.
    result = {"from": other, "session": s.id, "count": len(new),
              "context": wrap(note + render(new, other, budget), s, pair[here_tool]["cwd"], first=False)} if new else None
    updates.append((pair, other, dict(cursor=len(us), size=codex.size_of(s) if other == "codex" else None,
                   updated_at=s.mtime if other == "codex" else None, goal_sent=_goal_key(g) if new else None)))
    return result


def _pull_codex_task(pair: dict, here_tool: str, updates: list) -> Optional[dict]:
    """A Codex Cloud task's new result (a newer attempt or change) since the last sync."""
    o = pair["codex"]
    t = cloud.codex_task(o["id"])
    if not t or t["updated_at"] <= o.get("updated_at", 0):
        return None
    s = cloud.codex_session(t, o["cwd"])
    result = {"from": "codex", "session": t["id"], "count": 1,
              "context": wrap(render([("assistant", cloud.codex_task_text(t))], "codex", HOOK_BUDGET),
                              s, pair[here_tool]["cwd"], first=False)}
    updates.append((pair, "codex", dict(cursor=0, updated_at=t["updated_at"])))
    return result


def continue_from(here_tool: str, here_id: str, here_cwd: str, other_id: str, other: Optional[str] = None) -> dict:
    """Pair this conversation with `other_id` in another app and return that
    session's whole (compressed) conversation to carry on from."""
    if not other:
        found = locate(other_id, [t for t in TOOLS if t != here_tool])
        other = found.tool if found else ("claude" if cloud.is_claude(other_id) else OTHER[here_tool])
    if other == "claude" and cloud.is_claude(other_id) and not cloud.mirror(other_id):
        cloud.refresh_claude(other_id, here_cwd)  # first read: file it under this folder
    s, us = session_units(other, other_id)
    # A session ccx wrote from another app's conversation, not yet continued there:
    # its imported records are the whole conversation, so show those.
    shown = us if any(us) else session_units(other, other_id, include_imported=True)[1]
    if not s or not any(shown):
        raise RuntimeError(f"{NAME[other]} session {other_id} not found or empty")
    here = side(here_tool, here_id) if lookup(here_tool, here_id) else {"id": here_id, "cwd": here_cwd, "cursor": 0}
    here["cwd"] = here_cwd or here["cwd"]
    if here_tool == "codex":
        # In-conversation imports stay in the current thread's own workspace.
        # A foreign Claude folder remains reference context, never a silent move.
        opened_workspace = codex.register_desktop_workspace(here["cwd"])
        codex.ensure_thread_project(here_id, here["cwd"])
        if opened_workspace:
            subprocess.run(["open", f"codex://threads/{here_id}"], capture_output=True, check=False)
    g = goal(other, s.id)
    there = {"id": s.id, "cwd": s.cwd, "cursor": len(us), "goal_sent": _goal_key(g)}
    if other == "codex":
        there["size"], there["updated_at"] = codex.size_of(s), s.mtime
    context = wrap(goal_note(g, other) + render([u for u in shown if u], other, FULL_BUDGET), s, here["cwd"], first=True)
    link(here, there, tools=(here_tool, other))
    close_triangle(other, s.id, here_tool, here_id)
    return {"from": other, "session": s.id, "title": s.title, "cwd": s.cwd,
            "context": context}


def pending(tool: str, sid: str, other: Optional[str] = None) -> Tuple[int, int]:
    """(updates, estimated tokens) of `tool`'s progress its partner in `other`
    hasn't received yet; the next prompt over there brings them in. Does not
    advance the cursor."""
    pair = find(tool, sid, other)
    if not pair:
        return 0, 0
    if tool == "codex":
        t = codex.find(sid)
        if not t or (pair[tool].get("updated_at") == t.mtime and time.time() - t.mtime > 5):
            return 0, 0
    if tool == "antigravity":
        a = antigravity.find(sid)
        if not a or a.steps <= pair[tool]["cursor"]:
            return 0, 0
    s, us = session_units(tool, sid)
    new = [u for u in us[pair[tool]["cursor"]:] if u] if s else []
    return len(new), (est_tokens(render(new, tool, HOOK_BUDGET)) + 500 if new else 0)


def links(s: Session) -> dict:
    """{other app: {"id", "status"}} for every app this session is linked in.
    Status 'updated' means it has progress that partner hasn't received yet."""
    out, us = {}, None
    for pair in find_all(s.tool, s.id):
        other, mine = partner_tool(pair, s.tool), pair[s.tool]
        if s.tool == "antigravity":
            # Step counts come from Antigravity's summary table: the app needn't run.
            st = "updated" if getattr(s, "steps", 0) > mine["cursor"] else "linked"
        elif s.tool == "codex" and mine.get("updated_at") == s.mtime and time.time() - s.mtime > 5:
            st = "linked"
        else:
            if us is None:
                us = codex.units(codex.items(s.id)) if s.tool == "codex" else (claude.units(s.path) if s.path else [])
            st = "updated" if any(us[mine["cursor"]:]) else "linked"
        out[other] = {"id": pair[other]["id"], "status": st}
    return out


def status(s: Session) -> Tuple[str, Optional[str]]:
    """('new' | 'linked' | 'updated', partner id) for one session, over all its
    links; the partner is the one in its usual partner app when it has several."""
    lk = links(s)
    if not lk:
        return "new", None
    partner = (lk.get(OTHER[s.tool]) or next(iter(lk.values())))["id"]
    return ("updated" if any(v["status"] == "updated" for v in lk.values()) else "linked"), partner
