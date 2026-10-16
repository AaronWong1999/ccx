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

from . import __version__, claude, codex, history, pairs
from .common import NAME, OTHER, real
from .sync import STATUS, find_sessions, transfer


def tools(host: str) -> list:
    other = OTHER[host]
    cwd = {"type": "string", "description": "Absolute path of the current project (your working directory)"}
    query = {"type": "string", "description": f"Search {NAME[other]} sessions by title (a name the user typed or one "
                                              f"read from a screenshot); searches every project"}
    rw = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    return [
        {
            "name": "read_session",
            "description": f"Read {NAME[other]} history in small pages without consuming sync progress. "
                           "Use to recover earlier or truncated context; repeat with next_offset until null.",
            "inputSchema": {"type": "object", "required": ["session_id"], "properties": {
                "session_id": {"type": "string"}, "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 6000, "maximum": 12000}}},
            "annotations": {"title": f"Read {NAME[other]} history", "readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "continue_here",
            "description": (
                f"Bring {NAME[other]}'s progress on a task into this conversation so you can carry on here. "
                f"(1) With session_id: link this conversation to that {NAME[other]} session and return its whole "
                f"conversation (condensed); from then on both stay in sync. "
                f"(2) With only query: find sessions by title and return candidates; pick one (or ask the user) "
                f"and call again with its session_id. "
                f"(3) With neither: if this conversation is linked, return the other side's progress since the last "
                f"sync; otherwise return candidates. "
                f"Use it when the user says things like “continue from {NAME[other]}”, “import X from "
                f"{NAME[other]}”, “sync with {NAME[other]}”, 接着 {NAME[other]} 继续, or shares a "
                f"screenshot of a {NAME[other]} session."
            ),
            "inputSchema": {"type": "object", "required": ["cwd"], "properties": {
                "cwd": cwd, "query": query, "session_id": {"type": "string", "description": f"{NAME[other]} session id"}}},
            "annotations": {"title": f"Continue from {NAME[other]}", **rw},
        },
        {
            "name": "list_sessions",
            "description": f"List {NAME[other]} sessions (this project by default; with query, search every project "
                           f"by title) and whether each is linked to a {NAME[host]} conversation.",
            "inputSchema": {"type": "object", "required": ["cwd"],
                            "properties": {"cwd": cwd, "query": query, "limit": {"type": "integer", "default": 8}}},
            "annotations": {"title": f"List {NAME[other]} sessions", "readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "send_current_session",
            "description": (f"Hand this conversation to the {NAME[other]} desktop app: the first time it is imported "
                            f"there and linked; afterwards the linked {NAME[other]} conversation is opened (it gets "
                            f"this side's new progress with its next message)."),
            "inputSchema": {"type": "object", "properties": {"cwd": cwd}, "required": ["cwd"]},
            "annotations": {"title": f"Continue in {NAME[other]}", **rw},
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
        raise RuntimeError(f"no {NAME[host]} conversation found for {cwd}")
    return ss[0].id  # the active conversation is the most recently updated one


def _list(host: str, cwd: str, query, limit: int) -> str:
    other = OTHER[host]
    rows = find_sessions(other, cwd, query, limit)
    if not rows:
        return f"No {NAME[other]} sessions found" + (f" for “{query}”." if query else f" in {cwd}.")
    lines = [f"{NAME[other]} sessions, newest first" + (f", matching “{query}”" if query else "") + ":"]
    for i, r in enumerate(rows, 1):
        where = f" · folder {r['cwd']} (differs from yours)" if r["other_folder"] else ""
        lines.append(f"{i}. “{r['title']}” {r['updated']} · {STATUS[r['status']]}{where} · id={r['id']}")
    return "\n".join(lines)


def call(host: str, name: str, args: dict) -> str:
    other = OTHER[host]
    if name == "read_session":
        return json.dumps(history.read_page(other, args["session_id"], args.get("offset", 0),
                                            args.get("limit", 6000)), ensure_ascii=False)
    cwd = real(args.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    query = (args.get("query") or "").strip() or None
    if name == "list_sessions":
        return _list(host, cwd, query, int(args.get("limit") or 8))
    here = current_session(host, cwd)
    if name == "continue_here":
        if args.get("session_id"):
            res = pairs.continue_from(host, here, cwd, args["session_id"])
            return f"Linked “{res['title']}” and loaded its whole conversation. Both sides now stay in sync.\n\n{res['context']}"
        if query or not pairs.find(host, here):
            return ("No session chosen yet. Pick the best match below (ask the user if unsure), then call "
                    "continue_here again with its session_id.\n\n" + _list(host, cwd, query, 8))
        res = pairs.pull(host, here, budget=pairs.FULL_BUDGET)
        if not res:
            return f"Nothing new on the {NAME[other]} side since the last sync; this conversation is up to date."
        return f"Loaded {res['count']} new entries from {NAME[other]}:\n\n{res['context']}"
    if name == "send_current_session":
        res = transfer(host, here, open_app=True)
        return res["message"] + ("" if res.get("opened") else f" Open: {res['target']['deep_link']}")
    raise RuntimeError(f"unknown tool {name}")


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
                text, err = f"Failed: {e}", True
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
