---
name: from-claude
description: Continue, in this conversation, a task that was being worked on in Claude. The first time it imports and links the Claude session; after that it only brings over new progress. Use when the user says $from-claude, "continue from claude", "import the … session from claude", "load … from claude", "sync with claude", "what did claude get done", 接着 claude 继续, 从 claude 把…导入, shares a screenshot of a Claude session and asks to continue it, or pastes Claude output and asks to carry on.
---

# Continue from Claude

Use ccx's `continue_here` tool. Always pass the current working directory as `cwd`.

1. **The user named the session** (a title, some words from it, or a screenshot):
   - Take the name from the message or read the session title in the screenshot, and call `continue_here` with it as `query` (every project is searched).
   - Pick the candidate whose title matches best and call `continue_here` again with its `session_id`.
   - If several look equally likely, let the user choose: use a choice tool if you have one; otherwise list up to 5 (number, title, updated, status, folder if different) and wait for the number.
2. **The user did not name one** ("continue from claude", "sync"): call `continue_here` with no arguments.
   - Already linked: you get the other side's new progress.
   - Not linked yet: you get candidates; choose as in step 1.
3. With the `<ccx-sync>` block in hand, tell the user in one sentence what came over, then **carry on with their task right here**. Treat the block as work you did yourself; the files on disk are the source of truth.
   - If it shows a **task list**, continue from its first unfinished item.
   - If it says the other side **stopped in the middle of a step**, first check whether that step finished (look at the files, rerun a check), then continue.
4. **Different folder**: if the block has a "NOTE: … folder" line, tell the user and ask whether to continue in that folder or use the progress only as reference. Never edit the other folder on your own.
5. Once linked, the two stay in sync: later messages here get Claude's new progress injected automatically (`<ccx-sync>`). If it ever doesn't show up, call `continue_here` again.

If the user only pasted some Claude output and doesn't need a link, you can also just continue from what they pasted.
