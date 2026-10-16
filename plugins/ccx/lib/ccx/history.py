"""Local, readable history independent of the desktop's pagination UI."""
from __future__ import annotations

from . import pairs
from .common import NAME


def read_page(tool: str, sid: str, offset: int = 0, limit: int = 6000) -> dict:
    """Read without moving sync cursors; offsets are characters in rendered text."""
    src, units = pairs.session_units(tool, sid, include_imported=True)
    if not src:
        raise RuntimeError(f"{NAME[tool]} session {sid} not found")
    body = "\n\n".join(f"[{NAME[tool] if u[0] == 'assistant' else 'user'}] {u[1]}" for u in units if u)
    start = max(0, min(int(offset), len(body)))
    end = min(len(body), start + max(1, min(int(limit), 12000)))
    return {"title": src.title, "cwd": src.cwd, "text": body[start:end], "offset": start,
            "next_offset": end if end < len(body) else None, "total_chars": len(body)}
