"""Listing every app's sessions, and bringing a session over to another app: the first
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

from . import antigravity, claude, cloud, codex, pairs, repairs, zcode
from .common import (HOME, TOOLS, copy_to_clipboard, est_tokens, L, NAME, OTHER, Session, git_snapshot,
                     real, same_dir, setting)

STATUS = {"new": "not linked", "linked": "linked", "updated": "has new progress", "mirror": "imported copy"}


def deep_link(tool: str, sid: str) -> str:
    """The app's own link to a conversation ('' for Antigravity and ZCode, which have none)."""
    if tool in ("antigravity", "zcode"):
        return ""
    return f"codex://threads/{sid}" if tool == "codex" else f"claude://resume?session={sid}"


def open_in_app(tool: str, sid: str) -> bool:
    if tool == "antigravity":
        return antigravity.open_app()
    if tool == "zcode":
        return zcode.open_app()
    return subprocess.run(["open", deep_link(tool, sid)], capture_output=True).returncode == 0


def _open_new_conversation(url: str, app: str) -> str:
    try:
        result = subprocess.run(["open", url], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"Could not open a new {app} conversation: {e}") from e
    if result.returncode:
        raise RuntimeError(f"Could not open a new {app} conversation: " + result.stderr.strip())
    return url


def new_conversation(dst: str, sid: str) -> str:
    """Open a new `dst` conversation in the session's folder, prefilled to continue
    it. Each app's own deep link leaves sending to the user and never uses the
    clipboard (Codex: https://learn.chatgpt.com/docs/reference/commands#deep-links)."""
    src = pairs.locate(sid, [t for t in TOOLS if t != dst])
    if not src:
        raise RuntimeError(f"session {sid} not found")
    prompt = f"Continue the \u201c{src.title}\u201d session from {NAME[src.tool]} (session id {src.id})."
    if dst == "claude":
        url = "claude://code/new?" + urlencode({"folder": real(src.cwd), "q": prompt}, quote_via=quote)
    elif dst == "codex":
        url = "codex://new?" + urlencode({"path": real(src.cwd), "prompt": prompt}, quote_via=quote)
    elif dst == "antigravity":
        url = antigravity.new_conversation_link(real(src.cwd), prompt)
    else:
        raise RuntimeError(L("ZCode has no link that opens a new conversation with a prompt filled in: "
                             "move the conversation to ZCode instead.",
                             "ZCode 没有能打开新对话并填好指令的链接：请直接把对话转到 ZCode。"))
    return _open_new_conversation(url, NAME[dst])


def new_claude_conversation(sid: str) -> str:
    return new_conversation("claude", sid)


def new_codex_conversation(sid: str) -> str:
    return new_conversation("codex", sid)


def continue_phrase(tool: str) -> str:
    """What to say in the partner session to pull `tool`'s progress over."""
    return f"continue from {NAME[tool]}"


# ------------------------------------------------------------------ listing

def sessions(tool: str, cwd: Optional[str] = None, query: Optional[str] = None, limit: int = 30) -> List[Session]:
    if tool == "claude":
        return claude.sessions(cwd, query)[:limit]
    if tool == "antigravity":
        return antigravity.sessions(cwd, query, limit)
    if tool == "zcode":
        return zcode.sessions(cwd, query, limit)
    return codex.threads(cwd, query, limit)


def rows(tool: str, ss: List[Session], here_cwd: Optional[str] = None, mirrors=frozenset()) -> List[dict]:
    out = []
    for s in ss:
        # going back from a cloud session means a new local conversation over there
        lk = {t: v for t, v in pairs.links(s).items() if not _is_cloud(v["id"])}
        st = "updated" if any(v["status"] == "updated" for v in lk.values()) else "linked" if lk else "new"
        partner = (lk.get(OTHER[tool]) or next(iter(lk.values())))["id"] if lk else None
        if st == "new" and s.id in mirrors:
            st = "mirror"
        row = {"id": s.id, "title": s.title, "updated": s.when, "status": st, "linked_to": partner, "links": lk,
               "cwd": s.cwd, "other_folder": bool(here_cwd and s.cwd and not same_dir(s.cwd, here_cwd))}
        partner = (lk.get(OTHER[tool]) or {}).get("id") if tool in ("claude", "codex") else None
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
        pair = pairs.find(tool, c["id"], OTHER[tool])
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
                    "links": {OTHER[tool]: {"id": partner, "status": st}} if partner else {},
                    "updated": datetime.fromtimestamp(c["updated_at"]).strftime("%m-%d %H:%M"),
                    "cwd": cwd or "", "cloud": True})
    return out


