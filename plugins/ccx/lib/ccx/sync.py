"""Listing both sides, and bringing a session over to the other app: the first
time by a native import (which pairs the two), afterwards by opening the
partner, where the new progress arrives with the next prompt (see pairs.py)."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

from . import claude, codex, pairs
from .common import NAME, OTHER, Session, git_snapshot, real, same_dir

STATUS = {"new": "未关联", "linked": "已关联", "updated": "有新进展", "mirror": "从对面导入的副本"}


def deep_link(tool: str, sid: str) -> str:
    return f"codex://threads/{sid}" if tool == "codex" else f"claude://resume?session={sid}"


def open_in_app(tool: str, sid: str) -> bool:
    return subprocess.run(["open", deep_link(tool, sid)], capture_output=True).returncode == 0


def continue_phrase(tool: str) -> str:
    """What to say in the partner session to pull `tool`'s progress over."""
    return f"接着 {NAME[tool]} 继续"


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
        out.append({"id": s.id, "title": s.title, "updated": s.when, "status": st, "linked_to": partner,
                    "cwd": s.cwd, "other_folder": bool(here_cwd and s.cwd and not same_dir(s.cwd, here_cwd))})
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
    return {"projects": out}


# ---------------------------------------------------------------- transfers

def _import_to_codex(src: Session) -> str:
    prior = codex.import_history().get(str(src.path))
    if prior and codex.find(prior):
        return prior  # Codex already has it (from its own app or the official plugin)
    tid = codex.import_claude_session(str(src.path), src.cwd, src.title)
    if tid is None:  # imported before but that thread is gone: import a fresh copy
        tmp = claude.copy_with_new_id(src.path)
        try:
            tid = codex.import_claude_session(str(tmp), src.cwd, src.title)
        finally:
            tmp.unlink(missing_ok=True)
    if not tid:
        raise RuntimeError("Codex 没有返回导入结果")
    return tid


def _import_to_claude(src: Session) -> str:
    turns = codex.turns_for_claude(codex.items(src.id))
    if not turns:
        raise RuntimeError("这个 Codex 会话里没有可导入的对话内容")
    header = (f"[ccx] 以下对话从 Codex 会话 {src.id}（{src.when}）导入。"
              "工具调用和输出已压缩成摘要；代码改动以磁盘上的文件为准。\n\n")
    turns[0] = (turns[0][0], header + turns[0][1])
    tail = f"\n\n---\n[ccx] 导入时的 git 状态：\n```\n{git_snapshot(src.cwd)}\n```\n请在此基础上继续。"
    if turns[-1][0] == "assistant":
        turns[-1] = ("assistant", turns[-1][1] + tail)
    else:
        turns.append(("assistant", tail.strip()))
    return claude.write_session(src.cwd, turns, f"⇄ {src.title or 'Codex 会话'}").id


def transfer(tool: str, session_id: str, open_app: bool = True) -> dict:
    """Bring `tool`'s session to the other app: native import + pair the first
    time; afterwards just open the partner."""
    src = claude.find(session_id) if tool == "claude" else codex.find(session_id)
    if not src:
        raise RuntimeError(f"找不到 {NAME[tool]} 会话 {session_id}")
    dst = OTHER[tool]
    pair = pairs.find(tool, src.id)
    if pair:
        target, action = pair[dst]["id"], "linked"
    else:
        target = _import_to_codex(src) if dst == "codex" else _import_to_claude(src)
        sides = {tool: pairs.side(tool, src.id), dst: pairs.side(dst, target)}
        pairs.link(sides["claude"], sides["codex"])
        action = "created"
    res = {"action": action, "message": _message(action, tool, src.title),
           "source": {"tool": tool, "id": src.id, "title": src.title},
           "target": {"tool": dst, "id": target, "deep_link": deep_link(dst, target)}, "cwd": src.cwd}
    if open_app:
        res["opened"] = open_in_app(dst, target)
    return res


def _message(action: str, tool: str, title: str) -> str:
    dst = OTHER[tool]
    if action == "created":
        return f"已导入：{NAME[tool]}「{title}」→ {NAME[dst]}，两边已关联，之后会自动同步"
    if dst == "claude":
        return f"「{title}」已关联到 Claude 的会话。在那里随便说一句（比如“继续”），{NAME[tool]} 的新进展就会自动带进去"
    return (f"「{title}」已关联到 Codex 的会话。在那里说「{continue_phrase(tool)}」就会带上新进展"
            f"（在 Codex 里信任 ccx 的 hook 之后，随便说一句也会自动带上）")
