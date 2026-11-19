"""The Antigravity desktop app's side: its conversations, read and written
through the app itself.

Antigravity keeps each conversation in its own SQLite file as protobuf blobs,
plus one summary table for all of them. ccx reads the summary table directly
(titles, folders, step counts: that works with the app closed) and asks the
app's own local service for a conversation's content. New conversations are
started with `agentapi`, the command Antigravity ships for exactly that.

Nothing here edits Antigravity's files.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote, unquote, urlencode, urlparse

from .common import HOME, PLAN, TAG, Session, clip, real, same_dir, user_text

Unit = Optional[Tuple[str, str]]

ROOT = Path(os.environ.get("ANTIGRAVITY_HOME", HOME / ".gemini/antigravity"))
CONFIG = ROOT.parent / "config"
SUMMARIES = ROOT / "conversation_summaries.db"
APPS = ("/Applications/Antigravity.app", str(HOME / "Applications/Antigravity.app"))
SERVICE = "exa.language_server_pb.LanguageServerService"
OUTSIDE = "outside-of-project"
# Shown in Antigravity's sidebar, so an imported conversation is easy to spot.
MARK = "⇄ "


class Unavailable(RuntimeError):
    """Antigravity isn't running (or isn't installed), so its content can't be read."""


def app_path() -> Optional[str]:
    return next((a for a in APPS if os.path.isdir(a)), None)


def installed() -> bool:
    """The desktop app has been used on this Mac (it has a conversation store)."""
    return SUMMARIES.exists()


# ------------------------------------------------------------- local service

