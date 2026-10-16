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
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__
from .common import HOME, PLAN, TAG, Session, clip, first_line, real, user_text, which

APP_BUNDLES = ("/Applications/ChatGPT.app", "/Applications/Codex.app",
               str(HOME / "Applications/ChatGPT.app"), str(HOME / "Applications/Codex.app"))
SELF_SERVERS = ("ccx", "claudecodex")
# Every interactive and scripted source; sub-agents are internal and left out.
SOURCES = ["cli", "vscode", "exec", "appServer", "unknown"]

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
        self.notifications: List[dict] = []
        self.request("initialize", {"clientInfo": {"name": "ccx", "version": __version__}})
        self._send({"method": "initialized"})

    def _send(self, obj: dict):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def _read(self, timeout: float) -> Optional[dict]:
        r, _, _ = select.select([self.p.stdout], [], [], timeout)
        if not r:
            return None
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("Codex app-server exited unexpectedly")
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
    title = first_line(t.get("name") or t.get("preview") or "")
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


def items(tid: str) -> List[dict]:
    """Every item of every turn of a thread, in order."""
    t = server().request("thread/read", {"threadId": tid, "includeTurns": True})["thread"]
    return [it for turn in t.get("turns") or [] for it in turn.get("items") or []]


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


def _render(it: dict) -> Unit:
    t = it.get("type")
    if t == "userMessage":
        text = user_text(_text(it.get("content")))
        return ("user", text) if text and TAG not in text else None
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
