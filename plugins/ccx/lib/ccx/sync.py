"""Listing both sides, and bringing a session over to the other app: the first
time by a native import (which pairs the two), afterwards by opening the
partner, where the new progress arrives with the next prompt (see pairs.py)."""

from __future__ import annotations

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote, urlencode

from . import claude, cloud, codex, pairs, repairs
from .common import HOME, copy_to_clipboard, est_tokens, L, NAME, OTHER, Session, git_snapshot, real, same_dir

STATUS = {"new": "not linked", "linked": "linked", "updated": "has new progress", "mirror": "imported copy"}


def deep_link(tool: str, sid: str) -> str:
    return f"codex://threads/{sid}" if tool == "codex" else f"claude://resume?session={sid}"


def open_in_app(tool: str, sid: str) -> bool:
    return subprocess.run(["open", deep_link(tool, sid)], capture_output=True).returncode == 0


def _open_new_conversation(url: str, app: str) -> str:
    try:
        result = subprocess.run(["open", url], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"Could not open a new {app} conversation: {e}") from e
    if result.returncode:
        raise RuntimeError(f"Could not open a new {app} conversation: " + result.stderr.strip())
    return url


def new_claude_conversation(codex_id: str) -> str:
    """Open a new Claude conversation in the thread's folder, prefilled to continue it."""
    t = codex.find(codex_id)
    if not t:
        raise RuntimeError(f"Codex thread {codex_id} not found")
    prompt = f"Continue the \u201c{t.title}\u201d session from Codex (session id {t.id})."
    url = "claude://code/new?" + urlencode({"folder": real(t.cwd), "q": prompt}, quote_via=quote)
    return _open_new_conversation(url, "Claude")


def new_codex_conversation(claude_id: str) -> str:
    """Open a new Codex chat in the session's folder with its prompt prefilled.

    The native deep link leaves sending to the user and never uses the clipboard.
    See https://learn.chatgpt.com/docs/reference/commands#deep-links.
    """
    c = claude.find(claude_id)
    if not c:
        raise RuntimeError(f"Claude session {claude_id} not found")
    prompt = f"Continue the \u201c{c.title}\u201d session from Claude (session id {c.id})."
    url = "codex://new?" + urlencode({"path": real(c.cwd), "prompt": prompt}, quote_via=quote)
    return _open_new_conversation(url, "Codex")


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
        if partner and _is_cloud(partner):
            st, partner = "new", None  # going back means a new local conversation over there
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
    out = rows(tool, ss or sessions(tool, None, None, limit), cwd, mirrors)
    if tool == "claude" and cwd:
        placed, _ = cloud.place(cloud.claude_sessions()[0], [real(cwd)])
        out += cloud_rows("claude", placed.get(real(cwd), [])[:4], cwd)
    return out


def cloud_rows(tool: str, items: List[dict], cwd: Optional[str] = None) -> List[dict]:
    """Menu rows for cloud sessions, from their listing alone (nothing is downloaded).
    'updated' when the cloud changed after the last read, or the mirror holds
    progress the partner hasn't received."""
    out = []
    for c in items:
        pair = pairs.find(tool, c["id"])
        st, partner = "new", None
        if pair:
            partner, mine = pair[OTHER[tool]]["id"], pair[tool]
            if tool == "codex":
                newer = c["updated_at"] > mine.get("updated_at", 0)
            else:
                m = cloud.mirror(c["id"])
                newer = c["updated_at"] > cloud._mirror_meta(c["id"]).get("fetched_at", 0) + 1 or \
                    bool(m and any(claude.units(m.path)[mine["cursor"]:]))
            st = "updated" if newer else "linked"
        out.append({"id": c["id"], "title": c["title"] or c["id"], "status": st, "linked_to": partner,
                    "updated": datetime.fromtimestamp(c["updated_at"]).strftime("%m-%d %H:%M"),
                    "cwd": cwd or "", "cloud": True})
    return out


def _known_cwds() -> List[str]:
    return list(dict.fromkeys(real(s.cwd) for s in claude.sessions() + codex.threads(limit=300) if s.cwd))


def cloud_cwd(item: Optional[dict]) -> str:
    """The local checkout of a cloud session's repository, else the home folder."""
    if not item:
        return str(HOME)
    placed, _ = cloud.place([item], _known_cwds())
    return next(iter(placed), str(HOME))


