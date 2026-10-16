"""Small helpers shared by the Claude and Codex sides."""

from __future__ import annotations

import os
import re
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


# Units carrying a task list start with this, so the latest one is always kept.
PLAN = "[task list]"


def clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + f"… (truncated, {len(text)} chars)"


def first_line(text: str, n: int = 60) -> str:
    text = (text or "").strip()
    return text.splitlines()[0][:n] if text else ""


def real(path: str) -> str:
    return os.path.realpath(path).rstrip("/") if path else ""


def same_dir(a: str, b: str) -> bool:
    return bool(a and b) and real(a) == real(b)


_RELAYED = re.compile(r"<cross-session-message[^>]*>(.*?)</cross-session-message>", re.S)
_LEADING_TAG = re.compile(r"\A\s*<([A-Za-z][\w-]*)[^>]*>.*?</\1>\s*", re.S)


def user_text(text: str) -> str:
    """What the person actually typed: drop the tagged blocks (reminders,
    environment context) the apps prepend to a user turn. '' if nothing is left."""
    t = _RELAYED.sub(lambda m: m.group(1), text or "")  # a message relayed from another session
    while True:
        m = _LEADING_TAG.match(t)
        if not m:
            break
        t = t[m.end():]
    t = t.strip()
    if t.startswith("<") or t.startswith("# AGENTS.md") or t.startswith("# Context from my IDE"):
        return ""
    return t


def is_injected(text: str) -> bool:
    """True when a user turn holds nothing the person typed."""
    return not user_text(text)


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
    return clip(out, 1500) if out else "(not a git repository, or nothing to report)"


def git_branch(cwd: str) -> str:
    return _git(cwd, "branch", "--show-current") or "HEAD"


def folder_note(here: str, there: str, there_tool: str) -> str:
    """Explain a working-folder mismatch between two paired sessions ('' if same)."""
    if not here or not there or same_dir(here, there):
        return ""
    if not os.path.isdir(there):
        return (f"NOTE: the {NAME[there_tool]} session worked in {there}, which no longer exists on this Mac. "
                f"You are in {here}. Treat the progress below as reference only.")
    common_here, common_there = _git(here, "rev-parse", "--git-common-dir"), _git(there, "rev-parse", "--git-common-dir")
    if common_here and common_there and real(os.path.join(here, common_here)) == real(os.path.join(there, common_there)):
        return (f"NOTE: both sides use the same git repository but different folders (worktrees). "
                f"{NAME[there_tool]} worked in {there} (branch {git_branch(there)}); you are in {here} "
                f"(branch {git_branch(here)}). Its changes may not be in your files: check before editing, "
                f"and ask the user whether to switch to that folder.\n"
                f"git status over there:\n```\n{git_snapshot(there)}\n```")
    return (f"NOTE: the {NAME[there_tool]} session worked in a different folder, {there}; you are in {here}. "
            f"Its changes are in {there}, not here. Tell the user and ask whether to continue in {there} "
            f"or to use this only as reference. Do not edit the other folder on your own.")
