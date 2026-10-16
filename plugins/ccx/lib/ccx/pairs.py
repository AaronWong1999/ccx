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
import time
from typing import List, Optional, Tuple

from . import claude, codex
from .common import NAME, OTHER, PLAN, STATE_DIR, TAG, Session, clip, folder_note, git_snapshot

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


def _set_cursor(claude_id: str, side: str, cursor: int, size: Optional[int] = None):
    pairs = load()
    for p in pairs:
        if p["claude"]["id"] == claude_id:
            p[side]["cursor"] = cursor
            if size is not None:
                p[side]["size"] = size
            p["synced_at"] = time.time()
    save(pairs)


# -------------------------------------------------------------------- units

def session_units(tool: str, sid: str) -> Tuple[Optional[Session], List]:
    if tool == "claude":
        s = claude.find(sid)
        return s, (claude.units(s.path) if s else [])
    s = codex.find(sid)
    return s, (codex.units(codex.items(sid)) if s else [])


def side(tool: str, sid: str) -> dict:
    """A pair side positioned at the session's current end (nothing pending)."""
    s, us = session_units(tool, sid)
    if not s:
        raise RuntimeError(f"{NAME[tool]} session {sid} not found")
    d = {"id": s.id, "cwd": s.cwd, "cursor": len(us)}
    if tool == "codex":
        d["size"] = codex.size_of(s)
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
        f"from it; the files on disk are the source of truth for code.\n" + (f"\n{note}\n" if note else "") +
        f"\n{body}\n\ngit status here:\n```\n{git_snapshot(here_cwd or src.cwd)}\n```\n</{TAG}>"
    )


def pull(here_tool: str, here_id: str, budget: int = HOOK_BUDGET) -> Optional[dict]:
    """The partner's progress since the last sync, or None. Advances the cursor."""
    pair = find(here_tool, here_id)
    if not pair:
        return None
    other = OTHER[here_tool]
    o = pair[other]
    if other == "codex":
        s = codex.find(o["id"])
        if s and codex.size_of(s) == o.get("size"):
            return None  # unchanged since last time: no need to read the thread
    s, us = session_units(other, o["id"])
    if not s:
        return None
    new = [u for u in us[o["cursor"]:] if u]
    _set_cursor(pair["claude"]["id"], other, len(us), codex.size_of(s) if other == "codex" else None)
    if not new:
        return None
    return {"from": other, "session": s.id, "count": len(new),
            "context": wrap(render(new, other, budget), s, pair[here_tool]["cwd"], first=False)}


def continue_from(here_tool: str, here_id: str, here_cwd: str, other_id: str) -> dict:
    """Pair this conversation with `other_id` on the other side and return that
    session's whole (compressed) conversation to carry on from."""
    other = OTHER[here_tool]
    s, us = session_units(other, other_id)
    if not s or not any(us):
        raise RuntimeError(f"{NAME[other]} session {other_id} not found or empty")
    here = side(here_tool, here_id) if (claude.find(here_id) if here_tool == "claude" else codex.find(here_id)) \
        else {"id": here_id, "cwd": here_cwd, "cursor": 0}
    here["cwd"] = here_cwd or here["cwd"]
    there = {"id": s.id, "cwd": s.cwd, "cursor": len(us)}
    if other == "codex":
        there["size"] = codex.size_of(s)
    link(**({"claude_side": here, "codex_side": there} if here_tool == "claude"
            else {"claude_side": there, "codex_side": here}))
    return {"from": other, "session": s.id, "title": s.title, "cwd": s.cwd,
            "context": wrap(render([u for u in us if u], other, FULL_BUDGET), s, here["cwd"], first=True)}


def status(s: Session) -> Tuple[str, Optional[str]]:
    """('new' | 'linked' | 'updated', partner id) for one session.
    'updated' means it has progress its partner hasn't received yet."""
    pair = find(s.tool, s.id)
    if not pair:
        return "new", None
    mine, partner = pair[s.tool], pair[OTHER[s.tool]]["id"]
    if s.tool == "codex":
        if codex.size_of(s) == mine.get("size"):
            return "linked", partner
        us = codex.units(codex.items(s.id))
    else:
        us = claude.units(s.path) if s.path else []
    return ("updated" if any(us[mine["cursor"]:]) else "linked"), partner
