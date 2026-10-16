"""Minimal stdio MCP server exposing claudecodex to Claude Code and Codex.

    python -m claudecodex.mcp_server --host claude|codex

`--host` is the app this server runs inside; "the other side" is the other app.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import __version__, pairs
from .stores import claude_sessions, codex_sessions
from .sync import list_claude_for_codex, list_codex_for_claude, transfer

NAME = {"claude": "Claude", "codex": "Codex"}
STATUS = {"new": "未关联", "linked": "已关联", "updated": "有新进展", "mirror": "从对面导入的副本"}


def tools(host: str) -> list:
    other = "codex" if host == "claude" else "claude"
    cwd = {"type": "string", "description": "当前项目的绝对路径（你的工作目录）"}
    rw = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    return [
        {
            "name": "continue_here",
            "description": (
                f"把 {NAME[other]} 那边的进度拉进当前这个对话，让你在这里接着干。"
                f"不传 session_id：当前对话已和某个 {NAME[other]} 会话关联时，返回对面自上次同步以来的新进展；"
                f"还没关联时，返回可选的 {NAME[other]} 会话列表，让用户选。"
                f"传 session_id：把当前对话和那个会话关联，并返回它的完整对话（压缩），之后两边会自动同步。"
                f"用户说「接着 {NAME[other]} 继续」「从 {NAME[other]} 导入…」「同步一下 {NAME[other]}」时用它。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"cwd": cwd, "session_id": {"type": "string", "description": f"{NAME[other]} 会话 id（可选）"}},
                "required": ["cwd"],
            },
            "annotations": {"title": f"接着 {NAME[other]} 继续", **rw},
        },
        {
            "name": "list_sessions",
            "description": f"列出当前项目在 {NAME[other]} 里的会话，以及每个会话是否已和 {NAME[host]} 的会话关联。",
            "inputSchema": {"type": "object", "properties": {"cwd": cwd, "limit": {"type": "integer", "default": 8}},
                            "required": ["cwd"]},
            "annotations": {"title": f"列出 {NAME[other]} 的会话", "readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "send_current_session",
            "description": (f"让用户去 {NAME[other]} 桌面版接着干当前这个对话：第一次会导入过去并关联，"
                            f"之后直接打开已关联的那个会话（对面下次发消息时会自动带上这边的新进展）。"),
            "inputSchema": {"type": "object", "properties": {"cwd": cwd}, "required": ["cwd"]},
            "annotations": {"title": f"在 {NAME[other]} 里继续", **rw},
        },
    ]


def current_session(host: str, cwd: str) -> str:
    if host == "claude" and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return os.environ["CLAUDE_CODE_SESSION_ID"]
    for k in ("CODEX_THREAD_ID", "CODEX_SESSION_ID"):
        if host == "codex" and os.environ.get(k):
            return os.environ[k]
    sessions = claude_sessions(cwd) if host == "claude" else codex_sessions(cwd)
    if not sessions:
        raise RuntimeError(f"没找到当前项目（{cwd}）的 {NAME[host]} 会话")
    return sessions[0].id  # the active one is the most recently written


def _list(host: str, cwd: str, limit: int) -> str:
    other = "codex" if host == "claude" else "claude"
    lister = list_codex_for_claude if host == "claude" else list_claude_for_codex
    rows = lister(cwd, limit)
    if not rows:
        return f"{NAME[other]} 里没有这个项目（{cwd}）的会话。"
    lines = [f"{NAME[other]} 里本项目的会话（新的在前）："]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. 「{r['title']}」 {r['updated']} · {STATUS[r['status']]} · id={r['id']}")
    return "\n".join(lines)


def call(host: str, name: str, args: dict) -> str:
    other = "codex" if host == "claude" else "claude"
    cwd = os.path.realpath(args.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if name == "list_sessions":
        return _list(host, cwd, int(args.get("limit") or 8))
    here = current_session(host, cwd)
    if name == "continue_here":
        if args.get("session_id"):
            res = pairs.continue_from(host, here, args["session_id"], cwd)
            return (f"已关联，并拉取了 {NAME[other]} 会话的完整对话。以后两边会自动同步。\n\n" + res["context"])
        if not pairs.find(host, here):
            return ("当前对话还没有和任何 " + NAME[other] + " 会话关联。请让用户选一个，"
                    "然后带上 session_id 再调用一次 continue_here。\n\n" + _list(host, cwd, 8))
        res = pairs.pull(host, here, budget=pairs.FULL_BUDGET)
        if not res:
            return f"{NAME[other]} 那边自上次同步以来没有新进展，当前对话已经是最新的。"
        return f"拉取了 {NAME[other]} 的 {res['count']} 条新进展：\n\n" + res["context"]
    if name == "send_current_session":
        res = transfer(host, here, cwd, open_app=True)
        return res["message"] + ("，已在桌面版打开。" if res.get("opened") else f"。打开：{res['target']['deep_link']}")
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
            result = {
                "protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "claudecodex", "version": __version__},
            }
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