def _known_cwds() -> List[str]:
    return list(dict.fromkeys(real(s.cwd) for s in _all_sessions() if s.cwd))


def _all_sessions() -> List[Session]:
    out = list(claude.sessions())
    try:
        out += codex.threads(limit=300)
    except RuntimeError:
        pass  # Codex isn't installed
    if antigravity.installed():
        out += antigravity.sessions(limit=300)
    if zcode.installed():
        out += zcode.sessions(limit=300)
    return out


def apps() -> List[str]:
    """The apps ccx moves conversations between on this Mac, in menu order."""
    return ["claude", "codex"] + (["antigravity"] if antigravity.installed() else []) \
        + (["zcode"] if zcode.installed() else [])


def cloud_cwd(item: Optional[dict]) -> str:
    """The local checkout of a cloud session's repository, else the home folder."""
    if not item:
        return str(HOME)
    placed, _ = cloud.place([item], _known_cwds())
    return next(iter(placed), str(HOME))


def menu_data(projects: int = 8, per_side: int = 6) -> dict:
    """Recent projects with every app's sessions, for the menu bar app."""
    # The cloud listings (each cached for a few minutes) load while the local sessions are read.
    with ThreadPoolExecutor(2) as ex:
        claude_cloud, codex_cloud = ex.submit(cloud.claude_sessions), ex.submit(cloud.codex_tasks)
        mirrors = frozenset(codex.import_history().values())
        by_cwd: Dict[str, dict] = {}
        for s in _all_sessions():
            if not s.cwd:
                continue
            p = by_cwd.setdefault(real(s.cwd), {"claude": [], "codex": [], "antigravity": [], "zcode": [], "mtime": 0.0})
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
                    + cloud_rows("claude", placed["claude"][0].get(cwd, [])[:4], cwd),
                    "antigravity": rows("antigravity", newest(p["antigravity"])),
                    "zcode": rows("zcode", newest(p["zcode"]))})
        if len(out) >= projects:
            break
    return {"projects": out, "apps": apps(), "pending_history_repairs": len(repairs.retry_pending()),
            "claude_cloud_signin": claude_reason == "not_signed_in",
            "cloud_other": {"claude": cloud_rows("claude", placed["claude"][1][:8]),
                            "codex": cloud_rows("codex", placed["codex"][1][:8])}}


# ---------------------------------------------------------------- transfers

def _turns(us: list) -> list:
    """Alternating (user, assistant) turns from units, for writing a Claude session."""
    turns: list = []
    for u in us:
        if not u:
            continue
        if turns and turns[-1][0] == u[0]:
            turns[-1][1].append(u[1])
        else:
            turns.append([u[0], [u[1]]])
    while turns and turns[0][0] != "user":
        turns.pop(0)
    return [(r, "\n\n".join(c)) for r, c in turns]


KIND = {"claude": "Claude session", "codex": "Codex thread", "antigravity": "Antigravity conversation",
        "zcode": "ZCode conversation"}


def _marked(src: Session) -> str:
    """The title an imported copy gets: ⇄ in front, once, however many apps it has been through."""
    return "⇄ " + ((src.title or "").lstrip("⇄ ").strip() or KIND[src.tool])


def _import_to_codex(src: Session) -> str:
    """Native import into Codex; returns the thread id. A Claude session goes in
    as it is; an Antigravity conversation as a temporary Claude-format copy,
    because Codex's own importer is what gives the thread real history."""
    if src.tool != "claude":
        tmp = claude.write_session(src.cwd, _claude_turns(src), _marked(src))
        try:
            tid = codex.import_claude_session(str(tmp.path), src.cwd, _marked(src))
        finally:
            tmp.path.unlink(missing_ok=True)
        if not tid:
            raise RuntimeError(f"Codex skipped this conversation during import (folder {src.cwd}). "
                               f"Run `ccx doctor`, or report it at https://github.com/aaronwong1999/ccx/issues")
        return tid
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


