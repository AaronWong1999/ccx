---
name: from-zcode
description: Continue, in this conversation, a task that was being worked on in ZCode. The first time it imports and links the ZCode session; after that it only brings over new progress. Use when the user says $from-zcode, "continue from zcode", "import the … session from zcode", "load … from zcode", "sync with zcode", "what did zcode get done", 接着 zcode 继续, 从 zcode 把…导入, shares a screenshot of an ZCode session and asks to continue it, or pastes ZCode output and asks to carry on.
---

# Continue from ZCode

Use ccx's `continue_here` tool. Always pass the current working directory as `cwd` and `"zcode"` as `app`.

1. **The user named the session** (a title, some words from it, or a screenshot):
   - Take the name from the message or read the session title in the screenshot, and call `continue_here` with it as `query` (every project is searched).
   - Pick the candidate whose title matches best and call `continue_here` again with its `session_id`.
   - If several look equally likely, let the user choose: use a choice tool if you have one; otherwise list up to 5 (number, title, updated, status, folder if different) and wait for the number.
2. **The user did not name one** ("continue from zcode", "sync"): call `continue_here` with only `cwd` and `app`.
   - Already linked: you get the other side's new progress.
   - Not linked yet: you get candidates; choose as in step 1.
3. With the `<ccx-sync>` block in hand, tell the user in one sentence what came over, then **carry on with their task right here**. Treat the block as work you did yourself; the files on disk are the source of truth.
   - If it shows a **task list**, continue from its first unfinished item.
   - If it says the other side **stopped in the middle of a step**, first check whether that step finished (look at the files, rerun a check), then continue.
4. **Different folder**: if the block has a "NOTE: … folder" line, tell the user and ask whether to continue in that folder or use the progress only as reference. Never edit the other folder on your own.
5. Once linked, the two stay in sync: later messages here get ZCode's new progress injected automatically (`<ccx-sync>`). If it ever doesn't show up, call `continue_here` again.

If the user only pasted some ZCode output and doesn't need a link, you can also just continue from what they pasted.

If the user says "unlink", "stop syncing", 取消关联 or 不要同步了, call ccx's `unlink` with the current working directory as `cwd` and `"zcode"` as `app`. It forgets the link to the ZCode conversation, so neither side gets the other's progress any more; both conversations are kept, and handing over again links them afresh.
