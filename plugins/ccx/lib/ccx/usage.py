"""How much of the 5-hour window Claude and Codex have left. Nothing to configure.

Built in, from what the apps themselves report on this Mac:
- Codex: its app-server's `account/rateLimits/read` (exact percentages).
- Claude: the "You've hit your … limit · resets …" reply Claude Code writes into
  the session file. Claude keeps no other local usage signal, so built in, ccx
  can only tell that the limit was hit, not that it is close.

Usage tools the user already runs fill in the rest, each only when it is found,
and only through its documented output:
- CodexBar: `codexbar usage --provider both --format json` (Claude and Codex).
- abtop: `abtop --json`, its `rate_limits` (Claude, once `abtop --setup` ran, and Codex).
- Claude Code status lines that keep Claude's official limits on disk (Claude):
  claude-hud's `display.externalUsageWritePath` snapshot, the status line input
  Claude Status Bar (claude-code-usage-bar) keeps in
  `~/.cache/claude-statusbar/last_stdin.json`, ccstatusline's usage cache
  (`~/.cache/ccstatusline/usage.json`; written only when it calls the usage API
  itself, i.e. not while Claude Code's own `rate_limits` cover its widgets) and
  CCometixLine's (`~/.claude/ccline/.api_usage_cache.json`). Each only when fresh.
- Agent Sessions: the Claude snapshot its menu bar meter saves, in
  `~/Library/Application Support/com.triada.AgentSessions/claude_usage_latest.json`.
- Claude Code Usage Monitor: the state file `claude-monitor --write-state` keeps
  current, or else a `claude-monitor --once --output json` snapshot (Claude).
- ccusage: `ccusage blocks --json --token-limit max` (Claude; it only knows your
  largest 5-hour block so far, not the real limit, so it never reports "limit").

ccx never estimates usage itself. The menu bar app uses it to suggest moving a task
to the other app before one runs out; hooks never look at it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from . import claude, codex
from .common import HOME, STATE_DIR, which

STATE_FILE = Path(os.environ.get("CCX_CLAUDE_MONITOR_STATE", HOME / ".claude-monitor/state/latest.json"))
CACHE = STATE_DIR / "usage-cache.json"
CLAUDE_HUD_CONFIG = claude.CLAUDE_HOME / "plugins/claude-hud/config.json"
CCSTATUSLINE_CACHE = HOME / ".cache/ccstatusline/usage.json"
CLAUDE_STATUSBAR_STDIN = HOME / ".cache/claude-statusbar/last_stdin.json"
CCOMETIXLINE_CACHE = HOME / ".claude/ccline/.api_usage_cache.json"
AGENT_SESSIONS_SNAPSHOT = HOME / "Library/Application Support/com.triada.AgentSessions/claude_usage_latest.json"
NEAR = 90.0               # percent of the 5-hour window: suggest switching
FRESH = 15 * 60           # an older state file means the monitor isn't running
CLI_EVERY = 5 * 60        # how often to ask a usage tool's CLI (each takes seconds)
CODEX_EVERY = 2 * 60      # how often to ask Codex's app-server


def _epoch(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _window(pct, resets, source: str, now: float, limit_hit=False, near: Optional[bool] = None,
            weekly=False) -> dict:
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
    w = {"level": lvl, "used_percentage": pct, "resets_at_epoch": int(resets) if resets else None, "source": source}
    if weekly:
        w["window"] = "weekly"  # the weekly limit, not the 5-hour one, is what ran out
    return w


def _cached(name: str, every: float, now: float, fetch: Callable[[], object]):
    """fetch()'s result, asked at most once per `every` seconds."""
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(name)
    if isinstance(hit, dict) and 0 <= now - hit.get("taken", 0) < every:
        return hit.get("output")
    out = fetch()
    cache[name] = {"taken": now, "output": out}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    except OSError:
        pass
    return out


