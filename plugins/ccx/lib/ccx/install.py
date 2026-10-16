"""Install, update, check and remove ccx, using the CLIs bundled inside the
Claude and Codex desktop apps (no separate CLI installs needed)."""

from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__, claude, codex, pairs
from .common import HOME, STATE_DIR

REPO = "aaronwong1999/ccx"
SRC = Path(__file__).resolve().parents[4]          # repo root: plugins/ccx/lib/ccx/install.py
PLUGIN_BIN = SRC / "plugins/ccx/bin"
APP = HOME / "Applications/ccx.app"
LINK = HOME / ".local/bin/ccx"
AGENT_LABEL = "io.github.aaronwong1999.ccx"
AGENT = HOME / f"Library/LaunchAgents/{AGENT_LABEL}.plist"
LEGACY = "claudecodex"


def run(cmd: List[str], timeout: int = 300) -> Tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def say(ok: bool, text: str, quiet: bool = False):
    if not quiet or not ok:
        print(("✓ " if ok else "✗ ") + text)


def marketplace_source(dev: bool) -> str:
    """GitHub (the apps then update the plugin themselves), or this checkout for development."""
    return str(SRC) if dev else REPO


def is_dev_checkout() -> bool:
    return not str(SRC).startswith(str(HOME / "Library/Application Support/ccx"))


# ------------------------------------------------------------------ plugins

def setup_claude(source: str, quiet: bool = False) -> bool:
    cli = claude.desktop_cli()
    if not cli:
        say(False, "没找到 Claude 桌面版（或它自带的 Claude Code），跳过 Claude 插件", quiet)
        return False
    run([cli, "plugin", "uninstall", f"{LEGACY}@{LEGACY}"])
    run([cli, "plugin", "marketplace", "remove", LEGACY])
    code, out = run([cli, "plugin", "marketplace", "add", source])
    if code and "already" not in out.lower():
        run([cli, "plugin", "marketplace", "remove", "ccx"])
        code, out = run([cli, "plugin", "marketplace", "add", source])
    run([cli, "plugin", "marketplace", "update", "ccx"])
    code, out = run([cli, "plugin", "install", "ccx@ccx"])
    run([cli, "plugin", "update", "ccx@ccx"])
    ok = code == 0 or "already" in out.lower()
    say(ok, "Claude 插件已安装/更新（新开的会话生效）" if ok else f"Claude 插件安装失败：{out[-300:]}", quiet)
    return ok


def setup_codex(source: str, quiet: bool = False) -> bool:
    try:
        cli = codex.codex_bin()
    except RuntimeError:
        say(False, "没找到 Codex 桌面版，跳过 Codex 插件", quiet)
        return False
    run([cli, "plugin", "remove", f"{LEGACY}@{LEGACY}"])
    run([cli, "plugin", "marketplace", "remove", LEGACY])
    code, out = run([cli, "plugin", "marketplace", "add", source])
    if code and "already" not in out.lower():
        run([cli, "plugin", "marketplace", "remove", "ccx"])
        run([cli, "plugin", "marketplace", "add", source])
    run([cli, "plugin", "marketplace", "upgrade", "ccx"])
    code, out = run([cli, "plugin", "add", "ccx@ccx"])
    ok = code == 0
    say(ok, "Codex 插件已安装/更新（新开的线程生效）" if ok else f"Codex 插件安装失败：{out[-300:]}", quiet)
    return ok


# ------------------------------------------------------------------ menu bar

def _swift_hash() -> str:
    return hashlib.sha256((SRC / "menubar/main.swift").read_bytes() + __version__.encode()).hexdigest()[:16]


def build_menubar(quiet: bool = False, force: bool = False) -> bool:
    stamp = STATE_DIR / "menubar.hash"
    if not force and APP.exists() and stamp.exists() and stamp.read_text() == _swift_hash():
        return True
    if not shutil.which("swiftc"):
        say(False, "没有 swiftc（xcode-select --install 可装），跳过菜单栏图标", quiet)
        return False
    code, out = run(["/bin/sh", str(SRC / "menubar/build.sh"), str(APP), str(PLUGIN_BIN / "ccx"), __version__], 600)
    if code:
        say(False, f"菜单栏图标编译失败：{out[-300:]}", quiet)
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stamp.write_text(_swift_hash())
    restart_menubar()
    say(True, f"菜单栏图标 ⇄ 已就绪（{APP}）", quiet)
    return True


def restart_menubar():
    run(["pkill", "-x", "ccx"])
    run(["open", str(APP)])


def autostart(on: Optional[bool]) -> bool:
    """Start the menu bar app at login (a LaunchAgent). None = just report."""
    if on is None:
        return AGENT.exists()
    if on:
        AGENT.parent.mkdir(parents=True, exist_ok=True)
        with open(AGENT, "wb") as f:
            plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": ["/usr/bin/open", "-a", str(APP)],
                           "RunAtLoad": True}, f)
    else:
        AGENT.unlink(missing_ok=True)
    return on