def _claude_turns(src: Session) -> list:
    """`src`'s conversation as Claude turns, with where it came from and the state of the folder."""
    if src.tool == "codex":
        turns = codex.turns_for_claude(codex.items(src.id))
    else:
        turns = _turns(pairs.session_units(src.tool, src.id, include_imported=True)[1])
    if not turns:
        raise RuntimeError(f"this {KIND[src.tool]} has no conversation to import")
    header = (f"[ccx] Imported from {KIND[src.tool]} {src.id} ({src.when}). Tool calls and output are "
              "condensed; the files on disk are the source of truth for code.\n\n")
    turns[0] = (turns[0][0], header + turns[0][1])
    tail = f"\n\n---\n[ccx] git status at import:\n```\n{git_snapshot(src.cwd)}\n```\nPick up from here."
    if turns[-1][0] == "assistant":
        turns[-1] = ("assistant", turns[-1][1] + tail)
    else:
        turns.append(("assistant", tail.strip()))
    return turns


def _import_to_claude(src: Session) -> str:
    return claude.write_session(src.cwd, _claude_turns(src), _marked(src)).id


def _import_to_zcode(src: Session) -> str:
    """ZCode's own import (what its "import from Claude Code" does): the conversation
    becomes the new ZCode conversation's real history."""
    return zcode.new_session(src.cwd, _marked(src), _claude_turns(src))


# Antigravity has no way to add history to a conversation: a new one starts with
# the condensed conversation as its first message, which its model answers once.
ANTIGRAVITY_IMPORT_NOTE = (
    "[ccx] The user moved this task here from {app} to keep working on it in Antigravity. This message only "
    "carries the context: do not start working and do not call any tools yet. Reply with one short line "
    "saying you have the context from {app} and are ready, then wait for the user's next message.")


ANTIGRAVITY_ACK_MODEL = "flash_lite"


def _import_to_antigravity(src: Session) -> str:
    _, us = pairs.session_units(src.tool, src.id, include_imported=True)
    shown = [u for u in us if u]
    if not shown:
        raise RuntimeError(f"this {KIND[src.tool]} has no conversation to import")
    body = pairs.wrap(pairs.goal_note(pairs.goal(src.tool, src.id), src.tool)
                      + pairs.render(shown, src.tool, pairs.FULL_BUDGET), src, src.cwd, first=True)
    # The light model only says "got it" (seconds, not a minute on the default
    # model); the user's next message goes to the model they picked.
    cid = antigravity.new_conversation(src.cwd, _marked(src),
                                       body + "\n\n" + ANTIGRAVITY_IMPORT_NOTE.format(app=NAME[src.tool]),
                                       model=ANTIGRAVITY_ACK_MODEL)
    antigravity.wait_idle(cid)  # its one-line reply is part of the import, not progress to send back
    return cid


ANTIGRAVITY_NOTE = (
    "[ccx] New progress on this task from {app}, where the user worked on it since. This message only carries "
    "it: do not start working and do not call any tools. Reply with one short line saying you have the update, "
    "then wait for the user's next message.")


def _push_to_antigravity(cid: str) -> bool:
    """Post the linked Antigravity conversation's pending progress into it now, so
    it is there (and the agent knows it) when the user opens the conversation.
    False, with nothing consumed, when the agent is busy or the app refuses: then
    it comes along with the user's next message there, as before."""
    try:
        if antigravity.busy(cid):
            return False

        def send(res):
            apps = " + ".join(dict.fromkeys(NAME[t] for t in res["sources"]))
            antigravity.send_note(cid, L(f"⇄ Progress from {apps}", f"⇄ 来自 {apps} 的进展"),
                                  res["context"] + "\n\n" + ANTIGRAVITY_NOTE.format(app=apps))
        return bool(pairs.push("antigravity", cid, send))
    except RuntimeError:
        return False


IMPORT_OVERHEAD = 1.8  # native imports keep tool output ccx clips: measured ~215k vs ~118k rendered


def estimate(tool: str, session_id: str, dst: Optional[str] = None) -> dict:
    """Rough tokens the other app reads on the first reply: after a full native
    import vs. a new conversation that continues from the condensed progress."""
    n, added = pairs.pending(tool, session_id, dst)
    s, us = pairs.session_units(tool, session_id, include_imported=True)
    us = [u for u in us if u]
    if not s or not us:
        return {"full": 0, "condensed": 0, "pending": n, "pending_tokens": added}
    full = int(est_tokens("\n".join(t for _, t in us)) * IMPORT_OVERHEAD)
    condensed = est_tokens(pairs.render(us, tool, pairs.FULL_BUDGET)) + 2_000
    return {"full": full, "condensed": min(condensed, full), "pending": n, "pending_tokens": added}


