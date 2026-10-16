"""Local, readable history independent of the desktop's pagination UI."""
from __future__ import annotations

import html
import time

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


def export_linked() -> str:
    sections = []
    for pair in pairs.load():
        for tool in ("claude", "codex"):
            try:
                src, units = pairs.session_units(tool, pair[tool]["id"], include_imported=True)
                if not src:
                    continue
                body = "\n\n".join(f"[{NAME[tool] if u[0] == 'assistant' else 'user'}] {u[1]}" for u in units if u)
                sections.append(f"<details open><summary>{html.escape(NAME[tool] + ' · ' + src.title)}</summary>"
                                f"<p>{html.escape(src.cwd)}</p><pre>{html.escape(body)}</pre></details>")
            except (RuntimeError, TimeoutError) as e:
                sections.append("<p>Could not read history: " + html.escape(str(e)) + "</p>")
    # A throwaway snapshot (rewritten on each export, in the temp folder): the
    # conversations themselves stay in the two apps; nothing accumulates here.
    import tempfile
    from pathlib import Path
    path = Path(tempfile.gettempdir()) / "ccx-linked-history.html"
    path.write_text("<!doctype html><meta charset='utf-8'><title>ccx · Linked history</title>"
                    "<style>body{max-width:960px;margin:40px auto;padding:0 24px;font:15px/1.6 system-ui}"
                    "pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}"
                    "summary{cursor:pointer;font-weight:650}details{border-top:1px solid #aaa;padding:16px 0}"
                    "p{color:#666}</style><h1>ccx · Linked history</h1>"
                    "<p>Snapshot · " + time.strftime("%Y-%m-%d %H:%M:%S") + "</p>"
                    "<p>Synced progress is model context, not additional native chat bubbles. "
                    "This local snapshot lets you read both sources. Tool output is condensed.</p>"
                    + ("".join(sections) or "<p>No linked sessions.</p>"), encoding="utf-8")
    return str(path)
