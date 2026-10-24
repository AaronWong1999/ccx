"""Cloud sessions: Claude Code on the web and Codex Cloud tasks.

Read only, and only through each app's own CLI with its own sign-in; ccx never
handles credentials or calls a service itself:
- Claude: the CLI's `list_cloud_sessions` / `get_cloud_session_transcript`
  requests, which it answers for the program that started it, over stdin.
- Codex: `codex cloud list --json` and `codex cloud diff` (the task's code change;
  the CLI does not expose a task's messages).

Listing reads titles only. A conversation is read when the user picks it, into a
local mirror (a Claude-format JSONL in ccx's own folder, never in ~/.claude), and
afterwards only its new pages. When a CLI can't read the cloud (signed out, an old
version, or started from inside a Claude Code session), cloud rows are left out.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import select
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .common import HOME, STATE_DIR, Session, clip

CLOUD_DIR = STATE_DIR / "cloud"
CLAUDE_MIRRORS = CLOUD_DIR / "claude"
LIST_TTL = 180          # seconds a cloud listing is reused
LIST_TIMEOUT = 20
PAGE_TIMEOUT = 30
DIFF_BUDGET = 40_000    # chars of a Codex Cloud diff carried over
CONVERSATION = ("user", "assistant", "system", "attachment")


def is_claude(sid: str) -> bool:
    return (sid or "").startswith("session_")


def is_codex(sid: str) -> bool:
    return (sid or "").startswith("task_")


def _ts(v) -> float:
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e12 else 1)
    # Python 3.9's fromisoformat takes neither "Z" nor more than six fraction digits.
    s = re.sub(r"(\.\d{6})\d+", r"\1", str(v)).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return 0.0


# ------------------------------------------------------------------ caches

def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write(path: Path, d: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False))
    os.replace(tmp, path)


def _cached(name: str, fetch, max_age: float) -> Tuple[List[dict], Optional[str]]:
    """(items, reason they are unavailable) from a listing cache, refreshed when older than max_age."""
    path = CLOUD_DIR / f"{name}.json"
    c = _read(path)
    # A failed read is retried sooner: after signing in, cloud sessions appear on the next menu open.
    if c and time.time() - c.get("at", 0) < (min(max_age, 30) if c.get("reason") else max_age):
        return c.get("items", []), c.get("reason")
    try:
        items, reason = fetch(), None
    except Unavailable as e:
        items, reason = [], str(e)
    except Exception as e:  # a CLI that changed its output: no cloud rows, never a broken menu
        items, reason = [], f"error: {e}"
    _write(path, {"at": time.time(), "items": items, "reason": reason})
    return items, reason


class Unavailable(Exception):
    """The CLI can't read cloud sessions here; the message says why."""


# ------------------------------------------------------- Claude Code on the web

