# Privacy

ccx runs entirely on your Mac. It has no server, no account and no telemetry.

**What it reads**
- The email of the account Claude Code is signed in to, from `~/.claude.json`, only to pick that account out of magpie's list.
- Claude Code's session files under `~/.claude/projects` (or `CLAUDE_CONFIG_DIR`), to carry a task between the apps.
- Codex threads and Codex's own usage numbers, only through Codex's app-server API on your Mac.
- Antigravity conversations, when the Antigravity desktop app is installed: titles, folders and step counts from its summary database (`~/.gemini/antigravity/conversation_summaries.db`, opened read-only), and a conversation's content through the local service the app runs on 127.0.0.1. To talk to that service ccx reads its port and per-run access token from the file Antigravity writes for its own tools (`~/.gemini/antigravity/daemon/`); that token only works on your Mac and is never stored or sent anywhere else.
- ZCode conversations, when the ZCode desktop app is installed: titles, folders and content from its conversation database (`~/.zcode/cli/db/db.sqlite`, opened read-only), and, to know whether a conversation is already listed or which project a folder belongs to, its task index (`~/.zcode/v2/tasks-index.sqlite`, read-only).
- When they are installed, the local output of CodexBar, abtop, Claude Code Usage Monitor, ccusage, claude-hud, Claude Status Bar, magpie (`magpie quota`, which asks the vendors the way magpie always does), Agent Sessions, ccstatusline and CCometixLine, for the usage heads-up.

**What it writes**
- Link records and settings in `~/.ccx`.
- The progress it carries over, into the conversation you continue, in Claude's session files or through Codex's app-server.
- In Antigravity: its plugin in `~/.gemini/config/plugins/ccx`, a project entry for a folder Antigravity doesn't know yet, and new conversations started with Antigravity's own `agentapi` command. A task you send to Antigravity is the first message of such a conversation, so Antigravity handles it like anything you type there (it goes to the model you use in Antigravity). ccx never edits Antigravity's conversation files.
- In ZCode: its plugin, installed with ZCode's own `zcode plugins` command, and new conversations created through ZCode's own app-server import (the one behind its "Import from Claude Code"). Creating one doesn't call a model. So that ZCode lists a new conversation, ccx restarts ZCode: it quits it with a normal quit signal, only when no ZCode task is running (otherwise it asks you first), and while it is closed sets the folder ZCode opens on (`lastActiveWorkspace` in `~/.zcode/v2/setting.json`). ccx never edits ZCode's databases.

**Network**
- ccx contacts GitHub only to install and to check for updates (`git`), using your proxy if you have one. Your code and conversations are never uploaded by ccx.
- ccx never reads passwords, API keys or login tokens. Usage numbers come from the apps and tools above, not from your accounts.
- Codex's app-server, which ccx starts to read and write Codex threads, signs in with Codex's own login. ccx never opens Codex's or Claude's credential files and never sees those tokens; nothing ccx sends to GitHub carries them.
- The update check runs `git ls-remote` against the public repository with git's credential helpers turned off, so no stored GitHub credentials are used.

Questions: https://github.com/aaronwong1999/ccx/issues
