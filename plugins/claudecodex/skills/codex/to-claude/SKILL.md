---
name: to-claude
description: 让用户去 Claude 接着干当前这个对话（第一次导入并关联，之后直接打开关联的 Claude 会话）。Use when the user says $to-claude, "切到 claude", "转给 claude", "在 claude 里继续", or is running out of Codex usage.
---

# 去 Claude 继续

1. 如果还有没写完的改动，先停下来，不要留半截文件。
2. 调用 claudecodex 的 `send_current_session`，`cwd` 传当前工作目录。
3. 用一句话回复结果。之后不要再改代码，避免两边同时改。用户在 Claude 那边发消息时，这里的进展会自动带过去。
