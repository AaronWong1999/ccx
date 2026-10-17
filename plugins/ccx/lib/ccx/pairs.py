"""Paired sessions (one Claude session <-> one Codex thread) and incremental sync.

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

from . import claude, codex
from .common import NAME, OTHER, PLAN, STATE_DIR, TAG, Session, clip, est_tokens, folder_note, git_snapshot

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


def find(tool: str, sid: str) -> Optional[dict]:
    return next((p for p in load() if p[tool]["id"] == sid), None)


def link(claude_side: dict, codex_side: dict) -> dict:
    """Pair two sessions, replacing any pair either one was in.
    Each side: {"id", "cwd", "cursor"} (+ "size" for Codex)."""
    pairs = [p for p in load() if p["claude"]["id"] != claude_side["id"] and p["codex"]["id"] != codex_side["id"]]
    p = {"claude": claude_side, "codex": codex_side, "linked_at": time.time(), "synced_at": time.time()}
    save(pairs + [p])
    return p


def _set_cursor(claude_id: str, side: str, cursor: int, size: Optional[int] = None,
                updated_at: Optional[float] = None, goal_sent: Optional[str] = None):
    pairs = load()
    for p in pairs:
        if p["claude"]["id"] == claude_id:
            p[side]["cursor"] = cursor
            if goal_sent is not None:
                p[side]["goal_sent"] = goal_sent
            if size is not None:
                p[side]["size"] = size
            if updated_at is not None:
                p[side]["updated_at"] = updated_at
            p["synced_at"] = time.time()
    save(pairs)


# --------------------------------------------------------------------- goal

def goal(tool: str, sid: str) -> Optional[dict]:
    """A session's /goal, read from the app itself (never set by ccx)."""
    if tool == "codex":
        return codex.goal(sid)
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
        s = claude.find(sid)
        return s, (claude.units(s.path, include_imported) if s else [])
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
    last = items[-1][1] if items else ""
    if items and items[-1][0] == "assistant" and last.lstrip().startswith(("[tool", "[ran", "[result", "[edited", "[output")):
        tail.append(f"NOTE: {NAME[src_tool]} stopped in the middle of a step (for example it ran out of usage). "
                    f"Its last action is above; check whether it finished before you go on.")
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
    """The partner's progress since the last sync, or None. Advances the cursor.
    Serialized across processes, so two copies of the hook (e.g. a plugin from a
    directory next to the script-installed one) never deliver the same updates twice."""
    import fcntl
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "sync.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _pull(here_tool, here_id, budget)


def _pull(here_tool: str, here_id: str, budget: int) -> Optional[dict]:
    pair = find(here_tool, here_id)
    if not pair:
        return None
    other = OTHER[here_tool]
    o = pair[other]
    # Rollout size is not a valid change detector for paginated history (new items
    # may live in the history DB). The thread's updatedAt is: skip the full read
    # when it hasn't moved since the last sync (and isn't from the last few seconds).
    if other == "codex":
        s = codex.find(o["id"])
        if not s:
            return None
        if o.get("updated_at") == s.mtime and time.time() - s.mtime > 5:
            return None
        us = codex.units(codex.items(s.id))
    else:
        s, us = session_units(other, o["id"])
        if not s:
            return None
    new = [u for u in us[o["cursor"]:] if u]
    g = goal(other, s.id) if new else None
    note = goal_note(g, other) if new and _goal_key(g) != o.get("goal_sent", "") else ""
    _set_cursor(pair["claude"]["id"], other, len(us), codex.size_of(s) if other == "codex" else None,
                s.mtime if other == "codex" else None, _goal_key(g) if new else None)
    if not new:
        return None
    return {"from": other, "session": s.id, "count": len(new),
            "context": wrap(note + render(new, other, budget), s, pair[here_tool]["cwd"], first=False)}


def continue_from(here_tool: str, here_id: str, here_cwd: str, other_id: str) -> dict:
    """Pair this conversation with `other_id` on the other side and return that
    session's whole (compressed) conversation to carry on from."""
    other = OTHER[here_tool]
    s, us = session_units(other, other_id)
    # A Claude session ccx wrote from a Codex thread, not yet continued in Claude:
    # its imported records are the whole conversation, so show those.
    shown = us if any(us) else session_units(other, other_id, include_imported=True)[1]
    if not s or not any(shown):
        raise RuntimeError(f"{NAME[other]} session {other_id} not found or empty")
    here = side(here_tool, here_id) if (claude.find(here_id) if here_tool == "claude" else codex.find(here_id)) \
        else {"id": here_id, "cwd": here_cwd, "cursor": 0}
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
    link(**({"claude_side": here, "codex_side": there} if here_tool == "claude"
            else {"claude_side": there, "codex_side": here}))
    return {"from": other, "session": s.id, "title": s.title, "cwd": s.cwd,
            "context": wrap(goal_note(g, other) + render([u for u in shown if u], other, FULL_BUDGET), s, here["cwd"],
                            first=True)}


def pending(tool: str, sid: str) -> Tuple[int, int]:
    """(updates, estimated tokens) of `tool`'s progress its partner hasn't received
    yet; the next prompt over there brings them in. Does not advance the cursor."""
    pair = find(tool, sid)
    if not pair:
        return 0, 0
    if tool == "codex":
        t = codex.find(sid)
        if not t or (pair[tool].get("updated_at") == t.mtime and time.time() - t.mtime > 5):
            return 0, 0
    s, us = session_units(tool, sid)
    new = [u for u in us[pair[tool]["cursor"]:] if u] if s else []
    return len(new), (est_tokens(render(new, tool, HOOK_BUDGET)) + 500 if new else 0)


def status(s: Session) -> Tuple[str, Optional[str]]:
    """('new' | 'linked' | 'updated', partner id) for one session.
    'updated' means it has progress its partner hasn't received yet."""
    pair = find(s.tool, s.id)
    if not pair:
        return "new", None
    mine, partner = pair[s.tool], pair[OTHER[s.tool]]["id"]
    if s.tool == "codex":
        if mine.get("updated_at") == s.mtime and time.time() - s.mtime > 5:
            return "linked", partner
        us = codex.units(codex.items(s.id))
    else:
        us = claude.units(s.path) if s.path else []
    return ("updated" if any(us[mine["cursor"]:]) else "linked"), partner
