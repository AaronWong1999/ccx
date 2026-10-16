"""Read and write Claude Code / Codex session files on this machine."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CLAUDE_PROJECTS = CLAUDE_HOME / "projects"
CODEX_SESSIONS = CODEX_HOME / "sessions"

TOOL_OUTPUT_CHARS = 400
TOOL_INPUT_CHARS = 300


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


# ---------------------------------------------------------------- Claude Code

def claude_project_dir(cwd: str) -> Path:
    return CLAUDE_PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))


def _claude_meta(path: Path) -> tuple[str, str]:
    """Return (cwd, title) by scanning a Claude session file."""
    cwd, title, first_prompt = "", "", ""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            cwd = cwd or d.get("cwd", "")
            if d.get("type") == "custom-title":
                title = d.get("customTitle") or d.get("title") or title
            if not first_prompt and d.get("type") == "user" and not d.get("isMeta"):
                c = (d.get("message") or {}).get("content")
                if isinstance(c, str) and not c.startswith("<"):
                    first_prompt = c
    label = (title or first_prompt).strip()
    return cwd, label.splitlines()[0][:60] if label else ""


def claude_sessions(cwd: str | None = None) -> list[Session]:
    dirs = [claude_project_dir(cwd)] if cwd else [p for p in CLAUDE_PROJECTS.iterdir() if p.is_dir()]
    out = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.jsonl"):
            s_cwd, title = _claude_meta(p)
            if cwd and s_cwd and not same_dir(s_cwd, cwd):
                continue
            out.append(Session("claude", p.stem, p, s_cwd or cwd or "", p.stat().st_mtime, title))
    return sorted(out, key=lambda s: s.mtime, reverse=True)


def claude_version() -> str:
    try:
        return subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10).stdout.split()[0]
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


def write_claude_session(cwd: str, turns: list[tuple[str, str]], title: str) -> Session:
    """Write a resumable Claude Code session from (role, text) turns.

    Roles must alternate user/assistant starting with user.
    """
    sid = str(uuid.uuid4())
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
    }
    parent = None
    with open(path, "w", encoding="utf-8") as f:
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
    return Session("claude", sid, path, cwd, path.stat().st_mtime, title)


# ---------------------------------------------------------------------- Codex

def _open_rollout(path: Path):
    if path.suffix == ".zst":
        try:
            from compression import zstd  # Python 3.14+
            return zstd.open(path, "rt", encoding="utf-8", errors="replace")
        except ImportError:
            import io
            data = subprocess.run(["zstd", "-dc", str(path)], capture_output=True, check=True).stdout
            return io.StringIO(data.decode("utf-8", "replace"))
    return open(path, encoding="utf-8", errors="replace")


def _codex_meta(path: Path) -> dict:
    with _open_rollout(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "session_meta":
                return d.get("payload") or {}
    return {}


def codex_sessions(cwd: str | None = None, limit: int = 400) -> list[Session]:
    if not CODEX_SESSIONS.is_dir():
        return []
    files = sorted(
        (p for p in CODEX_SESSIONS.rglob("rollout-*.jsonl*")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    out = []
    for p in files:
        meta = _codex_meta(p)
        s_cwd = meta.get("cwd", "")
        if cwd and not (s_cwd and same_dir(s_cwd, cwd)):
            continue
        sid = meta.get("id") or meta.get("session_id") or p.stem
        out.append(Session("codex", sid, p, s_cwd, p.stat().st_mtime, _codex_title(p)))
    return out


def _is_injected(text: str) -> bool:
    t = text.lstrip()
    return t.startswith("<") or t.startswith("# AGENTS.md") or t.startswith("# Context from my IDE")


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if isinstance(c, dict) and c.get("text"):
            parts.append(c["text"])
    return "\n".join(parts)


def _codex_title(path: Path) -> str:
    with _open_rollout(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            p = d.get("payload") or {}
            if d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
                t = _content_text(p.get("content"))
                if t.strip() and not _is_injected(t):
                    return t.strip().splitlines()[0][:60]
    return ""


def codex_turns(path: Path) -> list[tuple[str, str]]:
    """Condense a Codex rollout into alternating (user, assistant) text turns."""
    turns: list[list] = []  # [role, [chunks]]

    def add(role: str, text: str):
        if not text.strip():
            return
        if turns and turns[-1][0] == role:
            turns[-1][1].append(text)
        else:
            turns.append([role, [text]])

    with _open_rollout(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
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
                out = _content_text(out) if not isinstance(out, str) else out
                if out.strip():
                    add("assistant", f"[工具结果]\n```\n{clip(out, TOOL_OUTPUT_CHARS)}\n```")

    while turns and turns[0][0] != "user":
        turns.pop(0)
    return [(role, "\n\n".join(chunks)) for role, chunks in turns]
