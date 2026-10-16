"""ccx - claudecodex: continue the same task across Claude Code and Codex."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from . import __version__, claude, codex, install
from .common import NAME, OTHER, real
from .sync import STATUS, continue_phrase, find_sessions, menu_data, transfer


def pick(tool: str, cwd: str, ref):
    if ref:
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
    if res["action"] == "linked" and t["tool"] == "codex" and codex.hooks_trusted() is False:
        # Without the hook Codex pulls on request: have the phrase ready to paste.
        subprocess.run(["pbcopy"], input=continue_phrase(src_tool).encode(), check=False)
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
    st = sub.add_parser("setup", help="install or repair: plugins in both apps, menu bar icon, `ccx` command")
    st.add_argument("--dev", action="store_true", help="install the plugin from this checkout (development)")
    up = sub.add_parser("update", help="update ccx and both apps' plugins")
    up.add_argument("--quiet", action="store_true")
    up.add_argument("--check", action="store_true", help="only check whether a new release is out")
    rf = sub.add_parser("_refresh", help=argparse.SUPPRESS)
    rf.add_argument("--quiet", action="store_true")
    sub.add_parser("doctor", help="check the installation")
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
        elif a.cmd == "menu-data":
            d = menu_data()
            d["version"] = __version__
            d["codex_hook_trusted"] = codex.hooks_trusted()
            print(json.dumps(d, ensure_ascii=False))
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
