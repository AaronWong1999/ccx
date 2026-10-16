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

SETTINGS = STATE_DIR / "settings.json"
DEFAULTS = {"language": "en", "warn_long_resume": True}


def setting(key: str):
    try:
        import json as _json
        return _json.loads(SETTINGS.read_text()).get(key, DEFAULTS.get(key))
    except (OSError, ValueError):
        return DEFAULTS.get(key)


def set_setting(key: str, value):
    import json as _json
    try:
        d = _json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        d = {}
    d[key] = value
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(_json.dumps(d, ensure_ascii=False, indent=1))


def L(en: str, zh: str) -> str:
    """Text in the language chosen in the menu bar app."""
    return zh if setting("language") == "zh" else en


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


# Tags the apps wrap around text the person did write: keep what's inside.
_KEEP_INNER = ("pasted_content", "cross-session-message", "command-name", "command-args")
# Tags the apps inject on their own: drop them with their contents.
_DROP = ("system-reminder", "environment_context", "user_instructions", "local-command-stdout",
         "local-command-stderr", "local-command-caveat", "command-message", "app-context",
         "external_codex_apps_open_page", "turn_aborted", "permissions instructions",
         "ide_opened_file", "ide_selection", "collaboration_mode", "skills_instructions")


def user_text(text: str) -> str:
    """What the person actually typed or pasted: injected blocks (reminders,
    environment) removed, wrapper tags around their own text unwrapped.
    Unknown tags are kept rather than risk dropping the person's words."""
    t = text or ""
    for tag in _DROP:
        t = re.sub(rf"<{re.escape(tag)}(\s[^>]*)?>.*?</{re.escape(tag)}(\s[^>]*)?>", "", t, flags=re.S)
    for tag in _KEEP_INNER:
        # (closing tags may carry attributes too: </pasted_content id="0320">)
        t = re.sub(rf"<{re.escape(tag)}(\s[^>]*)?>(.*?)</{re.escape(tag)}(\s[^>]*)?>", lambda m: m.group(2).strip() + " ", t, flags=re.S)
    t = re.sub(r"\A(/[\w:-]+)\s+", r"\1 ", t.strip())  # "/goal" + its args on one line
    if t.startswith("# AGENTS.md") or t.startswith("# Context from my IDE") or t.startswith("<INSTRUCTIONS>"):
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


def copy_to_clipboard(text: str):
    """pbcopy decodes its input using __CF_USER_TEXT_ENCODING; apps may start us
    without it (MacRoman then), which garbles non-ASCII text. Force UTF-8."""
    env = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
           "__CF_USER_TEXT_ENCODING": f"0x{os.getuid():X}:0x8000100:0x8000100"}  # UTF-8 for pbcopy
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=env, check=False)


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