class _ClaudeCLI:
    """The Claude CLI in SDK mode, answering cloud reads over stdin. No prompt is
    ever sent, so no model runs; nothing is persisted and no MCP server starts."""

    def __init__(self):
        from .claude import desktop_cli
        cli = desktop_cli()
        if not cli:
            raise Unavailable("Claude Code not found")
        self.p = subprocess.Popen(
            [cli, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
             "--no-session-persistence", "--strict-mcp-config"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=str(HOME))
        self.n = 0
        self.ask({"subtype": "initialize"}, LIST_TIMEOUT)

    def ask(self, request: dict, timeout: float) -> dict:
        self.n += 1
        rid = f"ccx-{self.n}"
        self.p.stdin.write(json.dumps({"type": "control_request", "request_id": rid, "request": request}) + "\n")
        self.p.stdin.flush()
        end = time.time() + timeout
        while time.time() < end:
            if not select.select([self.p.stdout], [], [], 0.5)[0]:
                continue
            line = self.p.stdout.readline()
            if not line:
                break
            try:
                d = json.loads(line)
            except ValueError:
                continue
            r = d.get("response") or {}
            if d.get("type") != "control_response" or r.get("request_id") != rid:
                continue
            if r.get("subtype") == "error":
                raise Unavailable(r.get("error") or "refused")
            out = r.get("response") or {}
            if out.get("status") == "unavailable":
                raise Unavailable(out.get("reason") or "unavailable")
            return out
        raise Unavailable("timed out")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self.p.kill()


def _claude_list() -> List[dict]:
    with _ClaudeCLI() as cli:
        r = cli.ask({"subtype": "list_cloud_sessions", "user_initiated": False}, LIST_TIMEOUT)
    out = []
    for s in r.get("sessions") or []:
        # Remote Control sessions run on this machine and are listed as local ones.
        if not is_claude(s.get("id")) or s.get("environment_kind") == "bridge" or s.get("status") == "archived":
            continue
        repo = s.get("repository") or {}
        out.append({"id": s["id"], "title": s.get("title") or "", "updated_at": _ts(s.get("updated_at")),
                    "status": s.get("status") or "idle",
                    "repo": f"{repo['owner']}/{repo['name']}".lower() if repo.get("owner") and repo.get("name") else ""})
    return out


def claude_sessions(max_age: float = LIST_TTL) -> Tuple[List[dict], Optional[str]]:
    return _cached("claude-list", _claude_list, max_age)


SIGNIN_WAIT = 300  # seconds the browser sign-in may take


def claude_signin(cli: Optional[str] = None) -> bool:
    """Claude Code's own sign-in, for a user who only signed in to the desktop app
    (its CLI is signed in only while the app runs it). `claude auth login` opens the
    browser and takes the result back itself, so no window is needed; only when the
    browser can't hand it back (it then asks for a pasted code) does Terminal open.
    ccx never sees the credential: the CLI keeps it, as after any `claude auth login`."""
    if not cli:
        from .claude import desktop_cli
        cli = desktop_cli()
    if not cli:
        raise RuntimeError("Claude Code not found")
    CLOUD_DIR.mkdir(parents=True, exist_ok=True)
    (CLOUD_DIR / "claude-list.json").unlink(missing_ok=True)
    log = CLOUD_DIR / "claude-sign-in.log"
    with open(log, "w") as out:
        # stdin stays open: the CLI treats a closed stdin as giving up on a pasted code.
        p = subprocess.Popen([cli, "auth", "login"], stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT,
                             cwd=str(HOME))
        end, done = time.time() + SIGNIN_WAIT, False
        while p.poll() is None and time.time() < end:
            time.sleep(0.5)
            text = log.read_text(errors="replace")
            done = "Login successful" in text  # it may keep waiting on the open stdin after this
            if done or "Paste code here >" in text.replace("Paste code here if prompted >", ""):
                break  # else the browser can't return the sign-in: finish it in Terminal
        if p.poll() is None:
            p.stdin.close()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        if done or p.returncode == 0:
            return True
    if time.time() >= end:
        return False  # left unfinished: nothing more to do
    script = CLOUD_DIR / "claude-sign-in.command"
    script.write_text("#!/bin/sh\nclear\necho 'Sign in to Claude Code so ccx can list your cloud sessions.'\n"
                      f"{shlex.quote(cli)} auth login && echo && echo 'Done. Open the ⇄ menu again; you can close this window.'\n")
    script.chmod(0o755)
    subprocess.run(["open", str(script)], check=False)
    return False


def mirror_path(sid: str) -> Path:
    return CLAUDE_MIRRORS / f"{sid}.jsonl"


def _mirror_meta(sid: str) -> dict:
    return _read(CLAUDE_MIRRORS / f"{sid}.json")


def mirror(sid: str) -> Optional[Session]:
    """The local mirror of a cloud Claude session, if it was read before."""
    p = mirror_path(sid)
    if not p.exists():
        return None
    m = _mirror_meta(sid)
    return Session("claude", sid, m.get("cwd") or str(HOME), p.stat().st_mtime, m.get("title") or "", p)


def _key(e: dict) -> str:
    return e.get("uuid") or hashlib.sha1(json.dumps(e, sort_keys=True).encode()).hexdigest()


def fetch_claude(sid: str, cwd: Optional[str] = None, title: Optional[str] = None) -> Session:
    """Bring a cloud Claude session's mirror up to date: the whole transcript the
    first time, afterwards from the last page read on. Each record's folder is the
    local checkout of its repository, so Codex imports it into that project."""
    CLAUDE_MIRRORS.mkdir(parents=True, exist_ok=True)
    with open(CLAUDE_MIRRORS / f"{sid}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        m = _mirror_meta(sid)
        cwd = cwd or m.get("cwd") or str(HOME)
        title = title or m.get("title") or ""
        path = mirror_path(sid)
        cursor, seen = m.get("cursor"), set(m.get("tail") or [])
        new, page_cursor, tail = [], cursor, list(seen)
        with _ClaudeCLI() as cli:
            while True:
                req = {"subtype": "get_cloud_session_transcript", "session_id": sid}
                if page_cursor:
                    req["cursor"] = page_cursor
                page = cli.ask(req, PAGE_TIMEOUT)
                entries = [e for e in page.get("entries") or [] if isinstance(e, dict)]
                new += [e for e in entries if _key(e) not in seen]
                tail = [_key(e) for e in entries] or tail
                nxt = page.get("next_cursor")
                if not nxt:
                    break
                page_cursor, seen = nxt, set()
        with open(path, "a" if m else "w", encoding="utf-8") as f:
            if not m:
                f.write(json.dumps({"type": "custom-title", "customTitle": title, "sessionId": sid}, ensure_ascii=False) + "\n")
            for e in new:
                if "cwd" in e or e.get("type") in CONVERSATION:
                    e["cwd"] = cwd  # cloud records carry none; Codex's importer takes the project from it
                if "sessionId" in e:
                    e["sessionId"] = sid
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        _write(CLAUDE_MIRRORS / f"{sid}.json", {"cwd": cwd, "title": title, "cursor": page_cursor, "tail": tail,
                                                 "fetched_at": time.time()})
    return mirror(sid)


_fresh: Dict[str, float] = {}  # sid -> when this process last read it


def refresh_claude(sid: str, cwd: Optional[str] = None) -> Optional[Session]:
    """Best effort before a sync: new pages if the CLI can read them, else the mirror
    as it is. Read at most once per few seconds per process (a transfer reads it
    through several steps)."""
    if time.time() - _fresh.get(sid, 0) < 10:
        return mirror(sid)
    try:
        s = fetch_claude(sid, cwd)
        _fresh[sid] = time.time()
        return s
    except Exception:
        return mirror(sid)


# ---------------------------------------------------------------- Codex Cloud

def _codex(*args: str, timeout: float = LIST_TIMEOUT) -> str:
    from .codex import codex_bin
    try:
        # Run in ccx's own folder: `codex cloud` writes an error.log where it runs.
        CLOUD_DIR.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([codex_bin(), "cloud", *args], capture_output=True, text=True, timeout=timeout,
                           cwd=str(CLOUD_DIR), stdin=subprocess.DEVNULL)
    except RuntimeError as e:
        raise Unavailable(str(e))
    except subprocess.TimeoutExpired:
        raise Unavailable("timed out")
    if r.returncode:
        raise Unavailable(clip(r.stderr or r.stdout, 200) or f"exit {r.returncode}")
    return r.stdout


def _codex_list() -> List[dict]:
    out = []
    for t in json.loads(_codex("list", "--json", "--limit", "20")).get("tasks") or []:
        if not is_codex(t.get("id")):
            continue
        s = t.get("summary") or {}
        out.append({"id": t["id"], "title": t.get("title") or "", "updated_at": _ts(t.get("updated_at")),
                    "status": (t.get("status") or "").lower(), "url": t.get("url") or "",
                    "repo": (t.get("environment_label") or "").lower(),
                    "files": s.get("files_changed") or 0, "added": s.get("lines_added") or 0,
                    "removed": s.get("lines_removed") or 0})
    return out


def codex_tasks(max_age: float = LIST_TTL) -> Tuple[List[dict], Optional[str]]:
    return _cached("codex-list", _codex_list, max_age)


def codex_task(tid: str, max_age: float = LIST_TTL) -> Optional[dict]:
    t = next((t for t in codex_tasks(max_age)[0] if t["id"] == tid), None)
    return t or next((t for t in codex_tasks(0)[0] if t["id"] == tid), None)


def codex_task_text(t: dict) -> str:
    """What a Codex Cloud task produced: its status and its code change."""
    head = (f"Codex Cloud task “{t['title']}” ({t['id']}), status {t['status'] or 'unknown'}"
            + (f", environment {t['repo']}" if t["repo"] else "") + (f"\n{t['url']}" if t["url"] else "") + "\n")
    if not t["files"]:
        return head + "\nIt has no code change (yet)."
    try:
        diff = _codex("diff", t["id"], timeout=60)
    except Unavailable as e:
        diff = f"(could not read the diff: {e})"
    return (head + f"\nChange: {t['files']} file(s), +{t['added']}/-{t['removed']}. It is not applied here; "
            f"`codex cloud apply {t['id']}` applies it to this checkout.\n\n```diff\n{clip(diff, DIFF_BUDGET)}\n```")


def codex_session(t: dict, cwd: str) -> Session:
    return Session("codex", t["id"], cwd, t["updated_at"], t["title"])


# ------------------------------------------------------- where a cloud session lives

def _github(url: str) -> str:
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}".lower() if m else ""


def repos_of(cwd: str) -> List[str]:
    """owner/name of the folder's GitHub remotes (cached by .git/config's mtime)."""
    cfg = Path(cwd) / ".git" / "config"
    try:
        mt = cfg.stat().st_mtime
    except OSError:
        return []
    cache_path = CLOUD_DIR / "repos.json"
    cache = _read(cache_path)
    hit = cache.get(cwd)
    if hit and hit[0] == mt:
        return hit[1]
    from .common import _git
    found = sorted({r for r in (_github(l.split()[1]) for l in _git(cwd, "remote", "-v").splitlines() if len(l.split()) > 1) if r})
    cache[cwd] = [mt, found]
    _write(cache_path, cache)
    return found


def place(rows: List[dict], cwds: List[str]) -> Tuple[Dict[str, List[dict]], List[dict]]:
    """Cloud rows by the local folder that checks out their repository (newest
    folder first), and the rest. A Codex environment label matches owner/name or name."""
    by_repo: Dict[str, str] = {}
    for cwd in cwds:
        for r in repos_of(cwd):
            by_repo.setdefault(r, cwd)
            by_repo.setdefault(r.split("/")[-1], cwd)
    placed: Dict[str, List[dict]] = {}
    rest = []
    for row in rows:
        cwd = by_repo.get(row["repo"]) or by_repo.get(row["repo"].split("/")[-1]) if row["repo"] else None
        if cwd:
            placed.setdefault(cwd, []).append(row)
        else:
            rest.append(row)
    return placed, rest


def status() -> Dict[str, str]:
    """For `ccx doctor`: whether each side's cloud can be read here."""
    out = {}
    for name, fn in (("claude", claude_sessions), ("codex", codex_tasks)):
        items, reason = fn()
        out[name] = f"unavailable ({reason})" if reason else f"{len(items)} cloud session(s)"
    return out