def menu_data(projects: int = 8, per_side: int = 6) -> dict:
    """Recent projects with both sides' sessions, for the menu bar app."""
    # The cloud listings (each cached for a few minutes) load while the local sessions are read.
    with ThreadPoolExecutor(2) as ex:
        claude_cloud, codex_cloud = ex.submit(cloud.claude_sessions), ex.submit(cloud.codex_tasks)
        mirrors = frozenset(codex.import_history().values())
        by_cwd: Dict[str, dict] = {}
        for s in claude.sessions() + codex.threads(limit=300):
            if not s.cwd:
                continue
            p = by_cwd.setdefault(real(s.cwd), {"claude": [], "codex": [], "mtime": 0.0})
            p[s.tool].append(s)
            p["mtime"] = max(p["mtime"], s.mtime)
        (claude_cloud, claude_reason), codex_cloud = claude_cloud.result(), codex_cloud.result()[0]
    live = [cwd for cwd in by_cwd if "/scratch-workspaces/" not in cwd and os.path.isdir(cwd)]
    placed = {"claude": cloud.place(claude_cloud, live), "codex": cloud.place(codex_cloud, live)}
    for tool in placed:
        for cwd, items in placed[tool][0].items():
            by_cwd[cwd]["mtime"] = max(by_cwd[cwd]["mtime"], *(c["updated_at"] for c in items))
    out = []
    for cwd, p in sorted(by_cwd.items(), key=lambda kv: kv[1]["mtime"], reverse=True):
        if "/scratch-workspaces/" in cwd or not os.path.isdir(cwd):
            continue
        newest = lambda xs: sorted(xs, key=lambda s: s.mtime, reverse=True)[:per_side]
        out.append({"cwd": cwd, "name": os.path.basename(cwd),
                    "updated": datetime.fromtimestamp(p["mtime"]).strftime("%m-%d %H:%M"),
                    "codex": rows("codex", newest(p["codex"]), None, mirrors)
                    + cloud_rows("codex", placed["codex"][0].get(cwd, [])[:4], cwd),
                    "claude": rows("claude", newest(p["claude"]))
                    + cloud_rows("claude", placed["claude"][0].get(cwd, [])[:4], cwd)})
        if len(out) >= projects:
            break
    return {"projects": out, "pending_history_repairs": len(repairs.retry_pending()),
            "claude_cloud_signin": claude_reason == "not_signed_in",
            "cloud_other": {"claude": cloud_rows("claude", placed["claude"][1][:8]),
                            "codex": cloud_rows("codex", placed["codex"][1][:8])}}


# ---------------------------------------------------------------- transfers

def _import_to_codex(src: Session) -> str:
    """Native import of a Claude session into Codex; returns the thread id."""
    prior = codex.import_history().get(str(src.path))
    if prior and codex.find(prior):
        codex.unarchive(prior)  # Codex already has it (from its own app or the official plugin)
        return prior
    # Codex imports only files under ~/.claude/projects: a cloud session's mirror
    # goes in as a temporary copy filed under its project (as below).
    tid = None if cloud.is_claude(src.id) else codex.import_claude_session(str(src.path), src.cwd, src.title)
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


IMPORT_OVERHEAD = 1.8  # native imports keep tool output ccx clips: measured ~215k vs ~118k rendered


def estimate(tool: str, session_id: str) -> dict:
    """Rough tokens the other app reads on the first reply: after a full native
    import vs. a new conversation that continues from the condensed progress."""
    n, added = pairs.pending(tool, session_id)
    s, us = pairs.session_units(tool, session_id, include_imported=True)
    us = [u for u in us if u]
    if not s or not us:
        return {"full": 0, "condensed": 0, "pending": n, "pending_tokens": added}
    full = int(est_tokens("\n".join(t for _, t in us)) * IMPORT_OVERHEAD)
    condensed = est_tokens(pairs.render(us, tool, pairs.FULL_BUDGET)) + 2_000
    return {"full": full, "condensed": min(condensed, full), "pending": n, "pending_tokens": added}


