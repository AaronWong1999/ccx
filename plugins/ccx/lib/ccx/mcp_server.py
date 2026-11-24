"""Minimal stdio MCP server exposing ccx to Claude Code, Codex, Antigravity and ZCode.

    python -m ccx.mcp_server --host claude|codex|antigravity|zcode

`--host` is the app this server runs inside; "the other apps" are the rest.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import __version__, antigravity, claude, cloud, codex, history, pairs, zcode
from .common import NAME, OTHER, TOOLS, others, real
from .sync import STATUS, default_target, find_sessions, transfer


def _or(tools) -> str:
    ns = [NAME[t] for t in tools]
    return ns[0] if len(ns) == 1 else ", ".join(ns[:-1]) + " or " + ns[-1]


def tools(host: str) -> list:
    os_ = others(host)
    other = _or(os_)
    cwd = {"type": "string", "description": "Absolute path of the current project (your working directory)"}
    query = {"type": "string", "description": f"Search {other} sessions by title (a name the user typed or one "
                                              f"read from a screenshot); searches every project"}
    app = {"app": {"type": "string", "enum": os_, "description":
                   f"Which app is meant: {' or '.join(os_)}. Set it when the user names one; leave it out to cover "
                   f"every other app (or, when sending, to use the conversation's existing link)."}}
    if host == "antigravity":
        # Antigravity starts one server for all conversations, so it can't tell us which one is calling.
        app["conversation_id"] = {"type": "string", "description":
                                  "This conversation's own id, when you know it (otherwise the most recently "
                                  "active conversation of this project is used)."}
    rw = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    return [
        {
            "name": "read_session",
            "description": f"Read {other} history in small pages without consuming sync progress. "
                           "Use to recover earlier or truncated context; repeat with next_offset until null.",
            "inputSchema": {"type": "object", "required": ["session_id"], "properties": {
                "session_id": {"type": "string"}, "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 6000, "maximum": 12000}}},
            "annotations": {"title": f"Read {other} history", "readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "continue_here",
            "description": (
                f"Bring {other}'s progress on a task into this conversation so you can carry on here. "
                f"(1) With session_id: link this conversation to that {other} session and return its whole "
                f"conversation (condensed); from then on they stay in sync. "
                f"(2) With only query: find sessions by title and return candidates; pick one (or ask the user) "
                f"and call again with its session_id. "
                f"(3) With neither: if this conversation is linked, return the other side's progress since the last "
                f"sync; otherwise return candidates. "
                f"Use it when the user says things like “continue from {os_[0].title()}”, “import X from "
                f"{os_[-1].title()}”, “sync with {os_[0].title()}”, 接着 {NAME[os_[0]]} 继续, or shares a "
                f"screenshot of a {other} session."
            ),
            "inputSchema": {"type": "object", "required": ["cwd"], "properties": {
                "cwd": cwd, "query": query, "session_id": {"type": "string", "description": f"{other} session id"},
                **app}},
            "annotations": {"title": f"Continue from {other}", **rw},
        },
        {
            "name": "list_sessions",
            "description": f"List {other} sessions (this project by default; with query, search every project "
                           f"by title) and whether each is linked to a {NAME[host]} conversation.",
            "inputSchema": {"type": "object", "required": ["cwd"],
                            "properties": {"cwd": cwd, "query": query, "limit": {"type": "integer", "default": 8}, **app}},
            "annotations": {"title": f"List {other} sessions", "readOnlyHint": True, "openWorldHint": False},
        },
        {
            "name": "send_current_session",
            "description": (f"Hand this conversation to the {other} desktop app: the first time it is imported "
                            f"there and linked; afterwards the linked conversation is opened (it gets "
                            f"this side's new progress with its next message)."),
            "inputSchema": {"type": "object", "properties": {"cwd": cwd, **app}, "required": ["cwd"]},
            "annotations": {"title": f"Continue in {other}", **rw},
        },
        {
            "name": "unlink",
            "description": (f"Stop syncing this conversation with its linked {other} conversation: ccx forgets "
                            f"the link, so neither side gets the other's progress any more. Every conversation is "
                            f"kept. Use when the user says “unlink”, “stop syncing”, 取消关联 or 不要同步了."),
            "inputSchema": {"type": "object", "properties": {"cwd": cwd, **app}, "required": ["cwd"]},
            "annotations": {"title": f"Unlink from {other}", "readOnlyHint": False, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False},
        },
    ]


def unlink_message(tool: str, sid: str, other: str = None) -> str:
    gone = pairs.unlink(tool, sid, other)
    if not gone:
        return f"This {NAME[tool]} conversation isn't linked to {_or([other] if other else others(tool))}; nothing to unlink."
    parts = [f"{NAME[t]} conversation {g[t]['id']}" for g in gone for t in [pairs.partner_tool(g, tool)]]
    there = _or([pairs.partner_tool(g, tool) for g in gone])
    return (f"Unlinked from {' and '.join(parts)}. Every conversation is kept; they no "
            f"longer sync. Sending this conversation to {there} again links it afresh.")


def current_session(host: str, cwd: str) -> str:
    """The conversation this tool call comes from."""
    if host == "claude" and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return os.environ["CLAUDE_CODE_SESSION_ID"]
    for k in ("CODEX_THREAD_ID", "CODEX_SESSION_ID"):
        if host == "codex" and os.environ.get(k):
            return os.environ[k]
    if host == "antigravity" and os.environ.get("ANTIGRAVITY_CONVERSATION_ID"):
        return os.environ["ANTIGRAVITY_CONVERSATION_ID"]
    if host == "zcode" and (os.environ.get("ZCODE_SESSION_ID") or "").startswith("sess_"):
        return os.environ["ZCODE_SESSION_ID"]
    ss = claude.sessions(cwd) if host == "claude" else codex.threads(cwd, limit=1) if host == "codex" \
        else zcode.sessions(cwd, limit=1) if host == "zcode" \
        else (antigravity.sessions(cwd, limit=1) or antigravity.sessions(limit=1))
    if not ss:
        raise RuntimeError(f"no {NAME[host]} conversation found for {cwd}")
    return ss[0].id  # the active conversation is the most recently updated one


def _list(host: str, cwd: str, query, limit: int, app: str = None) -> str:
    out = []
    for other in ([app] if app else others(host)):
        rows = find_sessions(other, cwd, query, limit)
        if not rows:
            out.append(f"No {NAME[other]} sessions found" + (f" for “{query}”." if query else f" in {cwd}."))
            continue
        lines = [f"{NAME[other]} sessions, newest first" + (f", matching “{query}”" if query else "") + ":"]
        for i, r in enumerate(rows, 1):
            where = f" · folder {r['cwd']} (differs from yours)" if r["other_folder"] else ""
            mine = (r.get("links") or {}).get(host)
            st = STATUS[mine["status"]] if mine else STATUS["mirror" if r["status"] == "mirror" else "new"]
            lines.append(f"{i}. “{r['title']}” {r['updated']} · {st}{where} · id={r['id']}")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def _hint() -> str:
    """Plugin-only installs (from a plugin directory): where the rest of ccx lives."""
    from . import presence
    return "" if presence.full_install() else (
        "\n\n(Mention to the user once, briefly: " + presence.setup_hint().replace("\n", " ") + ")")


def _tool_of(host: str, sid: str) -> str:
    """Which other app a session id belongs to."""
    s = pairs.locate(sid, others(host))
    if s:
        return s.tool
    return "codex" if host != "codex" and cloud.is_codex(sid) else "claude" if host != "claude" and cloud.is_claude(sid) \
        else OTHER[host]


def call(host: str, name: str, args: dict) -> str:
    app = args.get("app") if args.get("app") in TOOLS and args.get("app") != host else None
    if name == "read_session":
        return json.dumps(history.read_page(app or _tool_of(host, args["session_id"]), args["session_id"],
                                            args.get("offset", 0), args.get("limit", 6000)), ensure_ascii=False)
    cwd = real(args.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    query = (args.get("query") or "").strip() or None
    if name == "list_sessions":
        return _list(host, cwd, query, int(args.get("limit") or 8), app)
    here = (args.get("conversation_id") or "").strip() if host == "antigravity" else ""
    here = (antigravity.find(here).id if here and antigravity.find(here) else "") or current_session(host, cwd)
    if name == "continue_here":
        if args.get("session_id"):
            res = pairs.continue_from(host, here, cwd, args["session_id"], app or _tool_of(host, args["session_id"]))
            return (f"Linked “{res['title']}” and loaded its whole conversation. Both sides now stay in sync."
                    f"{_hint()}\n\n{res['context']}")
        if query or not pairs.find(host, here, app):
            return ("No session chosen yet. Pick the best match below (ask the user if unsure), then call "
                    "continue_here again with its session_id.\n\n" + _list(host, cwd, query, 8, app))
        res = pairs.pull(host, here, budget=pairs.FULL_BUDGET)
        if not res:
            there = _or([pairs.partner_tool(p, host) for p in pairs.find_all(host, here)])
            return f"Nothing new on the {there} side since the last sync; this conversation is up to date."
        return f"Loaded {res['count']} new entries from {_or(res.get('sources') or [res['from']])}:\n\n{res['context']}"
    if name == "send_current_session":
        res = transfer(host, here, open_app=True, dst=app or default_target(host, here))
        link = res["target"]["deep_link"]
        return res["message"] + ("" if res.get("opened") or not link else f" Open: {link}") + _hint()
    if name == "unlink":
        return unlink_message(host, here, app)
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
    p.add_argument("--host", choices=list(TOOLS), required=True)
    serve(p.parse_args().host)


if __name__ == "__main__":
    main()
