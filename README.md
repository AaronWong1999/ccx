<p align="center"><img src="docs/icon.png" width="128" alt="ccx icon"></p>

# ccx - claudecodex

**Continue the same task across Claude Code and Codex: when one runs out of usage, keep going in the other, and come back to the same conversation.**

在 Claude Code 和 Codex 之间接着干同一个任务：一边额度用完就到另一边继续，回来时还是原来那个会话。

> ccx is an independent open-source project, not affiliated with Anthropic or OpenAI. "Claude", "Claude Code" and "Codex" are trademarks of their owners.
>
> ccx 是独立的开源项目，与 Anthropic、OpenAI 无关。"Claude"、"Claude Code"、"Codex" 是其所有者的商标。

ccx links a Claude Code session with a Codex thread on your Mac. Whichever app you continue in, the other side's new progress is brought into the conversation you are in. You don't start over and you don't copy-paste. It works with both **desktop apps** while they are running, and it adds a menu bar icon for one-click switching.

ccx 在你的 Mac 上把一个 Claude Code 会话和一个 Codex 线程关联起来。无论你在哪个 app 里继续，另一边的新进展都会带进你当前的对话。不用从头再来，也不用复制粘贴。两个**桌面版** app 开着就能用，另外还有一个菜单栏图标，点一下就能切换。

## Install · 安装

You need macOS 13+ and the Claude and/or Codex desktop app. You don't need to install the Claude Code or Codex CLI: ccx uses the copies bundled inside the desktop apps.

需要 macOS 13 及以上，以及 Claude 和/或 Codex 桌面版。不需要另外安装 Claude Code 或 Codex 的命令行工具，ccx 用的是两个桌面版自带的那一份。

**The easy way:** paste this into Claude Code or Codex.
**最简单的方式：** 把下面这段话贴给 Claude Code 或 Codex。

```
Install ccx for me: run `curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh`, then run `ccx doctor` and tell me the result.
```

**Or run it yourself** in Terminal. **或者自己在终端运行：**

```bash
curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh
```

The installer:

1. puts ccx in `~/Library/Application Support/ccx`;
2. installs the ccx plugin into Claude and Codex;
3. trusts ccx's own sync hook in Codex;
4. builds the ⇄ menu bar icon on your Mac and starts it at login;
5. adds a `ccx` command.

If Apple's Command Line Tools are missing, it opens Apple's installer first. Run the command again when that finishes.

安装脚本会做五件事：

1. 把 ccx 放到 `~/Library/Application Support/ccx`；
2. 把 ccx 插件装进 Claude 和 Codex；
3. 在 Codex 里信任 ccx 自己的同步 hook；
4. 在本机编译菜单栏 ⇄ 图标，并设为登录时自动启动；
5. 安装一个 `ccx` 命令。

如果电脑上缺少苹果的"命令行开发者工具"，脚本会先打开系统的安装窗口，装好后再运行一次即可。

## Use · 使用

| You want to | Do this |
|---|---|
| Claude ran out of usage; continue in Codex | In a new Codex conversation, say **"continue the ‹name› session from Claude"**, or paste a screenshot of it and say "continue this". Or click ⇄ → project → session. |
| Codex ran out too; go back to Claude | Open the **same** Claude conversation and send anything ("continue"). Codex's progress comes in automatically. |
| Back to Codex again | Open the same Codex conversation and send anything. |
| Pull progress now | Claude: `/from-codex` · Codex: `$from-claude` |
| Hand this conversation over | Claude: `/to-codex` · Codex: `$to-claude` · or click ⇄ |

| 你想 | 怎么做 |
|---|---|
| Claude 额度用完，到 Codex 接着干 | 在 Codex 新开对话，说**"从 Claude 把 ‹名称› 那个会话导入，接着干"**，或者贴一张截图说"接着这个干"。也可以点 ⇄ → 项目 → 会话 |
| Codex 也用完了，回到 Claude | 打开**原来那个** Claude 会话，随便说一句（比如"继续"），Codex 的进展会自动带进来 |
| 再回到 Codex | 打开原来那个 Codex 对话，随便说一句 |
| 立刻同步一下 | Claude：`/from-codex` · Codex：`$from-claude` |
| 把当前对话交给另一边 | Claude：`/to-codex` · Codex：`$to-claude` · 或点 ⇄ |

The ⇄ menu lists recent projects and both sides' sessions: ○ not linked (click to import and link), ✓ linked (click to open the linked conversation), ↻ new progress the other side hasn't received. The menu can be shown in English or Chinese (Language / 语言).

⇄ 菜单按项目列出两边的会话：○ 未关联（点一下导入并关联），✓ 已关联（点一下打开关联的会话），↻ 有对面还没收到的新进展。菜单可以切换成英文或中文（Language / 语言）。

## FAQ · 常见问题

