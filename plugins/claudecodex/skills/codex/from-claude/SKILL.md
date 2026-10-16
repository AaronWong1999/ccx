---
name: from-claude
description: 在当前对话里接着 Claude 的进度继续干（第一次会从 Claude 导入并关联，之后只同步新进展）。Use when the user says $from-claude, "接着 claude 继续", "从 claude 导入…", "同步 claude", "claude 那边做到哪了", or wants to continue work done in Claude Code.
---

# 接着 Claude 继续

1. 调用 claudecodex 的 `continue_here`，`cwd` 传当前工作目录，不传 `session_id`。
2. 如果返回的是 Claude 的进展（`<claudecodex-sync>` 块）：用一句话告诉用户拉到了什么，然后**直接在这个对话里接着干**用户要做的事。
3. 如果返回"还没有关联"和会话列表：
   - 用户已经说了是哪个（比如"从 claude 把登录页那个导入"），就按标题选最匹配的；
   - 否则列出最多 5 个（编号、标题、更新时间、状态），让用户回复编号；有让用户选择的工具就用它。
   - 再调用 `continue_here`，带上选中的 `session_id`，然后同第 2 步。
4. 关联之后两边会自动同步：用户之后在这里发消息时，Claude 的新进展会自动出现在上下文里（`<claudecodex-sync>`），把它当作你自己做过的工作；如果没有自动出现，用户说"接着 claude 继续"时再调一次 `continue_here`。
