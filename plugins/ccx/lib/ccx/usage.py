"""Optional: Claude's 5-hour usage from Claude Code Usage Monitor (`claude-monitor`).

Read only through its state/export protocol: the state file that
`claude-monitor --write-state` keeps current, or else one
`claude-monitor --once --output json` snapshot (cached, it takes a few seconds).
ccx never estimates usage itself. Without claude-monitor this reports nothing,
and nothing else in ccx changes. The menu bar app uses it to suggest moving to
Codex when Claude is about to run out; hooks never look at it.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import claude
from .common import HOME, STATE_DIR, which

STATE_FILE = Path(os.environ.get("CCX_CLAUDE_MONITOR_STATE", HOME / ".claude-monitor/state/latest.json"))
CACHE = STATE_DIR / "claude-usage.json"
NEAR = 90.0               # percent of the 5-hour window: suggest switching
FRESH = 15 * 60           # an older state file means the monitor isn't running
CLI_EVERY = 5 * 60        # how often to take a one-shot snapshot without a state file


def _epoch(iso) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _fresh(snap, now: float) -> bool:
    t = _epoch(snap.get("generated_at")) if isinstance(snap, dict) else None
    return t is not None and now - t < FRESH


def _from_state_file(now: float) -> Optional[dict]:
    try:
        snap = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None
    return snap if _fresh(snap, now) else None


def _from_cli(now: float) -> Optional[dict]:
    try:
        cached = json.loads(CACHE.read_text())
        if now - cached["taken"] < CLI_EVERY:
            return cached["snapshot"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    exe = which("claude-monitor")
    if not exe:
        return None
    try:
        # Exit status 10/11 means near/at the limit; the JSON is printed either way.
        out = subprocess.run([exe, "--once", "--output", "json"], capture_output=True, text=True, timeout=60).stdout
        snap = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        snap = None
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"taken": now, "snapshot": snap}))
    except OSError:
        pass
    return snap


def level(snap: dict, now: float) -> dict:
    """The 5-hour window from one snapshot: ok, near (>= NEAR %) or limit."""
    five = (snap.get("limits") or {}).get("five_hour") or {}
    pct = five.get("used_percentage")
    resets = five.get("resets_at_epoch") or _epoch(five.get("resets_at"))
    label = (snap.get("status") or {}).get("label")
    if snap.get("stale") or (resets is not None and resets <= now):
        lvl = "unknown"  # old data, or the window it describes is already over
    elif label == "limit_hit" or (pct is not None and pct >= 100):
        lvl = "limit"
    elif pct is not None and pct >= NEAR:
        lvl = "near"
    elif pct is None:
        lvl = "unknown"
    else:
        lvl = "ok"
    return {"level": lvl, "used_percentage": pct, "resets_at_epoch": int(resets) if resets else None,
            "confidence": five.get("confidence") or snap.get("confidence")}


def claude_usage(now: Optional[float] = None) -> dict:
    """{"available": False} without claude-monitor; otherwise the 5-hour window's level
    and the newest Claude session, the one to continue in Codex."""
    now = time.time() if now is None else now
    snap, source = _from_state_file(now), "state_file"
    if snap is None:
        snap, source = _from_cli(now), "claude-monitor"
    if not isinstance(snap, dict):
        return {"available": False}
    out = {"available": True, "source": source, **level(snap, now)}
    if out["level"] in ("near", "limit"):
        latest = claude.sessions()[:1]
        if latest:
            out["session"] = {"id": latest[0].id, "title": latest[0].title, "cwd": latest[0].cwd}
    return out
