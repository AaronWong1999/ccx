---
name: to-claude
description: 把当前这个 Codex 会话发到 Claude Code（导入或同步）并在 Claude 桌面版打开，让用户在 Claude 接着干。Use when the user says $to-claude, "切到 claude", "转给 claude", "在 claude 里继续", or is running out of Codex usage.
---

# 发到 Claude

1. 如果还有没写完的改动，先停下来，不要留半截文件。
2. 调用 claudecodex 的 `send_current_session`，`cwd` 传当前工作目录。
3. 用一句话回复结果（例如「已发到 Claude，并在 Claude 桌面版打开」）。之后不要再改代码，避免两边同时改。
