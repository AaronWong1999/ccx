"""Bring a session to the other app: the first time by a native import (which
also pairs the two sessions); after that, by opening the paired session, where
the other side's new progress is injected on the next prompt (see pairs.py)."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

from . import codex_import, pairs
from .stores import (
    Session,
    claude_session,
    claude_sessions,
    codex_session,
    codex_sessions,
    codex_turns,
    copy_claude_session_with_new_id,
    git_snapshot,
    write_claude_session,
)

NAME = {"claude": "Claude", "codex": "Codex"}
OTHER = {"claude": "codex", "codex": "claude"}


def deep_link(tool: str, sid: str) -> str:
    return f"codex://threads/{sid}" if tool == "codex" else f"claude://resume?session={sid}"


def open_in_app(tool: str, sid: str) -> bool:
    return subprocess.run(["open", deep_link(tool, sid)], capture_output=True).returncode == 0


# ------------------------------------------------------------------- listing

def _history_by_source() -> Dict[str, dict]:
    """Latest Codex import per Claude source file (Codex app, official plugin, or us)."""
    try:
        hist = codex_import.import_history()
    except Exception:
        return {}
    by_src: Dict[str, dict] = {}
    for h in sorted(hist, key=lambda h: h["completed_at_ms"]):
        by_src[h["source"]] = h
    return by_src


def _row(s: Session, status: str, partner: Optional[str]) -> dict:
    return {"id": s.id, "title": s.title, "updated": s.when, "status": status,
            "linked_to": partner, "cwd": s.cwd}


def list_codex_for_claude(cwd: Optional[str], limit: int = 10, history=None, sessions=None) -> List[dict]:
    """Codex sessions of a project, with whether they are linked to a Claude session."""
    history = _history_by_source() if history is None else history
    mirrors = {h["target"] for h in history.values()}
    out = []
    for s in codex_sessions(cwd) if sessions is None else sessions:
        status, partner = pairs.status("codex", s.id, s.cwd)
        if status == "new" and s.id in mirrors:
            status = "mirror"
        out.append(_row(s, status, partner))
        if len(out) >= limit:
            break
    return out


def list_claude_for_codex(cwd: Optional[str], limit: int = 10, history=None, sessions=None) -> List[dict]:
    """Claude sessions of a project, with whether they are linked to a Codex thread."""
    out = []
    for s in claude_sessions(cwd) if sessions is None else sessions:
        status, partner = pairs.status("claude", s.id, s.cwd)
        out.append(_row(s, status, partner))
        if len(out) >= limit:
            break
    return out


def menu_data(projects: int = 8, per_side: int = 6) -> dict:
    """Recent projects with both sides' sessions and statuses, for the menu bar app."""
    history = _history_by_source()
    by_cwd: Dict[str, dict] = {}
    for s in claude_sessions(None) + codex_sessions(None):
        if not s.cwd:
            continue
        p = by_cwd.setdefault(os.path.realpath(s.cwd), {"claude": [], "codex": [], "mtime": 0})
        p[s.tool].append(s)
        p["mtime"] = max(p["mtime"], s.mtime)
    out = []
    for cwd, p in sorted(by_cwd.items(), key=lambda kv: kv[1]["mtime"], reverse=True):
        if "/scratch-workspaces/" in cwd or not os.path.isdir(cwd):
            continue
        newest = lambda xs: sorted(xs, key=lambda s: s.mtime, reverse=True)
        codex_rows = list_codex_for_claude(cwd, per_side, history, newest(p["codex"]))
        claude_rows = list_claude_for_codex(cwd, per_side, history, newest(p["claude"]))
        if not codex_rows and not claude_rows:
            continue
        out.append({"cwd": cwd, "name": os.path.basename(cwd),
                    "updated": datetime.fromtimestamp(p["mtime"]).strftime("%m-%d %H:%M"),
                    "codex": codex_rows, "claude": claude_rows})
        if len(out) >= projects:
            break
    return {"projects": out}


