"""Codex threads, read and written only through Codex's own app-server API
(the same JSON-RPC interface the Codex desktop app uses). No rollout file
parsing, so nothing depends on Codex's on-disk format or zstd."""

from __future__ import annotations

import atexit
import json
import os
import select
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__
from .common import (HOME, PLAN, TAG, Session, clip, first_line, image_line, real, strip_files_header,
                     user_text, which)

APP_BUNDLES = ("/Applications/ChatGPT.app", "/Applications/Codex.app",
               str(HOME / "Applications/ChatGPT.app"), str(HOME / "Applications/Codex.app"))
SELF_SERVERS = ("ccx", "claudecodex")
# Every interactive and scripted source; sub-agents are internal and left out.
SOURCES = ["cli", "vscode", "exec", "appServer", "unknown"]
DESKTOP_STATE = Path(os.environ.get("CODEX_HOME", HOME / ".codex")) / ".codex-global-state.json"

Unit = Optional[Tuple[str, str]]


def codex_bin() -> str:
    """The CLI bundled with the Codex desktop app (matches its models and formats)."""
    bundled = [f"{a}/Contents/Resources/codex-cli/bin/codex" for a in APP_BUNDLES]
    b = which("codex", *bundled)
    if not b:
        raise RuntimeError("Codex not found: install the Codex desktop app first")
    return b


