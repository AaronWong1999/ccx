---
name: to-codex
description: Hand the current Claude Code conversation over to Codex so the user can keep going there. Use when the user says /to-codex, "切到 codex", "转给 codex", "在 codex 里继续", or is running out of Claude usage and wants to continue in Codex.
---

# 转到 Codex

1. 如果有没写完的改动，先用一两句话告诉用户当前进度（会话内容会被完整导入，不需要额外总结）。
2. 运行（当前项目目录下）：

```bash
ccx --open app to-codex
```

它会把当前项目最近的 Claude 会话（就是这一个）通过 Codex 自带的导入器导入，并打开 Codex 桌面版。

3. 把命令输出里的 Codex 会话 ID 和 `codex resume <id>` 告诉用户，然后停下，不要再继续改代码，避免两边同时改。
