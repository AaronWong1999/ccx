---
name: to-claude
description: Hand the current Codex conversation over to Claude Code so the user can keep going there. Use when the user says $to-claude, "切到 claude", "转给 claude", "在 claude 里继续", or is running out of Codex usage and wants to continue in Claude Code.
---

# 转到 Claude Code

1. 运行（当前项目目录下）：

```bash
ccx --open none to-claude
```

它会把当前项目最近的 Codex 会话（就是这一个）转换成 Claude Code 会话。

2. 把输出里的 `claude --resume <id>` 告诉用户，然后停下，不要再继续改代码，避免两边同时改。
