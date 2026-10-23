---
name: from-codex
description: Continue, in this conversation, a task that was being worked on in Codex. The first time it imports and links the Codex session; after that it only brings over new progress. Use when the user says /from-codex, "continue from codex", "import the … session from codex", "load … from codex", "sync with codex", "what did codex get done", 接着 codex 继续, 从 codex 把…导入, shares a screenshot of a Codex session and asks to continue it, or pastes Codex output and asks to carry on.
---

# Continue from Codex

Use ccx's `continue_here` tool. Always pass the current working directory as `cwd`.

1. **The user named the session** (a title, some words from it, or a screenshot):
   - Take the name from the message or read the session title in the screenshot, and call `continue_here` with it as `query` (every project is searched).
   - Pick the candidate whose title matches best and call `continue_here` again with its `session_id`.
   - If several look equally likely, let the user choose: use AskUserQuestion: up to 4 options, `label` = title (≤30 chars), `description` = "updated · status · folder if different".
2. **The user did not name one** ("continue from codex", "sync"): call `continue_here` with no arguments.
   - Already linked: you get the other side's new progress.
   - Not linked yet: you get candidates; choose as in step 1.
3. With the `<ccx-sync>` block in hand, tell the user in one sentence what came over, then **carry on with their task right here**. Treat the block as work you did yourself; the files on disk are the source of truth.
   - If it shows a **task list**, continue from its first unfinished item.
   - If it says the other side **stopped in the middle of a step**, first check whether that step finished (look at the files, rerun a check), then continue.
4. **Different folder**: if the block has a "NOTE: … folder" line, tell the user and ask whether to continue in that folder or use the progress only as reference. Never edit the other folder on your own.
5. Once linked, the two stay in sync: later messages here get Codex's new progress injected automatically (`<ccx-sync>`). If it ever doesn't show up, call `continue_here` again.

If the user only pasted some Codex output and doesn't need a link, you can also just continue from what they pasted.

If the user says "unlink", "stop syncing", 取消关联 or 不要同步了, call ccx's `unlink` with the current working directory as `cwd`. It forgets the link to the Codex conversation, so neither side gets the other's progress any more; both conversations are kept, and handing over again links them afresh.