def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def hub() -> Optional[dict]:
    """The running app's local service: {"httpPort", "csrfToken", …}, or None."""
    for f in sorted((ROOT / "daemon").glob("hub_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d.get("httpPort") and d.get("csrfToken") and _alive(d.get("pid")):
            return d
    return None


def ensure_hub(launch: bool = True, wait: float = 25) -> dict:
    """The local service, starting Antigravity in the background if it is closed."""
    h = hub()
    if h:
        return h
    app = app_path()
    if not launch or not app:
        raise Unavailable("Antigravity isn't running" if app else "the Antigravity desktop app isn't installed")
    subprocess.run(["open", "-g", "-j", "-a", app], capture_output=True, check=False)  # hidden, in the background
    end = time.time() + wait
    while time.time() < end:
        time.sleep(0.5)
        h = hub()
        if h:
            return h
    raise Unavailable("Antigravity didn't start in time; open it and try again")


def rpc(method: str, body: Optional[dict] = None, timeout: float = 60, launch: bool = True) -> dict:
    h = ensure_hub(launch)
    req = urllib.request.Request(
        f"http://127.0.0.1:{h['httpPort']}/{SERVICE}/{method}", data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json", "x-codeium-csrf-token": h["csrfToken"],
                 "Connect-Protocol-Version": "1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("message", "")
        except ValueError:
            msg = ""
        raise RuntimeError(f"Antigravity refused {method}: {msg or e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Unavailable(f"couldn't reach Antigravity ({e})") from e


# ------------------------------------------------------------------ listing

def _path(uri: str) -> str:
    return real(unquote(urlparse(uri).path)) if uri.startswith("file://") else ""


def _epoch(text) -> float:
    """'2026-11-15 05:02:53.034063+00:00' (as SQLite stores it) to a timestamp."""
    try:
        return datetime.fromisoformat(str(text).replace(" ", "T", 1).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _rows(where: str = "", args: tuple = (), limit: int = 400) -> List[sqlite3.Row]:
    if not SUMMARIES.exists():
        return []
    try:
        db = sqlite3.connect(f"file:{quote(str(SUMMARIES))}?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            # Only conversations the person sees in the sidebar: no subagents.
            return db.execute(
                "select conversation_id, title, preview, step_count, last_modified_time, workspace_uris, project_id "
                "from conversation_summaries where parent_conversation_id = '' and nesting_depth = 0 and killed = 0 "
                + (f"and {where} " if where else "") + "order by last_modified_time desc limit ?",
                (*args, limit)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return []


def _session(r: sqlite3.Row) -> Session:
    try:
        uris = json.loads(r["workspace_uris"] or "[]") or []
    except ValueError:
        uris = []
    cwd = next((p for p in map(_path, uris) if p), "")
    if not cwd and r["project_id"] and r["project_id"] != OUTSIDE:
        cwd = project_folder(r["project_id"])
    title = (r["title"] or "").strip() or clip((r["preview"] or "").strip().splitlines()[0] if r["preview"] else "", 60)
    s = Session("antigravity", r["conversation_id"], cwd, _epoch(r["last_modified_time"]), title or "Untitled")
    s.steps = int(r["step_count"] or 0)  # how far the conversation has got; readable with the app closed
    return s


def sessions(cwd: Optional[str] = None, query: Optional[str] = None, limit: int = 60) -> List[Session]:
    from .claude import matches
    out = []
    for r in _rows():
        s = _session(r)
        if cwd and not same_dir(s.cwd, cwd):
            continue
        if query and not matches(query, s.title):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def find(cid: str) -> Optional[Session]:
    """By id or unique prefix."""
    if not cid or not all(c in "0123456789abcdef-" for c in cid.lower()):
        return None
    rows = _rows("conversation_id like ?", (cid.lower() + "%",), 2)
    return _session(rows[0]) if len(rows) == 1 else None


def step_count(cid: str) -> int:
    s = find(cid)
    return getattr(s, "steps", 0) if s else 0


# ------------------------------------------------------------------ content

def steps(cid: str, launch: bool = True) -> List[dict]:
    return (rpc("GetCascadeTrajectory", {"cascadeId": cid}, timeout=120, launch=launch).get("trajectory") or {}).get("steps") or []


def units(sts: List[dict], include_imported: bool = False) -> List[Unit]:
    """One entry per step (the cursor counts these).

    What ccx brought in (the import a conversation starts with, later sync
    notes) is None, so it is never sent back; include_imported renders the
    import too, for a full 'continue from' and for reading history."""
    out: List[Unit] = []
    ack = False  # the turn answering our own import prompt ("ready to continue") isn't progress
    for st in sts:
        if st.get("type", "").endswith("USER_INPUT"):
            ack = _is_import(st)
            out.append(_render(st, include_imported))
        else:
            out.append(None if ack else _render(st, include_imported))
    return out


def _is_import(st: dict) -> bool:
    return st.get("type", "").endswith("USER_INPUT") and f"<{TAG}" in ((st.get("userInput") or {}).get("userResponse") or "")


def _args(call: dict) -> str:
    return clip(call.get("argumentsJson") or json.dumps(call.get("args") or "", ensure_ascii=False), 300)


def _render(st: dict, include_imported: bool = False) -> Unit:
    t = st.get("type", "").replace("CORTEX_STEP_TYPE_", "")
    if t == "USER_INPUT":
        ui = st.get("userInput") or {}
        text = ui.get("userResponse") or "\n".join(i.get("text", "") for i in ui.get("items") or [] if isinstance(i, dict))
        if f"<{TAG}" in text:
            # Our import: the conversation it carries is this conversation's history.
            return ("user", _import_body(text)) if include_imported else None
        text = user_text(text)
        return ("user", text) if text else None
    if t == "PLANNER_RESPONSE":
        p = st.get("plannerResponse") or {}
        parts = []
        text = (p.get("modifiedResponse") or p.get("response") or "").strip()
        if text and TAG not in text:
            parts.append(text)
        for c in p.get("toolCalls") or []:
            name = c.get("name") or ""
            if "ccx" in name or name in ("read_file", "view_file", "list_dir", "run_command", "search_web",
                                         "read_url_content", "edit_file", "write_file", "call_mcp_tool"):
                continue  # ccx's own tools; and tools whose result step says it better
            parts.append(f"[tool {name}] {_args(c)}")
        return ("assistant", "\n".join(parts)) if parts else None
    if t == "RUN_COMMAND":
        r = st.get("runCommand") or {}
        cmd = r.get("commandLine") or r.get("proposedCommandLine") or (st.get("taskDetails") or {}).get("description") or ""
        if not cmd or "ccx" in cmd.split("/")[-1].split(" ")[0]:
            return None
        o = r.get("combinedOutput")
        out = clip((o.get("full") or "") if isinstance(o, dict) else str(o or ""), 400)
        return ("assistant", f"[ran] {clip(cmd, 300)}" + (f"\n[output] {out}" if out else ""))
    if t == "CODE_ACTION":
        c = st.get("codeAction") or {}
        spec = c.get("actionSpec") or {}
        path = next((v.get("file", {}).get("absoluteUri") or v.get("absoluteUri") or v.get("absolutePathUri")
                     for v in spec.values() if isinstance(v, dict)), None) if isinstance(spec, dict) else None
        what = c.get("description") or ""
        label = _path(path) if path else ""
        return ("assistant", "[edited] " + " — ".join(x for x in (label, clip(what, 200)) if x)) if (label or what) else None
    if t == "VIEW_FILE":
        v = st.get("viewFile") or {}
        p = _path(v.get("absolutePathUri") or "")
        return ("assistant", f"[read] {p}") if p and "/antigravity/mcp/ccx" not in p else None
    if t == "SEARCH_WEB":
        return ("assistant", f"[web search] {(st.get('searchWeb') or {}).get('query')}")
    if t == "READ_URL_CONTENT":
        return ("assistant", f"[read] {(st.get('readUrlContent') or {}).get('url')}")
    if t == "MCP_TOOL":
        m = st.get("mcpTool") or {}
        call, res = m.get("toolCall") or {}, str(m.get("resultString") or "")
        if "ccx" in (m.get("serverName") or "") or TAG in res:
            return None  # ccx's own tools
        return ("assistant", f"[tool {m.get('serverName')}.{call.get('name')}] {_args(call)}"
                             + (f"\n[result] {clip(res, 400)}" if res else ""))
    if t == "CHECKPOINT":
        return None  # a summary of earlier steps: sending it would repeat them
    if t == "GENERIC":
        g = st.get("generic") or {}
        args = g.get("args") or {}
        items = args.get("todos") or args.get("Todos") or args.get("tasks") if isinstance(args, dict) else None
        if isinstance(items, list) and items and all(isinstance(i, dict) for i in items):
            mark = {"completed": "[x]", "done": "[x]", "in_progress": "[~]"}
            return ("assistant", PLAN + "\n" + "\n".join(
                f"- {mark.get(str(i.get('status', '')).lower(), '[ ]')} {i.get('content') or i.get('title') or ''}" for i in items))
        return None
    return None  # system messages (ours and the app's), errors, subagent bookkeeping


def _import_body(text: str) -> str:
    a, b = text.find(f"<{TAG}"), text.rfind(f"</{TAG}>")
    body = text[text.find(">", a) + 1:b] if a >= 0 and b > a else text
    return "[imported by ccx]\n" + body.strip()


# ----------------------------------------------------------------- projects

def projects() -> List[dict]:
    out = []
    for f in (CONFIG / "projects").glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        folders = []
        for r in ((d.get("projectResources") or {}).get("resources") or []):
            uri = (r.get("gitFolder") or {}).get("folderUri") or r.get("folderUri") or ""
            if _path(uri):
                folders.append(_path(uri))
        out.append({"id": d.get("id") or f.stem, "name": d.get("name") or "", "folders": folders})
    return out


def project_folder(pid: str) -> str:
    return next((p["folders"][0] for p in projects() if p["id"] == pid and p["folders"]), "")


def project_for(cwd: str) -> Optional[dict]:
    return next((p for p in projects() if any(same_dir(f, cwd) for f in p["folders"])), None)


def ensure_project(cwd: str) -> Optional[str]:
    """The Antigravity project for this folder, added to the app when it has none.
    None when the folder can't be made a project (the conversation still works)."""
    p = project_for(cwd)
    if p:
        return p["id"]
    if not cwd or not os.path.isdir(cwd):
        return None
    pid = str(uuid.uuid4())
    uri = "file://" + quote(real(cwd))
    resource = {"gitFolder": {"folderUri": uri}} if os.path.exists(os.path.join(cwd, ".git")) else {"folderUri": uri}
    try:
        rpc("CreateProject", {"project": {"id": pid, "name": os.path.basename(real(cwd)),
                                          "projectResources": {"resources": [resource]}, "isWorkspaceOnly": False}})
    except RuntimeError:
        return None
    for _ in range(20):
        if project_for(cwd):
            return project_for(cwd)["id"]
        time.sleep(0.25)
    return pid


# ------------------------------------------------------------------ writing

def _agentapi() -> List[str]:
    wrapper = ROOT / "bin/agentapi"
    if os.access(wrapper, os.X_OK):
        return [str(wrapper)]
    app = app_path()
    binary = os.path.join(app or "", "Contents/Resources/bin/language_server")
    if not os.access(binary, os.X_OK):
        raise Unavailable("Antigravity's agentapi command wasn't found; open Antigravity once and try again")
    return [binary, "agentapi"]


def _run_agentapi(args: List[str], project: Optional[str] = None) -> dict:
    h = ensure_hub()
    env = {**os.environ, "ANTIGRAVITY_LS_ADDRESS": f"127.0.0.1:{h['httpPort']}", "ANTIGRAVITY_CSRF_TOKEN": h["csrfToken"]}
    env.pop("ANTIGRAVITY_PROJECT_ID", None)
    env.pop("ANTIGRAVITY_CONVERSATION_ID", None)  # never attach to the conversation ccx was called from
    if project:
        env["ANTIGRAVITY_PROJECT_ID"] = project
    try:
        r = subprocess.run(_agentapi() + args, capture_output=True, text=True, env=env, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"Antigravity's agentapi failed: {e}") from e
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        d = {}
    if r.returncode or d.get("error"):
        raise RuntimeError(f"Antigravity's agentapi failed: {d.get('error') or (r.stderr or r.stdout).strip()[-300:]}")
    return d.get("response") or {}


def new_conversation(cwd: str, title: str, prompt: str, model: Optional[str] = None) -> str:
    """Start a conversation in this folder's project with `prompt`; returns its id.

    `model` (flash_lite, flash, pro or a model id) answers only this first turn:
    the conversation's next message goes to whatever model the user has picked in
    Antigravity. An agentapi that doesn't know the flag gets the default model."""
    project = ensure_project(cwd)
    try:
        res = _run_agentapi(["new-conversation", f"--title={title}", *([f"--model={model}"] if model else []), prompt], project)
    except RuntimeError:
        if not model:
            raise
        res = _run_agentapi(["new-conversation", f"--title={title}", prompt], project)
    cid = (res.get("newConversation") or {}).get("conversationId")
    if not cid:
        raise RuntimeError("Antigravity didn't return the new conversation's id")
    return cid


def wait_idle(cid: str, timeout: float = 90) -> int:
    """Wait for the conversation's first reply to finish; returns its step count."""
    end, n = time.time() + timeout, 0
    while time.time() < end:
        try:
            t = rpc("GetCascadeTrajectory", {"cascadeId": cid}, launch=False).get("trajectory") or {}
        except RuntimeError:
            t = {}
        sts = t.get("steps") or []
        n = len(sts)
        done = n >= 2 and all(s.get("status", "").endswith(("DONE", "ERROR", "CANCELED")) for s in sts) \
            and sts[-1].get("type", "").endswith(("PLANNER_RESPONSE", "ERROR_MESSAGE")) \
            and not (sts[-1].get("plannerResponse") or {}).get("toolCalls")
        if done:
            break
        time.sleep(1)
    return n


def delete(cid: str):
    rpc("DeleteCascadeTrajectory", {"cascadeId": cid})


# ------------------------------------------------------------------ opening

def open_app() -> bool:
    app = app_path()
    return bool(app) and subprocess.run(["open", "-a", app], capture_output=True).returncode == 0


def new_conversation_link(cwd: str, prompt: str) -> str:
    """Antigravity's own deep link: a new conversation in the folder's project with
    the prompt filled in. Sending is left to the user."""
    q = {"prompt": prompt}
    pid = ensure_project(cwd)
    if pid:
        q["project"] = pid
    return "antigravity://open?" + urlencode(q, quote_via=quote)


# ------------------------------------------------------------------- plugin

PLUGIN_DIR = CONFIG / "plugins" / "ccx"


def plugin_installed() -> bool:
    return (PLUGIN_DIR / "plugin.json").exists()