def default_target(tool: str, session_id: str) -> str:
    """Where a session goes when the app isn't named: its one linked partner,
    else the usual partner app (Claude and Codex to each other)."""
    linked = [pairs.partner_tool(p, tool) for p in pairs.find_all(tool, session_id)]
    if len(linked) == 1:
        return linked[0]
    return OTHER[tool]


def _adopt(tool: str, sid: str, dst: str) -> Optional[dict]:
    """`tool`'s session has no partner in `dst`, but a conversation it is linked to
    in another app has one: that is this task's `dst` conversation, so link to it
    instead of importing a second copy."""
    for third in TOOLS:
        if third in (tool, dst):
            continue
        pa = pairs.find(tool, sid, third)
        pb = pairs.find(third, pa[third]["id"], dst) if pa else None
        if not pb or _is_cloud(pa[third]["id"]) or _is_cloud(pb[dst]["id"]) or pairs.find(dst, pb[dst]["id"], tool):
            continue
        if not pairs.lookup(dst, pb[dst]["id"]):
            continue
        # Each side owes the other what it still owed (or had sent) through the third app.
        return pairs.link(dict(pa[tool]), dict(pb[dst]), tools=(tool, dst))
    return None


def transfer(tool: str, session_id: str, open_app: bool = True, dst: Optional[str] = None) -> dict:
    """Bring `tool`'s session to another app (`dst`): import + pair the first
    time; afterwards just open the partner."""
    dst = dst or default_target(tool, session_id)
    if dst == tool or dst not in TOOLS:
        raise RuntimeError(f"can't move a {NAME[tool]} session to {NAME.get(dst, dst)}")
    if dst == "antigravity" and not antigravity.installed():
        raise RuntimeError(L("The Antigravity desktop app isn't set up on this Mac: open it once, then try again.",
                             "这台 Mac 上还没有用过 Antigravity 桌面版：先打开它一次，再试。"))
    if dst == "zcode" and not zcode.installed():
        raise RuntimeError(L("The ZCode desktop app isn't set up on this Mac: open it once, then try again.",
                             "这台 Mac 上还没有用过 ZCode 桌面版：先打开它一次，再试。"))
    if tool == "codex" and cloud.is_codex(session_id):
        if dst != "claude":
            raise RuntimeError(L("A Codex Cloud task comes down into Claude only. Bring it into Claude first, then "
                                 f"move that conversation to {NAME[dst]}.",
                                 f"Codex 云端任务只能带进 Claude。先带进 Claude，再把那个对话转到 {NAME[dst]}。"))
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
    src = pairs.lookup(tool, session_id)
    if not src:
        raise RuntimeError(f"{NAME[tool]} session {session_id} not found")
    pair = pairs.find(tool, src.id, dst)
    pending = (0, 0)
    if pair and _is_cloud(pair[dst]["id"]):
        # Cloud sessions only come down to this Mac: a local session goes back to a
        # local one on the other side, and that new pair replaces the cloud link.
        pair = None
    if pair and dst == "antigravity" and not antigravity.find(pair[dst]["id"]):
        pair = None  # that Antigravity conversation was deleted: import afresh
    if pair and dst == "zcode" and not zcode.find(pair[dst]["id"]):
        pair = None  # that ZCode conversation was deleted: import afresh
    pair = pair or _adopt(tool, src.id, dst)
    opened_project = project_warning = None
    if dst == "codex" and open_app:
        # Codex classifies existing chats before adding a folder to the sidebar.
        # Register first so the desktop doesn't classify a new import as projectless.
        target_session = codex.find(pair[dst]["id"]) if pair else None
        try:
            opened_project = codex.register_desktop_workspace(target_session.cwd if target_session else src.cwd)
        except (RuntimeError, TimeoutError) as e:
            project_warning = str(e)
            if not pair:
                raise RuntimeError(L(
                    "Import paused while waiting for the Codex project. If Codex asks you to trust the folder, "
                    "confirm there and retry the transfer.",
                    "导入已暂停，等待 Codex 项目就绪。如果 Codex 弹出目录信任提示，请在那里确认后再转移。")) from e
    if pair:
        target, action = pair[dst]["id"], "linked"
        pending = pairs.pending(tool, src.id, dst)
        if not pending[0]:
            action = "in_sync"
        elif dst == "antigravity" and _push_to_antigravity(target):
            action = "pushed"
    else:
        if dst == "zcode" and not zcode.project_for(src.cwd):
            if not open_app or not zcode.register_project(src.cwd):
                raise RuntimeError(L(
                    f"Import paused. Open {src.cwd} as a project in ZCode, confirm the folder there, and retry.",
                    f"导入已暂停。请在 ZCode 中把 {src.cwd} 打开为项目，确认目录后再试。"))
        # Capture the source cursor BEFORE the import. A running turn may finish
        # while the other app imports; those late records still need delivery.
        source_side = pairs.side(tool, src.id)
        if dst == "codex" and tool == "claude" and codex.import_history().get(str(src.path)):
            # An earlier native import is only a snapshot, not proof that today's
            # source progress was delivered. Re-read it once in the first hook.
            source_side["cursor"] = 0
        target = globals()[f"_import_to_{dst}"](src)
        pairs.link(source_side, pairs.side(dst, target), tools=(tool, dst))
        pairs.close_triangle(tool, src.id, dst, target)
        action = "created"
        pending = (0, estimate(tool, src.id, dst)["full"]) if (tool, dst) == ("claude", "codex") else (0, 0)
    res = {"action": action, "message": _message(action, tool, src.title, pending, dst), "pending": pending[0],
           "pending_tokens": pending[1], "source": {"tool": tool, "id": src.id, "title": src.title},
           "target": {"tool": dst, "id": target, "deep_link": deep_link(dst, target)}, "cwd": src.cwd}
    if dst == "antigravity":
        res["message"] += _where_in_antigravity(target, src.cwd)
    if dst == "zcode" and open_app:
        res["zcode"] = zcode.show(target, src.cwd)
        res["message"] += _where_in_zcode(target, res["zcode"])
        if res["zcode"] == "busy" and zcode.ask_restart_when_idle(setting("language") == "zh"):
            zcode.spawn_restart_when_idle(src.cwd)
            res["message"] += L(" ccx restarts ZCode once its running task is done.",
                                "ccx 会在那个任务完成后自动重启 ZCode。")
    if dst == "codex":
        # Save the pair before grouping: if grouping fails, retry repairs this
        # thread instead of importing another copy. Also repairs pre-0.0.9 pairs.
        if project_warning:
            res["target"]["project_warning"] = project_warning
            res["message"] += L(
                "\n\nThe sidebar project is still pending. If Codex asks you to trust the folder, "
                "confirm there and retry the transfer. It will reuse the linked chat.",
                "\n\n侧栏项目仍待确认。如果 Codex 弹出目录信任提示，请在 Codex 里确认后再转移一次，CCX 会复用已关联的聊天。")
        try:
            if "project_warning" not in res["target"]:
                res["target"]["project_id"] = codex.ensure_thread_project(target, src.cwd, opened_project)
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
    if open_app and dst != "zcode":
        res["opened"] = open_in_app(dst, target)
        if dst == "codex" and not res["opened"]:
            res["message"] = L(
                "The Codex chat is saved and linked. macOS couldn't open it automatically. "
                "Retry the transfer to open the same chat.",
                "Codex 聊天已保存并关联。macOS 未能自动打开它，再次转移会打开同一条聊天。")
    elif open_app:
        res["opened"] = res["zcode"] != "busy"
    return res