class AppServer:
    def __init__(self):
        self.p = subprocess.Popen([codex_bin(), "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True)
        self._id = 0
        self._received = bytearray()
        self.notifications: List[dict] = []
        self.request("initialize", {"clientInfo": {"name": "ccx", "version": __version__},
                                    "capabilities": {"experimentalApi": True}})
        self._send({"method": "initialized"})

    def _send(self, obj: dict):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def _read(self, timeout: float) -> Optional[dict]:
        # TextIOWrapper.readline can read ahead: select then sees no OS bytes,
        # even though the next notification is already in the wrapper's buffer.
        # Buffer raw bytes ourselves, so burst responses never strand imports.
        if b"\n" in self._received:
            line, _, rest = self._received.partition(b"\n")
            self._received = bytearray(rest)
            return json.loads(line)
        r, _, _ = select.select([self.p.stdout], [], [], timeout)
        if not r:
            return None
        chunk = os.read(self.p.stdout.fileno(), 65536)
        if not chunk:
            raise RuntimeError("Codex app-server exited unexpectedly")
        self._received.extend(chunk)
        if b"\n" not in self._received:
            return None
        line, _, rest = self._received.partition(b"\n")
        self._received = bytearray(rest)
        return json.loads(line)

    def request(self, method: str, params: dict, timeout: float = 60) -> dict:
        self._id += 1
        rid = self._id
        self._send({"id": rid, "method": method, "params": params})
        end = time.time() + timeout
        while time.time() < end:
            msg = self._read(1)
            if msg is None:
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"Codex {method} failed: {msg['error'].get('message', msg['error'])}")
                return msg.get("result") or {}
            if "method" in msg:
                self.notifications.append(msg)
        raise TimeoutError(f"Codex {method} timed out")

    def wait_notification(self, method: str, match, timeout: float = 180) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            for n in self.notifications:
                if n.get("method") == method and match(n.get("params") or {}):
                    return n["params"]
            msg = self._read(1)
            if msg and "method" in msg:
                self.notifications.append(msg)
        raise TimeoutError(f"timed out waiting for Codex {method}")

    def close(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait()
        self.p.stdin.close()
        self.p.stdout.close()


_server: Optional[AppServer] = None


def server() -> AppServer:
    """One app-server per process, started on first use."""
    global _server
    if _server is None or _server.p.poll() is not None:
        _server = AppServer()
        atexit.register(_server.close)
    return _server


# ------------------------------------------------------------------ threads

def _session(t: dict) -> Session:
    path = Path(t["path"]) if t.get("path") else None
    title = first_line(t.get("name") or user_text(t.get("preview") or ""))
    return Session("codex", t["id"], t.get("cwd") or "", float(t.get("updatedAt") or 0), title, path)


def threads(cwd: Optional[str] = None, query: Optional[str] = None, limit: int = 60) -> List[Session]:
    """Codex threads, newest first; limited to a project folder and/or a title search."""
    params = {"limit": min(limit, 100), "sortKey": "updated_at", "sourceKinds": SOURCES}
    if cwd:
        params["cwd"] = real(cwd)
    if query:
        params["searchTerm"] = query
    out: List[Session] = []
    while len(out) < limit:
        res = server().request("thread/list", params)
        out += [_session(t) for t in res.get("data", []) if not t.get("ephemeral")]
        if not res.get("nextCursor"):
            break
        params["cursor"] = res["nextCursor"]
    return [s for s in out if s.title][:limit]


def find(tid: str) -> Optional[Session]:
    try:
        return _session(server().request("thread/read", {"threadId": tid, "includeTurns": False})["thread"])
    except RuntimeError:
        return None


def desktop_project(cwd: str) -> Optional[dict]:
    """Read the desktop's saved-folder index (never write its live state file).

    A project created with app-server project/create alone isn't registered in
    every desktop version. The UI maintains a separate local ID -> server ID map.
    """
    try:
        state = json.loads(DESKTOP_STATE.read_text())
    except (OSError, ValueError):
        return None
    root = real(cwd)
    mappings = state.get("app-server-project-id-by-legacy-project-id-by-host", {})
    host = "local:" + str(DESKTOP_STATE.parent)
    for pid, project in state.get("local-projects", {}).items():
        if any(real(path) == root for path in project.get("rootPaths", [])):
            local_map = mappings.get(host, {})
            return {"id": pid, "server_id": local_map.get(pid), "cwd": root,
                    "registered_server_ids": list(local_map.values())}
    return None


def register_desktop_workspace(cwd: str, timeout: float = 15) -> bool:
    """Use the official CLI to register the workspace in the live desktop.

    Returns True only when registration was needed (the caller may want to
    restore its thread afterwards). Merely restarting the app doesn't import
    project/create records into this desktop index. No direct state-file writes.
    """
    root = real(cwd) if cwd else ""
    if not root or not os.path.isdir(root) or "/scratch-workspaces/" in root or desktop_project(root):
        return False
    proc = subprocess.run([codex_bin(), "app", root], capture_output=True, text=True, timeout=30)
    if proc.returncode:
        raise RuntimeError("Codex could not register the desktop workspace: " + clip(proc.stderr or proc.stdout, 400))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if desktop_project(root):
            return True
        time.sleep(0.1)  # opening the workspace is asynchronous after the CLI returns
    raise RuntimeError("Codex opened the folder but has not registered it in the desktop project list yet; retry")


def ensure_thread_project(tid: str, cwd: str) -> Optional[str]:
    """Attach a projectless thread to the desktop project for its working folder.

    cwd is execution context, not sidebar membership. Reuse an exact canonical
    root match, or create a local project through Codex's project API. Never move
    a thread the user already assigned, or collapse distinct worktrees together.
    Called on existing pairs too, so reopening repairs older ccx imports.
    """
    srv = server()
    thread = srv.request("thread/read", {"threadId": tid, "includeTurns": False})["thread"]
    root = real(thread.get("cwd") or cwd) if thread.get("cwd") or cwd else ""
    if not root or not os.path.isdir(root) or "/scratch-workspaces/" in root:
        return thread.get("projectId")  # don't create projects for missing/temporary folders
    registered = desktop_project(root)
    preferred = (registered or {}).get("server_id")
    current = thread.get("projectId")
    if current and current != preferred:
        # Preserve explicit assignments. Only repair an orphan created by ccx's
        # previous backend-only flow when it has the same root and is not a
        # separately registered desktop project.
        if not preferred or current in registered.get("registered_server_ids", []):
            return current
        try:
            existing = srv.request("project/read", {"projectId": current})["project"]
        except RuntimeError:
            return current
        roots = [real(r["path"]) for r in existing.get("roots", []) if r.get("path")]
        if roots != [root]:
            return current
    if current and current == preferred:
        return current
    project_id, cursor = preferred, None
    while project_id is None:
        page = srv.request("project/list", {"limit": 100, "cursor": cursor})
        match = next((p for p in page.get("data", [])
                      if any(real(r["path"]) == root for r in p.get("roots", []) if r.get("path"))), None)
        if match:
            project_id = match["id"]
            break
        cursor = page.get("nextCursor")
        if not cursor:
            break
    if project_id is None:
        # A deterministic key makes concurrent/retried imports create one project.
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, "ccx:local-project:" + root))
        project_id = srv.request("project/create", {
            "idempotencyKey": key, "name": Path(root).name,
            "roots": [{"path": root}],
        })["project"]["id"]
    srv.request("thread/metadata/update", {"threadId": tid, "projectId": project_id})
    actual = srv.request("thread/read", {"threadId": tid, "includeTurns": False})["thread"].get("projectId")
    if actual != project_id:
        raise RuntimeError("Codex did not save the thread's project assignment; retry the transfer")
    return project_id


def items(tid: str) -> List[dict]:
    """Every item of every turn of a thread, in order."""
    srv = server()
    meta = srv.request("thread/read", {"threadId": tid, "includeTurns": False})["thread"]
    if meta.get("historyMode") == "paginated":
        out, cursor = [], None
        while True:
            page = srv.request("thread/items/list", {"threadId": tid, "limit": 100,
                                                    "sortDirection": "asc", "cursor": cursor})
            out.extend(row["item"] for row in page.get("data", []))
            cursor = page.get("nextCursor")
            if not cursor:
                return out
    t = srv.request("thread/read", {"threadId": tid, "includeTurns": True})["thread"]
    return [it for turn in t.get("turns") or [] for it in turn.get("items") or []]


