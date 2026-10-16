# ccx - claudecodex

**Continue the same task across Claude Code and Codex: when one runs out of usage, keep going in the other, and come back to the same conversation.**
在 Claude Code 和 Codex 之间接着干同一个任务：一边额度用完就到另一边继续，回来时还是原来那个会话。

> ccx is an independent open-source project, not affiliated with Anthropic or OpenAI. "Claude", "Claude Code" and "Codex" are trademarks of their owners.

ccx links a Claude Code session with a Codex thread on your Mac. Whichever app you continue in, the other side's new progress is brought into the conversation you are in. You don't start over and you don't copy-paste. It works with both **desktop apps** while they are running, and it adds a menu bar icon for one-click switching.

## Install

You need macOS 13+ and the Claude and/or Codex desktop app. You don't need to install the Claude Code or Codex CLI: ccx uses the copies bundled inside the desktop apps.

**The easy way:** paste this into Claude Code or Codex.

```
Install ccx for me: run `curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh`, then run `ccx doctor` and tell me the result.
```

**Or run it yourself** in Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh
```

The installer:

1. puts ccx in `~/Library/Application Support/ccx`;
2. installs the ccx plugin into Claude and Codex from this repository;
3. trusts ccx's own sync hook in Codex (Codex otherwise asks you to approve each third-party hook by hand);
4. builds the ⇄ menu bar icon on your Mac (no download, so no signing needed) and starts it at login;
5. adds a `ccx` command.

If Apple's Command Line Tools are missing (they provide git and python3), the installer opens Apple's installer first. Run the command again when it finishes.

## Use

| You want to | Do this |
|---|---|
| Claude ran out of usage; continue in Codex | In a new Codex conversation, say **"continue the ‹name› session from Claude"**. You can also paste a screenshot of the Claude session and say "continue this". Or click ⇄ → project → the session. |
| Codex ran out too; go back to Claude | Open the **same** Claude conversation and send anything ("continue"). Codex's progress comes in automatically. |
| Back to Codex again | Open the same Codex conversation and send anything. Claude's progress comes in automatically. |
| Pull the other side's progress now | Claude: `/from-codex`; Codex: `$from-claude`; or just say "continue from Codex/Claude". |
| Hand this conversation to the other app | Claude: `/to-codex`; Codex: `$to-claude`; or click ⇄. |

The ⇄ menu lists recent projects and both sides' sessions:

- **○ not linked**: click to import into the other app and link the two.
- **✓ linked**: click to open the linked conversation.
- **↻ new progress**: this side has progress the other side hasn't received yet.

In Terminal: `ccx ls`, `ccx ls -q <words>`, `ccx to-codex`, `ccx to-claude`, `ccx doctor`, `ccx update`, `ccx uninstall`.

## FAQ

**Can it carry a big, complex task, or one that stopped because usage ran out?**
Yes, that's the main use case. Both apps write every message and tool call to disk as they go, so a conversation cut off by a usage limit is complete up to the moment it stopped. When you continue on the other side, ccx brings over:

- every user message and assistant reply;
- tool calls and their output, condensed;
- the **latest task list**, in full: Claude's todo list or Codex's plan;
- a note when the other side **stopped in the middle of a step**, so the model checks whether that step finished before it moves on;
- `git status`.

The code itself is already on your disk and is never copied. Limits:

- tool output is truncated to a few hundred characters per call;
- Codex's hidden reasoning is encrypted and can't be carried over;
- a very long first import keeps the most recent ~60k characters, plus every earlier user request and the task list.

**Do I have to close an app first?** No. Codex data is only read and written through Codex's own app-server API. Syncing only adds context to the conversation you're in; it never edits a live session file.

**What if the two sides work in different folders?** ccx says so in the synced context and the model asks you whether to switch folders or use the progress as reference only. For two worktrees of the same repo, it shows both branches and the other side's `git status`.

**Is anything uploaded?** No. Everything runs locally. ccx only uses the apps' own plugin systems, import API and deep links.

## How it works

```
 Claude desktop                                  Codex desktop
 ┌──────────────────────┐                      ┌──────────────────────┐
 │ ccx plugin            │                      │ ccx plugin            │
 │  · skills /from-codex │                      │  · skills $from-claude│
 │  · MCP tools          │──┐              ┌────│  · MCP tools          │
 │  · prompt hook        │  │              │    │  · prompt hook        │
 └──────────────────────┘  │              │    └──────────────────────┘
      reads ~/.claude/projects/*.jsonl    Codex app-server API (thread/list,
                           │              │    thread/read, session import)
                           ▼              ▼
              ~/.ccx/pairs.json  (A ↔ T, and how far each side has been delivered)
                           ▲
                 ⇄ menu bar app and `ccx` CLI (same code)
```

- **Linking.** A Claude session A and a Codex thread T form a pair. Each side keeps a cursor: how much of it the other side has already received.
- **Syncing.** When you send a message in A, the prompt hook checks T for anything past its cursor. If there is, it adds that to your message as context and moves the cursor. Every piece of progress is delivered exactly once and never bounces back.
- **First import.**
  - Saying "continue X from …" in a conversation links *that* conversation to X.
  - The menu bar and `/to-…` import natively: Codex's own importer, or a new Claude session file opened through `claude://resume`.
- **Finding sessions.** Titles are searched across every project, so a name you type or one in a screenshot is enough.

## Updates

Releases are published on GitHub. The ⇄ app checks every few hours. When a new release is out, it **installs it automatically** and notifies you. You can turn this off in the menu ("Install Updates Automatically"). Then you get a notification and an "Update to x.y.z" item instead. `ccx update` and the menu's "Check for Updates…" do the same by hand.

## Uninstall

```bash
ccx uninstall          # removes the plugins, the menu bar icon and the `ccx` command
ccx uninstall --purge  # also deletes the link records in ~/.ccx
```

## Development

```bash
git clone https://github.com/aaronwong1999/ccx && cd ccx
./install.sh --dev                      # install the plugin from this checkout
python3 -m unittest discover -s tests   # needs neither Claude nor Codex
```

- `plugins/ccx/` is the plugin. It carries both a `.claude-plugin` and a `.codex-plugin` manifest; `lib/ccx/` is the core, in standard-library Python 3.9+.
- `menubar/` is the Swift menu bar app.

To release, see [docs/RELEASING.md](docs/RELEASING.md).

## License

MIT. If ccx saves you some time, a ⭐ at [github.com/aaronwong1999/ccx](https://github.com/aaronwong1999/ccx) helps others find it.
