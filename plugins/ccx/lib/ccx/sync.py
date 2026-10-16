"""Listing both sides, and bringing a session over to the other app: the first
time by a native import (which pairs the two), afterwards by opening the
partner, where the new progress arrives with the next prompt (see pairs.py)."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Optional

from . import claude, codex, pairs, repairs
from .common import L, NAME, OTHER, Session, git_snapshot, real, same_dir

STATUS = {"new": "not linked", "linked": "linked", "updated": "has new progress", "mirror": "imported copy"}


def deep_link(tool: str, sid: str) -> str:
    return f"codex://threads/{sid}" if tool == "codex" else f"claude://resume?session={sid}"


def open_in_app(tool: str, sid: str) -> bool:
    return subprocess.run(["open", deep_link(tool, sid)], capture_output=True).returncode == 0


def new_claude_conversation(codex_id: str) -> str:
    """Open a new Claude conversation in the thread's folder, prefilled to continue it."""
    t = codex.find(codex_id)
    if not t:
        raise RuntimeError(f"Codex thread {codex_id} not found")
    from urllib.parse import quote
    prompt = f"Continue the \u201c{t.title}\u201d session from Codex (session id {t.id})."
    url = f"claude://code/new?folder={quote(t.cwd)}&q={quote(prompt)}"
    subprocess.run(["open", url], capture_output=True, check=False)
    return url


def new_codex_conversation(claude_id: str) -> str:
    """Open Codex in the session's folder and put a 'continue from Claude' prompt on
    the clipboard (Codex has no link that pre-fills a new chat)."""
    c = claude.find(claude_id)
    if not c:
        raise RuntimeError(f"Claude session {claude_id} not found")
    prompt = f"Continue the \u201c{c.title}\u201d session from Claude (session id {c.id})."
    subprocess.run(["pbcopy"], input=prompt.encode(), check=False)
    subprocess.run([codex.codex_bin(), "app", c.cwd], capture_output=True, check=False)
    return prompt


def continue_phrase(tool: str) -> str:
    """What to say in the partner session to pull `tool`'s progress over."""
    return f"continue from {NAME[tool]}"


# ------------------------------------------------------------------ listing

def sessions(tool: str, cwd: Optional[str] = None, query: Optional[str] = None, limit: int = 30) -> List[Session]:
    if tool == "claude":
        return claude.sessions(cwd, query)[:limit]
    return codex.threads(cwd, query, limit)


def rows(tool: str, ss: List[Session], here_cwd: Optional[str] = None, mirrors=frozenset()) -> List[dict]:
    out = []
    for s in ss:
        st, partner = pairs.status(s)
        if st == "new" and s.id in mirrors:
            st = "mirror"
        row = {"id": s.id, "title": s.title, "updated": s.when, "status": st, "linked_to": partner,
               "cwd": s.cwd, "other_folder": bool(here_cwd and s.cwd and not same_dir(s.cwd, here_cwd))}
        if tool == "claude":
            # Sending a long Claude conversation to Codex: a full import makes Codex
            # read all of it on its first reply; a linked Codex thread may be idle.
            tokens, last = claude.context_state(s.path) if s.path else (0, 0)
            row["own_tokens"] = tokens
            if partner:
                t = codex.find(partner)
                if t:
                    ptok, plast = codex.context_state(t)
                    row["partner_tokens"], row["partner_idle_min"] = ptok, int((time.time() - plast) / 60)
        if tool == "codex" and partner:
            # Opening a huge Claude conversation that has sat idle re-reads all of it:
            # let the menu offer a fresh, linked conversation instead.
            c = claude.find(partner)
            if c:
                tokens, last = claude.context_state(c.path)
                row["partner_tokens"], row["partner_idle_min"] = tokens, int((time.time() - last) / 60)
        out.append(row)
    return out


def find_sessions(tool: str, cwd: Optional[str], query: Optional[str], limit: int = 8) -> List[dict]:
    """The other side's sessions for this project; with a query, search every project
    (a title from a screenshot may belong to any folder)."""
    mirrors = frozenset(codex.import_history().values()) if tool == "codex" else frozenset()
    if query:
        here = sessions(tool, cwd, query, limit)
        rest = [s for s in sessions(tool, None, query, limit * 2) if s.id not in {h.id for h in here}]
        return rows(tool, (here + rest)[:limit], cwd, mirrors)
    ss = sessions(tool, cwd, None, limit)
    return rows(tool, ss or sessions(tool, None, None, limit), cwd, mirrors)


def menu_data(projects: int = 8, per_side: int = 6) -> dict:
    """Recent projects with both sides' sessions, for the menu bar app."""
    mirrors = frozenset(codex.import_history().values())
    by_cwd: Dict[str, dict] = {}
    for s in claude.sessions() + codex.threads(limit=300):
        if not s.cwd:
            continue
        p = by_cwd.setdefault(real(s.cwd), {"claude": [], "codex": [], "mtime": 0.0})
        p[s.tool].append(s)
        p["mtime"] = max(p["mtime"], s.mtime)
    out = []
    for cwd, p in sorted(by_cwd.items(), key=lambda kv: kv[1]["mtime"], reverse=True):
        if "/scratch-workspaces/" in cwd or not os.path.isdir(cwd):
            continue
        newest = lambda xs: sorted(xs, key=lambda s: s.mtime, reverse=True)[:per_side]
        out.append({"cwd": cwd, "name": os.path.basename(cwd),
                    "updated": datetime.fromtimestamp(p["mtime"]).strftime("%m-%d %H:%M"),
                    "codex": rows("codex", newest(p["codex"]), None, mirrors),
                    "claude": rows("claude", newest(p["claude"]))})
        if len(out) >= projects:
            break
    return {"projects": out, "pending_history_repairs": len(repairs.retry_pending())}


