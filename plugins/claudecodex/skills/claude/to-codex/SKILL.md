---
name: to-codex
description: 把当前这个 Claude 会话发到 Codex（导入或同步）并在 Codex 里打开，让用户在 Codex 接着干。Use when the user says /to-codex, "切到 codex", "转给 codex", "在 codex 里继续", or is running out of Claude usage.
---

# 发到 Codex

1. 如果还有没写完的改动，先停下来，不要留半截文件。
2. 调用 claudecodex 的 `send_current_session`，`cwd` 传当前工作目录。
3. 用一句话回复结果（例如「已发到 Codex，并在 Codex 桌面版打开」）。之后不要再改代码，避免两边同时改。
