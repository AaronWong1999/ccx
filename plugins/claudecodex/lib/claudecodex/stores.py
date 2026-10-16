"""Read and write Claude Code / Codex session files on this machine."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

HOME = Path.home()
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", HOME / ".claude"))
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
CLAUDE_PROJECTS = CLAUDE_HOME / "projects"
CODEX_SESSIONS = CODEX_HOME / "sessions"

# Field we stamp on every record we write into a Claude session, so a later
# sync can tell our records apart from turns the user added in Claude.
MARKER = "ccxImported"

TOOL_OUTPUT_CHARS = 400
TOOL_INPUT_CHARS = 300

Turn = Tuple[str, str]  # (role, text)


@dataclass
class Session:
    tool: str  # "claude" | "codex"
    id: str
    path: Path
    cwd: str
    mtime: float
    title: str = ""

    @property
    def when(self) -> str:
        return datetime.fromtimestamp(self.mtime).strftime("%m-%d %H:%M")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n] + f"…（截断，原长 {len(text)} 字符）"


def same_dir(a: str, b: str) -> bool:
    return os.path.realpath(a).rstrip("/") == os.path.realpath(b).rstrip("/")


def first_line(text: str, n: int = 60) -> str:
    text = text.strip()
    return text.splitlines()[0][:n] if text else ""


def which(name: str, *candidates: str) -> Optional[str]:
    """Find a binary even when launched from a GUI app with a minimal PATH."""
    for c in candidates:
        if c and os.access(c, os.X_OK):
            return c
    found = shutil.which(name)
    if found:
        return found
    for d in ("/opt/homebrew/bin", "/usr/local/bin", str(HOME / ".local/bin")):
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    return None


def codex_bin() -> str:
    # The desktop app bundles a CLI that matches its own session format and models.
    b = which("codex", "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
              "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex")
    if not b:
        raise RuntimeError("找不到 Codex（既没有 Codex 桌面版，也没有 codex 命令）")
    return b


# ---------------------------------------------------------------- Claude Code

def claude_project_dir(cwd: str) -> Path:
    return CLAUDE_PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))


def _claude_records(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _claude_meta(path: Path) -> Tuple[str, str]:
    """Return (cwd, title) of a Claude session file."""
    cwd, title, first_prompt = "", "", ""
    for d in _claude_records(path):
        cwd = cwd or d.get("cwd", "")
        if d.get("type") == "custom-title":
            title = d.get("customTitle") or d.get("title") or title
        if not first_prompt and d.get("type") == "user" and not d.get("isMeta"):
            c = (d.get("message") or {}).get("content")
            if isinstance(c, str) and not c.startswith("<"):
                first_prompt = c
    return cwd, first_line(title or first_prompt)


def claude_sessions(cwd: Optional[str] = None) -> List[Session]:
    if cwd:
        dirs = [claude_project_dir(cwd)]
    else:
        dirs = [p for p in CLAUDE_PROJECTS.iterdir() if p.is_dir()] if CLAUDE_PROJECTS.is_dir() else []
    out = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.jsonl"):
            s_cwd, title = _claude_meta(p)
            if cwd and s_cwd and not same_dir(s_cwd, cwd):
                continue
            if not title:  # empty / metadata-only sessions
                continue
            out.append(Session("claude", p.stem, p, s_cwd or cwd or "", p.stat().st_mtime, title))
    return sorted(out, key=lambda s: s.mtime, reverse=True)


def claude_session(cwd: str, sid: str) -> Optional[Session]:
    p = claude_project_dir(cwd) / f"{sid}.jsonl"
    if not p.exists():
        return None
    s_cwd, title = _claude_meta(p)
    return Session("claude", sid, p, s_cwd or cwd, p.stat().st_mtime, title)


def claude_has_own_turns(path: Path) -> bool:
    """True if the user added conversation turns that we did not write."""
    for d in _claude_records(path):
        if d.get("type") in ("user", "assistant") and not d.get(MARKER):
            return True
    return False


def claude_version() -> str:
    b = which("claude", str(HOME / ".local/bin/claude"))
    try:
        return subprocess.run([b, "--version"], capture_output=True, text=True, timeout=10).stdout.split()[0]
    except Exception:
        return "2.1.0"


def git_branch(cwd: str) -> str:
    r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True)
    return r.stdout.strip() or "HEAD"


def git_snapshot(cwd: str) -> str:
    r = subprocess.run(["git", "-C", cwd, "status", "--short", "--branch"], capture_output=True, text=True)
    if r.returncode != 0:
        return "（不是 git 仓库）"
    return clip(r.stdout, 1500) or "（工作区干净）"


def write_claude_session(cwd: str, turns: List[Turn], title: str, sid: Optional[str] = None) -> Session:
    """Write (or overwrite, when sid is given) a resumable Claude Code session.

    Roles must alternate user/assistant starting with user.
    """
    sid = sid or str(uuid.uuid4())
    d = claude_project_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sid}.jsonl"
    base = {
        "isSidechain": False,
        "userType": "external",
        "cwd": cwd,
        "sessionId": sid,
        "version": claude_version(),
        "gitBranch": git_branch(cwd),
        MARKER: True,
    }
    parent = None
    tmp = path.with_suffix(".ccx-tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for role, text in turns:
            u = str(uuid.uuid4())
            if role == "user":
                msg = {"role": "user", "content": text}
            else:
                msg = {
                    "id": f"msg_ccx_{uuid.uuid4().hex[:20]}",
                    "type": "message",
                    "role": "assistant",
                    "model": "<synthetic>",
                    "content": [{"type": "text", "text": text}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                }
            rec = {"parentUuid": parent, **base, "type": role, "message": msg, "uuid": u, "timestamp": now_iso()}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            parent = u
        f.write(json.dumps({"type": "custom-title", "customTitle": title, "sessionId": sid}, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return Session("claude", sid, path, cwd, path.stat().st_mtime, title)


def copy_claude_session_with_new_id(src: Path) -> Path:
    """Copy a Claude session under a fresh id next to the original."""
    nid = str(uuid.uuid4())
    dst = src.parent / f"{nid}.jsonl"
    with open(src, encoding="utf-8", errors="replace") as f, open(dst, "w", encoding="utf-8") as g:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "sessionId" in r:
                r["sessionId"] = nid
            g.write(json.dumps(r, ensure_ascii=False) + "\n")
    return dst


# ---------------------------------------------------------------------- Codex

def _open_rollout(path: Path):
    if path.suffix != ".zst":
        return open(path, encoding="utf-8", errors="replace")
    try:
        from compression import zstd  # Python 3.14+
        return zstd.open(path, "rt", encoding="utf-8", errors="replace")
    except ImportError:
        z = which("zstd")
        if not z:
            raise RuntimeError("读取 Codex 会话需要 Python 3.14+ 或 zstd 命令（brew install zstd）")
        data = subprocess.run([z, "-dc", str(path)], capture_output=True, check=True).stdout
        return io.StringIO(data.decode("utf-8", "replace"))


def _rollout_records(path: Path):
    with _open_rollout(path) as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _is_injected(text: str) -> bool:
    t = text.lstrip()
    return t.startswith("<") or t.startswith("# AGENTS.md") or t.startswith("# Context from my IDE")


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(c["text"] for c in content or [] if isinstance(c, dict) and c.get("text"))


def _codex_head(path: Path) -> Tuple[dict, str]:
    """Return (session_meta payload, title) reading only as far as needed."""
    meta, title = {}, ""
    for d in _rollout_records(path):
        p = d.get("payload") or {}
        if d.get("type") == "session_meta":
            meta = p
        elif d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
            t = _content_text(p.get("content"))
            if t.strip() and not _is_injected(t):
                title = first_line(t)
                break
    return meta, title


def codex_sessions(cwd: Optional[str] = None, limit: int = 400) -> List[Session]:
    if not CODEX_SESSIONS.is_dir():
        return []
    files = sorted(CODEX_SESSIONS.rglob("rollout-*.jsonl*"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[:limit]:
        meta, title = _codex_head(p)
        s_cwd = meta.get("cwd", "")
        if cwd and not (s_cwd and same_dir(s_cwd, cwd)):
            continue
        if not title:
            continue
        sid = meta.get("id") or meta.get("session_id") or p.stem
        out.append(Session("codex", sid, p, s_cwd, p.stat().st_mtime, title))
    return out


def codex_session(sid: str) -> Optional[Session]:
    for p in CODEX_SESSIONS.rglob(f"rollout-*{sid}*.jsonl*"):
        meta, title = _codex_head(p)
        return Session("codex", sid, p, meta.get("cwd", ""), p.stat().st_mtime, title)
    return None


def codex_turns(path: Path) -> List[Turn]:
    """Condense a Codex rollout into alternating (user, assistant) text turns."""
    turns: list = []  # [role, [chunks]]

    def add(role: str, text: str):
        if not text.strip():
            return
        if turns and turns[-1][0] == role:
            turns[-1][1].append(text)
        else:
            turns.append([role, [text]])

    for d in _rollout_records(path):
        if d.get("type") != "response_item":
            continue
        p = d.get("payload") or {}
        t = p.get("type")
        if t == "message":
            text = _content_text(p.get("content"))
            if p.get("role") == "user" and not _is_injected(text):
                add("user", text)
            elif p.get("role") == "assistant":
                add("assistant", text)
        elif t in ("function_call", "custom_tool_call", "local_shell_call"):
            name = p.get("name") or t
            if p.get("namespace"):
                name = f"{p['namespace']}.{name}"
            args = p.get("arguments") or p.get("input") or p.get("action") or ""
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            add("assistant", f"[工具调用 {name}]\n```\n{clip(args, TOOL_INPUT_CHARS)}\n```")
        elif t in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            out = p.get("output")
            out = out if isinstance(out, str) else _content_text(out)
            if out.strip():
                add("assistant", f"[工具结果]\n```\n{clip(out, TOOL_OUTPUT_CHARS)}\n```")

    while turns and turns[0][0] != "user":
        turns.pop(0)
    return [(role, "\n\n".join(chunks)) for role, chunks in turns]


def codex_user_turn_count(path: Path) -> int:
    n = 0
    for d in _rollout_records(path):
        p = d.get("payload") or {}
        if d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
            if not _is_injected(_content_text(p.get("content"))):
                n += 1
    return n