def transfer(tool: str, session_id: str, open_app: bool = True) -> dict:
    """Bring `tool`'s session to the other app: native import + pair the first
    time; afterwards just open the partner."""
    if tool == "codex" and cloud.is_codex(session_id):
        return _transfer_codex_task(session_id, open_app)
    if tool == "claude" and cloud.is_claude(session_id):
        # Read the cloud conversation now (only this one), into its local mirror.
        item = next((c for c in cloud.claude_sessions()[0] if c["id"] == session_id), None)
        m = cloud.mirror(session_id)
        try:
            cloud.fetch_claude(session_id, m.cwd if m else cloud_cwd(item), item["title"] if item else None)
        except cloud.Unavailable as e:
            if not m:
                why = L(" Claude Code only reads cloud sessions for a program started outside its own sessions: "
                        "use the ⇄ menu or a regular Terminal.",
                        " Claude Code 只为在它的会话之外启动的程序读取云端会话：请用 ⇄ 菜单或普通终端。") \
                    if str(e) == "started_by_session" else ""
                raise RuntimeError(L(f"Couldn't read this cloud session from Claude Code ({e}).",
                                     f"无法通过 Claude Code 读取这个云端会话（{e}）。") + why) from e
        cloud._fresh[session_id] = time.time()
    src = claude.find(session_id) if tool == "claude" else codex.find(session_id)
    if not src:
        raise RuntimeError(f"{NAME[tool]} session {session_id} not found")
    dst = OTHER[tool]
    pair = pairs.find(tool, src.id)
    pending = (0, 0)
    if pair and _is_cloud(pair[dst]["id"]):
        # Cloud sessions only come down to this Mac: a local session goes back to a
        # local one on the other side, and that new pair replaces the cloud link.
        pair = None
    if pair:
        target, action = pair[dst]["id"], "linked"
        pending = pairs.pending(tool, src.id)
        if not pending[0]:
            action = "in_sync"
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
        pending = (0, estimate(tool, src.id)["full"]) if dst == "codex" else (0, 0)
    res = {"action": action, "message": _message(action, tool, src.title, pending),
           "pending": pending[0], "pending_tokens": pending[1],
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
    # A /goal doesn't move between the apps (and ccx won't start autonomous work on
    # its own): say so, with the command ready on the clipboard to set it there.
    g = pairs.goal(tool, src.id)
    if g and g["status"] != "complete":
        there = pairs.goal(dst, target)
        if not (there and there["objective"].strip() == g["objective"].strip() and there["status"] != "complete"):
            res["goal"] = g
            res["message"] += L(f"\n\nThis {NAME[tool]} conversation has an unfinished /goal ({g['status']}). Goals don't "
                                f"carry over by themselves: to keep working toward it in {NAME[dst]}, paste the /goal "
                                f"command that is now on your clipboard.",
                                f"\n\n这个 {NAME[tool]} 对话有一个未完成的 /goal（{g['status']}）。目标不会自动带过去："
                                f"要在 {NAME[dst]} 里继续这个目标，粘贴剪贴板里的 /goal 指令即可。")
            if open_app:
                copy_to_clipboard(f"/goal {g['objective']}")
    if open_app:
        res["opened"] = open_in_app(dst, target)
    return res


def _is_cloud(sid: str) -> bool:
    return cloud.is_claude(sid) or cloud.is_codex(sid)


def _transfer_codex_task(tid: str, open_app: bool) -> dict:
    """A Codex Cloud task into Claude: a new Claude conversation holding the task's
    status and code change, linked so a newer result arrives with the next prompt."""
    t = cloud.codex_task(tid)
    if not t:
        raise RuntimeError(L(f"Codex Cloud task {tid} not found.", f"找不到 Codex 云端任务 {tid}。"))
    pair = pairs.find("codex", tid)
    if pair:
        target, n = pair["claude"]["id"], int(t["updated_at"] > pair["codex"].get("updated_at", 0))
        action = "linked" if n else "in_sync"
    else:
        cwd, n = cloud_cwd(t), 0
        header = (f"[ccx] Imported from Codex Cloud task {tid}. The task ran in the cloud; its change below is "
                  "not applied to this checkout unless the user asks.")
        s = claude.write_session(cwd, [("user", header), ("assistant", cloud.codex_task_text(t) + "\n\nPick up from here.")],
                                 f"⇄ ☁ {t['title'] or 'Codex Cloud task'}")
        target = s.id
        pairs.link(pairs.side("claude", target), {"id": tid, "cwd": cwd, "cursor": 0, "updated_at": t["updated_at"]})
        action = "created"
    res = {"action": action, "message": _message(action, "codex", t["title"], (n, 0)), "pending": n, "pending_tokens": 0,
           "source": {"tool": "codex", "id": tid, "title": t["title"]},
           "target": {"tool": "claude", "id": target, "deep_link": deep_link("claude", target)},
           "cwd": pairs.find("codex", tid)["codex"]["cwd"]}
    if open_app:
        res["opened"] = open_in_app("claude", target)
    return res


def _k(tokens: int) -> str:
    return f"{max(1, round(tokens / 1000))}k"


def _message(action: str, tool: str, title: str, pending=(0, 0)) -> str:
    dst = OTHER[tool]
    n, tokens = pending
    if action == "created":
        cost = L(f" Its first reply there reads about {_k(tokens)} tokens of history.",
                 f"它在那边第一次回复时大约读取 {_k(tokens)} token 的历史。") if tokens else ""
        return L(f"Imported {NAME[tool]} \u201c{title}\u201d into {NAME[dst]} and linked them; they stay in sync from now on.",
                 f"已把 {NAME[tool]} 的「{title}」导入 {NAME[dst]} 并关联，之后两边会自动同步。") + cost
    if action == "in_sync":
        return L(f"\u201c{title}\u201d is already in sync with {NAME[dst]}: nothing new to bring over, nothing was added. "
                 f"Opened the {NAME[dst]} conversation.",
                 f"「{title}」已经和 {NAME[dst]} 同步过了，没有新内容，这次没有追加任何数据。已为你打开 {NAME[dst]} 的会话。")
    if n:
        return L(f"\u201c{title}\u201d is linked; opened it in {NAME[dst]}. {n} new updates (about {_k(tokens)} tokens, condensed) "
                 f"come along with your next message there, once. Nothing is re-sent.",
                 f"「{title}」已关联，已在 {NAME[dst]} 打开。你在那边发下一条消息时，会一次性带入 {n} 条新进展"
                 f"（压缩后约 {_k(tokens)} token），已同步过的不会重复发送。")
    return L(f"\u201c{title}\u201d is already linked to a {NAME[dst]} conversation, opened it. Send any message there "
             f"(e.g. \u201ccontinue\u201d) and the {NAME[tool]} progress comes along.",
             f"「{title}」已关联到 {NAME[dst]} 的会话，已为你打开。在那里随便说一句（比如\u201c继续\u201d），"
             f"{NAME[tool]} 的进展就会带过去。")
