---
name: from-codex
description: 在当前对话里接着 Codex 的进度继续干（第一次会从 Codex 导入并关联，之后只同步新进展）。Use when the user says /from-codex, "接着 codex 继续", "从 codex 导入…", "同步 codex", "codex 那边做到哪了", or wants to continue work done in Codex.
---

# 接着 Codex 继续

1. 调用 claudecodex 的 `continue_here`，`cwd` 传当前工作目录，不传 `session_id`。
2. 如果返回的是 Codex 的进展（`<claudecodex-sync>` 块）：用一句话告诉用户拉到了什么，然后**直接在这个对话里接着干**用户要做的事。
3. 如果返回"还没有关联"和会话列表：
   - 用户已经说了是哪个（比如"从 codex 把登录页那个导入"），就按标题选最匹配的；
   - 否则用 AskUserQuestion 让用户选：选项最多 4 个，`label` 用标题（≤30 字），`description` 写「更新时间 · 状态」。
   - 再调用 `continue_here`，带上选中的 `session_id`，然后同第 2 步。
4. 关联之后两边会自动同步：用户之后在这里发消息时，Codex 的新进展会自动出现在上下文里（`<claudecodex-sync>`），把它当作你自己做过的工作。