# ----------------------------------------------------------------- transfers

def _import_to_codex(src: Session) -> str:
    """Native import of a Claude session into Codex; returns the thread id."""
    prior = _history_by_source().get(str(src.path))
    if prior and codex_session(prior["target"]):
        return prior["target"]  # Codex already has it (imported by the app or the official plugin)
    rec = codex_import.import_claude_session(str(src.path), src.cwd, src.title)
    if rec is None:  # imported before but that thread is gone: import a fresh copy
        tmp = copy_claude_session_with_new_id(src.path)
        try:
            rec = codex_import.import_claude_session(str(tmp), src.cwd, src.title)
        finally:
            tmp.unlink(missing_ok=True)
    if not rec:
        raise RuntimeError("Codex 没有返回导入结果")
    return rec["target"]


def _import_to_claude(src: Session) -> str:
    """Write a Claude session from a Codex thread; returns the Claude session id."""
    turns = codex_turns(src.path)
    if not turns:
        raise RuntimeError("这个 Codex 会话里没有可导入的对话内容")
    header = (f"[claudecodex] 以下对话从 Codex 会话 {src.id}（{src.when}）导入。"
              "工具调用和输出已压缩成摘要；代码改动已经在工作区里。\n\n")
    turns[0] = (turns[0][0], header + turns[0][1])
    tail = f"\n\n---\n[claudecodex] 导入时的 git 状态：\n```\n{git_snapshot(src.cwd)}\n```\n请在此基础上继续。"
    if turns[-1][0] == "assistant":
        turns[-1] = ("assistant", turns[-1][1] + tail)
    else:
        turns.append(("assistant", tail.strip()))
    return write_claude_session(src.cwd, turns, f"⇄ {src.title or 'Codex 会话'}").id


def transfer(tool: str, session_id: str, cwd: Optional[str], open_app: bool = True) -> dict:
    """Bring `tool`'s session over to the other app.

    First time: native import + pair. Already paired: just open the partner;
    the new progress is pulled in on the next prompt there."""
    src = codex_session(session_id) if tool == "codex" else claude_session(cwd or "", session_id)
    if not src:
        raise RuntimeError(f"找不到 {NAME[tool]} 会话 {session_id}")
    dst = OTHER[tool]
    pair = pairs.find(tool, src.id)
    if pair:
        target, action = pair[dst]["id"], "linked"
    else:
        target = _import_to_codex(src) if dst == "codex" else _import_to_claude(src)
        ids = {tool: src.id, dst: target}
        pairs.link(src.cwd, ids["claude"], ids["codex"],
                   len(pairs.units("claude", ids["claude"], src.cwd)),
                   len(pairs.units("codex", ids["codex"], src.cwd)))
        action = "created"
    res = {
        "action": action,
        "message": _message(action, tool, src.title),
        "source": {"tool": tool, "id": src.id, "title": src.title},
        "target": {"tool": dst, "id": target, "deep_link": deep_link(dst, target)},
        "cwd": src.cwd,
    }
    if open_app:
        res["opened"] = open_in_app(dst, target)
    return res


def continue_phrase(tool: str) -> str:
    """What to say in the partner session to pull `tool`'s progress over."""
    return f"接着 {NAME[tool]} 继续"


def _message(action: str, tool: str, title: str) -> str:
    dst = OTHER[tool]
    if action == "created":
        return f"已导入：{NAME[tool]}「{title}」→ {NAME[dst]}，两边已关联，之后会自动同步"
    if dst == "claude":
        return (f"「{title}」已关联到 Claude 的会话，已打开。随便说一句（比如“继续”），"
                f"{NAME[tool]} 的新进展就会自动带进去")
    return (f"「{title}」已关联到 Codex 的会话，已打开。在那里说「{continue_phrase(tool)}」就会带上新进展"
            f"（在 Codex 里信任 claudecodex 的 hook 之后，随便说一句也会自动带上）")
