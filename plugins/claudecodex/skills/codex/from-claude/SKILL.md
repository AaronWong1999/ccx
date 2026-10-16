---
name: from-claude
description: 把 Claude Code 里的会话导入（或同步）到 Codex，接着在 Codex 里干。Use when the user says $from-claude, "导入 claude", "同步 claude", "接着 claude 的继续", "claude 那边做到哪了", or wants to continue work they did in Claude Code.
---

# 从 Claude 导入会话

1. 调用 claudecodex 的 `list_sessions`，`cwd` 传当前工作目录。
2. 没有会话就一句话告诉用户，结束。
3. 让用户选一个（用户已经指明是哪个就跳过）：如果你有让用户做选择的工具就用它，否则列出最近的最多 5 个（编号、标题、更新时间、状态），等用户回复编号。
4. 调用 `import_session`，传选中的 `session_id` 和 `cwd`。之前导入过的会自动只做同步。
5. 用一句话回复结果（例如「已导入，已在 Codex 打开『…』」）。不要在当前会话里继续做那个任务。
