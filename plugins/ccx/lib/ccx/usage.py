"""Optional: how much of the 5-hour window Claude and Codex have left, read from
usage tools the user already runs. Nothing to configure: each one is used only
when it is found on this Mac, and only through its documented output.

- CodexBar: `codexbar usage --provider both --format json` (Claude and Codex).
- Claude Code Usage Monitor: the state file `claude-monitor --write-state` keeps
  current, or else a `claude-monitor --once --output json` snapshot (Claude).
- ccusage: `ccusage blocks --json --token-limit max` (Claude; it only knows your
  largest 5-hour block so far, not the real limit, so it never reports "limit").

ccx never estimates usage itself. Without any of them this reports nothing and
nothing else in ccx changes. The menu bar app uses it to suggest moving a task
to the other app before one runs out; hooks never look at it.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from . import claude, codex
from .common import HOME, STATE_DIR, which

STATE_FILE = Path(os.environ.get("CCX_CLAUDE_MONITOR_STATE", HOME / ".claude-monitor/state/latest.json"))
CACHE = STATE_DIR / "usage-cache.json"
NEAR = 90.0               # percent of the 5-hour window: suggest switching
FRESH = 15 * 60           # an older state file means the monitor isn't running
CLI_EVERY = 5 * 60        # how often to ask a usage tool's CLI (each takes seconds)


def _epoch(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _window(pct, resets, source: str, now: float, limit_hit=False, near: Optional[bool] = None) -> dict:
    """One app's 5-hour window: ok, near (>= NEAR %), limit, or unknown."""
    resets = _epoch(resets)
    if resets is not None and resets <= now:
        lvl = "unknown"  # the window it describes is already over
    elif limit_hit or (pct is not None and pct >= 100):
        lvl = "limit"
    elif near or (pct is not None and pct >= NEAR):
        lvl = "near"
    else:
        lvl = "ok" if pct is not None or near is not None else "unknown"
    return {"level": lvl, "used_percentage": pct, "resets_at_epoch": int(resets) if resets else None, "source": source}


def _cli(name: str, args, now: float):
    """A usage tool's JSON output, at most once per CLI_EVERY. Non-zero exits are
    fine (claude-monitor uses them for near/at the limit) as long as JSON came out."""
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(name)
    if isinstance(hit, dict) and now - hit.get("taken", 0) < CLI_EVERY:
        return hit.get("output")
    exe = which(name)
    if not exe:
        return None
    try:
        out = json.loads(subprocess.run([exe, *args], capture_output=True, text=True, timeout=90).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        out = None
    cache[name] = {"taken": now, "output": out}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- sources

def codexbar(now: float) -> Dict[str, dict]:
    out = _cli("codexbar", ["usage", "--provider", "both", "--format", "json", "--json-only"], now)
    found = {}
    for p in out if isinstance(out, list) else [out] if isinstance(out, dict) else []:
        app = p.get("provider") if isinstance(p, dict) else None
        primary = ((p.get("usage") or {}).get("primary") or {}) if app in ("claude", "codex") else {}
        if primary.get("usedPercent") is not None and primary.get("windowMinutes") in (None, 300):
            found[app] = _window(primary["usedPercent"], primary.get("resetsAt"), "codexbar", now)
    return found


def claude_monitor(now: float) -> Dict[str, dict]:
    try:
        snap = json.loads(STATE_FILE.read_text())
        t = _epoch(snap.get("generated_at"))
        if t is None or now - t >= FRESH:
            snap = None
    except (OSError, ValueError, AttributeError):
        snap = None
    if snap is None:
        snap = _cli("claude-monitor", ["--once", "--output", "json"], now)
    if not isinstance(snap, dict) or snap.get("stale"):
        return {}
    five = (snap.get("limits") or {}).get("five_hour") or {}
    if five.get("used_percentage") is None:
        return {}
    limit_hit = (snap.get("status") or {}).get("label") == "limit_hit"
    return {"claude": _window(five["used_percentage"], five.get("resets_at_epoch") or five.get("resets_at"),
                              "claude-monitor", now, limit_hit=limit_hit)}


def ccusage(now: float) -> Dict[str, dict]:
    out = _cli("ccusage", ["blocks", "--json", "--token-limit", "max", "--offline"], now)
    blocks = out.get("blocks") if isinstance(out, dict) else None
    active = next((b for b in blocks or [] if isinstance(b, dict) and b.get("isActive")), None)
    status = (active or {}).get("tokenLimitStatus") or {}
    if not status.get("status"):
        return {}
    # Projected past your largest 5-hour block so far: a hint, never "used up".
    return {"claude": _window(None, active.get("endTime"), "ccusage", now,
                              near=status["status"] in ("warning", "exceeds"))}


SOURCES = (codexbar, claude_monitor, ccusage)   # most exact first


def _newest(app: str) -> Optional[dict]:
    try:
        s = (claude.sessions() if app == "claude" else codex.threads(limit=1))[:1]
    except Exception:  # Codex missing or busy: no shortcut, the notification still says enough
        return None
    return {"id": s[0].id, "title": s[0].title, "cwd": s[0].cwd} if s else None


def usage(now: Optional[float] = None) -> dict:
    """{"available": False} without any usage tool; otherwise each app's window that
    one of them reports and, when one is close to running out, its newest session
    to continue in the other app."""
    now = time.time() if now is None else now
    found: Dict[str, dict] = {}
    for source in SOURCES:
        if "claude" in found and "codex" in found:
            break
        for app, w in source(now).items():
            found.setdefault(app, w)
    if not found:
        return {"available": False}
    out = {"available": True, **found}
    # The one to act on: a used-up window first, then Claude.
    for app in sorted((a for a in found if found[a]["level"] in ("near", "limit")),
                      key=lambda a: (found[a]["level"] != "limit", a != "claude")):
        s = _newest(app)
        if s:
            out["switch"] = {"from": app, "session": s}
            break
    return out
