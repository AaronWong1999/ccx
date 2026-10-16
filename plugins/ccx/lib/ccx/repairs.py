"""Retry native history migration after the desktop releases an old thread.

Never stop Codex, edit its database, or replace a user's active conversation.
The menu bar's normal refresh retries one queued thread per minute.
"""
from __future__ import annotations

import fcntl
import json
import time
import uuid

from . import codex
from .common import STATE_DIR

ROOT = STATE_DIR / "history-repairs"


def prepare(tid: str) -> str:
    # IDs are native UUIDs; validate before constructing a filename.
    tid = str(uuid.UUID(tid))
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "repair.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        status = codex.ensure_paginated_history(tid)
        p = ROOT / (tid + ".json")
        if status == "ready":
            p.unlink(missing_ok=True)
        else:
            p.write_text(json.dumps({"thread_id": tid, "status": status, "attempted_at": time.time()}))
    return status


def pending() -> list:
    out = []
    for p in ROOT.glob("*.json"):
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return out


def retry_pending() -> list:
    for row in pending():
        if time.time() - row.get("attempted_at", 0) < 60:
            continue
        try:
            prepare(row["thread_id"])
        except (RuntimeError, OSError, ValueError, TimeoutError) as e:
            # Back off failed rows too, so one bad thread doesn't starve others.
            row.update(attempted_at=time.time(), error=str(e))
            (ROOT / (str(uuid.UUID(row["thread_id"])) + ".json")).write_text(json.dumps(row))
        break
    return pending()
