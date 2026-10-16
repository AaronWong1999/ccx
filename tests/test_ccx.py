"""Unit tests for ccx. Runs without Claude or Codex installed: Claude sessions
are written to a temp dir and Codex's app-server API is replaced by a fake.

    python3 -m unittest discover -s tests
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix="ccx-test-")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(TMP, "claude")
os.environ["CCX_HOME"] = os.path.join(TMP, "state")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/ccx/lib"))

from ccx import claude, codex, hook, mcp_server, pairs, sync  # noqa: E402
from ccx.common import TAG, Session  # noqa: E402

PROJ_A = os.path.join(TMP, "proj-a")
PROJ_B = os.path.join(TMP, "proj-b")
os.makedirs(PROJ_A)
os.makedirs(PROJ_B)


def claude_file(cwd, sid, records, title=None):
    d = claude.project_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sid}.jsonl"
    with open(p, "w") as f:
        for r in records:
            f.write(json.dumps({"cwd": cwd, "sessionId": sid, **r}, ensure_ascii=False) + "\n")
        if title:
            f.write(json.dumps({"type": "custom-title", "customTitle": title}) + "\n")
    return p


def user(text, **kw):
    return {"type": "user", "message": {"role": "user", "content": text}, **kw}


def assistant(*blocks, **kw):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}, **kw}


def text(t):
    return {"type": "text", "text": t}


class FakeCodex:
    """Stands in for Codex's app-server: threads with items, and a growing rollout size."""

    def __init__(self):
        self.threads = {}

    def add(self, tid, cwd, title, items):
        self.threads[tid] = {"cwd": cwd, "title": title, "items": list(items)}

    def append(self, tid, *items):
        self.threads[tid]["items"] += items

    def find(self, tid):
        t = self.threads.get(tid)
        return Session("codex", tid, t["cwd"], 1000.0 + len(t["items"]), t["title"], Path(f"/fake/{tid}")) if t else None

    def items(self, tid):
        return list(self.threads[tid]["items"])

    def size_of(self, s):
        return len(self.threads[s.id]["items"]) * 100 if s and s.id in self.threads else -1

    def list(self, cwd=None, query=None, limit=60):
        out = [self.find(t) for t in self.threads
               if (not cwd or self.threads[t]["cwd"] == cwd) and (not query or query in self.threads[t]["title"])]
        return out[:limit]

    def patch(self, test):
        for name, fn in (("find", self.find), ("items", self.items), ("size_of", self.size_of),
                         ("threads", self.list), ("import_history", lambda: {}), ("hooks_trusted", lambda: None)):
            p = mock.patch.object(codex, name, fn)
            p.start()
            test.addCleanup(p.stop)


def umsg(t):
    return {"type": "userMessage", "content": [{"type": "text", "text": t}]}


def amsg(t):
    return {"type": "agentMessage", "text": t}


class Base(unittest.TestCase):
    def setUp(self):
        pairs.PAIRS.unlink(missing_ok=True)
        self.cx = FakeCodex()
        self.cx.patch(self)


class ClaudeUnits(Base):
    def test_filters_injected_marker_and_own_tools(self):
        p = claude_file(PROJ_A, "c-units", [
            user("把登录页做完"),
            user("<system-reminder>ignore me</system-reminder>"),
            user("synthetic", ccxImported=True),
            user("meta", isMeta=True),
            assistant(text("好的，我先看代码"), {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"cmd": "ls"}}),
            user([{"type": "tool_result", "tool_use_id": "t1", "content": "a.py"}]),
            assistant({"type": "tool_use", "id": "t2", "name": "mcp__plugin_ccx_ccx__continue_here", "input": {}}),
            user([{"type": "tool_result", "tool_use_id": "t2", "content": f"<{TAG}>stuff</{TAG}>"}]),
            assistant(text(f"<{TAG}>echo</{TAG}>")),
        ])
        us = claude.units(p)
        self.assertEqual(len(us), 9)  # cursor counts every user/assistant record
        live = [u for u in us if u]
        self.assertEqual(live[0], ("user", "把登录页做完"))
        self.assertIn("好的，我先看代码", live[1][1])
        self.assertIn("[tool Bash]", live[1][1])
        self.assertIn("[result] a.py", live[2][1])
        self.assertEqual(len(live), 3)

    def test_keeps_text_after_prepended_reminder(self):
        p = claude_file(PROJ_A, "c-reminder", [
            user("<system-reminder>\nThis conversation is now continuing…\n</system-reminder>\n\n暗号是什么？"),
            user([text("<system-reminder>only a reminder</system-reminder>"), text("第二句")]),
            user('<system-reminder>x</system-reminder>\n<cross-session-message from="s1">\n转发来的话\n</cross-session-message>'),
        ])
        self.assertEqual([u for u in claude.units(p) if u],
                         [("user", "暗号是什么？"), ("user", "第二句"), ("user", "转发来的话")])

    def test_find_across_projects_and_title_search(self):
        claude_file(PROJ_B, "c-elsewhere-1234", [user("微信支付接入")], title="微信支付接入需求确认")
        s = claude.find("c-elsewhere")
        self.assertEqual(s.cwd, PROJ_B)
        self.assertEqual([x.id for x in claude.sessions(query="支付 需求")], ["c-elsewhere-1234"])
        self.assertTrue(claude.matches("「微信支付」", "微信支付接入需求确认"))
        self.assertFalse(claude.matches("支付宝", "微信支付接入需求确认"))


