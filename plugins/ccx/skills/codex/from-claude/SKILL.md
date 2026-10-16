---
name: from-claude
description: 在当前对话里接着 Claude 的进度继续干：第一次从 Claude 导入并关联，之后只同步新进展。Use when the user says $from-claude, "接着 claude 继续", "从 claude 把…导入", "把 claude 里的…加载出来", "同步 claude", "claude 那边做到哪了", shares a screenshot of a Claude session and asks to continue it, or pastes Claude output and asks to carry on.
---

# 接着 Claude 继续

用 ccx 的 `continue_here` 工具，`cwd` 永远传当前工作目录。

1. **用户说了是哪个会话**（名字、关键词，或者给了截图）：
   - 从用户的话里，或者截图上看到的会话标题，提取出名称，作为 `query` 调用 `continue_here`。它会搜索所有项目。
   - 从返回的候选里挑出标题最吻合的那个，再用它的 `session_id` 调一次 `continue_here`。
   - 有好几个都很像、拿不准时，就让用户选：有让用户做选择的工具就用它；否则列出最多 5 个（编号、标题、更新时间、状态、目录如果不同），等用户回复编号。
2. **用户没说是哪个**（"接着 claude 继续""同步一下"）：不带参数调用 `continue_here`。
   - 当前对话已经关联过：返回的就是对面的新进展。
   - 还没关联：返回候选列表，按第 1 步的方式选一个。
3. 拿到 `<ccx-sync>` 块以后，用一句话告诉用户拉到了什么，然后**直接在这个对话里接着干**用户要做的事。把块里的内容当作你自己已经做过的工作；代码以磁盘上的文件为准。
4. **工作目录不一致**：如果块里写了"注意：…目录…"，先把这一点告诉用户，问清楚是切换到那个目录继续，还是只把它当参考。不要擅自去改另一个目录里的文件。
5. 关联以后两边会自动同步。之后用户在这里发消息时，对面的新进展会自动出现在上下文里（`<ccx-sync>`）；没有自动出现时，用户再说"接着 claude 继续"，就再调一次。

用户只是贴来一段 Claude 的输出、并不需要关联时，也可以直接根据贴来的内容接着干。
