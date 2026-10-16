"""Minimal stdio MCP server exposing ccx to Claude Code and Codex.

    python -m ccx.mcp_server --host claude|codex

`--host` is the app this server runs inside; "the other side" is the other app.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import __version__, claude, codex, pairs
from .common import NAME, OTHER, real
from .sync import STATUS, find_sessions, transfer


def tools(host: str) -> list:
    other = OTHER[host]
    cwd = {"type": "string", "description": "当前项目的绝对路径（你的工作目录）"}
    query = {"type": "string", "description": f"按标题搜索 {NAME[other]} 会话（比如用户截图或口述里的会话名称），会搜索所有项目"}
    rw = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    return [
        {
            "name": "continue_here",
            "description": (
                f"把 {NAME[other]} 那边的进度拉进当前对话，在这里接着干。"
                f"① 传 session_id：把当前对话和那个 {NAME[other]} 会话关联，返回它的完整对话（压缩）；之后两边自动同步。"
                f"② 只传 query：按标题找会话（截图/口述里的名称），返回候选让你挑或让用户选，再用 session_id 调一次。"
                f"③ 都不传：当前对话已关联时返回对面自上次同步以来的新进展；没关联时返回候选列表。"
                f"用户说「接着 {NAME[other]} 继续」「从 {NAME[other]} 把…导入」「同步一下 {NAME[other]}」或给出会话截图时用它。"
            ),
            "inputSchema": {"type": "object", "required": ["cwd"], "properties": {
                "cwd": cwd, "query": query,
                "session_id": {"type": "string", "description": f"{NAME[other]} 会话 id"}}},
            "annotations": {"title": f"接着 {NAME[other]} 继续", **rw},
        },
        {
            "name": "list_sessions",
            "description": f"列出 {NAME[other]} 的会话（默认当前项目；带 query 时按标题搜索所有项目），以及是否已和 {NAME[host]} 关联。",
            "inputSchema": {"type": "object", "required": ["cwd"],
                            "properties": {"cwd": cwd, "query": query, "limit": {"type": "integer", "default": 8}}},
            "annotations": {"title": f"列出 {NAME[other]} 的会话", "readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "send_current_session",
            "description": (f"让用户去 {NAME[other]} 桌面版接着干当前对话：第一次导入过去并关联，"
                            f"之后直接打开已关联的那个会话（那边发消息时会带上这边的新进展）。"),
            "inputSchema": {"type": "object", "properties": {"cwd": cwd}, "required": ["cwd"]},
            "annotations": {"title": f"在 {NAME[other]} 里继续", **rw},
        },
    ]


def current_session(host: str, cwd: str) -> str:
    """The conversation this tool call comes from."""
    if host == "claude" and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return os.environ["CLAUDE_CODE_SESSION_ID"]
    for k in ("CODEX_THREAD_ID", "CODEX_SESSION_ID"):
        if host == "codex" and os.environ.get(k):
            return os.environ[k]
    ss = claude.sessions(cwd) if host == "claude" else codex.threads(cwd, limit=1)
    if not ss:
        raise RuntimeError(f"没找到当前项目（{cwd}）的 {NAME[host]} 会话")
    return ss[0].id  # the active conversation is the most recently updated one


def _list(host: str, cwd: str, query, limit: int) -> str:
    other = OTHER[host]
    rows = find_sessions(other, cwd, query, limit)
    if not rows:
        return f"{NAME[other]} 里没有找到会话" + (f"（搜索：{query}）" if query else f"（项目：{cwd}）") + "。"
    lines = [f"{NAME[other]} 的会话（新的在前）" + (f"，搜索「{query}」" if query else "") + "："]
    for i, r in enumerate(rows, 1):
        where = f" · 目录 {r['cwd']}（和当前目录不同）" if r["other_folder"] else ""
        lines.append(f"{i}. 「{r['title']}」 {r['updated']} · {STATUS[r['status']]}{where} · id={r['id']}")
    return "\n".join(lines)


def call(host: str, name: str, args: dict) -> str:
    other = OTHER[host]
    cwd = real(args.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    query = (args.get("query") or "").strip() or None
    if name == "list_sessions":
        return _list(host, cwd, query, int(args.get("limit") or 8))
    here = current_session(host, cwd)
    if name == "continue_here":
        if args.get("session_id"):
            res = pairs.continue_from(host, here, cwd, args["session_id"])
            return f"已关联「{res['title']}」，并拉取了它的完整对话。以后两边会自动同步。\n\n{res['context']}"
        if query or not pairs.find(host, here):
            return ("还没有选定要接着的会话。从下面挑最符合的一个（拿不准就让用户选），"
                    "然后带上 session_id 再调用一次 continue_here。\n\n" + _list(host, cwd, query, 8))
        res = pairs.pull(host, here, budget=pairs.FULL_BUDGET)
        if not res:
            return f"{NAME[other]} 那边自上次同步以来没有新进展，当前对话已经是最新的。"
        return f"拉取了 {NAME[other]} 的 {res['count']} 条新进展：\n\n{res['context']}"
    if name == "send_current_session":
        res = transfer(host, here, open_app=True)
        return res["message"] + ("（已在桌面版打开）" if res.get("opened") else f"。打开：{res['target']['deep_link']}")
    raise RuntimeError(f"未知工具 {name}")


def serve(host: str):
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue  # notification
        if method == "initialize":
            result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "ccx", "version": __version__}}
        elif method == "tools/list":
            result = {"tools": tools(host)}
        elif method == "tools/call":
            p = msg.get("params") or {}
            try:
                text, err = call(host, p.get("name"), p.get("arguments") or {}), False
            except Exception as e:
                text, err = f"失败：{e}", True
                traceback.print_exc(file=sys.stderr)
            result = {"content": [{"type": "text", "text": text}], "isError": err}
        elif method == "ping":
            result = {}
        else:
            reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", choices=["claude", "codex"], required=True)
    serve(p.parse_args().host)


if __name__ == "__main__":
    main()
