"""ccx — switch the current project's conversation between Claude Code and Codex."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .stores import (
    Session,
    claude_sessions,
    codex_sessions,
    codex_turns,
    git_snapshot,
    write_claude_session,
)

OTHER = {"claude": "codex", "codex": "claude"}
NAME = {"claude": "Claude Code", "codex": "Codex"}


def latest(tool: str, cwd: str) -> Session | None:
    s = claude_sessions(cwd) if tool == "claude" else codex_sessions(cwd)
    return s[0] if s else None


def find(tool: str, cwd: str, ref: str | None) -> Session:
    sessions = claude_sessions(cwd) if tool == "claude" else codex_sessions(cwd)
    if not ref:
        if not sessions:
            sys.exit(f"当前目录没有 {NAME[tool]} 会话：{cwd}")
        return sessions[0]
    for s in sessions:
        if s.id.startswith(ref) or str(s.path) == ref:
            return s
    sys.exit(f"找不到 {NAME[tool]} 会话 {ref}（用 ccx ls 查看）")


# ------------------------------------------------------------------ transfers

def to_codex(src: Session) -> str:
    from .codex_import import import_claude_session

    rec = import_claude_session(str(src.path), src.cwd, src.title)
    # The importer writes a new rollout; the newest Codex session for this cwd is it.
    new = latest("codex", src.cwd)
    return new.id if new else (rec.get("target") or "")


def to_claude(src: Session) -> str:
    turns = codex_turns(src.path)
    if not turns:
        sys.exit("这个 Codex 会话里没有可导入的对话内容")
    stamp = datetime.fromtimestamp(src.mtime).strftime("%Y-%m-%d %H:%M")
    header = (
        f"[claudecodex] 以下对话从 Codex 会话 {src.id}（{stamp}）导入。"
        "工具调用和输出已压缩成摘要；代码改动已经在工作区里。\n\n"
    )
    first_role, first_text = turns[0]
    turns[0] = (first_role, header + first_text)
    tail = f"\n\n---\n[claudecodex] 导入时的 git 状态：\n```\n{git_snapshot(src.cwd)}\n```\n请在此基础上继续。"
    if turns[-1][0] == "assistant":
        turns[-1] = ("assistant", turns[-1][1] + tail)
    else:
        turns.append(("assistant", tail.strip()))
    new = write_claude_session(src.cwd, turns, f"⇄ {src.title or 'Codex 会话'}")
    return new.id


def launch(tool: str, sid: str, cwd: str, how: str):
    if how == "none":
        return
    if how == "app":
        if tool == "codex":
            os.execvp("codex", ["codex", "app"])
        os.execvp("open", ["open", "-a", "Claude"])
    os.chdir(cwd)
    if tool == "codex":
        os.execvp("codex", ["codex", "resume", sid])
    os.execvp("claude", ["claude", "--resume", sid])


def transfer(src: Session, how: str):
    dst = OTHER[src.tool]
    print(f"→ 把 {NAME[src.tool]} 会话「{src.title or src.id[:8]}」({src.when}) 转到 {NAME[dst]} …")
    sid = to_codex(src) if dst == "codex" else to_claude(src)
    print(f"✓ 完成：{NAME[dst]} 会话 {sid}")
    if dst == "codex":
        print(f"  终端续上：codex resume {sid}    （Codex 桌面版的会话列表里也能看到）")
    else:
        print(f"  终端续上：claude --resume {sid}")
    launch(dst, sid, src.cwd, how)


# ----------------------------------------------------------------- commands

def cmd_switch(a):
    cwd = os.path.realpath(a.cwd)
    c, x = latest("claude", cwd), latest("codex", cwd)
    if not c and not x:
        sys.exit(f"当前目录没有任何 Claude / Codex 会话：{cwd}")
    src = max((s for s in (c, x) if s), key=lambda s: s.mtime)
    transfer(src, a.open)


def cmd_to(a, dst: str):
    cwd = os.path.realpath(a.cwd)
    transfer(find(OTHER[dst], cwd, a.session), a.open)


def cmd_ls(a):
    cwd = None if a.all else os.path.realpath(a.cwd)
    rows = sorted(claude_sessions(cwd) + codex_sessions(cwd), key=lambda s: s.mtime, reverse=True)[: a.n]
    if not rows:
        print("没有会话")
    for s in rows:
        where = "" if cwd else f"  {s.cwd}"
        print(f"{s.when}  {s.tool:<6}  {s.id[:8]}  {s.title}{where}")


PKG_DIR = Path(__file__).resolve().parent
SHIM = Path.home() / ".local" / "bin" / "ccx"
SKILL_TARGETS = {
    "to-codex": Path.home() / ".claude" / "skills" / "to-codex",
    "to-claude": Path.home() / ".codex" / "skills" / "to-claude",
}


def cmd_install(a):
    SHIM.parent.mkdir(parents=True, exist_ok=True)
    SHIM.write_text(
        f'#!/bin/sh\nPYTHONPATH="{PKG_DIR.parent}" exec "{sys.executable}" -m claudecodex "$@"\n'
    )
    SHIM.chmod(0o755)
    print(f"✓ 命令 ccx → {SHIM}")
    for name, dst in SKILL_TARGETS.items():
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(PKG_DIR / "skills" / name / "SKILL.md", dst / "SKILL.md")
        print(f"✓ skill {name} → {dst}")
    if str(SHIM.parent) not in os.environ.get("PATH", "").split(":"):
        print(f"注意：{SHIM.parent} 不在 PATH 里，需要加到 ~/.zshrc")


def cmd_uninstall(a):
    SHIM.unlink(missing_ok=True)
    for dst in SKILL_TARGETS.values():
        shutil.rmtree(dst, ignore_errors=True)
    print("✓ 已移除 ccx 命令和两个 skill")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ccx", description="在 Claude Code 和 Codex 之间互转当前项目的会话")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-C", dest="cwd", default=os.getcwd(), help="项目目录（默认当前目录）")
    p.add_argument(
        "--open",
        choices=["cli", "app", "none"],
        default="cli",
        help="转完后怎么打开：cli=在终端直接续上（默认），app=打开桌面版，none=只转换",
    )
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("switch", help="（默认）把最近用过的那边的会话转到另一边")
    for dst in ("codex", "claude"):
        sp = sub.add_parser(f"to-{dst}", help=f"把 {NAME[OTHER[dst]]} 会话转到 {NAME[dst]}")
        sp.add_argument("session", nargs="?", help="会话 ID 前缀（默认最近一个）")
    ls = sub.add_parser("ls", help="列出当前项目两边的会话")
    ls.add_argument("-a", "--all", action="store_true", help="所有项目")
    ls.add_argument("-n", type=int, default=15)
    sub.add_parser("install", help="安装 ccx 命令，以及 Claude 的 /to-codex 和 Codex 的 to-claude skill")
    sub.add_parser("uninstall", help="移除上面装的东西")
    a = p.parse_args(argv)

    for tool in ("claude", "codex"):
        if not shutil.which(tool):
            print(f"提示：没找到 `{tool}` 命令", file=sys.stderr)

    if a.cmd in (None, "switch"):
        cmd_switch(a)
    elif a.cmd == "to-codex":
        cmd_to(a, "codex")
    elif a.cmd == "to-claude":
        cmd_to(a, "claude")
    elif a.cmd == "ls":
        cmd_ls(a)
    elif a.cmd == "install":
        cmd_install(a)
    elif a.cmd == "uninstall":
        cmd_uninstall(a)


if __name__ == "__main__":
    main()