class CodexUnits(Base):
    def test_render_and_filter(self):
        us = codex.units([
            umsg("记住暗号 蓝鲸-42"),
            umsg("<environment_context>x</environment_context>"),
            {"type": "reasoning"},
            {"type": "hookPrompt", "text": "injected"},
            amsg("已记住"),
            {"type": "commandExecution", "command": "ls", "aggregatedOutput": "a.py\n"},
            {"type": "mcpToolCall", "server": "ccx", "tool": "continue_here", "arguments": {}, "result": {}},
            {"type": "mcpToolCall", "server": "github", "tool": "search", "arguments": {"q": 1}, "result": {"content": [text("ok")]}},
            {"type": "fileChange", "changes": [{"path": "src/a.py"}]},
        ])
        live = [u for u in us if u]
        self.assertEqual(live[0], ("user", "记住暗号 蓝鲸-42"))
        self.assertEqual(live[1], ("assistant", "已记住"))
        self.assertIn("[ran] ls", live[2][1])
        self.assertIn("github.search", live[3][1])
        self.assertIn("src/a.py", live[4][1])
        self.assertEqual(len(live), 5)
        self.assertEqual(len(us), 9)

    def test_turns_for_claude_alternate(self):
        turns = codex.turns_for_claude([amsg("orphan"), umsg("q1"), amsg("a1"), amsg("a2"), umsg("q2")])
        self.assertEqual([r for r, _ in turns], ["user", "assistant", "user"])
        self.assertIn("a2", turns[1][1])


