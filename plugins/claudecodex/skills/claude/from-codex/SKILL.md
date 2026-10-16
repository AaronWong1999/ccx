---
name: from-codex
description: 把 Codex 里的会话导入（或同步）到 Claude，接着在 Claude 里干。Use when the user says /from-codex, "导入 codex", "同步 codex", "接着 codex 的继续", "codex 那边做到哪了", or wants to continue work they did in Codex.
---

# 从 Codex 导入会话

1. 调用 claudecodex 的 `list_sessions`，`cwd` 传当前工作目录。
2. 没有会话就一句话告诉用户，结束。
3. 用 AskUserQuestion 让用户选一个（用户已经指明是哪个就跳过这步）：
   - 问题：「要把哪个 Codex 会话拿过来？」
   - 选项：最近的最多 4 个，`label` 用标题（≤30 字），`description` 写「{updated} · {状态}」。
   - 状态为「从 Claude 导入的副本」的排在最后，其它选项够 4 个就不放。
4. 调用 `import_session`，传选中的 `session_id` 和 `cwd`。之前导入过的会自动只做同步。
5. 用一句话回复工具返回的结果（例如「已导入，桌面版已打开『…』」）。不要在当前会话里继续做那个任务——用户会在新打开的会话里继续。
