"""ccx — continue the same task across Claude Code and Codex."""

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
            sys.exit(f"找不到 {NAME[tool]} 会话 {ref}（用 ccx ls 查看）")
        return s
    ss = claude.sessions(cwd) if tool == "claude" else codex.threads(cwd, limit=1)
    if not ss:
        sys.exit(f"当前目录没有 {NAME[tool]} 会话：{cwd}")
    return ss[0]


def run_transfer(src_tool: str, sid: str, a):
    res = transfer(src_tool, sid, open_app=not a.no_open)
    t = res["target"]
    if res["action"] == "linked" and t["tool"] == "codex":
        # Until Codex's hook is trusted, Codex pulls on request: have the phrase ready to paste.
        subprocess.run(["pbcopy"], input=continue_phrase(src_tool).encode(), check=False)
        res["message"] += "（这句话已复制到剪贴板）"
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"✓ {res['message']}")
        if a.no_open:
            print(f"  打开：open '{t['deep_link']}'")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ccx", description="在 Claude Code 和 Codex 之间接着干同一个任务")
    p.add_argument("--version", action="version", version=f"ccx {__version__}")
    p.add_argument("-C", dest="cwd", default=os.getcwd(), help="项目目录（默认当前目录）")
    p.add_argument("--no-open", action="store_true", help="只导入/关联，不打开桌面版")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("switch", help="（默认）把当前目录最近用过的那边的会话带到另一边")
    for dst in ("codex", "claude"):
        sp = sub.add_parser(f"to-{dst}", help=f"把 {NAME[OTHER[dst]]} 会话带到 {NAME[dst]}（第一次导入并关联，之后打开关联的会话）")
        sp.add_argument("session", nargs="?", help="会话 ID 或前缀（默认当前目录最近一个）")
    ls = sub.add_parser("ls", help="列出两边的会话和关联状态")
    ls.add_argument("-q", "--query", help="按标题搜索（所有项目）")
    ls.add_argument("-n", type=int, default=8)
    sub.add_parser("menu-data", help="（菜单栏程序用）最近项目和两边会话的 JSON")
    st = sub.add_parser("setup", help="安装/修复：两边的插件、菜单栏图标、ccx 命令")
    st.add_argument("--dev", action="store_true", help="插件从这个本地仓库安装（开发用）")
    up = sub.add_parser("update", help="更新 ccx 和两边的插件")
    up.add_argument("--quiet", action="store_true")
    rf = sub.add_parser("_refresh", help=argparse.SUPPRESS)
    rf.add_argument("--quiet", action="store_true")
    sub.add_parser("doctor", help="检查安装状态")
    au = sub.add_parser("autostart", help="登录时自动启动菜单栏图标")
    au.add_argument("state", choices=["on", "off", "status"])
    un = sub.add_parser("uninstall", help="移除两边的插件、菜单栏图标和 ccx 命令")
    un.add_argument("--purge", action="store_true", help="同时删除配对记录 ~/.ccx")
    a = p.parse_args(argv)
    cwd = real(a.cwd)

    try:
        if a.cmd in (None, "switch"):
            c, x = claude.sessions(cwd), codex.threads(cwd, limit=1)
            if not c and not x:
                sys.exit(f"当前目录没有任何 Claude / Codex 会话：{cwd}")
            src = max((ss[0] for ss in (c, x) if ss), key=lambda s: s.mtime)
            run_transfer(src.tool, src.id, a)
        elif a.cmd in ("to-codex", "to-claude"):
            src_tool = "claude" if a.cmd == "to-codex" else "codex"
            run_transfer(src_tool, pick(src_tool, cwd, a.session).id, a)
        elif a.cmd == "ls":
            for tool, label in (("codex", "Codex 的会话（可带到 Claude）"), ("claude", "Claude 的会话（可带到 Codex）")):
                rows = find_sessions(tool, cwd, a.query, a.n)
                print(f"[{label}]")
                for r in rows:
                    where = f"  ({r['cwd']})" if r["other_folder"] else ""
                    print(f"  {r['updated']}  {r['id'][:8]}  {STATUS[r['status']]:<5} {r['title']}{where}")
                if not rows:
                    print("  （无）")
        elif a.cmd == "menu-data":
            d = menu_data()
            d["version"] = __version__
            d["codex_hook_trusted"] = codex.hooks_trusted()
            print(json.dumps(d, ensure_ascii=False))
        elif a.cmd == "setup":
            sys.exit(install.setup(dev=a.dev))
        elif a.cmd == "update":
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
            print(f"✓ 登录时自动启动：{'开' if a.state == 'on' else '关'}")
        elif a.cmd == "uninstall":
            sys.exit(install.uninstall(purge=a.purge))
    except RuntimeError as e:
        sys.exit(f"✗ {e}")


if __name__ == "__main__":
    main()