class PairsSync(Base):
    def make_pair(self):
        claude_file(PROJ_A, "c-pair", [user("开始任务"), assistant(text("收到"))], title="任务 A")
        self.cx.add("x-pair", PROJ_A, "任务 A", [umsg("开始任务"), amsg("收到")])
        pairs.link(pairs.side("claude", "c-pair"), pairs.side("codex", "x-pair"))

    def test_codex_progress_reaches_claude_once(self):
        self.make_pair()
        self.assertIsNone(pairs.pull("claude", "c-pair"))  # nothing new yet
        self.cx.append("x-pair", umsg("记住暗号 蓝鲸-42"), amsg("已记住"))
        res = pairs.pull("claude", "c-pair")
        self.assertEqual(res["count"], 2)
        self.assertIn("蓝鲸-42", res["context"])
        self.assertTrue(res["context"].startswith(f"<{TAG}"))
        self.assertIsNone(pairs.pull("claude", "c-pair"))  # delivered exactly once

    def test_claude_progress_reaches_codex_and_no_echo(self):
        self.make_pair()
        p = claude.find("c-pair").path
        with open(p, "a") as f:
            # what the hook injection looks like in a Claude transcript: an attachment, not a turn
            f.write(json.dumps({"type": "attachment", "attachment": {"type": "hook_additional_context",
                                                                      "content": [f"<{TAG}>x</{TAG}>"]}}) + "\n")
            f.write(json.dumps(user("Codex 那边的暗号是什么")) + "\n")
            f.write(json.dumps(assistant(text("蓝鲸-42"))) + "\n")
        res = pairs.pull("codex", "x-pair")
        self.assertEqual(res["count"], 2)
        self.assertIn("暗号是什么", res["context"])
        # the Codex side receives it as a hookPrompt item, which must not bounce back
        self.cx.append("x-pair", {"type": "hookPrompt", "text": res["context"]})
        self.assertIsNone(pairs.pull("claude", "c-pair"))

    def test_status(self):
        self.make_pair()
        self.assertEqual(pairs.status(claude.find("c-pair"))[0], "linked")
        self.cx.append("x-pair", amsg("新进展"))
        self.assertEqual(pairs.status(self.cx.find("x-pair"))[0], "updated")
        pairs.pull("claude", "c-pair")
        self.assertEqual(pairs.status(self.cx.find("x-pair"))[0], "linked")

    def test_continue_from_other_folder_warns(self):
        claude_file(PROJ_A, "c-here", [user("新对话")])
        self.cx.add("x-there", PROJ_B, "B 项目的任务", [umsg("在 B 里做事"), amsg("做完了一半")])
        res = pairs.continue_from("claude", "c-here", PROJ_A, "x-there")
        self.assertIn("whole conversation", res["context"])
        self.assertIn("做完了一半", res["context"])
        self.assertIn("different folder", res["context"])
        self.assertIn(PROJ_B, res["context"])
        pair = pairs.find("claude", "c-here")
        self.assertEqual(pair["codex"]["id"], "x-there")
        self.assertIsNone(pairs.pull("claude", "c-here"))

    def test_relink_replaces_old_pair(self):
        self.make_pair()
        self.cx.add("x-new", PROJ_A, "新线程", [umsg("hi")])
        pairs.continue_from("codex", "x-new", PROJ_A, "c-pair")
        self.assertEqual(pairs.find("claude", "c-pair")["codex"]["id"], "x-new")
        self.assertIsNone(pairs.find("codex", "x-pair"))

    def test_task_list_survives_budget_and_interruption_is_flagged(self):
        p = claude_file(PROJ_A, "c-plan", [
            user("重构登录模块"),
            assistant({"type": "tool_use", "id": "p1", "name": "TodoWrite", "input": {"todos": [
                {"content": "拆分 auth.py", "status": "completed"},
                {"content": "补测试", "status": "in_progress"},
                {"content": "更新文档", "status": "pending"}]}}),
        ] + [assistant(text(f"第 {i} 步" * 40)) for i in range(30)] + [
            assistant({"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "pytest tests/test_auth.py"}}),
        ])
        out = pairs.render([u for u in claude.units(p) if u], "claude", budget=2000)
        self.assertIn("Latest task list", out)
        self.assertIn("[~] 补测试", out)
        self.assertIn("[ ] 更新文档", out)
        self.assertIn("stopped in the middle of a step", out)
        self.assertIn("pytest tests/test_auth.py", out)

    def test_codex_plan_kept(self):
        us = codex.units([umsg("做个页面"), {"type": "plan", "text": "1. 布局 ✓\n2. 样式"}, amsg("开始写样式")])
        out = pairs.render([u for u in us if u], "codex", budget=10_000)
        self.assertIn("2. 样式", out)
        self.assertNotIn("stopped in the middle", out)

    def test_render_budget_keeps_newest(self):
        items = [("user", f"问题{i}") for i in range(50)] + [("assistant", "最后的回答")]
        out = pairs.render(items, "codex", budget=60)
        self.assertIn("最后的回答", out)
        self.assertIn("omitted", out)


class Interfaces(Base):
    def test_hook_injects_only_for_paired_sessions(self):
        claude_file(PROJ_A, "c-hook", [user("hi")], title="hook")
        self.cx.add("x-hook", PROJ_A, "hook", [umsg("hi")])
        pairs.link(pairs.side("claude", "c-hook"), pairs.side("codex", "x-hook"))
        self.cx.append("x-hook", amsg("Codex 做了新东西"))
        for sid, expect in (("c-hook", True), ("someone-else", False)):
            out = io.StringIO()
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"session_id": sid}))), \
                    redirect_stdout(out), self.assertRaises(SystemExit):
                hook.main()
            if expect:
                ctx = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
                self.assertIn("Codex 做了新东西", ctx)
            else:
                self.assertEqual(out.getvalue(), "")

    def test_mcp_continue_here_search_then_link(self):
        claude_file(PROJ_A, "c-mcp", [user("新对话")])
        self.cx.add("x-login", PROJ_B, "百度登录页面", [umsg("打开百度登录页"), amsg("找到了")])
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "c-mcp"}):
            listing = mcp_server.call("claude", "continue_here", {"cwd": PROJ_A, "query": "登录"})
            self.assertIn("百度登录页面", listing)
            self.assertIn("x-login", listing)
            self.assertIn("differs from yours", listing)
            done = mcp_server.call("claude", "continue_here", {"cwd": PROJ_A, "session_id": "x-login"})
            self.assertIn("找到了", done)
            again = mcp_server.call("claude", "continue_here", {"cwd": PROJ_A})
            self.assertIn("Nothing new", again)

    def test_mcp_protocol(self):
        tools = {t["name"] for t in mcp_server.tools("codex")}
        self.assertEqual(tools, {"continue_here", "list_sessions", "send_current_session"})

    def test_transfer_creates_pair_then_reopens(self):
        claude_file(PROJ_A, "c-xfer", [user("做个页面"), assistant(text("好"))], title="做个页面")
        self.cx.add("x-imported", PROJ_A, "做个页面", [umsg("做个页面"), amsg("好")])
        with mock.patch.object(sync, "_import_to_codex", lambda s: "x-imported"):
            first = sync.transfer("claude", "c-xfer", open_app=False)
            second = sync.transfer("claude", "c-xfer", open_app=False)
        self.assertEqual(first["action"], "created")
        self.assertEqual(second["action"], "linked")
        self.assertEqual(second["target"]["id"], "x-imported")


if __name__ == "__main__":
    unittest.main()
