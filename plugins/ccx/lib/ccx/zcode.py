"""The ZCode desktop app's side: its conversations ("tasks"), read from the app's
own session database and written through the app's own protocol server.

ZCode keeps every conversation in one SQLite database (~/.zcode/cli/db/db.sqlite,
opencode-style sessions, messages and parts). ccx reads it directly, read-only
(that works with the app closed). New conversations are created by ZCode's own
`app-server` (the protocol the desktop app itself speaks) with `importedHistory`,
the same call ZCode's built-in "import from Claude Code" makes, so an imported
conversation is a real ZCode conversation with real history.

The desktop app lists a folder's conversations from what its background process
loaded the first time that folder was opened since the app started; one created
from outside appears once the app loads the folder afresh. So after an import
ccx makes the folder ZCode's last active one and starts ZCode (restarting it when
it is idle; when it is busy, only with the user's say-so): it opens right on that
folder, with the conversation listed (see show()).

The only file of ZCode's that ccx writes is that one setting, and only while
ZCode is closed.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

from .common import HOME, PLAN, TAG, Session, clip, image_line, real, same_dir, user_text

Unit = Optional[Tuple[str, str]]

ROOT = Path(os.environ.get("ZCODE_HOME", HOME / ".zcode"))
DB = ROOT / "cli/db/db.sqlite"
TASKS = ROOT / "v2/tasks-index.sqlite"
SETTINGS = ROOT / "v2/setting.json"
APPS = ("/Applications/ZCode.app", str(HOME / "Applications/ZCode.app"))
BUNDLE_ID = "dev.zcode.app"
PROCESS = "ZCode"
# Tools of ccx itself (its MCP server inside ZCode): never synced.
SELF = ("ccx", "claudecodex")


def app_path() -> Optional[str]:
    return next((a for a in APPS if os.path.isdir(a)), None)


def installed() -> bool:
    """The desktop app is here and has been used (it has a conversation store)."""
    return bool(app_path()) and DB.exists()


# ---------------------------------------------------------------- database

def _connect(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    try:
        db = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=3)
        db.row_factory = sqlite3.Row
        return db
    except sqlite3.Error:
        return None


def _query(sql: str, args: tuple = (), path: Path = DB) -> List[sqlite3.Row]:
    db = _connect(path)
    if not db:
        return []
    try:
        return db.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()


_LISTED = ("parent_id is null and time_deleted is null and time_archived is null "
           "and coalesce(task_type, 'interactive') = 'interactive'")


def _session(r: sqlite3.Row) -> Session:
    return Session("zcode", r["id"], real(r["directory"] or r["path"] or ""),
                   (r["time_updated"] or 0) / 1000, (r["title"] or "").strip() or "Untitled")


def sessions(cwd: Optional[str] = None, query: Optional[str] = None, limit: int = 60) -> List[Session]:
    from .claude import matches
    out = []
    for r in _query(f"select id, directory, path, title, time_updated from session where {_LISTED} "
                    "order by time_updated desc limit 500"):
        s = _session(r)
        if cwd and not same_dir(s.cwd, cwd):
            continue
        if query and not matches(query, s.title):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def find(sid: str) -> Optional[Session]:
    """By id ("sess_…") or unique prefix, with or without the "sess_"."""
    if not sid or not all(c.isalnum() or c in "-_" for c in sid):
        return None
    sid = sid if sid.startswith("sess_") else "sess_" + sid
    rows = _query("select id, directory, path, title, time_updated from session where id like ? "
                  "and parent_id is null and time_deleted is null limit 2", (sid + "%",))
    return _session(rows[0]) if len(rows) == 1 else None


# ------------------------------------------------------------------- units

def _rows(sid: str) -> List[sqlite3.Row]:
    return _query(
        "select m.id as mid, m.data as mdata, p.data as pdata from message m "
        "left join part p on p.message_id = m.id where m.session_id = ? "
        "order by coalesce(m.sequence, 0), m.time_created, m.id, coalesce(p.sequence, 0), p.time_created, p.id",
        (sid,))


def units(sid: str, include_imported: bool = False) -> List[Unit]:
    """One entry per part of a finished message (the cursor counts these).

    A reply still being written stops the list there, so a half-streamed turn is
    never sent. What ccx (or ZCode's own importer) brought in is None, so it is
    never sent back; include_imported renders it too, for a full 'continue from'
    and for reading history."""
    out: List[Unit] = []
    for r in _rows(sid):
        try:
            m = json.loads(r["mdata"] or "{}")
        except ValueError:
            continue
        if m.get("role") == "assistant" and not (m.get("time") or {}).get("completed"):
            break
        if r["pdata"] is None:
            continue
        try:
            p = json.loads(r["pdata"])
        except ValueError:
            out.append(None)
            continue
        imported = bool((m.get("metadata") or {}).get("migrationSource") or (p.get("metadata") or {}).get("migrationSource"))
        out.append(None if imported and not include_imported else _render(m.get("role") or "", p))
    return out


def _tool_text(state: dict) -> str:
    o = state.get("output")
    if isinstance(o, (dict, list)):
        o = json.dumps(o, ensure_ascii=False)
    return str(o or state.get("error") or "")


def _render(role: str, p: dict) -> Unit:
    t = p.get("type")
    if t == "text":
        text = p.get("text") or ""
        if p.get("synthetic") or p.get("ignored") or TAG in text:
            return None
        if role == "user":
            text = user_text(text)
            return ("user", text) if text else None
        return ("assistant", text) if text.strip() else None
    if t == "file":
        mime = p.get("mime") or ""
        url = p.get("url") or ""
        path = url[7:] if url.startswith("file://") else (url if url.startswith("/") else None)
        if mime.startswith("image/"):
            return ("user" if role == "user" else "assistant", image_line(path))
        name = p.get("filename") or path
        return (role or "user", f"[file: {name}]") if name else None
    if t == "tool":
        name = str(p.get("tool") or "")
        state = p.get("state") or {}
        inp = state.get("input") or {}
        res = _tool_text(state)
        if any(s in name.lower() for s in SELF) or TAG in res:
            return None  # ccx's own tools
        low = name.lower()
        todos = inp.get("todos") if isinstance(inp, dict) else None
        if isinstance(todos, list) and todos and all(isinstance(i, dict) for i in todos):
            mark = {"completed": "[x]", "done": "[x]", "in_progress": "[~]"}
            return ("assistant", PLAN + "\n" + "\n".join(
                f"- {mark.get(str(i.get('status', '')).lower(), '[ ]')} {i.get('content') or i.get('activeForm') or ''}"
                for i in todos))
        if low in ("bash", "shell", "run_command", "exec"):
            cmd = inp.get("command") if isinstance(inp, dict) else None
            out = clip(res, 400)
            return ("assistant", f"[ran] {clip(str(cmd or inp), 300)}" + (f"\n[output] {out}" if out else ""))
        if low in ("edit", "write", "multiedit", "applypatch", "apply_patch", "notebookedit"):
            path = (inp.get("filePath") or inp.get("file_path") or inp.get("path") or "") if isinstance(inp, dict) else ""
            return ("assistant", f"[edited] {path}" if path else f"[tool {name}] {clip(json.dumps(inp, ensure_ascii=False), 300)}")
        if low in ("read", "glob", "grep", "list", "ls"):
            return None  # what was read shows in what the agent did with it
        body = clip(json.dumps(inp, ensure_ascii=False), 300)
        return ("assistant", f"[tool {name}] {body}" + (f"\n[result] {clip(res, 400)}" if res.strip() else ""))
    return None  # reasoning, step markers, snapshots, patches, compaction


# ----------------------------------------------------------- app-server

def _cli() -> List[str]:
    app = app_path()
    if not app:
        raise RuntimeError("the ZCode desktop app isn't installed")
    exe = os.path.join(app, "Contents/MacOS/ZCode")
    js = os.path.join(app, "Contents/Resources/glm/zcode.cjs")
    if not (os.access(exe, os.X_OK) and os.path.exists(js)):
        raise RuntimeError("this ZCode version has no command-line agent ccx can use; update ZCode")
    return [exe, js]


def _env() -> dict:
    """ZCode's own Electron runs its command-line agent as plain Node, so ccx needs
    no Node of its own. The built-in provider file is the one the app ships."""
    app = app_path() or ""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ZCODE_SESSION", "ZCODE_PLUGIN", "CLAUDE_PLUGIN", "CLAUDE_CODE_SESSION"))}
    env.update(ELECTRON_RUN_AS_NODE="1", ZCODE_MODEL_TELEMETRY_ENABLED="0", NO_COLOR="1")
    builtin = os.path.join(app, "Contents/Resources/config/provider/zcode-builtin.json")
    if os.path.exists(builtin):
        env["ZCODE_BUILTIN_PROVIDER_CONFIG_FILE"] = builtin
    return env


def run_cli(args: List[str], timeout: int = 120) -> Tuple[int, str]:
    try:
        r = subprocess.run(_cli() + args, capture_output=True, text=True, env=_env(), timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as e:
        return 1, str(e)


class AppServer:
    """`zcode app-server`: ZCode's protocol over stdio (one JSON object per line)."""

    def __init__(self, cwd: str):
        self.err = open(os.devnull, "w")
        self.p = subprocess.Popen(_cli() + ["app-server", "--surface", "desktop"], cwd=cwd, env=_env(), text=True,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1)
        self.lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self.tail: List[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()
        self.n = 0

    def _read(self):
        for line in self.p.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _stderr(self):
        for line in self.p.stderr:
            self.tail = (self.tail + [line.rstrip()])[-20:]

    def _send(self, o: dict):
        self.p.stdin.write(json.dumps(o, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def request(self, method: str, params: dict, timeout: float = 120) -> dict:
        self.n += 1
        mid = f"ccx-{self.n}"
        self._send({"id": mid, "method": method, "params": params})
        end = time.time() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                raise RuntimeError(f"ZCode didn't answer {method} in time")
            if line is None:
                raise RuntimeError("ZCode's agent stopped: " + " | ".join(self.tail[-3:]))
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if "method" in o and "id" in o:
                # The server asks the client (normally the desktop app) for its preferences.
                self._send({"id": o["id"], "result": {"nativeSearchEnhancementsEnabled": False}
                            if "RuntimePreferences" in o["method"] else {}})
            elif o.get("id") == mid:
                if o.get("error"):
                    raise RuntimeError(f"ZCode refused {method}: {str(o['error'].get('message'))[:300]}")
                return o.get("result") or {}

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
            self.p.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.p.kill()


def last_model() -> Optional[dict]:
    """The model the user last sent a message with in ZCode (None if never)."""
    rows = _query("select data from message where json_extract(data, '$.role') = 'user' "
                  "and json_extract(data, '$.metadata.migrationSource') is null "
                  "and json_extract(data, '$.modelSelection.modelId') is not null "
                  "order by time_created desc limit 1")
    try:
        sel = json.loads(rows[0]["data"]).get("modelSelection") if rows else None
    except ValueError:
        return None
    return {"providerId": sel["providerId"], "modelId": sel["modelId"]} \
        if isinstance(sel, dict) and sel.get("providerId") and sel.get("modelId") else None


def new_session(cwd: str, title: str, turns: List[Tuple[str, str]]) -> str:
    """A new ZCode conversation in `cwd` holding `turns` as its history (ZCode's own
    import: the messages are real history, not a prompt). Returns its id."""
    cwd = real(cwd)
    if not os.path.isdir(cwd):
        raise RuntimeError(f"the folder {cwd} doesn't exist on this Mac")
    msgs = [{"role": r, "content": t} for r, t in turns if t.strip()]
    if not msgs:
        raise RuntimeError("nothing to import")
    params = {"workspace": {"workspacePath": cwd, "workspaceKey": cwd}, "persistence": "immediate",
              "titleGenerationEnabled": False,
              "importedHistory": {"source": "claudeCode", "title": title, "messages": msgs}}
    model = last_model()
    if model:
        params["model"] = model
    srv = AppServer(cwd)
    try:
        res = srv.request("session/create", params)
    finally:
        srv.close()
    sid = res.get("sessionId") or (res.get("session") or {}).get("sessionId") or next(
        ((m.get("info") or {}).get("sessionId") for m in res.get("messages") or [] if (m.get("info") or {}).get("sessionId")), None)
    if not sid:
        raise RuntimeError("ZCode didn't return the new conversation's id")
    return sid


# ----------------------------------------------------------------- the app

def _pid() -> Optional[int]:
    """The desktop app's main process (its helpers have other names)."""
    app = app_path()
    r = subprocess.run(["pgrep", "-x", PROCESS], capture_output=True, text=True)
    for pid in r.stdout.split():
        try:
            exe = subprocess.run(["ps", "-o", "comm=", "-p", pid], capture_output=True, text=True).stdout.strip()
        except OSError:
            continue
        if not app or exe.startswith(app) or exe == PROCESS:
            return int(pid)
    return None


def running() -> bool:
    return _pid() is not None


def busy() -> bool:
    """A ZCode conversation is mid-turn or has messages queued: restarting the app
    now would interrupt it."""
    cutoff = int((time.time() - 6 * 3600) * 1000)
    return bool(_query(
        "select 1 from session_input where status = 'admitted' limit 1")) or bool(_query(
        "select 1 from message where time_created > ? and json_extract(data, '$.role') = 'assistant' "
        "and json_extract(data, '$.time.completed') is null limit 1", (cutoff,)))


def project_for(cwd: str) -> Optional[dict]:
    """The desktop app's project that has this folder, if it has one."""
    for r in _query("select p.project_id, p.name, r.root_path from projects p join project_roots r using(project_id) "
                    "where p.deleted = 0", path=TASKS):
        if same_dir(r["root_path"], cwd):
            return {"id": r["project_id"], "name": r["name"]}
    return None


def listed(sid: str) -> bool:
    """The desktop app already lists this conversation."""
    return bool(_query("select 1 from tasks where task_id = ? and deleted = 0", (sid,), path=TASKS))


def open_app() -> bool:
    app = app_path()
    return bool(app) and subprocess.run(["open", "-a", app], capture_output=True).returncode == 0


def quit_app(wait: float = 20) -> bool:
    """Quit ZCode the way the app quits itself. A signal, not an Apple Event: no
    automation permission is involved (Electron quits cleanly on SIGTERM)."""
    pid = _pid()
    if pid:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    end = time.time() + wait
    while time.time() < end:
        if not running():
            time.sleep(0.5)  # let its helpers finish writing
            return True
        time.sleep(0.3)
    return False


def set_active_folder(cwd: str) -> bool:
    """Make `cwd` the folder ZCode opens on at its next start (ZCode closed only:
    the app writes this file itself while it runs)."""
    if running():
        return False
    try:
        d = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return False
    w = {"kind": "local", "workspacePath": real(cwd), "workspacePurpose": "project"}
    d["lastActiveWorkspace"] = w
    rest = [x for x in d.get("lastWorkspaceSession") or [] if not (isinstance(x, dict) and same_dir(x.get("workspacePath", ""), cwd))]
    d["lastWorkspaceSession"] = [w] + rest
    tmp = SETTINGS.with_suffix(f".ccx-{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2))
        os.replace(tmp, SETTINGS)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    return True


def restart(cwd: Optional[str] = None) -> bool:
    """(Re)start ZCode on `cwd`, so it lists the conversations created there from
    outside."""
    if running() and not quit_app():
        return False
    if cwd:
        set_active_folder(cwd)
    return open_app()


def show(sid: str, cwd: str) -> str:
    """Bring ZCode up with the conversation in its list. Returns what happened:
    'listed' (it was already there; ZCode is opened), 'launched' (ZCode was
    closed and opens on the folder), 'restarted' (ZCode was idle and was
    restarted on the folder), or 'busy' (ZCode is working on something: nothing
    was done, the caller asks the user)."""
    if listed(sid):
        open_app()
        return "listed"
    if not running():
        restart(cwd)
        return "launched"
    if busy():
        return "busy"
    return "restarted" if restart(cwd) else "busy"


def restart_when_idle(cwd: Optional[str] = None, timeout: float = 4 * 3600, every: float = 10) -> bool:
    """Wait until no ZCode conversation is working, then restart ZCode on `cwd`."""
    end = time.time() + timeout
    while time.time() < end:
        if not running() or not busy():
            return restart(cwd)
        time.sleep(every)
    return False


def ask_restart_when_idle(zh: bool) -> bool:
    """A native dialog: ZCode is busy; restart it once it's done? True = yes."""
    if zh:
        msg = "ZCode 里有任务正在运行。新导入的对话要在 ZCode 重启后才会出现在它的任务列表里。\n\n要在任务完成后自动重启 ZCode 吗？"
        yes, no = "任务完成后重启", "我稍后自己重启"
    else:
        msg = ("A ZCode task is running. The imported conversation shows in ZCode's task list after ZCode restarts."
               "\n\nRestart ZCode automatically once the task is done?")
        yes, no = "Restart when done", "I'll restart it later"
    script = (f'display dialog {json.dumps(msg)} with title "ccx" buttons {{{json.dumps(no)}, {json.dumps(yes)}}} '
              f'default button {json.dumps(yes)} giving up after 120')
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=130)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and yes in r.stdout


def spawn_restart_when_idle(cwd: str):
    """Run restart_when_idle in a detached ccx process (it outlives this one)."""
    ccx = Path(__file__).resolve().parents[2] / "bin/ccx"
    subprocess.Popen([str(ccx), "zcode-restart", "--when-idle", "-C", real(cwd)], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


# ------------------------------------------------------------------ plugin

def plugin_version() -> Optional[str]:
    """The installed ccx plugin's version in ZCode (None when not installed)."""
    code, out = run_cli(["plugins", "list", "--json"], 60)
    if code:
        return None
    try:
        data = json.loads(out[out.find("["):] if out.lstrip()[:1] != "{" else out)
    except ValueError:
        return None
    items = data.get("plugins") if isinstance(data, dict) else data
    for p in items or []:
        if isinstance(p, dict) and str(p.get("id") or "").startswith("ccx@"):
            try:
                return json.loads(Path(p["manifestPath"]).read_text()).get("version") or "?"
            except (OSError, ValueError, KeyError, TypeError):
                return "?"
    return None
