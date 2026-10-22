# Privacy

ccx runs entirely on your Mac. It has no server, no account and no telemetry.

**What it reads**
- Claude Code's session files under `~/.claude/projects` (or `CLAUDE_CONFIG_DIR`), to carry a task between the apps.
- Codex threads and Codex's own usage numbers, only through Codex's app-server API on your Mac.
- When they are installed, the local output of CodexBar, abtop, Claude Code Usage Monitor, ccusage, claude-hud, Claude Status Bar, ccstatusline and CCometixLine, for the usage heads-up.

**What it writes**
- Link records and settings in `~/.ccx`.
- The progress it carries over, into the conversation you continue, in Claude's session files or through Codex's app-server.

**Network**
- ccx contacts GitHub only to install and to check for updates (`git`), using your proxy if you have one. Your code and conversations are never uploaded by ccx.
- ccx never reads passwords, API keys or login tokens. Usage numbers come from the apps and tools above, not from your accounts.

Questions: https://github.com/aaronwong1999/ccx/issues
