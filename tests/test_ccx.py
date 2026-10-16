"""Unit tests for ccx. Runs without Claude or Codex installed: Claude sessions
are written to a temp dir and Codex's app-server API is replaced by a fake.

    python3 -m unittest discover -s tests
"""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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

    def test_resume_guard_stops_once_then_lets_resend_through(self):
        from ccx import common
        common.set_setting("warn_long_resume", True)
        self._big_idle_pair("c-big", 800_000, 2)
        first = self._hook("c-big", "接着干")
        self.assertEqual(first["decision"], "block")
        self.assertIn("800k", first["reason"])
        self.assertIn("接着干", first["reason"])          # the message is echoed back to copy
        self.assertNotEqual((self._hook("c-big") or {}).get("decision"), "block")

    def test_resume_guard_skips_small_recent_or_disabled(self):
        from ccx import common
        common.set_setting("warn_long_resume", True)
        self._big_idle_pair("c-small", 40_000, 3)
        self._big_idle_pair("c-recent", 800_000, 0.2)
        for sid in ("c-small", "c-recent"):
            self.assertNotEqual((self._hook(sid) or {}).get("decision"), "block")
        common.set_setting("warn_long_resume", False)
        self._big_idle_pair("c-off", 800_000, 3)
        self.assertNotEqual((self._hook("c-off") or {}).get("decision"), "block")
        common.set_setting("warn_long_resume", True)

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
        self.assertEqual(second["action"], "linked")
        self.assertEqual(second["target"]["id"], "x-imported")
        self.assertEqual(second["target"]["project_id"], "project-test")

    def test_grouping_failure_does_not_duplicate_import_on_retry(self):
        claude_file(PROJ_A, "c-repair", [user("repair")])
        self.cx.add("x-repair", PROJ_A, "repair", [umsg("repair")])
        with mock.patch.object(sync, "_import_to_codex", return_value="x-repair") as imp, \
                mock.patch.object(codex, "ensure_thread_project", side_effect=[RuntimeError("offline"), "project-a"]):
            with self.assertRaisesRegex(RuntimeError, "without importing again"):
                sync.transfer("claude", "c-repair", open_app=False)
            result = sync.transfer("claude", "c-repair", open_app=False)
        self.assertEqual(imp.call_count, 1)
        self.assertEqual(result["action"], "linked")
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

    def test_history_reader_escapes_imported_html(self):
        from ccx import history
        source = Session("claude", "x", PROJ_A, 0, "<script>bad</script>", None)
        pair = {"claude": {"id": "x"}, "codex": {"id": "y"}}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(history, "STATE_DIR", Path(directory)), \
                mock.patch.object(pairs, "load", return_value=[pair]), \
                mock.patch.object(pairs, "session_units", return_value=(source, [("user", "<img onerror=bad>")])):
            page = Path(history.export_linked()).read_text()
        self.assertIn("&lt;img onerror=bad&gt;", page)
        self.assertNotIn("<script>bad", page)

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
