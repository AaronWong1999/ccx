"""ccx — move the current project's conversation between Claude Code and Codex."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from . import __version__
from .stores import claude_sessions, codex_bin, codex_sessions, which
from .sync import continue_phrase, list_claude_for_codex, list_codex_for_claude, menu_data, transfer

NAME = {"claude": "Claude", "codex": "Codex"}
OTHER = {"claude": "codex", "codex": "claude"}
STATUS = {"new": "未关联", "linked": "已关联", "updated": "有新进展", "mirror": "副本"}


def pick(tool: str, cwd: str, ref):
    sessions = claude_sessions(cwd) if tool == "claude" else codex_sessions(cwd)
    if not sessions:
        sys.exit(f"当前目录没有 {NAME[tool]} 会话：{cwd}")
    if not ref:
        return sessions[0]
    for s in sessions:
        if s.id.startswith(ref):
            return s
    sys.exit(f"找不到 {NAME[tool]} 会话 {ref}（用 ccx ls 查看）")


def run(src_tool: str, sid: str, cwd: str, a):
    res = transfer(src_tool, sid, cwd, open_app=not (a.no_open or a.cli))
    t = res["target"]
    if res["action"] == "linked" and t["tool"] == "codex":
        # Codex only pulls on request until its hook is trusted: have the phrase ready to paste.
        subprocess.run(["pbcopy"], input=continue_phrase(src_tool).encode(), check=False)
        res["message"] += "（这句话已复制到剪贴板）"
    print(f"✓ {res['message']}")
    if a.cli:
        os.chdir(res["cwd"])
        if t["tool"] == "codex":
            os.execv(codex_bin(), ["codex", "resume", t["id"]])
        os.execv(which("claude"), ["claude", "--resume", t["id"]])
    elif a.no_open:
        print(f"  打开：open '{t['deep_link']}'")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ccx", description="在 Claude Code 和 Codex 之间导入/同步当前项目的会话")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-C", dest="cwd", default=os.getcwd(), help="项目目录（默认当前目录）")
    p.add_argument("--cli", action="store_true", help="在终端里续上，而不是打开桌面版")
    p.add_argument("--no-open", action="store_true", help="只转换，不打开")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("switch", help="（默认）把最近用过的那边的会话转到另一边")
    for dst in ("codex", "claude"):
        sp = sub.add_parser(f"to-{dst}", help=f"把 {NAME[OTHER[dst]]} 会话导入/同步到 {NAME[dst]}")
        sp.add_argument("session", nargs="?", help="会话 ID 前缀（默认最近一个）")
    ls = sub.add_parser("ls", help="列出当前项目两边的会话和同步状态")
    ls.add_argument("-n", type=int, default=8)
    sub.add_parser("menu-data", help="（给菜单栏程序用）输出最近项目和两边会话的 JSON")
    a = p.parse_args(argv)
    cwd = os.path.realpath(a.cwd)

    try:
        if a.cmd in (None, "switch"):
            c, x = claude_sessions(cwd), codex_sessions(cwd)
            if not c and not x:
                sys.exit(f"当前目录没有任何 Claude / Codex 会话：{cwd}")
            src = max((s[0] for s in (c, x) if s), key=lambda s: s.mtime)
            run(src.tool, src.id, cwd, a)
        elif a.cmd in ("to-codex", "to-claude"):
            src_tool = "claude" if a.cmd == "to-codex" else "codex"
            run(src_tool, pick(src_tool, cwd, a.session).id, cwd, a)
        elif a.cmd == "menu-data":
            print(json.dumps(menu_data(), ensure_ascii=False))
        elif a.cmd == "ls":
            for label, rows in (("Codex → Claude", list_codex_for_claude(cwd, a.n)),
                                ("Claude → Codex", list_claude_for_codex(cwd, a.n))):
                print(f"[{label}]")
                for r in rows:
                    print(f"  {r['updated']}  {r['id'][:8]}  {STATUS[r['status']]:<4}  {r['title']}")
                if not rows:
                    print("  （无）")
    except RuntimeError as e:
        sys.exit(f"✗ {e}")


if __name__ == "__main__":
    main()
