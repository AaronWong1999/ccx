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

from . import __version__
from .stores import claude_sessions, codex_sessions
from .sync import list_claude_for_codex, list_codex_for_claude, transfer

NAME = {"claude": "Claude Code", "codex": "Codex"}
STATUS = {"new": "未导入", "updated": "对面有新内容，可同步", "synced": "已同步", "mirror": "从 Claude 导入的副本"}


def tools(host: str) -> list:
    other = "codex" if host == "claude" else "claude"
    cwd = {"type": "string", "description": "当前项目的绝对路径（你的工作目录）"}
    return [
        {
            "name": "list_sessions",
            "description": f"列出当前项目在 {NAME[other]} 里的会话，以及每个会话是否已经导入到 {NAME[host]}。"
                           f"用户想把 {NAME[other]} 的对话拿过来继续时先调用它，然后让用户选。",
            "inputSchema": {
                "type": "object",
                "properties": {"cwd": cwd, "limit": {"type": "integer", "default": 8}},
                "required": ["cwd"],
            },
            "annotations": {"title": "列出对面的会话", "readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "import_session",
            "description": f"把一个 {NAME[other]} 会话导入到 {NAME[host]}；如果之前导入过，就只同步新内容。"
                           f"完成后会在 {NAME[host]} 桌面版里直接打开它。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "list_sessions 返回的 id"},
                    "cwd": cwd,
                    "open": {"type": "boolean", "default": True, "description": "完成后在桌面版打开"},
                },
                "required": ["session_id", "cwd"],
            },
            "annotations": {"title": "导入或同步会话", "readOnlyHint": False, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False},
        },
        {
            "name": "send_current_session",
            "description": f"把当前这个 {NAME[host]} 会话发到 {NAME[other]}（导入或同步），并在 {NAME[other]} 桌面版打开，"
                           f"让用户在 {NAME[other]} 里接着干。",
            "inputSchema": {
                "type": "object",
                "properties": {"cwd": cwd, "open": {"type": "boolean", "default": True}},
                "required": ["cwd"],
            },
            "annotations": {"title": "发送当前会话到对面", "readOnlyHint": False, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False},
        },
    ]


def call(host: str, name: str, args: dict) -> str:
    other = "codex" if host == "claude" else "claude"
    cwd = os.path.realpath(args.get("cwd") or os.getcwd())
    if name == "list_sessions":
        lister = list_codex_for_claude if host == "claude" else list_claude_for_codex
        rows = lister(cwd, int(args.get("limit") or 8))
        if not rows:
            return f"{NAME[other]} 里没有这个项目（{cwd}）的会话。"
        lines = [f"{NAME[other]} 里本项目的会话（新的在前）："]
        for i, r in enumerate(rows, 1):
            lines.append(f"{i}. 「{r['title']}」 {r['updated']} · {STATUS[r['status']]} · id={r['id']}")
        return "\n".join(lines) + "\n\n" + json.dumps(rows, ensure_ascii=False)
    if name == "import_session":
        res = transfer(other, args["session_id"], cwd, bool(args.get("open", True)))
        return _done(res)
    if name == "send_current_session":
        sessions = claude_sessions(cwd) if host == "claude" else codex_sessions(cwd)
        if not sessions:
            raise RuntimeError(f"没找到当前项目（{cwd}）的 {NAME[host]} 会话")
        res = transfer(host, sessions[0].id, cwd, bool(args.get("open", True)))
        return _done(res)
    raise RuntimeError(f"未知工具 {name}")


def _done(res: dict) -> str:
    t = res["target"]
    opened = "，已在桌面版打开" if res.get("opened") else f"，打开链接：{t['deep_link']}"
    return f"{res['message']}{opened}\n\n" + json.dumps(res, ensure_ascii=False)


def serve(host: str):
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue  # notification
        try:
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
        except Exception as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}) + "\n")
            sys.stdout.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", choices=["claude", "codex"], required=True)
    serve(p.parse_args().host)


if __name__ == "__main__":
    main()
