"""Pairs of linked sessions (one Claude session <-> one Codex thread) and the
incremental "what happened over there since we last synced" deltas.

A pair keeps one cursor per side: how many units of that side's transcript
have already been delivered to the other side. Write-back never edits a live
session file; the delta is injected into the receiving conversation (by a
UserPromptSubmit hook, or returned from an MCP tool call), so the receiving
session simply continues with the other side's progress in its context.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .stores import (
    MARKER,
    _content_text,
    _is_injected,
    _rollout_records,
    claude_project_dir,
    clip,
    codex_session,
    git_snapshot,
)

STATE_DIR = Path(os.environ.get("CLAUDECODEX_HOME", Path.home() / ".claudecodex"))
PAIRS = STATE_DIR / "pairs.json"
TAG = "claudecodex-sync"
SELF_TOOL = "claudecodex"  # our own tool calls are never forwarded
NAME = {"claude": "Claude", "codex": "Codex"}
OTHER = {"claude": "codex", "codex": "claude"}

HOOK_BUDGET = 24_000   # chars injected automatically on a prompt
FULL_BUDGET = 60_000   # chars for a first-time "continue from this session"


# ------------------------------------------------------------------- storage

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


def find(tool: str, sid: str, pairs: Optional[List[dict]] = None) -> Optional[dict]:
    for p in load() if pairs is None else pairs:
        if p[tool]["id"] == sid:
            return p
    return None


def link(cwd: str, claude_id: str, codex_id: str, claude_cursor: int, codex_cursor: int) -> dict:
    """Pair two sessions (replacing any pair either of them was in)."""
    pairs = [p for p in load() if p["claude"]["id"] != claude_id and p["codex"]["id"] != codex_id]
    p = {
        "cwd": cwd,
        "claude": {"id": claude_id, "cursor": claude_cursor},
        "codex": {"id": codex_id, "cursor": codex_cursor},
        "linked_at": time.time(),
        "synced_at": time.time(),
    }
    pairs.append(p)
    save(pairs)
    return p


def _update_cursor(claude_id: str, side: str, cursor: int):
    pairs = load()
    for p in pairs:
        if p["claude"]["id"] == claude_id:
            p[side]["cursor"] = cursor
            p["synced_at"] = time.time()
    save(pairs)


# --------------------------------------------------------------------- units
# A "unit" is one transcript record that can carry conversation: a Claude
# user/assistant record, or a Codex response_item. Cursors count units.

def claude_path(cwd: str, sid: str) -> Path:
    return claude_project_dir(cwd) / f"{sid}.jsonl"


def claude_units(path: Path) -> List[Optional[Tuple[str, str]]]:
    """One entry per user/assistant record: (role, text) to forward, or None."""
    out: List[Optional[Tuple[str, str]]] = []
    skip_ids = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") not in ("user", "assistant"):
                continue
            out.append(None if d.get(MARKER) or d.get("isMeta") or d.get("isSidechain")
                       else _claude_render(d, skip_ids))
    return out


def _claude_render(d: dict, skip_ids: set) -> Optional[Tuple[str, str]]:
    msg = d.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        if d["type"] == "user" and not _is_injected(content) and TAG not in content:
            return ("user", content)
        return None
    parts = []
    role = "user" if d["type"] == "user" else "assistant"
    for c in content or []:
        t = c.get("type")
        if t == "text" and c.get("text", "").strip() and TAG not in c["text"]:
            if role == "user" and _is_injected(c["text"]):
                continue
            parts.append(c["text"])
        elif t == "tool_use":
            if SELF_TOOL in c.get("name", ""):
                skip_ids.add(c.get("id"))
                continue
            args = json.dumps(c.get("input"), ensure_ascii=False)
            parts.append(f"[调用工具 {c.get('name')}] {clip(args, 300)}")
            role = "assistant"
        elif t == "tool_result":
            if c.get("tool_use_id") in skip_ids:
                continue
            r = c.get("content")
            r = r if isinstance(r, str) else _content_text(r)
            if r.strip():
                parts.append(f"[工具结果] {clip(r, 400)}")
            role = "assistant"  # tool results read as part of the agent's work
    return (role, "\n".join(parts)) if parts else None


def codex_units(path: Path) -> List[Optional[Tuple[str, str]]]:
    out: List[Optional[Tuple[str, str]]] = []
    skip_calls = set()
    for d in _rollout_records(path):
        if d.get("type") != "response_item":
            continue
        p = d.get("payload") or {}
        t = p.get("type")
        unit = None
        if t == "message":
            text = _content_text(p.get("content"))
            if p.get("role") == "user" and text.strip() and not _is_injected(text) and TAG not in text:
                unit = ("user", text)
            elif p.get("role") == "assistant" and text.strip() and TAG not in text:
                unit = ("assistant", text)
        elif t in ("function_call", "custom_tool_call", "local_shell_call"):
            name = ".".join(x for x in (p.get("namespace"), p.get("name")) if x) or t
            args = p.get("arguments") or p.get("input") or p.get("action") or ""
            args = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            if SELF_TOOL in name or SELF_TOOL in args:
                skip_calls.add(p.get("call_id"))
            else:
                unit = ("assistant", f"[调用工具 {name}] {clip(args, 300)}")
        elif t in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            if p.get("call_id") not in skip_calls:
                o = p.get("output")
                o = o if isinstance(o, str) else _content_text(o)
                if o.strip() and TAG not in o:
                    unit = ("assistant", f"[工具结果] {clip(o, 400)}")
        out.append(unit)
    return out


def units(tool: str, sid: str, cwd: str) -> List[Optional[Tuple[str, str]]]:
    if tool == "claude":
        p = claude_path(cwd, sid)
        return claude_units(p) if p.exists() else []
    s = codex_session(sid)
    return codex_units(s.path) if s else []


# -------------------------------------------------------------------- deltas

def render(items: List[Tuple[str, str]], src_tool: str, budget: int) -> str:
    """Turn units into a readable transcript, keeping the newest within budget."""
    who = {"user": "【用户】", "assistant": f"【{NAME[src_tool]}】"}
    lines = [who[r] + t.strip() for r, t in items]
    kept, size = [], 0
    for line in reversed(lines):
        if size + len(line) > budget and kept:
            break
        kept.append(line)
        size += len(line)
    kept.reverse()
    dropped = len(lines) - len(kept)
    head = ""
    if dropped:
        asks = [clip(t, 200) for r, t in items[:dropped] if r == "user"]
        head = f"（更早的 {dropped} 条已省略。其中用户说过：" + "；".join(asks[-15:]) + "）\n\n"
    return head + "\n\n".join(kept)


def wrap(body: str, src_tool: str, src_id: str, cwd: str, first: bool) -> str:
    what = "完整对话（已压缩）" if first else "自上次同步以来的新进展"
    return (
        f"<{TAG} from=\"{src_tool}\" session=\"{src_id}\">\n"
        f"以下是这个任务在 {NAME[src_tool]} 里的{what}。把它当作你自己已经做过的工作，"
        f"在此基础上继续；代码改动已经在工作区里，以磁盘上的文件为准。\n\n"
        f"{body}\n\n"
        f"当前 git 状态：\n```\n{git_snapshot(cwd)}\n```\n"
        f"</{TAG}>"
    )


def pull(here_tool: str, here_id: str, budget: int = HOOK_BUDGET) -> Optional[dict]:
    """New progress from the paired session, or None when there is nothing new.

    Advances the cursor, so each piece of progress is delivered once."""
    pair = find(here_tool, here_id)
    if not pair:
        return None
    other = OTHER[here_tool]
    o = pair[other]
    us = units(other, o["id"], pair["cwd"])
    new = [u for u in us[o["cursor"]:] if u]
    if len(us) <= o["cursor"]:
        return None
    _update_cursor(pair["claude"]["id"], other, len(us))
    if not new:
        return None
    return {
        "from": other,
        "session": o["id"],
        "count": len(new),
        "context": wrap(render(new, other, budget), other, o["id"], pair["cwd"], first=False),
    }


def continue_from(here_tool: str, here_id: str, other_id: str, cwd: str) -> dict:
    """Pair this session with `other_id` on the other side and return its full
    (compressed) conversation, so this session can carry on from it."""
    other = OTHER[here_tool]
    us = units(other, other_id, cwd)
    if not us:
        raise RuntimeError(f"{NAME[other]} 会话 {other_id} 是空的或不存在")
    here_units = len(units(here_tool, here_id, cwd))
    ids = {here_tool: here_id, other: other_id}
    cur = {here_tool: here_units, other: len(us)}
    link(cwd, ids["claude"], ids["codex"], cur["claude"], cur["codex"])
    body = render([u for u in us if u], other, FULL_BUDGET)
    return {"from": other, "session": other_id, "context": wrap(body, other, other_id, cwd, first=True)}


def status(tool: str, sid: str, cwd: str) -> Tuple[str, Optional[str]]:
    """For a session on `tool`'s side: ('new'|'linked'|'updated', partner id).

    'updated' means this session has progress its partner hasn't received."""
    pair = find(tool, sid)
    if not pair:
        return "new", None
    partner = pair[OTHER[tool]]["id"]
    pending = any(units(tool, sid, cwd)[pair[tool]["cursor"]:])
    return ("updated" if pending else "linked"), partner
