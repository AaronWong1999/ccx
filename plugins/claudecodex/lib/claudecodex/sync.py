"""Import-or-sync logic between Claude Code and Codex, plus desktop deep links.

Links are remembered in ~/.claudecodex/links.json so that bringing the same
session over again only syncs it instead of creating a duplicate.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import codex_import
from .stores import (
    MARKER,
    Session,
    claude_has_own_turns,
    claude_session,
    claude_sessions,
    codex_session,
    codex_sessions,
    codex_turns,
    copy_claude_session_with_new_id,
    git_snapshot,
    write_claude_session,
)

STATE_DIR = Path(os.environ.get("CLAUDECODEX_HOME", Path.home() / ".claudecodex"))
LINKS = STATE_DIR / "links.json"
C2K = "codex>claude"
K2C = "claude>codex"


# --------------------------------------------------------------------- links

def load_links() -> Dict[str, dict]:
    try:
        d = json.loads(LINKS.read_text())
    except (OSError, ValueError):
        d = {}
    d.setdefault(C2K, {})
    d.setdefault(K2C, {})
    return d


def save_links(d: Dict[str, dict]):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LINKS.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, LINKS)


def claude_turn_count(path: Path) -> int:
    n = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                if json.loads(line).get("type") in ("user", "assistant"):
                    n += 1
            except ValueError:
                continue
    return n


def deep_link(tool: str, sid: str) -> str:
    return f"codex://threads/{sid}" if tool == "codex" else f"claude://resume?session={sid}"


def open_in_app(tool: str, sid: str) -> bool:
    return subprocess.run(["open", deep_link(tool, sid)], capture_output=True).returncode == 0


def _fmt_ms(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


# ------------------------------------------------------------------- listing

def list_codex_for_claude(cwd: Optional[str], limit: int = 10, history=None, sessions=None) -> List[dict]:
    """Codex sessions of a project, each with its import status into Claude."""
    links = load_links()
    from_claude = {l["target"] for l in links[K2C].values()}
    history = _history_by_source() if history is None else history
    mirrors = {h["target"] for h in history.values()}
    out = []
    for s in codex_sessions(cwd) if sessions is None else sessions:
        link = links[C2K].get(s.id)
        target = claude_session(s.cwd, link["target"]) if link else None
        if s.id in from_claude and not target:
            # A thread we created from a Claude session; only worth showing once
            # the user continued it in Codex.
            k2c = next(l for l in links[K2C].values() if l["target"] == s.id)
            if s.path.stat().st_size == k2c.get("target_size"):
                continue
        if not target:
            status = "mirror" if s.id in mirrors else "new"
        elif s.path.stat().st_size != link.get("src_size"):
            status = "updated"
        else:
            status = "synced"
        out.append(_row(s, status, target.id if target else None))
        if len(out) >= limit:
            break
    return out


def list_claude_for_codex(cwd: Optional[str], limit: int = 10, history=None, sessions=None) -> List[dict]:
    """Claude sessions of a project, each with its import status into Codex."""
    links = load_links()
    history = _history_by_source() if history is None else history
    out = []
    for s in claude_sessions(cwd) if sessions is None else sessions:
        if _is_pure_ccx_import(s.path):
            continue
        link = _claude_link(s, links, history)
        if not link:
            status = "new"
        elif _claude_changed(s, link):
            status = "updated"
        else:
            status = "synced"
        out.append(_row(s, status, link["target"] if link else None))
        if len(out) >= limit:
            break
    return out


def _row(s: Session, status: str, target: Optional[str]) -> dict:
    return {"id": s.id, "title": s.title, "updated": s.when, "status": status,
            "linked_to": target, "cwd": s.cwd}


def _is_pure_ccx_import(path: Path) -> bool:
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.readline()
    return MARKER in head and not claude_has_own_turns(path)


def _history_by_source() -> Dict[str, dict]:
    """Latest Codex import per Claude source file (all of Codex's history, not just ours)."""
    try:
        hist = codex_import.import_history()
    except Exception:
        return {}
    by_src: Dict[str, dict] = {}
    for h in sorted(hist, key=lambda h: h["completed_at_ms"]):
        by_src[h["source"]] = h
    return by_src


def _claude_link(s: Session, links: Dict[str, dict], history: Dict[str, dict]) -> Optional[dict]:
    link = links[K2C].get(s.id)
    if link and codex_session(link["target"]):
        return link
    h = history.get(str(s.path))  # imported by the Codex app or the official plugin
    if h and codex_session(h["target"]):
        return {"target": h["target"], "at": h["completed_at_ms"] / 1000}
    return None


def _claude_changed(s: Session, link: dict) -> bool:
    if "src_turns" in link:
        return claude_turn_count(s.path) != link["src_turns"]
    return s.mtime > link["at"] + 5


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
        codex_rows = list_codex_for_claude(cwd, per_side, history, sorted(p["codex"], key=lambda s: s.mtime, reverse=True))
        claude_rows = list_claude_for_codex(cwd, per_side, history, sorted(p["claude"], key=lambda s: s.mtime, reverse=True))
        if not codex_rows and not claude_rows:
            continue
        out.append({"cwd": cwd, "name": os.path.basename(cwd), "updated": datetime.fromtimestamp(p["mtime"]).strftime("%m-%d %H:%M"),
                    "codex": codex_rows, "claude": claude_rows})
        if len(out) >= projects:
            break
    return {"projects": out, "generated_at": time.time()}


# ----------------------------------------------------------------- transfers

def codex_to_claude(codex_id: str) -> dict:
    src = codex_session(codex_id)
    if not src:
        raise RuntimeError(f"找不到 Codex 会话 {codex_id}")
    links = load_links()
    link = links[C2K].get(src.id)
    target = claude_session(src.cwd, link["target"]) if link else None
    size = src.path.stat().st_size

    if target and size == link.get("src_size"):
        action, sid = "unchanged", target.id
    else:
        turns = _codex_turns_for_claude(src)
        # Only overwrite in place if nobody (the user, or a running Claude app)
        # has touched the file since we wrote it; otherwise write a new session.
        untouched = target and target.path.stat().st_mtime == link.get("target_mtime") \
            and not claude_has_own_turns(target.path)
        if untouched:
            action, sid = "synced", write_claude_session(src.cwd, turns, _title(src), sid=target.id).id
        else:
            action = "forked" if target else "created"
            sid = write_claude_session(src.cwd, turns, _title(src)).id
        mtime = claude_session(src.cwd, sid).path.stat().st_mtime
        links[C2K][src.id] = {"target": sid, "src_size": size, "target_mtime": mtime, "at": time.time()}
        save_links(links)
    return _result(src, "claude", sid, action)


def claude_to_codex(claude_id: str, cwd: str) -> dict:
    src = claude_session(cwd, claude_id)
    if not src:
        raise RuntimeError(f"找不到 Claude 会话 {claude_id}（项目 {cwd}）")
    links = load_links()
    link = _claude_link(src, links, _history_by_source())

    if link and not _claude_changed(src, link):
        return _result(src, "codex", link["target"], "unchanged")

    rec = None if link else codex_import.import_claude_session(str(src.path), src.cwd, src.title)
    if rec is None:
        # Codex imports each source file once, so a re-import goes through a
        # fresh copy that we delete right after.
        tmp = copy_claude_session_with_new_id(src.path)
        try:
            rec = codex_import.import_claude_session(str(tmp), src.cwd, src.title)
        finally:
            tmp.unlink(missing_ok=True)
    if not rec:
        raise RuntimeError("Codex 没有返回导入结果")
    new_id = rec["target"]

    action = "created"
    if link:
        old = codex_session(link["target"])
        untouched = old and link.get("target_size") is not None and old.path.stat().st_size == link["target_size"]
        if untouched and codex_import.archive_thread(link["target"]):
            action = "synced"
        else:
            action = "forked"

    new = codex_session(new_id)
    links[K2C][src.id] = {
        "target": new_id,
        "src_turns": claude_turn_count(src.path),
        "target_size": new.path.stat().st_size if new else None,
        "at": time.time(),
    }
    save_links(links)
    return _result(src, "codex", new_id, action)


def _title(src: Session) -> str:
    return f"⇄ {src.title or 'Codex 会话'}"


def _codex_turns_for_claude(src: Session):
    turns = codex_turns(src.path)
    if not turns:
        raise RuntimeError("这个 Codex 会话里没有可导入的对话内容")
    header = (
        f"[claudecodex] 以下对话从 Codex 会话 {src.id}（{src.when}）导入。"
        "工具调用和输出已压缩成摘要；代码改动已经在工作区里。\n\n"
    )
    turns[0] = (turns[0][0], header + turns[0][1])
    tail = f"\n\n---\n[claudecodex] 导入时的 git 状态：\n```\n{git_snapshot(src.cwd)}\n```\n请在此基础上继续。"
    if turns[-1][0] == "assistant":
        turns[-1] = ("assistant", turns[-1][1] + tail)
    else:
        turns.append(("assistant", tail.strip()))
    return turns


ACTION_TEXT = {
    "created": "已导入",
    "synced": "已同步到最新",
    "unchanged": "已经是最新，无需同步",
    "forked": "已导入为新会话（旧的那份正在使用或已被继续聊过，保留不动）",
}
NAME = {"claude": "Claude", "codex": "Codex"}


def _result(src: Session, dst: str, sid: str, action: str) -> dict:
    return {
        "action": action,
        "message": f"{ACTION_TEXT[action]}：{NAME[src.tool]}「{src.title}」→ {NAME[dst]}",
        "source": {"tool": src.tool, "id": src.id, "title": src.title},
        "target": {"tool": dst, "id": sid, "deep_link": deep_link(dst, sid)},
        "cwd": src.cwd,
    }


def transfer(tool: str, session_id: str, cwd: Optional[str], open_app: bool = True) -> dict:
    """Bring `tool`'s session over to the other side (import or sync)."""
    if tool == "codex":
        res = codex_to_claude(session_id)
    else:
        if not cwd:
            raise RuntimeError("需要项目目录 cwd")
        res = claude_to_codex(session_id, cwd)
    if open_app:
        res["opened"] = open_in_app(res["target"]["tool"], res["target"]["id"])
    return res
