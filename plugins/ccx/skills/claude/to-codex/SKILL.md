---
name: to-codex
description: Hand this conversation to Codex so the user can keep going there. The first time it is imported and linked; after that the linked Codex conversation is opened. Use when the user says /to-codex, "switch to codex", "continue in codex", 切到 codex, 转给 codex, or is running out of Claude usage. Also when the user says "unlink", "stop syncing" or 取消关联.
---

# Continue in Codex

1. If a change is half-written, finish or stop it cleanly first. Don't leave broken files.
2. If you have a task list, make sure it's up to date: it travels with the conversation.
3. Call ccx's `send_current_session` with the current working directory as `cwd`.
4. Reply with one sentence about the result. Then stop editing, so the two apps don't change files at the same time. When the user sends a message on the Codex side, this side's progress goes with it.

If the user says "unlink", "stop syncing", 取消关联 or 不要同步了, call ccx's `unlink` with the current working directory as `cwd`. It forgets the link to the Codex conversation, so neither side gets the other's progress any more; both conversations are kept, and handing over again links them afresh.