def ensure_paginated_history(tid: str) -> str:
    """Use Codex's targeted migration, without touching a live writer ourselves.

    Importers still emit legacy history on some desktop versions. Those threads
    cannot serve the items/list requests the desktop uses to expand old turns.
    A busy thread must be retried after Codex releases it; never rewrite its DB.
    """
    meta = server().request("thread/read", {"threadId": tid, "includeTurns": False})["thread"]
    if meta.get("historyMode") == "paginated":
        return "ready"
    proc = subprocess.run([codex_bin(), "migrate-rollouts", "--thread", tid, "--apply", "--json"],
                          capture_output=True, text=True, timeout=180)
    if proc.returncode:
        raise RuntimeError("Codex history migration failed: " + clip(proc.stderr or proc.stdout, 500))
    outcomes = json.loads(proc.stdout).get("outcomes", [])
    outcome = next((o for o in outcomes if o.get("thread_id") == tid), {})
    if outcome.get("status") == "skipped_busy":
        return "busy"
    actual = server().request("thread/read", {"threadId": tid, "includeTurns": False})["thread"]
    if actual.get("historyMode") != "paginated":
        raise RuntimeError("Codex history migration did not complete: " + str(outcome.get("status", "no result")))
    # Verify the very API used to expand the oldest imported messages.
    server().request("thread/items/list", {"threadId": tid, "sortDirection": "asc", "limit": 1})
    return "ready"


def unarchive(tid: str):
    """Bring an archived thread back (no-op when it isn't archived)."""
    try:
        server().request("thread/unarchive", {"threadId": tid})
    except RuntimeError:
        pass


COMPACTED_TOKENS = 20_000  # rough size of a compacted Codex thread


def context_state(s: Session) -> Tuple[int, float]:
    """(tokens in the thread's context at its last model call, unix time of that
    call), read from the end of its rollout. (0, updatedAt) if unknown."""
    from datetime import datetime
    if not s.path or not s.path.exists():
        return 0, s.mtime
    try:
        if s.path.suffix == ".zst":
            lines = list(_zst_lines(s.path))[-400:]
        else:
            size = s.path.stat().st_size
            with open(s.path, "rb") as f:
                f.seek(max(0, size - 3_000_000))
                lines = f.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return 0, s.mtime
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        p = d.get("payload") or {}
        if d.get("type") == "compacted" or p.get("type") == "context_compacted":
            # Codex compacted after its last model call: the next one reads the summary.
            try:
                ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                ts = s.mtime
            return COMPACTED_TOKENS, ts
        if d.get("type") == "event_msg" and p.get("type") == "token_count" and p.get("info"):
            u = p["info"].get("last_token_usage") or {}
            try:
                ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                ts = s.mtime
            return int(u.get("input_tokens", 0)), ts
    return 0, s.mtime


def _zst_lines(path: Path):
    try:
        from compression import zstd  # Python 3.14+
        with zstd.open(path, "rt", errors="replace") as f:
            yield from f
    except ImportError:
        z = which("zstd")
        if z:
            yield from subprocess.run([z, "-dc", str(path)], capture_output=True).stdout.decode("utf-8", "replace").splitlines()


def size_of(s: Optional[Session]) -> int:
    """Cheap change detector: the rollout file grows whenever the thread does."""
    try:
        return s.path.stat().st_size if s and s.path else -1
    except OSError:
        return -1


# -------------------------------------------------------------------- units

def units(its: List[dict]) -> List[Unit]:
    """One entry per thread item (the cursor counts these)."""
    return [_render(it) for it in its]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content or [] if isinstance(c, dict))


def _url(url: str) -> Optional[str]:
    return None if url.startswith("data:") else url or None  # inline data has no file to point to


