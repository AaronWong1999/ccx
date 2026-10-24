"""ccx - claudecodex: continue the same task across Claude Code and Codex."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__, claude, cloud, codex, install, pairs, repairs, usage
from .common import copy_to_clipboard, DEFAULTS, NAME, OTHER, L, Session, real, set_setting, setting
from .sync import (STATUS, continue_phrase, estimate, find_sessions, menu_data, new_claude_conversation, new_codex_conversation,
                   transfer)


def pick(tool: str, cwd: str, ref):
    if ref:
        if cloud.is_claude(ref) if tool == "claude" else cloud.is_codex(ref):
            return Session(tool, ref, cwd, 0, ref)  # a cloud session: transfer reads it
        s = claude.find(ref) if tool == "claude" else codex.find(ref)
        if not s:
            sys.exit(f"{NAME[tool]} session {ref} not found (see `ccx ls`)")
        return s
    ss = claude.sessions(cwd) if tool == "claude" else codex.threads(cwd, limit=1)
    if not ss:
        sys.exit(f"no {NAME[tool]} session in {cwd}")
    return ss[0]


def run_transfer(src_tool: str, sid: str, a):
    res = transfer(src_tool, sid, open_app=not a.no_open)
    t = res["target"]
    if res["action"] == "linked" and t["tool"] == "codex" and not res.get("goal") and codex.hooks_trusted() is False:
        # Without the hook Codex pulls on request: have the phrase ready to paste.
        copy_to_clipboard(continue_phrase(src_tool))
        res["message"] += f" (Say “{continue_phrase(src_tool)}” there; it is on your clipboard.)"
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"✓ {res['message']}")
        if a.no_open:
            print(f"  open: open '{t['deep_link']}'")


def _reorder(argv, commands) -> list:
    """Move shared flags given before the subcommand to after it (default: switch)."""
    if any(x in ("-h", "--help", "--version") for x in argv[:1]):
        return argv
    head, i = [], 0
    while i < len(argv) and argv[i] not in commands:
        head.append(argv[i])
        i += 1
    rest = argv[i:] or ["switch"]
    return rest[:1] + head + rest[1:]


def main(argv=None):
    # Shared flags work before or after the subcommand: `ccx --json update --check`
    # is rewritten to `ccx update --check --json` before parsing.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-C", dest="cwd", default=os.getcwd(), help="project folder (default: current folder)")
    common.add_argument("--no-open", action="store_true", help="import/link only, don't open the desktop app")
    common.add_argument("--json", action="store_true", help="JSON output")
    p = argparse.ArgumentParser(prog="ccx", description="ccx - claudecodex: continue the same task across Claude Code and Codex")
    p.add_argument("--version", action="version", version=f"ccx - claudecodex {__version__}")
    sub = p.add_subparsers(dest="cmd")
    _add = sub.add_parser
    sub.add_parser = lambda *args, **kw: _add(*args, parents=[common], **kw)
    sub.add_parser("switch", help="(default) take this folder's most recent session to the other app")
    for dst in ("codex", "claude"):
        sp = sub.add_parser(f"to-{dst}", help=f"take a {NAME[OTHER[dst]]} session to {NAME[dst]} "
                                              f"(import and link the first time, then open the linked one)")
        sp.add_argument("session", nargs="?", help="session id or prefix (default: newest in this folder)")
    ls = sub.add_parser("ls", help="list both sides' sessions and their link status")
    ls.add_argument("-q", "--query", help="search titles in every project")
    ls.add_argument("-n", type=int, default=8)
    sub.add_parser("menu-data", help=argparse.SUPPRESS)
    sub.add_parser("cloud-signin", help="sign in to Claude Code once so its cloud sessions show up (opens Terminal)")
    inf = sub.add_parser("info", help="which app a session belongs to and whether it is linked (for integrations)")
    inf.add_argument("session", help="Claude session id or Codex thread id")
    ul = sub.add_parser("unlink", help="stop syncing a linked pair; both conversations are kept")
    ul.add_argument("session", help="Claude session id or Codex thread id (either side of the pair)")
    tc = sub.add_parser("call", help="run one of ccx's MCP tools from a shell (for skills used without the MCP server)")
    tc.add_argument("host", choices=("claude", "codex"), help="the app the conversation is in")
    tc.add_argument("tool", choices=("continue_here", "list_sessions", "send_current_session", "read_session",
                                         "unlink"))
    tc.add_argument("--session-id")
    tc.add_argument("--query")
    tc.add_argument("--offset", type=int, default=0)
    sub.add_parser("usage", help="Claude's and Codex's 5-hour usage (built in, plus CodexBar, Claude Code Usage Monitor or ccusage if installed)")
    es = sub.add_parser("estimate", help=argparse.SUPPRESS)
    es.add_argument("tool", choices=("claude", "codex"))
    es.add_argument("session")
    nc = sub.add_parser("new-claude", help="open a new Claude conversation that continues a Codex thread")
    nc.add_argument("thread")
    nx = sub.add_parser("new-codex", help="open Codex to continue a Claude session in a new thread")
    nx.add_argument("session")
    cf = sub.add_parser("config", help="show or change a setting (language)")
    cf.add_argument("key", nargs="?")
    cf.add_argument("value", nargs="?")
    st = sub.add_parser("setup", help="install or repair: plugins in both apps, menu bar icon, `ccx` command")
    st.add_argument("--dev", action="store_true", help="install the plugin from this checkout (development)")
    up = sub.add_parser("update", help="update ccx and both apps' plugins")
    up.add_argument("--quiet", action="store_true")
    up.add_argument("--check", action="store_true", help="only check whether a new release is out")
    rf = sub.add_parser("_refresh", help=argparse.SUPPRESS)
    rf.add_argument("--quiet", action="store_true")
    sub.add_parser("doctor", help="check the installation")
    sub.add_parser("repair", help="repair linked Codex project grouping and history format (never stops Codex)")
    au = sub.add_parser("autostart", help="start the menu bar icon at login")
    au.add_argument("state", choices=["on", "off", "status"])
    un = sub.add_parser("uninstall", help="remove the plugins, menu bar icon and `ccx` command")
    un.add_argument("--purge", action="store_true", help="also delete link records in ~/.ccx")
    a = p.parse_args(_reorder(list(sys.argv[1:] if argv is None else argv), set(sub.choices)))
    cwd = real(a.cwd)

    try:
        if a.cmd in (None, "switch"):
            c, x = claude.sessions(cwd), codex.threads(cwd, limit=1)
            if not c and not x:
                sys.exit(f"no Claude or Codex session in {cwd}")
            src = max((ss[0] for ss in (c, x) if ss), key=lambda s: s.mtime)
            run_transfer(src.tool, src.id, a)
        elif a.cmd in ("to-codex", "to-claude"):
            src_tool = "claude" if a.cmd == "to-codex" else "codex"
            run_transfer(src_tool, pick(src_tool, cwd, a.session).id, a)
        elif a.cmd == "ls":
            for tool in ("codex", "claude"):
                rows = find_sessions(tool, cwd, a.query, a.n)
                print(f"[{NAME[tool]} sessions → continue in {NAME[OTHER[tool]]}]")
                for r in rows:
                    where = f"  ({r['cwd']})" if r["other_folder"] else ""
                    print(f"  {r['updated']}  {r['id'][:8]}  {STATUS[r['status']]:<16} {r['title']}{where}")
                if not rows:
                    print("  (none)")
        elif a.cmd == "cloud-signin":
            ok = cloud.claude_signin()
            print(json.dumps({"signed_in": ok}) if a.json else
                  L("✓ Signed in: Claude's cloud sessions now show in the ⇄ menu.", "✓ 已登录：Claude 云端会话会显示在 ⇄ 菜单里。")
                  if ok else L("Not signed in.", "未登录。"))
        elif a.cmd == "menu-data":
            d = menu_data()
            d["version"] = __version__
            d["codex_hook_trusted"] = codex.hooks_trusted()
            d["needs_setup"] = install.needs_setup()
            print(json.dumps(d, ensure_ascii=False))
        elif a.cmd == "info":
            s = claude.find(a.session) or codex.find(a.session)
            if not s:
                sys.exit(f"no Claude session or Codex thread {a.session}")
            st, partner = pairs.status(s)
            d = {"tool": s.tool, "id": s.id, "title": s.title, "cwd": s.cwd, "status": st,
                 "linked_to": partner, "continue_in": OTHER[s.tool]}
            print(json.dumps(d, ensure_ascii=False) if a.json else
                  f"{NAME[s.tool]} · {s.title} · {STATUS[st]}" + (f" · linked to {partner}" if partner else ""))
        elif a.cmd == "unlink":
            s = claude.find(a.session) or codex.find(a.session)
            if not s and cloud.is_codex(a.session) and pairs.find("codex", a.session):
                t = cloud.codex_task(a.session)  # a Codex Cloud task has no local thread
                s = Session("codex", a.session, pairs.find("codex", a.session)["codex"]["cwd"], 0,
                            t["title"] if t else a.session)
            if not s:
                sys.exit(f"no Claude session or Codex thread {a.session}")
            gone = pairs.unlink(s.tool, s.id)
            if a.json:
                print(json.dumps({"unlinked": bool(gone), "tool": s.tool, "id": s.id,
                                  "partner": gone[OTHER[s.tool]]["id"] if gone else None}))
            else:
                other = NAME[OTHER[s.tool]]
                print(L(f"✓ Unlinked “{s.title}” from {other}. Both conversations are kept; they no longer sync.",
                        f"✓ 已取消“{s.title}”与 {other} 的关联。两边的对话都保留，之后不再同步。") if gone
                      else L(f"“{s.title}” isn't linked; nothing to unlink.", f"“{s.title}”没有关联，无需取消。"))
        elif a.cmd == "call":
            from . import mcp_server
            args = {"cwd": cwd, "session_id": a.session_id, "query": a.query, "offset": a.offset}
            print(mcp_server.call(a.host, a.tool, {k: v for k, v in args.items() if v is not None}))
        elif a.cmd == "usage":
            u = usage.usage()
            if a.json:
                print(json.dumps(u, ensure_ascii=False))
            elif not u["available"]:
                print("No usage reading yet: Codex isn't installed and Claude hasn't hit a limit. CodexBar, "
                      "Claude Code Usage Monitor or ccusage, when installed, add more.")
            for tool in ("claude", "codex"):
                w = None if a.json else u.get(tool)
                if w:
                    pct = "?" if w["used_percentage"] is None else f"{w['used_percentage']:g}%"
                    resets = time.strftime("%H:%M", time.localtime(w["resets_at_epoch"])) if w["resets_at_epoch"] else "?"
                    print(f"{NAME[tool]} {'weekly' if w.get('window') == 'weekly' else '5-hour'} window: {pct} used, resets {resets} ({w['level']}, from {w['source']})")
        elif a.cmd == "estimate":
            print(json.dumps(estimate(a.tool, a.session)))
        elif a.cmd == "new-claude":
            new_claude_conversation(a.thread)
            print("✓ " + L("Opened a new Claude conversation with the prompt filled in. Dismiss this dialog, then send it in Claude to continue.",
                           "已打开一个新的 Claude 对话，接着干的指令已填入输入框。关闭此提示后，在 Claude 里点击发送即可继续。"))
        elif a.cmd == "new-codex":
            new_codex_conversation(a.session)
            print("✓ " + L("Opened a new Codex conversation with the prompt filled in. Dismiss this dialog, then send it in Codex to continue.",
                           "已打开一个新的 Codex 对话，接着干的指令已填入输入框。关闭此提示后，在 Codex 里点击发送即可继续。"))
        elif a.cmd == "config":
            if a.key and a.value is not None:
                v = {"true": True, "on": True, "false": False, "off": False}.get(a.value.lower(), a.value)
                set_setting(a.key, v)
            print(json.dumps({k: setting(k) for k in DEFAULTS} if not a.key else {a.key: setting(a.key)}))
        elif a.cmd == "setup":
            sys.exit(install.setup(dev=a.dev))
        elif a.cmd == "update":
            if a.check:
                c = install.check()
                if a.json:
                    print(json.dumps(c))
                else:
                    print(f"ccx {c['current']}: " + (f"{c['latest']} is available ({c['url']}). Run `ccx update`."
                                                    if c["available"] else "up to date."))
                sys.exit(0)
            sys.exit(install.update(quiet=a.quiet))
        elif a.cmd == "_refresh":
            sys.exit(install.refresh(quiet=a.quiet))
        elif a.cmd == "doctor":
            sys.exit(install.doctor())
        elif a.cmd == "repair":
            for pair in pairs.load():
                side = pair["codex"]
                codex.ensure_thread_project(side["id"], side["cwd"])
                status = repairs.prepare(side["id"])
                print(side["id"] + ": " + ("ready" if status == "ready" else
                      "queued: quit Codex when convenient to release this thread; ccx will retry"))
        elif a.cmd == "autostart":
            if a.state == "status":
                on = install.autostart(None)
                print("on" if on else "off")
                sys.exit(0 if on else 1)
            install.autostart(a.state == "on")
            print(f"✓ start at login: {a.state}")
        elif a.cmd == "uninstall":
            sys.exit(install.uninstall(purge=a.purge))
    except RuntimeError as e:
        sys.exit(f"✗ {e}")


if __name__ == "__main__":
    main()
