"""Unit tests for ccx. Runs without Claude or Codex installed: Claude sessions
are written to a temp dir and Codex's app-server API is replaced by a fake.

    python3 -m unittest discover -s tests
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

TMP = tempfile.mkdtemp(prefix="ccx-test-")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(TMP, "claude")
os.environ["CCX_HOME"] = os.path.join(TMP, "state")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/ccx/lib"))

from ccx import claude, codex, hook, mcp_server, pairs, repairs, sync  # noqa: E402
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
        p = mock.patch.object(codex, "ensure_thread_project", return_value="project-test")
        p.start()
        test.addCleanup(p.stop)
        p = mock.patch.object(codex, "register_desktop_workspace", return_value=False)
        p.start()
        test.addCleanup(p.stop)
        p = mock.patch.object(repairs, "prepare", return_value="ready")
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

    def test_project_is_the_folder_it_is_filed_under(self):
        # Started in a scratch folder, moved to PROJ_A, shell wandered into sub-folders.
        d = claude.project_dir(PROJ_A)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "c-moved.jsonl", "w") as f:
            for c in ("/tmp/scratch-123", PROJ_A, os.path.join(PROJ_A, "lib"), "/tmp/scratch-123", os.path.join(PROJ_A, "menubar")):
                f.write(json.dumps({"type": "user", "cwd": c, "message": {"role": "user", "content": "hi"}}) + "\n")
        self.assertEqual(claude.find("c-moved").cwd, PROJ_A)
        self.assertIn("c-moved", [x.id for x in claude.sessions(PROJ_A)])

    def test_normalized_copy_for_codex_import(self):
        p = claude_file("/tmp/scratch-xyz", "c-scratch", [user("从临时目录开始"), assistant(text("好"))])
        cp = claude.copy_with_new_id(p, PROJ_A)
        try:
            recs = [json.loads(l) for l in cp.read_text().splitlines()]
            self.assertTrue(all(r["cwd"] == PROJ_A for r in recs if "cwd" in r))
            self.assertEqual(cp.parent, claude.project_dir(PROJ_A))
            self.assertNotEqual(recs[0]["sessionId"], "c-scratch")
        finally:
            cp.unlink()

    def test_pasted_content_and_slash_command_args_are_kept(self):
        from ccx.common import user_text
        self.assertIn("做一套交易界面", user_text('\n\n<pasted_content id="0320">\n在仓库里做一套交易界面\n</pasted_content id="0320">'))
        self.assertEqual(user_text("<command-name>/goal</command-name>\n<command-message>goal</command-message>\n"
                                   "<command-args>修好 to codex</command-args>"), "/goal 修好 to codex")
        self.assertNotIn("pasted_content", user_text('<pasted_content id="a1">x</pasted_content id="a1">'))
        self.assertEqual(user_text("<environment_context><cwd>/x</cwd></environment_context>"), "")
        self.assertEqual(user_text("<local-command-stdout>Goal set</local-command-stdout>"), "")

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

    def test_failed_context_generation_does_not_consume_progress(self):
        for target, sid in (("claude", "c-pair"), ("codex", "x-pair")):
            for step in ("render", "wrap"):
                with self.subTest(target=target, step=step):
                    self.make_pair()
                    if target == "claude":
                        self.cx.append("x-pair", amsg("must survive failed handoff"))
                    else:
                        with claude.find("c-pair").path.open("a") as f:
                            f.write(json.dumps(assistant(text("must survive failed handoff"))) + "\n")
                    before = pairs.load()
                    with mock.patch.object(pairs, step, side_effect=RuntimeError("context generation failed")):
                        with self.assertRaisesRegex(RuntimeError, "context generation failed"):
                            pairs.pull(target, sid)
                    self.assertEqual(pairs.load(), before)
                    self.assertIn("must survive failed handoff", pairs.pull(target, sid)["context"])
                    self.assertIsNone(pairs.pull(target, sid))

    def test_failed_initial_context_does_not_replace_existing_pair(self):
        self.make_pair()
        self.cx.add("x-new", PROJ_A, "New source", [umsg("new task"), amsg("new progress")])
        before = pairs.load()
        with mock.patch.object(pairs, "wrap", side_effect=RuntimeError("context generation failed")):
            with self.assertRaisesRegex(RuntimeError, "context generation failed"):
                pairs.continue_from("claude", "c-pair", PROJ_A, "x-new")
        self.assertEqual(pairs.load(), before)
        result = pairs.continue_from("claude", "c-pair", PROJ_A, "x-new")
        self.assertIn("new progress", result["context"])
        self.assertEqual(pairs.find("claude", "c-pair")["codex"]["id"], "x-new")

    def test_progress_is_not_lost_when_rollout_size_is_unchanged_or_missing(self):
        self.make_pair()
        with mock.patch.object(codex, "size_of", return_value=-1):
            self.cx.append("x-pair", umsg("new DB item"), amsg("saved"))
            result = pairs.pull("claude", "c-pair")
            self.assertIn("new DB item", result["context"])
            self.cx.append("x-pair", amsg("another DB item"))
            self.assertEqual(pairs.status(self.cx.find("x-pair"))[0], "updated")
            self.assertIn("another DB item", pairs.pull("claude", "c-pair")["context"])

    def test_history_pages_do_not_consume_progress(self):
        from ccx import history
        self.make_pair()
        before = pairs.load()
        self.cx.append("x-pair", umsg("latest"))
        one = history.read_page("codex", "x-pair", limit=10)
        two = history.read_page("codex", "x-pair", offset=one["next_offset"], limit=12000)
        self.assertIn("latest", one["text"] + two["text"])
        self.assertEqual(pairs.load(), before)
        self.assertIn("latest", pairs.pull("claude", "c-pair")["context"])

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

    def test_continue_from_a_claude_copy_of_a_codex_thread(self):
        # A Claude session ccx wrote from Codex, with no Claude turns since.
        claude_file(PROJ_A, "c-copy", [user("从 Codex 导入的问题", ccxImported=True),
                                       assistant(text("从 Codex 导入的回答"), ccxImported=True)], title="copy")
        self.cx.add("x-fresh", PROJ_A, "fresh", [umsg("hi")])
        res = pairs.continue_from("codex", "x-fresh", PROJ_A, "c-copy")
        self.assertIn("从 Codex 导入的回答", res["context"])
        self.assertIsNone(pairs.pull("codex", "x-fresh"))  # and nothing bounces back later

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

    def test_quota_message_keeps_failed_tests_marked_as_unfinished(self):
        for message in ("You've hit your session limit · resets 10:10am (Asia/Shanghai)",
                        "You've hit your limit · Please try again later.", "已达到会话限额"):
            with self.subTest(message=message):
                out = pairs.render([
                    ("assistant", "Writing tests for the fix"),
                    ("assistant", "[result] Failed Tests 2: expected undefined to be 25"),
                    ("assistant", message),
                ], "claude", budget=2000)
                self.assertIn("Failed Tests 2", out)
                self.assertIn("stopped in the middle", out)
                self.assertIn("unfinished step", out)

    def test_slow_git_never_blocks(self):
        from ccx import common
        def slow(*a, **k):
            raise common.subprocess.TimeoutExpired(cmd="git", timeout=4)
        with mock.patch.object(common.subprocess, "run", side_effect=slow):
            self.assertIn("took too long", common.git_snapshot(PROJ_A))
            self.assertEqual(common.git_branch(PROJ_A), "HEAD")

    def test_render_budget_keeps_newest(self):
        items = [("user", f"问题{i}") for i in range(50)] + [("assistant", "最后的回答")]
        out = pairs.render(items, "codex", budget=60)
        self.assertIn("最后的回答", out)
        self.assertIn("omitted", out)


class Interfaces(Base):
    def test_cli_flags_before_or_after_subcommand(self):
        from ccx import cli, install
        fake = {"current": "0.0.1", "latest": "0.0.2", "available": True, "url": "u"}
        for argv in (["update", "--check", "--json"], ["--json", "update", "--check"]):
            out = io.StringIO()
            with mock.patch.object(install, "check", lambda: fake), redirect_stdout(out), self.assertRaises(SystemExit) as e:
                cli.main(argv)
            self.assertEqual(e.exception.code, 0)
            self.assertEqual(json.loads(out.getvalue())["latest"], "0.0.2")

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

    def _hook(self, sid, prompt="hi"):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"session_id": sid, "prompt": prompt}))), \
                redirect_stdout(out), self.assertRaises(SystemExit):
            hook.main()
        return json.loads(out.getvalue()) if out.getvalue().strip() else None

    def _big_idle_pair(self, sid, tokens, hours_idle):
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(time.time() - hours_idle * 3600, timezone.utc).isoformat().replace("+00:00", "Z")
        claude_file(PROJ_A, sid, [user("长任务", timestamp=ts),
                                  assistant(text("ok"), timestamp=ts, **{"message": {"role": "assistant", "content": [text("ok")],
                                            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 0,
                                                      "cache_read_input_tokens": tokens}}})], title="长任务")
        self.cx.add("x-" + sid, PROJ_A, "长任务", [umsg("长任务")])
        pairs.link(pairs.side("claude", sid), pairs.side("codex", "x-" + sid))

    def test_hook_never_blocks_a_long_idle_conversation(self):
        self._big_idle_pair("c-big", 800_000, 3)
        self.assertNotEqual((self._hook("c-big", "接着干") or {}).get("decision"), "block")

    def test_hook_shows_a_visible_notice_and_skips_unchanged_threads(self):
        claude_file(PROJ_A, "c-note", [user("hi")], title="note")
        self.cx.add("x-note", PROJ_A, "note", [umsg("hi")])
        pairs.link(pairs.side("claude", "c-note"), pairs.side("codex", "x-note"))
        self.cx.append("x-note", amsg("新进展"))
        out = self._hook("c-note")
        self.assertIn("1", out["systemMessage"])
        with mock.patch.object(codex, "items", side_effect=AssertionError("full read on an unchanged thread")):
            self.assertIsNone(pairs.pull("claude", "c-note"))

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
        self.assertEqual(tools, {"continue_here", "list_sessions", "send_current_session", "read_session"})

    def test_transfer_creates_pair_then_reopens(self):
        claude_file(PROJ_A, "c-xfer", [user("做个页面"), assistant(text("好"))], title="做个页面")
        self.cx.add("x-imported", PROJ_A, "做个页面", [umsg("做个页面"), amsg("好")])
        with mock.patch.object(sync, "_import_to_codex", lambda s: "x-imported"):
            first = sync.transfer("claude", "c-xfer", open_app=False)
            second = sync.transfer("claude", "c-xfer", open_app=False)
        self.assertEqual(first["action"], "created")
        self.assertEqual(second["action"], "in_sync")  # nothing new: nothing re-sent
        self.assertEqual(second["pending"], 0)
        self.assertEqual(second["target"]["id"], "x-imported")
        self.assertEqual(second["target"]["project_id"], "project-test")

    def test_relinking_reports_pending_updates_once(self):
        c = claude_file(PROJ_A, "c-more", [user("做个页面"), assistant(text("好"))], title="做个页面")
        self.cx.add("x-more", PROJ_A, "做个页面", [umsg("做个页面")])
        with mock.patch.object(sync, "_import_to_codex", lambda s: "x-more"):
            sync.transfer("claude", "c-more", open_app=False)
            with open(c, "a") as f:
                f.write(json.dumps(user("加个按钮")) + "\n" + json.dumps(assistant(text("按钮加好了"))) + "\n")
            again = sync.transfer("claude", "c-more", open_app=False)
            self.assertEqual((again["action"], again["pending"]), ("linked", 2))
            self.assertGreater(again["pending_tokens"], 0)
            self.assertEqual(sync.estimate("claude", "c-more")["pending"], 2)
            pairs.pull("codex", "x-more")  # the next Codex prompt delivers them
            self.assertEqual(sync.transfer("claude", "c-more", open_app=False)["action"], "in_sync")

    def test_estimate_full_vs_condensed(self):
        claude_file(PROJ_A, "c-big", [x for i in range(300) for x in
                                      (user(f"step {i} " + "detail " * 200), assistant(text("done " * 300)))])
        e = sync.estimate("claude", "c-big")
        self.assertGreater(e["full"], e["condensed"] * 3)

    def test_pasted_images_point_at_the_apps_own_cache(self):
        c = claude_file(PROJ_A, "c-img", [user([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "eA=="}},
                                                {"type": "text", "text": "look at this"}], imagePasteIds=[3])])
        cache = Path(TMP) / "claude-tmp" / f"claude-{os.getuid()}" / c.parent.name / "c-img" / "images"
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_TMPDIR": str(Path(TMP) / "claude-tmp")}):
            self.assertIn("[image: no longer cached]", claude.units(c)[0][1])  # cleaned up: gone, no copy kept
            cache.mkdir(parents=True)
            (cache / "3.png").write_bytes(b"x")
            self.assertIn(f"[image: {cache / '3.png'}]", claude.units(c)[0][1])
        shot = Path(tempfile.mkdtemp()) / "codex-clipboard-1.png"
        shot.write_bytes(b"codex shot")
        u = codex._render({"type": "userMessage", "content": [
            {"type": "text", "text": f"\n# Files mentioned by the user:\n\n## a.png: {shot}\nImage attachment: true\n\n## My request:\nfix it"},
            {"type": "localImage", "path": str(shot)}]})
        self.assertEqual(u[1], f"fix it\n[image: {shot}]")

    def test_claude_goal_set_met_and_cleared(self):
        g = lambda cond, met: {"type": "attachment", "attachment": {"type": "goal_status", "condition": cond, "met": met}}
        c = claude_file(PROJ_A, "c-goal", [user("hi"), g("ship it", False)])
        self.assertEqual(claude.goal(c), {"objective": "ship it", "status": "active"})
        with open(c, "a") as f:
            f.write(json.dumps(g("ship it", True)) + "\n")
        self.assertEqual(claude.goal(c)["status"], "complete")
        with open(c, "a") as f:
            f.write(json.dumps(g("next", False)) + "\n")
            f.write(json.dumps({"type": "system", "subtype": "local_command", "commandRun": {"command": "goal", "args": "clear"},
                                "content": "<local-command-stdout>Goal cleared: next</local-command-stdout>"}) + "\n")
        self.assertIsNone(claude.goal(c))

    def test_transfer_mentions_unfinished_goal_and_pull_carries_it_once(self):
        claude_file(PROJ_A, "c-g2", [user("做页面")])
        self.cx.add("x-g2", PROJ_A, "做页面", [umsg("做页面")])
        pairs.link(pairs.side("claude", "c-g2"), pairs.side("codex", "x-g2"))
        self.cx.append("x-g2", amsg("做了一半"))
        goal = {"objective": "做到能发布", "status": "usageLimited"}
        with mock.patch.object(codex, "goal", return_value=goal):
            res = sync.transfer("codex", "x-g2", open_app=False)
            self.assertEqual(res["goal"], goal)
            self.assertIn("/goal", res["message"])
            self.assertIn("做到能发布", pairs.pull("claude", "c-g2")["context"])
            self.cx.append("x-g2", amsg("又做了一点"))
            self.assertNotIn("做到能发布", pairs.pull("claude", "c-g2")["context"])  # unchanged goal: not repeated

    def test_presence_finds_every_copy_of_the_plugin(self):
        from ccx import presence
        home = Path(tempfile.mkdtemp())
        (home / ".claude/plugins").mkdir(parents=True)
        (home / ".claude/plugins/installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"ccx@ccx": [{}], "ccx@claude-plugins-official": [{}], "other@x": [{}]}}))
        (home / ".codex").mkdir()
        (home / ".codex/config.toml").write_text('[plugins."ccx@ccx"]\nenabled = true\n\n[plugins."foo@bar"]\n')
        with mock.patch.object(presence, "HOME", home), mock.patch.object(codex, "CODEX_HOME", home / ".codex"):
            self.assertEqual(presence.claude_copies(), ["ccx@ccx", "ccx@claude-plugins-official"])
            self.assertEqual(presence.codex_copies(), ["ccx@ccx"])

    def test_plugin_only_install_points_to_the_rest_a_few_times(self):
        from ccx import presence
        now = [0.0]
        with mock.patch.object(presence, "MENU_APP", Path("/nonexistent/ccx.app")), \
                mock.patch.object(presence, "NUDGE", Path(tempfile.mkdtemp()) / "n.json"), \
                mock.patch.object(presence.time, "time", side_effect=lambda: now[0]):
            self.assertTrue(presence.nudge_due())       # first time
            now[0] = 60
            self.assertFalse(presence.nudge_due())      # too soon
            for _ in range(2):
                now[0] += presence.NUDGE_GAP + 1
                self.assertTrue(presence.nudge_due())   # a day later, twice more
            now[0] += presence.NUDGE_GAP + 1
            self.assertFalse(presence.nudge_due())      # shown 3 times: never again
        self.assertIn("github.com/aaronwong1999/ccx", presence.setup_hint())
        with mock.patch.object(presence, "MENU_APP", Path(tempfile.mkdtemp())):
            self.assertFalse(presence.nudge_due())      # full install: no hint

    def test_two_copies_of_the_hook_deliver_once(self):
        import threading
        claude_file(PROJ_A, "c-twice", [user("go")])
        self.cx.add("x-twice", PROJ_A, "go", [umsg("go")])
        pairs.link(pairs.side("claude", "c-twice"), pairs.side("codex", "x-twice"))
        self.cx.append("x-twice", amsg("done once"))
        got = []
        ts = [threading.Thread(target=lambda: got.append(pairs.pull("claude", "c-twice"))) for _ in range(2)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(sum(1 for r in got if r), 1)

    def test_setup_keeps_a_directory_copy_and_never_installs_a_second(self):
        from ccx import install, presence
        calls = []
        with mock.patch.object(claude, "desktop_cli", return_value="/x/claude"), \
                mock.patch.object(presence, "claude_copies", return_value=["ccx@ccx", "ccx@claude-plugins-official"]), \
                mock.patch.object(install, "run", side_effect=lambda cmd, timeout=300: calls.append(cmd) or (0, "")):
            self.assertTrue(install.setup_claude("/src", quiet=True))
        self.assertIn(["/x/claude", "plugin", "uninstall", "ccx@ccx"], calls)
        self.assertFalse(any(c[1:3] == ["plugin", "install"] for c in calls))

    def test_git_uses_the_system_proxy_unless_one_is_set(self):
        from ccx import common
        out = "<dictionary> {\n  HTTPSEnable : 1\n  HTTPSPort : 7890\n  HTTPSProxy : 127.0.0.1\n}"
        done = subprocess.CompletedProcess([], 0, out, "")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(common.subprocess, "run", return_value=done):
            self.assertEqual(common.proxy_env()["https_proxy"], "http://127.0.0.1:7890")
        with mock.patch.dict(os.environ, {"https_proxy": "http://mine:1"}, clear=True):
            self.assertEqual(common.proxy_env()["https_proxy"], "http://mine:1")

    def test_compaction_resets_context_size(self):
        c = claude_file(PROJ_A, "c-compact", [user("hi"), assistant(text("ok"))])
        with open(c, "a") as f:
            f.write(json.dumps({"type": "system", "subtype": "compact_boundary", "timestamp": "2026-01-01T00:00:00Z",
                                "compactMetadata": {"trigger": "idle", "preTokens": 900000, "postTokens": 14000}}) + "\n")
            f.write(json.dumps({"type": "user", "isCompactSummary": True, "timestamp": "2026-01-01T00:00:01Z",
                                "message": {"role": "user", "content": "This session is being continued..."}}) + "\n")
        self.assertEqual(claude.context_state(c)[0], 14000)
        self.assertIsNone(claude.units(c)[-1])

    def test_grouping_failure_does_not_duplicate_import_on_retry(self):
        claude_file(PROJ_A, "c-repair", [user("repair")])
        self.cx.add("x-repair", PROJ_A, "repair", [umsg("repair")])
        with mock.patch.object(sync, "_import_to_codex", return_value="x-repair") as imp, \
                mock.patch.object(codex, "ensure_thread_project", side_effect=[RuntimeError("offline"), "project-a"]):
            with self.assertRaisesRegex(RuntimeError, "without importing again"):
                sync.transfer("claude", "c-repair", open_app=False)
            result = sync.transfer("claude", "c-repair", open_app=False)
        self.assertEqual(imp.call_count, 1)
        self.assertIn(result["action"], ("linked", "in_sync"))
        self.assertEqual(result["target"]["project_id"], "project-a")

    def test_source_progress_during_import_is_still_pending(self):
        c = claude_file(PROJ_A, "c-racing", [user("start")])
        self.cx.add("x-racing", PROJ_A, "race", [umsg("start")])
        def import_and_finish_turn(src):
            with open(c, "a") as f:
                f.write(json.dumps(assistant(text("finished while importing"))) + "\n")
            return "x-racing"
        with mock.patch.object(sync, "_import_to_codex", side_effect=import_and_finish_turn):
            sync.transfer("claude", "c-racing", open_app=False)
        self.assertIn("finished while importing", pairs.pull("codex", "x-racing")["context"])

    def test_codex_to_claude_preserves_folder_and_existing_pair(self):
        self.cx.add("x-reverse", PROJ_B, "reverse", [umsg("start"), amsg("half done")])
        with mock.patch.object(claude, "version", return_value="2.1.0"):
            first = sync.transfer("codex", "x-reverse", open_app=False)
            second = sync.transfer("codex", "x-reverse", open_app=False)
        self.assertEqual(first["target"]["id"], second["target"]["id"])
        self.assertEqual(claude.find(first["target"]["id"]).cwd, PROJ_B)


class NewConversations(unittest.TestCase):
    targets = (("claude", "codex", "new", "path", "prompt"),
               ("codex", "claude", "code", "folder", "q"))

    def test_prefills_exact_session_in_project_without_using_clipboard(self):
        for source, target, host, folder_key, prompt_key in self.targets:
            with self.subTest(target=target):
                session = Session(source, "source-session", "/tmp/项目 A + B/#目录", 0,
                                  '修复 "a&b" + 100% / 登录?\n第二行', None)
                with mock.patch.object(claude if source == "claude" else codex, "find", return_value=session), \
                     mock.patch.object(sync, "copy_to_clipboard") as clipboard, \
                     mock.patch.object(sync.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                    url = getattr(sync, f"new_{target}_conversation")(session.id)
                parsed = urlparse(url)
                self.assertEqual((parsed.scheme, parsed.netloc, parsed.fragment), (target, host, ""))
                self.assertEqual(parsed.path, "/new" if target == "claude" else "")
                self.assertEqual(parse_qs(parsed.query), {
                    folder_key: [os.path.realpath(session.cwd)],
                    prompt_key: [f"Continue the “{session.title}” session from {source.title()} (session id {session.id})."],
                })
                self.assertEqual(run.call_args.args[0], ["open", url])
                run.assert_called_once()
                clipboard.assert_not_called()

    def test_open_failure_is_reported_instead_of_claiming_success(self):
        for source, target, *_ in self.targets:
            with self.subTest(target=target):
                session = Session(source, "source-session", PROJ_A, 0, "Continue me", None)
                with mock.patch.object(claude if source == "claude" else codex, "find", return_value=session), \
                     mock.patch.object(sync.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "No app found")):
                    with self.assertRaisesRegex(RuntimeError, "No app found"):
                        getattr(sync, f"new_{target}_conversation")(session.id)

    def test_missing_session_does_not_open_app(self):
        for source, target, *_ in self.targets:
            with self.subTest(target=target):
                with mock.patch.object(claude if source == "claude" else codex, "find", return_value=None), \
                     mock.patch.object(sync.subprocess, "run") as run:
                    with self.assertRaisesRegex(RuntimeError, "not found"):
                        getattr(sync, f"new_{target}_conversation")("missing")
                run.assert_not_called()

    def test_success_messages_tell_user_to_send_prefilled_prompt(self):
        from ccx import cli
        for target in ("claude", "codex"):
            with self.subTest(target=target):
                out = io.StringIO()
                with mock.patch.object(cli, f"new_{target}_conversation"), \
                     mock.patch.object(cli, "L", side_effect=lambda en, zh: en), redirect_stdout(out):
                    cli.main([f"new-{target}", "source-session"])
                self.assertIn("prompt filled in", out.getvalue())
                self.assertIn(f"send it in {target.title()}", out.getvalue())
                self.assertNotIn("clipboard", out.getvalue())


class ProjectAssignment(unittest.TestCase):
    def server_for(self, project_id=None, pages=None):
        self.state = {"thread": {"id": "x", "cwd": PROJ_A, "projectId": project_id}}
        pages = iter(pages or [{"data": [], "nextCursor": None}])
        def request(method, args):
            if method == "thread/read":
                return self.state
            if method == "project/list":
                return next(pages)
            if method == "project/create":
                return {"project": {"id": "created"}}
            if method == "project/read":
                return {"project": {"id": args["projectId"], "roots": [{"path": PROJ_A}]}}
            if method == "thread/metadata/update":
                self.state["thread"]["projectId"] = args["projectId"]
                return {}
            self.fail(method)
        srv = mock.Mock()
        srv.request.side_effect = request
        return srv

    def test_reuses_project_on_later_page(self):
        srv = self.server_for(pages=[{"data": [], "nextCursor": "more"}, {"data": [
            {"id": "existing", "roots": [{"path": PROJ_A}]}], "nextCursor": None}])
        with mock.patch.object(codex, "server", return_value=srv):
            self.assertEqual(codex.ensure_thread_project("x", PROJ_A), "existing")
        self.assertNotIn("project/create", [c.args[0] for c in srv.request.call_args_list])

    def test_creates_only_for_exact_root_and_stays_idempotent(self):
        srv = self.server_for(pages=[{"data": [{"id": "parent", "roots": [{"path": TMP}]}]}])
        with mock.patch.object(codex, "server", return_value=srv):
            self.assertEqual(codex.ensure_thread_project("x", PROJ_A), "created")
            self.assertEqual(codex.ensure_thread_project("x", PROJ_A), "created")
        creates = [c.args[1] for c in srv.request.call_args_list if c.args[0] == "project/create"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["roots"], [{"path": os.path.realpath(PROJ_A)}])

    def test_preserves_user_assignment(self):
        srv = self.server_for(project_id="chosen-by-user")
        with mock.patch.object(codex, "server", return_value=srv):
            self.assertEqual(codex.ensure_thread_project("x", PROJ_A), "chosen-by-user")
        self.assertEqual(srv.request.call_count, 1)

    def test_missing_directory_does_not_create_project(self):
        srv = self.server_for()
        self.state["thread"]["cwd"] = "/ccx/missing/directory"
        with mock.patch.object(codex, "server", return_value=srv):
            self.assertIsNone(codex.ensure_thread_project("x", PROJ_A))
        self.assertEqual(srv.request.call_count, 1)

    def test_repairs_backend_only_project_to_desktop_mapping(self):
        srv = self.server_for(project_id="old-backend-only")
        registered = {"server_id": "native-server", "registered_server_ids": ["native-server"]}
        with mock.patch.object(codex, "server", return_value=srv), \
                mock.patch.object(codex, "desktop_project", return_value=registered):
            self.assertEqual(codex.ensure_thread_project("x", PROJ_A), "native-server")
        self.assertEqual(self.state["thread"]["projectId"], "native-server")

    def test_does_not_override_another_registered_project(self):
        srv = self.server_for(project_id="chosen-visible-project")
        registered = {"server_id": "native-server",
                      "registered_server_ids": ["native-server", "chosen-visible-project"]}
        with mock.patch.object(codex, "server", return_value=srv), \
                mock.patch.object(codex, "desktop_project", return_value=registered):
            self.assertEqual(codex.ensure_thread_project("x", PROJ_A), "chosen-visible-project")
        self.assertEqual(srv.request.call_count, 1)


class DesktopWorkspace(unittest.TestCase):
    def test_reads_native_id_mapping_without_writing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / ".codex-global-state.json"
            state = {"local-projects": {"ui-project": {"rootPaths": [PROJ_A]}},
                     "app-server-project-id-by-legacy-project-id-by-host": {
                         "local:" + directory: {"ui-project": "server-project"}}}
            original = json.dumps(state)
            p.write_text(original)
            with mock.patch.object(codex, "DESKTOP_STATE", p):
                result = codex.desktop_project(PROJ_A)
                self.assertEqual(result["id"], "ui-project")
                self.assertEqual(result["server_id"], "server-project")
                self.assertIsNone(codex.desktop_project(PROJ_B))
            self.assertEqual(p.read_text(), original)

    def test_registers_folder_through_official_cli_and_waits_for_index(self):
        with mock.patch.object(codex, "desktop_project", side_effect=[None, None, {"id": "new-ui-project"}]), \
                mock.patch.object(codex, "codex_bin", return_value="bundled-codex"), \
                mock.patch.object(codex.subprocess, "run", return_value=mock.Mock(returncode=0)) as run, \
                mock.patch.object(codex.time, "sleep"):
            self.assertTrue(codex.register_desktop_workspace(PROJ_A))
        self.assertEqual(run.call_args.args[0], ["bundled-codex", "app", os.path.realpath(PROJ_A)])

    def test_existing_folder_is_not_reopened(self):
        with mock.patch.object(codex, "desktop_project", return_value={"id": "exists"}), \
                mock.patch.object(codex.subprocess, "run") as run:
            self.assertFalse(codex.register_desktop_workspace(PROJ_A))
        run.assert_not_called()

    def test_failed_registration_is_not_reported_as_success(self):
        with mock.patch.object(codex, "desktop_project", return_value=None), \
                mock.patch.object(codex, "codex_bin", return_value="bundled-codex"), \
                mock.patch.object(codex.subprocess, "run", return_value=mock.Mock(returncode=1, stderr="failed")):
            with self.assertRaisesRegex(RuntimeError, "could not register"):
                codex.register_desktop_workspace(PROJ_A)


class NativeHistory(unittest.TestCase):
    def test_busy_repair_stays_queued_until_writer_is_released(self):
        import uuid
        tid = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(repairs, "ROOT", Path(directory)), \
                mock.patch.object(codex, "ensure_paginated_history", side_effect=["busy", "ready"]):
            self.assertEqual(repairs.prepare(tid), "busy")
            self.assertEqual(repairs.pending()[0]["thread_id"], tid)
            self.assertEqual(repairs.prepare(tid), "ready")
            self.assertEqual(repairs.pending(), [])

    def test_paginated_history_unwraps_items_and_reads_all_pages(self):
        srv = mock.Mock()
        srv.request.side_effect = [
            {"thread": {"historyMode": "paginated"}},
            {"data": [{"item": umsg("first")}], "nextCursor": "more"},
            {"data": [{"item": amsg("last")}], "nextCursor": None},
        ]
        with mock.patch.object(codex, "server", return_value=srv):
            self.assertEqual(codex.items("x"), [umsg("first"), amsg("last")])
        self.assertEqual(srv.request.call_args_list[-1].args[1]["cursor"], "more")

    def test_targeted_migration_verifies_item_paging(self):
        srv = mock.Mock()
        srv.request.side_effect = [{"thread": {"historyMode": "legacy"}},
                                   {"thread": {"historyMode": "paginated"}}, {"data": []}]
        proc = mock.Mock(returncode=0, stdout=json.dumps({"outcomes": [
            {"thread_id": "x", "status": "migrated"}]}))
        with mock.patch.object(codex, "server", return_value=srv), \
                mock.patch.object(codex, "codex_bin", return_value="codex"), \
                mock.patch.object(codex.subprocess, "run", return_value=proc) as run:
            self.assertEqual(codex.ensure_paginated_history("x"), "ready")
        self.assertEqual(run.call_args.args[0], ["codex", "migrate-rollouts", "--thread", "x", "--apply", "--json"])
        self.assertEqual(srv.request.call_args.args[0], "thread/items/list")

    def test_live_writer_is_queued_and_never_forced(self):
        srv = mock.Mock()
        srv.request.return_value = {"thread": {"historyMode": "legacy"}}
        proc = mock.Mock(returncode=0, stdout=json.dumps({"outcomes": [
            {"thread_id": "x", "status": "skipped_busy"}]}))
        with mock.patch.object(codex, "server", return_value=srv), \
                mock.patch.object(codex, "codex_bin", return_value="codex"), \
                mock.patch.object(codex.subprocess, "run", return_value=proc):
            self.assertEqual(codex.ensure_paginated_history("x"), "busy")
        self.assertEqual(srv.request.call_count, 1)

    def test_burst_rpc_notifications_are_not_stranded(self):
        rpc = object.__new__(codex.AppServer)
        rpc._received = bytearray(b'{"id":1,"result":{}}\n{"method":"import/completed"}\n')
        self.assertEqual(rpc._read(0)["id"], 1)
        self.assertEqual(rpc._read(0)["method"], "import/completed")


if __name__ == "__main__":
    unittest.main()