# ---------------------------------------------------------------- transfers

def _import_to_codex(src: Session) -> str:
    """Native import of a Claude session into Codex; returns the thread id."""
    prior = codex.import_history().get(str(src.path))
    if prior and codex.find(prior):
        codex.unarchive(prior)  # Codex already has it (from its own app or the official plugin)
        return prior
    tid = codex.import_claude_session(str(src.path), src.cwd, src.title)
    if tid is None:
        # Codex skipped the file: it was imported before, or its recorded folder
        # looks temporary to Codex (sessions started in a scratch workspace and
        # moved later). Import a copy filed under the session's real project.
        tmp = claude.copy_with_new_id(src.path, src.cwd)
        try:
            tid = codex.import_claude_session(str(tmp), src.cwd, src.title)
        finally:
            tmp.unlink(missing_ok=True)
    if not tid:
        raise RuntimeError(f"Codex skipped this session during import (folder {src.cwd}). "
                           f"Run `ccx doctor`, or report it at https://github.com/aaronwong1999/ccx/issues")
    return tid


def _import_to_claude(src: Session) -> str:
    turns = codex.turns_for_claude(codex.items(src.id))
    if not turns:
        raise RuntimeError("this Codex thread has no conversation to import")
    header = (f"[ccx] Imported from Codex thread {src.id} ({src.when}). Tool calls and output are "
              "condensed; the files on disk are the source of truth for code.\n\n")
    turns[0] = (turns[0][0], header + turns[0][1])
    tail = f"\n\n---\n[ccx] git status at import:\n```\n{git_snapshot(src.cwd)}\n```\nPick up from here."
    if turns[-1][0] == "assistant":
        turns[-1] = ("assistant", turns[-1][1] + tail)
    else:
        turns.append(("assistant", tail.strip()))
    return claude.write_session(src.cwd, turns, f"⇄ {src.title or 'Codex thread'}").id


def transfer(tool: str, session_id: str, open_app: bool = True) -> dict:
    """Bring `tool`'s session to the other app: native import + pair the first
    time; afterwards just open the partner."""
    src = claude.find(session_id) if tool == "claude" else codex.find(session_id)
    if not src:
        raise RuntimeError(f"{NAME[tool]} session {session_id} not found")
    dst = OTHER[tool]
    pair = pairs.find(tool, src.id)
    if pair:
        target, action = pair[dst]["id"], "linked"
    else:
        # Capture the source cursor BEFORE the import. A running Claude turn may
        # finish while Codex imports; those late records still need delivery.
        source_side = pairs.side(tool, src.id)
        if dst == "codex" and codex.import_history().get(str(src.path)):
            # An earlier native import is only a snapshot, not proof that today's
            # source progress was delivered. Re-read it once in the first hook.
            source_side["cursor"] = 0
        target = _import_to_codex(src) if dst == "codex" else _import_to_claude(src)
        sides = {tool: source_side, dst: pairs.side(dst, target)}
        pairs.link(sides["claude"], sides["codex"])
        action = "created"
    res = {"action": action, "message": _message(action, tool, src.title),
           "source": {"tool": tool, "id": src.id, "title": src.title},
           "target": {"tool": dst, "id": target, "deep_link": deep_link(dst, target)}, "cwd": src.cwd}
    if dst == "codex":
        # Save the pair before grouping: if grouping fails, retry repairs this
        # thread instead of importing another copy. Also repairs pre-0.0.9 pairs.
        try:
            if open_app:
                target_session = codex.find(target)
                codex.register_desktop_workspace(target_session.cwd if target_session else src.cwd)
            res["target"]["project_id"] = codex.ensure_thread_project(target, src.cwd)
            res["target"]["history_status"] = repairs.prepare(target)
        except (RuntimeError, TimeoutError) as e:
            raise RuntimeError(f"The conversation is linked to Codex thread {target}, but desktop preparation failed: "
                               f"{e}. Retry this transfer to repair it without importing again.") from e
        if res["target"]["history_status"] == "busy":
            res["message"] += (" Older history needs Codex's native format migration, queued until this thread "
                               "is released. Quit Codex when convenient; ccx retries in the background. "
                               "Your conversation and ongoing work are not replaced.")
    if open_app:
        res["opened"] = open_in_app(dst, target)
    return res


def _message(action: str, tool: str, title: str) -> str:
    dst = OTHER[tool]
    if action == "created":
        return L(f"Imported {NAME[tool]} \u201c{title}\u201d into {NAME[dst]} and linked them; they stay in sync from now on.",
                 f"已把 {NAME[tool]} 的「{title}」导入 {NAME[dst]} 并关联，之后两边会自动同步。")
    return L(f"\u201c{title}\u201d is already linked to a {NAME[dst]} conversation, opened it. Send any message there "
             f"(e.g. \u201ccontinue\u201d) and the {NAME[tool]} progress comes along.",
             f"「{title}」已关联到 {NAME[dst]} 的会话，已为你打开。在那里随便说一句（比如\u201c继续\u201d），"
             f"{NAME[tool]} 的进展就会带过去。")