def _where_in_zcode(sid: str, how: str) -> str:
    """ZCode has no link that opens one conversation: say where it is, and what
    ccx did to make ZCode list it."""
    z = zcode.find(sid)
    p = zcode.task_project(sid)
    title = z.title if z else ""
    if p:
        where = L(f"\n\nIn ZCode it is under the project “{p['name']}”" + (f": “{title}”." if title else "."),
                  f"\n\n在 ZCode 里，它在项目「{p['name']}」下" + (f"：「{title}」。" if title else "。"))
    elif zcode.listed(sid):
        where = L(f"\n\nFind “{title}” in ZCode's standalone Tasks section.",
                  f"\n\n在 ZCode 的独立「任务」区找到「{title}」。")
    else:
        where = L(f"\n\nLook for “{title}” after ZCode refreshes its task list.",
                  f"\n\nZCode 刷新任务列表后，查找「{title}」。")
    return where + {
        "restarted": L(" ZCode was idle, so ccx restarted it on this folder to list the conversation.",
                       "ZCode 当时空闲，ccx 已在这个文件夹上重启 ZCode，让它显示这个对话。"),
        "busy": L(" A ZCode task is running, so ZCode wasn't restarted: the conversation shows in its list "
                  "after ZCode restarts.",
                  "ZCode 里有任务在运行，所以没有重启它：ZCode 重启后，任务列表里就会出现这个对话。"),
    }.get(how, "")