**Can it carry a big, complex task, or one that stopped because usage ran out?** Yes, that's the main use case. Both apps write every message and tool call to disk as they go, so a conversation cut off by a usage limit is complete up to the moment it stopped. ccx brings over every user message and reply, condensed tool calls and output, the latest task list in full (Claude's todos or Codex's plan), a note when the other side stopped mid-step, and `git status`. The code is already on your disk. Limits: tool output is truncated per call, Codex's encrypted reasoning can't be carried, and a very long first import keeps the most recent ~60k characters plus every user request and the task list.

**能不能迁移复杂任务，或者因为额度用完而中断的会话？** 能，这正是主要用途。两个 app 每说一句话、每调用一次工具都会立刻写到磁盘，所以额度用完那一刻之前的内容都在。ccx 会带过去：所有用户消息和回复、压缩后的工具调用和输出、完整的最新任务清单（Claude 的待办或 Codex 的计划）、对面是否停在某一步中间的提示，以及 `git status`。代码本来就在你的磁盘上。限制：每次工具输出会截断；Codex 加密的推理内容带不过去；很长的会话第一次导入时，只保留最近约 6 万字符，加上你所有的提问和任务清单。

**Do I have to close an app first?** No. Codex data only goes through Codex's own app-server API, and syncing only adds context to the conversation you're in. It never edits a live session file.

**要先关掉某个 app 吗？** 不用。Codex 的数据只通过 Codex 自己的 app-server 接口读写；同步只是往当前对话里加上下文，从不修改正在使用的会话文件。

**What if the two sides work in different folders?** ccx says so, and the model asks whether to switch folders or use the progress as reference. For two worktrees of one repo it shows both branches.

**两边的工作目录不一样怎么办？** ccx 会写明这一点，模型会先问你：是切换到那个目录接着干，还是只拿来参考。如果是同一个仓库的两个 worktree，还会显示两边的分支。

**Is anything uploaded?** No. Everything runs locally.

**会上传什么吗？** 不会，所有处理都在本机进行。

## How it works · 原理

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

A Claude session A and a Codex thread T form a pair, and each side keeps a cursor of how much the other side has received. When you send a message in A, the prompt hook adds T's new progress to that message and moves the cursor, so every piece of progress arrives exactly once and never bounces back. Saying "continue X from …" links the conversation you're in to X; the menu bar and `/to-…` use the apps' native import instead. Session titles are searched across all projects, so a typed name or a screenshot is enough.

Claude 会话 A 和 Codex 线程 T 组成一对，两边各记一个"对面已经收到多少"的位置。你在 A 里发消息时，hook 会把 T 的新进展加到这条消息里，然后移动位置。所以每条进展只送达一次，也不会来回反弹。在对话里说"从 … 接着 X 干"，会把当前对话和 X 关联起来；菜单栏和 `/to-…` 则用两个 app 自带的导入功能。会话标题会在所有项目里搜索，所以说出名称或给一张截图就够了。

## Updates · 更新

When a new release is published, the ⇄ app installs it automatically and notifies you. You can switch this off in the menu, and then you get a notification and an "Update to x.y.z" item instead. `ccx update` does the same by hand.

GitHub 上发布新版本后，⇄ 菜单栏程序会自动安装并通知你。可以在菜单里关掉自动安装，关掉后只会收到通知，菜单里出现"更新到 x.y.z"。手动更新用 `ccx update`。

## Uninstall · 卸载

```bash
ccx uninstall          # remove the plugins, menu bar icon and `ccx` command · 移除插件、菜单栏图标和 ccx 命令
ccx uninstall --purge  # also delete link records in ~/.ccx · 同时删除 ~/.ccx 里的关联记录
```

## Development · 开发

```bash
git clone https://github.com/aaronwong1999/ccx && cd ccx
./install.sh --dev                      # install the plugin from this checkout · 从本地目录安装插件
python3 -m unittest discover -s tests   # needs neither Claude nor Codex · 不需要 Claude 或 Codex
```

`plugins/ccx/` is the plugin, with both a `.claude-plugin` and a `.codex-plugin` manifest; `lib/ccx/` is the core in standard-library Python 3.9+. `menubar/` is the Swift menu bar app. Releases: [docs/RELEASING.md](docs/RELEASING.md).

`plugins/ccx/` 是插件本体，同时带有 `.claude-plugin` 和 `.codex-plugin` 两套清单；`lib/ccx/` 是核心代码，只用 Python 3.9+ 标准库。`menubar/` 是 Swift 写的菜单栏程序。发布流程见 [docs/RELEASING.md](docs/RELEASING.md)。

## License · 许可

MIT. If ccx saves you time, a ⭐ at [github.com/aaronwong1999/ccx](https://github.com/aaronwong1999/ccx) helps others find it.

MIT 许可。如果 ccx 帮你省了时间，欢迎到 [github.com/aaronwong1999/ccx](https://github.com/aaronwong1999/ccx) 点个 ⭐，让更多人看到它。
