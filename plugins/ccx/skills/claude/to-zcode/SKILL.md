---
name: to-zcode
description: Hand this conversation to ZCode so the user can keep going there. The first time it is imported and linked; after that the linked ZCode conversation is opened. Use when the user says /to-zcode, "switch to zcode", "continue in zcode", 切到 zcode, 转给 zcode, or is running out of Claude usage. Also when the user says "unlink", "stop syncing" or 取消关联.
---

# Continue in ZCode

1. If a change is half-written, finish or stop it cleanly first. Don't leave broken files.
2. If you have a task list, make sure it's up to date: it travels with the conversation.
3. Call ccx's `send_current_session` with the current working directory as `cwd` and `"zcode"` as `app`.
4. Reply with one sentence about the result. ZCode can't be told which conversation to show, so pass on where ccx says to find it. Then stop editing, so the two apps don't change files at the same time. When the user sends a message on the ZCode side, this side's progress goes with it.

If the user says "unlink", "stop syncing", 取消关联 or 不要同步了, call ccx's `unlink` with the current working directory as `cwd` and `"zcode"` as `app`. It forgets the link to the ZCode conversation, so neither side gets the other's progress any more; both conversations are kept, and handing over again links them afresh.
