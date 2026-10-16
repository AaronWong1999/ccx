"""Small helpers shared by the Claude and Codex sides."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HOME = Path.home()
STATE_DIR = Path(os.environ.get("CCX_HOME", HOME / ".ccx"))
NAME = {"claude": "Claude", "codex": "Codex"}
OTHER = {"claude": "codex", "codex": "claude"}

# Every piece of text we inject is wrapped in this tag, so neither side ever
# forwards our own sync content back to the other.
TAG = "ccx-sync"


@dataclass
class Session:
    tool: str  # "claude" | "codex"
    id: str
    cwd: str
    mtime: float
    title: str = ""
    path: Optional[Path] = None

    @property
    def when(self) -> str:
        return datetime.fromtimestamp(self.mtime).strftime("%m-%d %H:%M")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + f"…（截断，原长 {len(text)} 字符）"


def first_line(text: str, n: int = 60) -> str:
    text = (text or "").strip()
    return text.splitlines()[0][:n] if text else ""


def real(path: str) -> str:
    return os.path.realpath(path).rstrip("/") if path else ""


def same_dir(a: str, b: str) -> bool:
    return bool(a and b) and real(a) == real(b)


def is_injected(text: str) -> bool:
    """Text the apps inject into a user turn (environment, reminders, commands)."""
    t = (text or "").lstrip()
    return t.startswith("<") or t.startswith("# AGENTS.md") or t.startswith("# Context from my IDE")


def which(name: str, *candidates: str) -> Optional[str]:
    """Find a binary even when launched by a GUI app with a minimal PATH."""
    for c in candidates:
        if c and os.access(c, os.X_OK):
            return c
    found = shutil.which(name)
    if found:
        return found
    for d in ("/opt/homebrew/bin", "/usr/local/bin", str(HOME / ".local/bin"), "/usr/bin"):
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    return None


def _git(cwd: str, *args: str) -> str:
    if not cwd or not os.path.isdir(cwd):
        return ""
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def git_snapshot(cwd: str) -> str:
    out = _git(cwd, "status", "--short", "--branch")
    return clip(out, 1500) if out else "（不是 git 仓库，或工作区干净）"


def git_branch(cwd: str) -> str:
    return _git(cwd, "branch", "--show-current") or "HEAD"


def folder_note(here: str, there: str, there_tool: str) -> str:
    """Explain a working-folder mismatch between two paired sessions ('' if same)."""
    if not here or not there or same_dir(here, there):
        return ""
    if not os.path.isdir(there):
        return (f"注意：{NAME[there_tool]} 那个会话的工作目录 {there} 在这台电脑上已经不存在了，"
                f"你现在在 {here}。下面的进展只能当参考。")
    same_repo = _git(here, "rev-parse", "--git-common-dir") and \
        real(os.path.join(here, _git(here, "rev-parse", "--git-common-dir"))) == \
        real(os.path.join(there, _git(there, "rev-parse", "--git-common-dir")))
    if same_repo:
        return (f"注意：两边是同一个 git 仓库的不同目录（worktree）。{NAME[there_tool]} 在 {there}"
                f"（分支 {git_branch(there)}），你现在在 {here}（分支 {git_branch(here)}）。"
                f"那边的改动不一定在这边的文件里，动手前先确认，必要时请用户切换到那个目录。\n"
                f"{NAME[there_tool]} 那边的 git 状态：\n```\n{git_snapshot(there)}\n```")
    return (f"注意：{NAME[there_tool]} 那个会话是在另一个目录 {there} 里做的，你现在在 {here}。"
            f"那边的改动在 {there} 里，不在当前目录。先告诉用户这一点，问清是切换到 {there} 继续，"
            f"还是只把它当参考；不要擅自去改另一个目录。")
