"""Import a Claude Code session into Codex via Codex's own app-server importer."""

from __future__ import annotations

import json
import select
import subprocess
import time

from . import __version__


class AppServer:
    def __init__(self):
        self.p = subprocess.Popen(
            ["codex", "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._id = 0
        self.notifications: list[dict] = []
        self.request("initialize", {"clientInfo": {"name": "claudecodex", "version": __version__}})
        self._send({"method": "initialized"})

    def _send(self, obj: dict):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def _read(self, timeout: float) -> dict | None:
        r, _, _ = select.select([self.p.stdout], [], [], timeout)
        if not r:
            return None
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("codex app-server 意外退出")
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
                    raise RuntimeError(f"{method} 失败: {msg['error']}")
                return msg.get("result") or {}
            if "method" in msg:
                self.notifications.append(msg)
        raise TimeoutError(f"{method} 超时")

    def wait_notification(self, method: str, match, timeout: float = 120) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            for n in self.notifications:
                if n.get("method") == method and match(n.get("params") or {}):
                    return n["params"]
            msg = self._read(1)
            if msg and "method" in msg:
                self.notifications.append(msg)
        raise TimeoutError(f"等待 {method} 超时")

    def close(self):
        self.p.kill()


def import_claude_session(path: str, cwd: str, title: str | None) -> dict:
    """Returns the success record from Codex (contains source/target), or raises."""
    srv = AppServer()
    try:
        item = {
            "itemType": "SESSIONS",
            "description": f"Import Claude Code session {path}",
            "cwd": None,
            "details": {"sessions": [{"cwd": cwd, "path": path, "title": title or None}]},
        }
        res = srv.request("externalAgentConfig/import", {"migrationItems": [item], "source": "claudecodex"})
        import_id = res["importId"]
        done = srv.wait_notification(
            "externalAgentConfig/import/completed", lambda p: p.get("importId") == import_id
        )
        for r in done.get("itemTypeResults", []):
            if r.get("itemType") != "SESSIONS":
                continue
            if r.get("failures"):
                f = r["failures"][0]
                raise RuntimeError(f"Codex 导入失败（{f.get('failureStage')}）: {f.get('message')}")
            if r.get("successes"):
                return r["successes"][0]
        raise RuntimeError(f"Codex 没有返回导入结果: {done}")
    finally:
        srv.close()