# ------------------------------------------------------------------ commands

def setup(dev: bool = False, quiet: bool = False) -> int:
    if sys.version_info < (3, 9):
        print("✗ 需要 Python 3.9+")
        return 1
    dev = dev or is_dev_checkout()
    source = marketplace_source(dev)
    if not quiet:
        print(f"ccx {__version__} · 插件来源：{source}")
    ok_claude = setup_claude(source, quiet)
    ok_codex = setup_codex(source, quiet)
    LINK.parent.mkdir(parents=True, exist_ok=True)
    if LINK.is_symlink() or LINK.exists():
        LINK.unlink()
    LINK.symlink_to(PLUGIN_BIN / "ccx")
    say(True, f"终端命令 ccx → {LINK}", quiet)
    # The pre-rename menu bar app and state.
    run(["pkill", "-x", "ClaudeCodex"])
    shutil.rmtree(HOME / "Applications/ClaudeCodex.app", ignore_errors=True)
    if build_menubar(quiet, force=True):
        if not AGENT.exists():
            autostart(True)
    if ok_codex and codex.hooks_trusted() is False and not quiet:
        print("\n还差一步（只需一次）：在 Codex 里信任 ccx 的 hook，这样 Codex 那边也能随便说一句就自动同步。\n"
              "  Codex 桌面版：设置 → Hooks → 找到 ccx → 信任；或在终端版 Codex 里输入 /hooks。\n"
              "  不信任也能用：在 Codex 里说「接着 Claude 继续」即可。")
    return 0 if (ok_claude or ok_codex) else 1


def update(quiet: bool = False) -> int:
    before = __version__
    if (SRC / ".git").exists() and not is_dev_checkout():
        code, out = run(["git", "-C", str(SRC), "pull", "--ff-only", "--quiet"])
        if code:
            say(False, f"拉取更新失败：{out[-300:]}", quiet)
            return 1
    # Re-exec the (possibly new) code to refresh both apps' plugins and the menu bar.
    code, out = run([str(PLUGIN_BIN / "ccx"), "_refresh"] + (["--quiet"] if quiet else []), 900)
    if out:
        print(out)
    return code


def refresh(quiet: bool = False) -> int:
    source = marketplace_source(is_dev_checkout())
    setup_claude(source, quiet)
    setup_codex(source, quiet)
    build_menubar(quiet)
    say(True, f"ccx 已是最新：{__version__}", quiet)
    return 0


def doctor() -> int:
    rows = []
    rows.append((sys.version_info >= (3, 9), f"Python {sys.version.split()[0]}（{sys.executable}）"))
    cli = claude.desktop_cli()
    rows.append((bool(cli), f"Claude Code：{cli or '没找到 Claude 桌面版'}"))
    if cli:
        code, out = run([cli, "plugin", "list"])
        rows.append(("ccx@ccx" in out, "Claude 插件 ccx" + ("已安装" if "ccx@ccx" in out else "未安装（运行 ccx setup）")))
    try:
        cb = codex.codex_bin()
        rows.append((True, f"Codex：{cb}"))
        trusted = codex.hooks_trusted()
        rows.append((trusted is not None, "Codex 插件 ccx" + ("已安装" if trusted is not None else "未安装（运行 ccx setup）")))
        if trusted is not None:
            rows.append((bool(trusted), "Codex 自动同步 hook " + ("已信任" if trusted else
                         "未信任：Codex 设置 → Hooks 里信任 ccx（不信任时说「接着 Claude 继续」也能同步）")))
    except RuntimeError as e:
        rows.append((False, str(e)))
    running = run(["pgrep", "-x", "ccx"])[0] == 0
    rows.append((running, "菜单栏图标 " + ("运行中" if running else "未运行（open ~/Applications/ccx.app）")))
    rows.append((autostart(None), "登录时自动启动 " + ("开" if autostart(None) else "关")))
    rows.append((True, f"已配对的会话：{len(pairs.load())} 对 · 状态目录 {STATE_DIR}"))
    for ok, text in rows:
        say(ok, text)
    return 0 if all(ok for ok, _ in rows[:2]) else 1


def uninstall(purge: bool = False) -> int:
    cli = claude.desktop_cli()
    if cli:
        run([cli, "plugin", "uninstall", "ccx@ccx"])
        run([cli, "plugin", "marketplace", "remove", "ccx"])
    try:
        cb = codex.codex_bin()
        run([cb, "plugin", "remove", "ccx@ccx"])
        run([cb, "plugin", "marketplace", "remove", "ccx"])
    except RuntimeError:
        pass
    autostart(False)
    run(["pkill", "-x", "ccx"])
    shutil.rmtree(APP, ignore_errors=True)
    if LINK.is_symlink():
        LINK.unlink()
    if purge:
        shutil.rmtree(STATE_DIR, ignore_errors=True)
    print("✓ 已移除两边的插件、菜单栏图标和 ccx 命令" + ("，以及配对记录" if purge else "（配对记录保留在 ~/.ccx）"))
    return 0
