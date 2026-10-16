---
name: to-codex
description: Hand this conversation to Codex so the user can keep going there. The first time it is imported and linked; after that the linked Codex conversation is opened. Use when the user says /to-codex, "switch to codex", "continue in codex", 切到 codex, 转给 codex, or is running out of Claude usage.
---

# Continue in Codex

1. If a change is half-written, finish or stop it cleanly first. Don't leave broken files.
2. If you have a task list, make sure it's up to date: it travels with the conversation.
3. Call ccx's `send_current_session` with the current working directory as `cwd`.
4. Reply with one sentence about the result. Then stop editing, so the two apps don't change files at the same time. When the user sends a message on the Codex side, this side's progress goes with it.