def _cli(name: str, args, now: float):
    """A usage tool's JSON output, at most once per CLI_EVERY. Non-zero exits are
    fine (claude-monitor uses them for near/at the limit) as long as JSON came out."""
    exe = which(name)
    if not exe:
        return None

    def run():
        try:
            return json.loads(subprocess.run([exe, *args], capture_output=True, text=True, timeout=90).stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    return _cached(name, CLI_EVERY, now, run)


# ---------------------------------------------------------------- built in

def codex_app(now: float) -> Dict[str, dict]:
    def read():
        try:
            return codex.rate_limits()
        except Exception:  # Codex not installed, signed out, or an older app-server
            return None
    rl = _cached("codex-app-server", CODEX_EVERY, now, read)
    if not isinstance(rl, dict):
        return {}
    five, week = rl.get("primary") or {}, rl.get("secondary") or {}
    if (week.get("usedPercent") or 0) >= 100:  # out for the week: that reset is the one that matters
        return {"codex": _window(100, week.get("resetsAt"), "codex", now, weekly=True)}
    if five.get("usedPercent") is None:
        return {}
    return {"codex": _window(five["usedPercent"], five.get("resetsAt"), "codex", now)}


RESETS = re.compile(r"resets (.+?)(?: \(([^)]+)\))?\s*$")


def _reset_time(text: str, hit_at: float) -> Optional[float]:
    """When Claude says the limit resets: "resets 10:10am (Asia/Shanghai)" or
    "resets Oct 24 at 9am (…)". Times without a date are the next such time."""
    m = RESETS.search(text.strip())
    if not m:
        return None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(m.group(2)) if m.group(2) else None
    except Exception:
        tz = None
    when = m.group(1).replace(" at ", " ").replace(",", "").strip().lower()
    base = datetime.fromtimestamp(hit_at, tz)
    for fmt in ("%I:%M%p", "%I%p", "%b %d %I:%M%p", "%b %d %I%p"):
        try:
            t = datetime.strptime(f"{base.year} {when}", "%Y " + fmt)  # a year, so Feb 29 parses
        except ValueError:
            continue
        dated = "%b" in fmt
        cand = base.replace(month=t.month, day=t.day) if dated else base
        cand = cand.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        while cand.timestamp() <= hit_at:
            cand = cand.replace(year=cand.year + 1) if dated else datetime.fromtimestamp(cand.timestamp() + 86400, tz)
        return cand.timestamp()
    return None


def claude_sessions(now: float) -> Dict[str, dict]:
    hit = claude.last_limit_hit()
    if not hit:
        return {}
    at, text = hit
    weekly = "weekly" in text.lower()
    resets = _reset_time(text, at) or (None if weekly else at + 5 * 3600)
    if resets is None and now - at > 5 * 3600:
        return {}  # no reset time we can read: assume a 5-hour window at most
    return {"claude": _window(100, resets, "claude", now, limit_hit=True, weekly=weekly)}


# ---------------------------------------------------------------- usage tools

def codexbar(now: float) -> Dict[str, dict]:
    out = _cli("codexbar", ["usage", "--provider", "both", "--format", "json", "--json-only"], now)
    found = {}
    for p in out if isinstance(out, list) else [out] if isinstance(out, dict) else []:
        app = p.get("provider") if isinstance(p, dict) else None
        primary = ((p.get("usage") or {}).get("primary") or {}) if app in ("claude", "codex") else {}
        if primary.get("usedPercent") is not None and primary.get("windowMinutes") in (None, 300):
            found[app] = _window(primary["usedPercent"], primary.get("resetsAt"), "codexbar", now)
    return found


def abtop(now: float) -> Dict[str, dict]:
    out = _cli("abtop", ["--json"], now)
    found = {}
    for r in (out.get("rate_limits") if isinstance(out, dict) else None) or []:
        app = r.get("source") if isinstance(r, dict) else None
        if app not in ("claude", "codex"):
            continue
        week = r.get("seven_day_pct")
        if week is not None and week >= 100 and r.get("seven_day_window_minutes") in (None, 10080):
            found[app] = _window(100, r.get("seven_day_resets_at") or None, "abtop", now, weekly=True)
        elif r.get("five_hour_pct") is not None and r.get("five_hour_window_minutes") in (None, 300):
            # resets_at 0 means abtop doesn't know it
            found[app] = _window(r["five_hour_pct"], r.get("five_hour_resets_at") or None, "abtop", now)
    return found


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _claude_window(five, five_reset, week, week_reset, source: str, now: float) -> Dict[str, dict]:
    """Claude's window from a status line's copy of the official limits: the weekly
    one when it is used up, else the 5-hour one."""
    if isinstance(week, (int, float)) and week >= 100:
        return {"claude": _window(100, week_reset, source, now, weekly=True)}
    if not isinstance(five, (int, float)):
        return {}
    return {"claude": _window(five, five_reset, source, now)}


def claude_hud(now: float) -> Dict[str, dict]:
    """The snapshot claude-hud writes "for other local tools" when
    `display.externalUsageWritePath` is set in its config."""
    cfg = _read_json(CLAUDE_HUD_CONFIG)
    target = ((cfg or {}).get("display") or {}).get("externalUsageWritePath") if isinstance(cfg, dict) else None
    if not isinstance(target, str) or not target.strip():
        return {}
    path = Path(os.path.expandvars(os.path.expanduser(target.strip())))
    snap = _read_json(path) if path.is_absolute() else None
    t = _epoch(snap.get("updated_at")) if isinstance(snap, dict) else None
    if t is None or now - t >= FRESH:
        return {}
    five, week = snap.get("five_hour") or {}, snap.get("seven_day") or {}
    return _claude_window(five.get("used_percentage"), five.get("resets_at"), week.get("used_percentage"),
                          week.get("resets_at"), "claude-hud", now)


def claude_statusbar(now: float) -> Dict[str, dict]:
    """Claude Status Bar saves each status line input Claude Code sends it; its
    `rate_limits` are Claude Code's own numbers."""
    try:
        if now - CLAUDE_STATUSBAR_STDIN.stat().st_mtime >= FRESH:
            return {}
    except OSError:
        return {}
    d = _read_json(CLAUDE_STATUSBAR_STDIN)
    rl = d.get("rate_limits") if isinstance(d, dict) else None
    if not isinstance(rl, dict):
        return {}
    five, week = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    return _claude_window(five.get("used_percentage"), five.get("resets_at"), week.get("used_percentage"),
                          week.get("resets_at"), "claude-statusbar", now)


def ccstatusline(now: float) -> Dict[str, dict]:
    """ccstatusline's cache of Claude's usage, kept while its usage widgets are on."""
    path = CCSTATUSLINE_CACHE
    try:
        if now - path.stat().st_mtime >= FRESH:
            return {}
    except OSError:
        return {}
    d = _read_json(path)
    if not isinstance(d, dict) or d.get("error"):
        return {}
    return _claude_window(d.get("sessionUsage"), d.get("sessionResetAt"), d.get("weeklyUsage"),
                          d.get("weeklyResetAt"), "ccstatusline", now)


def ccometixline(now: float) -> Dict[str, dict]:
    """CCometixLine's usage cache. Its one reset time is the weekly window's, so
    the 5-hour reset stays unknown."""
    d = _read_json(CCOMETIXLINE_CACHE)
    t = _epoch(d.get("cached_at")) if isinstance(d, dict) else None
    if t is None or now - t >= FRESH:
        return {}
    return _claude_window(d.get("five_hour_utilization"), None, d.get("seven_day_utilization"),
                          d.get("resets_at"), "ccometixline", now)


def agent_sessions(now: float) -> Dict[str, dict]:
    """The Claude snapshot the Agent Sessions app keeps for its next start. Its
    ratios run 0...1; reset times are ISO instants, except from its tmux fallback
    (a localized string, so the reset stays unknown)."""
    d = _read_json(AGENT_SESSIONS_SNAPSHOT)
    t = _epoch(d.get("fetchedAt")) if isinstance(d, dict) else None
    if t is None or now - t >= FRESH or d.get("health") == "failed" or d.get("source") == "unavailable":
        return {}
    pct = lambda r: r * 100 if isinstance(r, (int, float)) else None
    return _claude_window(pct(d.get("fiveHourUsedRatio")), d.get("fiveHourResetText"), pct(d.get("weeklyUsedRatio")),
                          d.get("weeklyResetText"), "agent-sessions", now)


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


# Most exact first. Built in for Claude only reports a hit limit, so the tools,
# which can also see it coming, are asked when it hasn't been hit.
SOURCES = (codex_app, claude_sessions, codexbar, abtop, claude_hud, claude_statusbar, agent_sessions, ccstatusline, ccometixline,
           claude_monitor, ccusage)


def _newest(app: str) -> Optional[dict]:
    try:
        s = (claude.sessions() if app == "claude" else codex.threads(limit=1))[:1]
    except Exception:  # Codex missing or busy: no shortcut, the notification still says enough
        return None
    return {"id": s[0].id, "title": s[0].title, "cwd": s[0].cwd} if s else None


def usage(now: Optional[float] = None) -> dict:
    """{"available": False} when nothing reports usage; otherwise each app's window
    from the most exact source that knows it and, when one is close to running out,
    its newest session to continue in the other app."""
    now = time.time() if now is None else now
    found: Dict[str, dict] = {}
    for source in SOURCES:
        if all(found.get(a, {}).get("level", "unknown") != "unknown" for a in ("claude", "codex")):
            break
        for app, w in source(now).items():
            if found.get(app, {}).get("level", "unknown") == "unknown":
                found[app] = w
    if not found:
        return {"available": False}
    out = {"available": True, **found}
    # The one to act on: a used-up window first, then Claude.
    other = {"claude": "codex", "codex": "claude"}
    for app in sorted((a for a in found if found[a]["level"] in ("near", "limit")
                       and found.get(other[a], {}).get("level") != "limit"),  # no use moving to a side that's out too
                      key=lambda a: (found[a]["level"] != "limit", a != "claude")):
        s = _newest(app)
        if s:
            out["switch"] = {"from": app, "session": s}
            break
    return out
