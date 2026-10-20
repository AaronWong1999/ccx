"""Claude Code sessions: plain JSONL files under ~/.claude/projects/<project>/."""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .common import (
    HOME, PLAN, STATE_DIR, TAG, Session, clip, first_line, git_branch, image_line, now_iso, real,
    same_dir, user_text, which,
)

CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", HOME / ".claude"))
PROJECTS = CLAUDE_HOME / "projects"
DESKTOP_CLI_GLOB = str(HOME / "Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")

# Stamped on every record we write, so those records are never sent back to Codex.
MARKER = "ccxImported"
# Our own MCP tools (current and pre-rename names); their calls are never forwarded.
SELF_TOOL = re.compile(r"(ccx|claudecodex)__(continue_here|list_sessions|send_current_session|import_session)")

Unit = Optional[Tuple[str, str]]  # (role, text) to forward, or None


def project_dir(cwd: str) -> Path:
    return PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", real(cwd))


# ------------------------------------------------------------ listing (cached)

_CACHE = STATE_DIR / "claude-meta-v2.json"


def _load_cache() -> Dict[str, list]:
    try:
        return json.loads(_CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _meta(path: Path, cache: Dict[str, list]) -> Tuple[str, str, bool]:
    """(cwd, title, written-by-ccx) of a session file, cached by size+mtime."""
    st = path.stat()
    key = str(path)
    hit = cache.get(key)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime:
        return hit[2], hit[3], hit[4]
    cwds, title, prompt, ours = [], "", "", False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            c = d.get("cwd")
            if c and (not cwds or cwds[-1] != c):
                cwds.append(c)
            ours = ours or bool(d.get(MARKER))
            if d.get("type") == "custom-title":
                title = d.get("customTitle") or d.get("title") or title
            elif not prompt and d.get("type") == "user" and not d.get("isMeta"):
                c = (d.get("message") or {}).get("content")
                if isinstance(c, list):
                    c = next((x.get("text", "") for x in c if x.get("type") == "text"), "")
                if isinstance(c, str) and user_text(c):
                    prompt = user_text(c)
    # Each record's cwd is wherever the shell was at that moment (a sub-folder, or
    # the folder the session started in before it was moved). The session belongs
    # to the project whose folder it is filed under; otherwise use the latest cwd.
    cwd = next((c for c in reversed(cwds) if project_dir(c).name == path.parent.name), cwds[-1] if cwds else "")
    label = first_line(title or prompt)
    cache[key] = [st.st_size, st.st_mtime, cwd, label, ours]
    return cwd, label, ours


DESKTOP_INDEX = HOME / "Library/Application Support/Claude/claude-code-sessions"


def archived_ids() -> set:
    """Sessions archived in the Claude desktop app (the session files don't record it)."""
    out = set()
    for f in DESKTOP_INDEX.glob("*/*/local_*.json"):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d.get("isArchived") and d.get("cliSessionId"):
            out.add(d["cliSessionId"])
    return out


def sessions(cwd: Optional[str] = None, query: Optional[str] = None) -> List[Session]:
    """Claude sessions, newest first; limited to a project folder and/or a title search.
    Sessions archived in the desktop app are left out."""
    if not PROJECTS.is_dir():
        return []
    hidden = archived_ids()
    files = list(project_dir(cwd).glob("*.jsonl")) if cwd else list(PROJECTS.glob("*/*.jsonl"))
    cache = _load_cache()
    out = []
    for p in files:
        try:
            s_cwd, title, _ = _meta(p, cache)
        except OSError:
            continue
        if not title or p.stem in hidden or (cwd and s_cwd and not same_dir(s_cwd, cwd)):
            continue
        if query and not matches(query, title):
            continue
        out.append(Session("claude", p.stem, s_cwd or cwd or "", p.stat().st_mtime, title, p))
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    except OSError:
        pass
    return sorted(out, key=lambda s: s.mtime, reverse=True)


def find(sid: str) -> Optional[Session]:
    """A Claude session by id (or unique id prefix), in any project folder."""
    hits = glob.glob(str(PROJECTS / "*" / f"{sid}*.jsonl"))
    if len(hits) != 1:
        return None
    p = Path(hits[0])
    s_cwd, title, _ = _meta(p, {})
    return Session("claude", p.stem, s_cwd, p.stat().st_mtime, title, p)


def matches(query: str, title: str) -> bool:
    """Loose title match: every word of the query appears in the title."""
    q, t = query.lower().strip(), title.lower()
    if not q:
        return True
    words = [w for w in re.split(r"[\s，。,.「」『』“”\"'：:·•|/\-]+", q) if w]
    return q in t or all(w in t for w in words)


# ------------------------------------------------------------------- units

def units(path: Path, include_imported: bool = False) -> List[Unit]:
    """One entry per user/assistant record (the cursor counts these).

    Records ccx wrote from a Codex thread are None by default, so incremental sync
    never sends them back; include_imported renders them too (for a full
    'continue from' and for reading history)."""
    out: List[Unit] = []
    skip_ids = set()
    # The desktop app caches pasted images as <tmp>/claude-<uid>/<project>/<session>/images/<paste id>.<ext>
    images = Path(os.environ.get("CLAUDE_CODE_TMPDIR", "/private/tmp")) / f"claude-{os.getuid()}" \
        / path.parent.name / path.stem / "images"
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") not in ("user", "assistant"):
                continue
            # A compaction summary restates earlier records; sending it would repeat them.
            d["_images"] = images
            if ((d.get(MARKER) and not include_imported) or d.get("isMeta") or d.get("isSidechain")
                    or d.get("isCompactSummary")):
                out.append(None)
            else:
                out.append(_render(d, skip_ids))
    return out


def _render(d: dict, skip_ids: set) -> Unit:
    content = (d.get("message") or {}).get("content")
    if isinstance(content, str):
        typed = user_text(content) if d["type"] == "user" else ""
        return ("user", typed) if typed and TAG not in typed else None
    parts, role = [], ("user" if d["type"] == "user" else "assistant")
    paste_ids = iter(d.get("imagePasteIds") or [])
    for c in content or []:
        t = c.get("type")
        if t == "text":
            text = user_text(c.get("text", "")) if role == "user" else c.get("text", "")
            if text.strip() and TAG not in text:
                parts.append(text)
        elif t == "image" and role == "user":
            pid = next(paste_ids, None)
            cached = next(iter(sorted(d["_images"].glob(f"{pid}.*"))), None) if pid is not None and d.get("_images") else None
            parts.append(image_line(str(cached) if cached else (c.get("source") or {}).get("url")))
        elif t == "tool_use":
            if SELF_TOOL.search(c.get("name", "")):
                skip_ids.add(c.get("id"))
                continue
            todos = (c.get("input") or {}).get("todos") if c.get("name") == "TodoWrite" else None
            if isinstance(todos, list):
                mark = {"completed": "[x]", "in_progress": "[~]"}
                parts.append(PLAN + "\n" + "\n".join(
                    f"- {mark.get(t.get('status'), '[ ]')} {t.get('content') or t.get('activeForm') or ''}" for t in todos))
            else:
                parts.append(f"[tool {c.get('name')}] {clip(json.dumps(c.get('input'), ensure_ascii=False), 300)}")
            role = "assistant"
        elif t == "tool_result":
            if c.get("tool_use_id") in skip_ids:
                continue
            r = c.get("content")
            if isinstance(r, list):
                r = "\n".join(x.get("text", "") for x in r if isinstance(x, dict))
            if (r or "").strip() and TAG not in r:
                parts.append(f"[result] {clip(r, 400)}")
            role = "assistant"  # results read as part of the agent's work
    return (role, "\n".join(parts)) if parts else None


# ------------------------------------------------------------------- goal

def goal(path: Path) -> Optional[dict]:
    """The conversation's /goal as Claude Code recorded it: {"objective", "status"}
    with status "active" or "complete"; None if never set or cleared."""
    g = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"goal' not in line and "Goal cleared" not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            a = d.get("attachment") or {}
            if a.get("type") == "goal_status" and a.get("condition"):
                g = {"objective": a["condition"], "status": "complete" if a.get("met") else "active"}
            elif d.get("type") == "system" and "Goal cleared" in str(d.get("content") or ""):
                g = None  # "/goal clear", or Claude Code cleared it after an error
    return g


# ------------------------------------------------------------- cost of resuming

def context_state(path: Path) -> Tuple[int, float]:
    """(tokens in the conversation's context at its last model call, unix time of
    its last activity). Reads only the end of the file."""
    from datetime import datetime
    size = path.stat().st_size
    with open(path, "rb") as f:
        f.seek(max(0, size - 4_000_000))
        tail = f.read().decode("utf-8", "replace").splitlines()
    tokens, last = 0, 0.0
    for line in reversed(tail):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        # Idle time counts from the last conversation turn; opening a session can
        # append metadata records that don't refresh the prompt cache.
        if not last and d.get("timestamp") and d.get("type") in ("user", "assistant"):
            try:
                last = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        # A compaction (manual, auto or Claude Code's idle compaction) after the last
        # model call shrank the context: what the next message reads is its result.
        if not tokens and d.get("subtype") == "compact_boundary":
            tokens = (d.get("compactMetadata") or {}).get("postTokens") or 1
        u = (d.get("message") or {}).get("usage") if d.get("type") == "assistant" else None
        if u and not tokens:
            tokens = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
        if tokens and last:
            break
    return tokens, last or path.stat().st_mtime


# ------------------------------------------------------------------ writing

def desktop_cli() -> Optional[str]:
    """The Claude Code CLI bundled with the Claude desktop app (newest), else any on PATH."""
    bundled = sorted(glob.glob(DESKTOP_CLI_GLOB), key=os.path.getmtime, reverse=True)
    return which("claude", *bundled, str(HOME / ".local/bin/claude"))


_VERSION: Optional[str] = None


def version() -> str:
    global _VERSION
    if _VERSION is None:
        try:
            _VERSION = subprocess.run([desktop_cli(), "--version"], capture_output=True, text=True,
                                      timeout=10).stdout.split()[0]
        except Exception:
            _VERSION = "2.1.0"
    return _VERSION


def write_session(cwd: str, turns: List[Tuple[str, str]], title: str) -> Session:
    """Write a resumable Claude Code session from alternating (role, text) turns."""
    sid = str(uuid.uuid4())
    d = project_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sid}.jsonl"
    base = {"isSidechain": False, "userType": "external", "cwd": cwd, "sessionId": sid,
            "version": version(), "gitBranch": git_branch(cwd), MARKER: True}
    parent = None
    tmp = path.with_suffix(".ccx-tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for role, text in turns:
            u = str(uuid.uuid4())
            if role == "user":
                msg = {"role": "user", "content": text}
            else:
                msg = {"id": f"msg_ccx_{uuid.uuid4().hex[:20]}", "type": "message", "role": "assistant",
                       "model": "<synthetic>", "content": [{"type": "text", "text": text}],
                       "stop_reason": "end_turn", "stop_sequence": None,
                       "usage": {"input_tokens": 0, "output_tokens": 0}}
            rec = {"parentUuid": parent, **base, "type": role, "message": msg, "uuid": u, "timestamp": now_iso()}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            parent = u
        f.write(json.dumps({"type": "custom-title", "customTitle": title, "sessionId": sid}, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return Session("claude", sid, cwd, path.stat().st_mtime, title, path)


def copy_with_new_id(src: Path, cwd: Optional[str] = None) -> Path:
    """Copy a session under a fresh id. With `cwd`, every record's cwd is set to it
    and the copy is filed under that project: Codex's importer skips sessions whose
    recorded folder looks temporary (e.g. a Claude scratch workspace) or doesn't
    match, and it imports each source file only once."""
    nid = str(uuid.uuid4())
    folder = project_dir(cwd) if cwd else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"{nid}.jsonl"
    with open(src, encoding="utf-8", errors="replace") as f, open(dst, "w", encoding="utf-8") as g:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "sessionId" in r:
                r["sessionId"] = nid
            if cwd and "cwd" in r:
                r["cwd"] = cwd
            g.write(json.dumps(r, ensure_ascii=False) + "\n")
    return dst