def _where_in_antigravity(cid: str, cwd: str) -> str:
    """Antigravity has no link that opens one conversation, so say where it is."""
    a = antigravity.find(cid)
    p = antigravity.project_for(cwd)
    title, project = (a.title if a else ""), (p["name"] if p else "")
    return L(f"\n\nIn Antigravity, find it in the sidebar" + (f" under the project “{project}”" if project else "")
             + (f": “{title}”." if title else "."),
             "\n\n在 Antigravity 的侧边栏里" + (f"，项目「{project}」下" if project else "")
             + (f"找到「{title}」即可。" if title else "即可找到。"))


def _is_cloud(sid: str) -> bool:
    return cloud.is_claude(sid) or cloud.is_codex(sid)


def _transfer_codex_task(tid: str, open_app: bool) -> dict:
    """A Codex Cloud task into Claude: a new Claude conversation holding the task's
    status and code change, linked so a newer result arrives with the next prompt."""
    t = cloud.codex_task(tid)
    if not t:
        raise RuntimeError(L(f"Codex Cloud task {tid} not found.", f"找不到 Codex 云端任务 {tid}。"))
    pair = pairs.find("codex", tid, "claude")
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
           "cwd": pairs.find("codex", tid, "claude")["codex"]["cwd"]}
    if open_app:
        res["opened"] = open_in_app("claude", target)
    return res


def _k(tokens: int) -> str:
    return f"{max(1, round(tokens / 1000))}k"


def _message(action: str, tool: str, title: str, pending=(0, 0), dst: Optional[str] = None) -> str:
    dst = dst or OTHER[tool]
    n, tokens = pending
    if action == "created":
        cost = L(f" Its first reply there reads about {_k(tokens)} tokens of history.",
                 f"它在那边第一次回复时大约读取 {_k(tokens)} token 的历史。") if tokens else ""
        return L(f"Imported {NAME[tool]} \u201c{title}\u201d into {NAME[dst]} and linked them; they stay in sync from now on.",
                 f"已把 {NAME[tool]} 的「{title}」导入 {NAME[dst]} 并关联，之后会自动同步。") + cost
    if action == "in_sync":
        return L(f"\u201c{title}\u201d is already in sync with {NAME[dst]}: nothing new to bring over, nothing was added. "
                 f"Opened the {NAME[dst]} conversation.",
                 f"「{title}」已经和 {NAME[dst]} 同步过了，没有新内容，这次没有追加任何数据。已为你打开 {NAME[dst]} 的会话。")
    if action == "pushed":
        return L(f"\u201c{title}\u201d is linked; brought {n} new updates (about {_k(tokens)} tokens, condensed) into the "
                 f"{NAME[dst]} conversation, where they show as a \u201c\u21c4 Progress\u201d card, and opened {NAME[dst]}. "
                 f"Just keep going there.",
                 f"\u300c{title}\u300d\u5df2\u5173\u8054\uff1a{n} \u6761\u65b0\u8fdb\u5c55\uff08\u538b\u7f29\u540e\u7ea6 {_k(tokens)} token\uff09\u5df2\u7ecf\u63a8\u9001\u5230 {NAME[dst]} \u7684\u5bf9\u8bdd\u91cc\uff0c"
                 f"\u663e\u793a\u4e3a\u4e00\u5f20\u300c\u21c4 \u8fdb\u5c55\u300d\u5361\u7247\uff0c\u5e76\u5df2\u6253\u5f00 {NAME[dst]}\u3002\u76f4\u63a5\u5728\u90a3\u8fb9\u63a5\u7740\u8bf4\u5c31\u884c\u3002")
    if n:
        return L(f"\u201c{title}\u201d is linked; opened it in {NAME[dst]}. {n} new updates (about {_k(tokens)} tokens, condensed) "
                 f"come along with your next message there, once. Nothing is re-sent.",
                 f"「{title}」已关联，已在 {NAME[dst]} 打开。你在那边发下一条消息时，会一次性带入 {n} 条新进展"
                 f"（压缩后约 {_k(tokens)} token），已同步过的不会重复发送。")
    return L(f"\u201c{title}\u201d is already linked to a {NAME[dst]} conversation, opened it. Send any message there "
             f"(e.g. \u201ccontinue\u201d) and the {NAME[tool]} progress comes along.",
             f"「{title}」已关联到 {NAME[dst]} 的会话，已为你打开。在那里随便说一句（比如\u201c继续\u201d），"
             f"{NAME[tool]} 的进展就会带过去。")