def _render(it: dict) -> Unit:
    t = it.get("type")
    if t == "userMessage":
        text = user_text(strip_files_header(_text(it.get("content"))))
        if TAG in text:
            return None
        images = [image_line(c.get("path") if c.get("type") == "localImage" else _url(c.get("url", "")))
                  for c in it.get("content") or []
                  if isinstance(c, dict) and c.get("type") in ("localImage", "image")]
        text = "\n".join([text] * bool(text) + images)
        return ("user", text) if text else None
    if t == "agentMessage":
        text = it.get("text") or ""
        return ("assistant", text) if text.strip() and TAG not in text else None
    if t == "plan":
        return ("assistant", f"{PLAN}\n{it.get('text', '').strip()}")
    if t == "commandExecution":
        out = clip(it.get("aggregatedOutput") or "", 400)
        return ("assistant", f"[ran] {clip(str(it.get('command')), 300)}" + (f"\n[output] {out}" if out else ""))
    if t == "fileChange":
        paths = [c.get("path", "") for c in it.get("changes") or [] if isinstance(c, dict)]
        return ("assistant", "[edited] " + ", ".join(paths[:20])) if paths else None
    if t == "mcpToolCall":
        if it.get("server") in SELF_SERVERS:
            return None
        res = it.get("result")
        res = _text((res or {}).get("content")) if isinstance(res, dict) else str(res or "")
        if TAG in res:
            return None
        return ("assistant", f"[tool {it.get('server')}.{it.get('tool')}] "
                             f"{clip(json.dumps(it.get('arguments'), ensure_ascii=False), 300)}\n[result] {clip(res, 400)}")
    if t in ("dynamicToolCall", "functionCallOutput"):
        body = json.dumps(it.get("arguments") or it.get("output") or "", ensure_ascii=False)
        return ("assistant", f"[tool {it.get('tool') or it.get('name')}] {clip(body, 300)}")
    if t == "webSearch":
        return ("assistant", f"[web search] {it.get('query')}")
    return None  # reasoning, hookPrompt (our own injections), compaction, images, …


def turns_for_claude(its: List[dict]) -> List[Tuple[str, str]]:
    """Alternating (user, assistant) turns, for writing a Claude session."""
    turns: List[list] = []
    for u in units(its):
        if not u:
            continue
        role, text = u
        if turns and turns[-1][0] == role:
            turns[-1][1].append(text)
        else:
            turns.append([role, [text]])
    while turns and turns[0][0] != "user":
        turns.pop(0)
    return [(r, "\n\n".join(c)) for r, c in turns]


# ------------------------------------------------------------------ imports

def import_claude_session(path: str, cwd: str, title: Optional[str]) -> Optional[str]:
    """Import a Claude session with Codex's own importer. Returns the new thread
    id, or None when Codex says this source file was already imported."""
    srv = server()
    item = {"itemType": "SESSIONS", "description": f"Import Claude Code session {path}", "cwd": None,
            "details": {"sessions": [{"cwd": cwd, "path": path, "title": title or None}]}}
    res = srv.request("externalAgentConfig/import", {"migrationItems": [item], "source": "ccx"})
    done = srv.wait_notification("externalAgentConfig/import/completed",
                                 lambda p: p.get("importId") == res["importId"])
    for r in done.get("itemTypeResults", []):
        if r.get("itemType") != "SESSIONS":
            continue
        if r.get("failures"):
            f = r["failures"][0]
            raise RuntimeError(f"Codex import failed ({f.get('failureStage')}): {f.get('message')}")
        if r.get("successes"):
            return r["successes"][0].get("target")
    return None


def import_history() -> Dict[str, str]:
    """Claude source file -> Codex thread, for every import Codex has done
    (from its own app, the official plugin, or us); latest wins."""
    try:
        res = server().request("externalAgentConfig/import/readHistories", {})
    except Exception:
        return {}
    pairs = []
    for h in res.get("data", []):
        for s in h.get("successes", []):
            if s.get("itemType") == "SESSIONS" and s.get("source") and s.get("target"):
                pairs.append((h.get("completedAtMs", 0), s["source"], s["target"]))
    return {src: tgt for _, src, tgt in sorted(pairs)}


def _our_hooks() -> List[dict]:
    res = server().request("hooks/list", {"cwds": [str(HOME)]})
    return [h for g in res.get("data", []) for h in g.get("hooks", []) if (h.get("pluginId") or "").startswith("ccx@")]


def trust_hooks() -> int:
    """Trust ccx's own plugin hooks, the way Codex's own hooks screen does
    (config/batchWrite of hooks.state."<key>".trusted_hash). Only ccx's hooks
    are touched. Returns how many were newly trusted."""
    edits = [{"keyPath": f'hooks.state."{h["key"]}".trusted_hash', "value": h["currentHash"], "mergeStrategy": "upsert"}
             for h in _our_hooks() if h.get("trustStatus") != "trusted" and h.get("currentHash")]
    if edits:
        server().request("config/batchWrite", {"edits": edits, "reloadUserConfig": True})
    return len(edits)


def hooks_trusted() -> Optional[bool]:
    """Whether Codex trusts our UserPromptSubmit hook (None if not installed)."""
    try:
        res = server().request("hooks/list", {"cwds": [str(HOME)]})
    except Exception:
        return None
    for group in res.get("data", []):
        for h in group.get("hooks", []):
            if h.get("pluginId", "") .startswith("ccx@") and h.get("eventName") == "userPromptSubmit":
                return h.get("trustStatus") == "trusted"
    return None
