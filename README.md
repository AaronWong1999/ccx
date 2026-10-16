<p align="center"><img src="docs/icon.png" width="128" alt="ccx icon"></p>

# ccx - claudecodex

**Sync task memory between Claude Code and Codex. When one runs out of usage, keep going in the other, and come back to the same conversation.**

在 Claude Code 和 Codex 之间同步任务记忆。一边额度用完就到另一边继续，回来时还是原来那个会话。

> ccx is an independent open-source project, not affiliated with Anthropic or OpenAI. "Claude", "Claude Code" and "Codex" are trademarks of their owners.
>
> ccx 是独立的开源项目，与 Anthropic、OpenAI 无关。"Claude"、"Claude Code"、"Codex" 是其所有者的商标。

ccx links a Claude Code session with a Codex thread on your Mac. Whichever app you continue in, the other side's new progress is brought into the conversation you are in. You don't start over and you don't copy-paste. It works with both **desktop apps** while they are running, and it adds a menu bar icon for one-click switching.

ccx 在你的 Mac 上把一个 Claude Code 会话和一个 Codex 线程关联起来。无论你在哪个 app 里继续，另一边的新进展都会带进你当前的对话。不用从头再来，也不用复制粘贴。两个**桌面版** app 开着就能用，另外还有一个菜单栏图标，点一下就能切换。

## Install · 安装

You need macOS 13+ and the Claude and/or Codex desktop app. You don't need to install the Claude Code or Codex CLI: ccx uses the copies bundled inside the desktop apps.

需要 macOS 13 及以上，以及 Claude 和/或 Codex 桌面版。不需要另外安装 Claude Code 或 Codex 的命令行工具，ccx 用的是两个桌面版自带的那一份。

**The easy way:** paste this into Claude Code or Codex. It runs the installer for you (approve the command when asked).
**最简单的方式：** 把下面这段话贴给 Claude Code 或 Codex，它会帮你运行安装命令（弹出确认时点允许即可）。

```
Install ccx for me: run `curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh`, then run `ccx doctor` and tell me the result.
```

**Or run it yourself** in Terminal. **或者自己在终端运行：**

```bash
curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh
```

The installer:

1. puts ccx in `~/Library/Application Support/ccx`;
2. installs the ccx plugin into Claude and Codex. Each plugin syncs in **both directions** with a prompt hook: whenever you send a message, it brings over the other side's new progress;
3. turns that hook on in Codex. Claude Code enables a plugin's hooks as soon as the plugin is installed, but Codex asks you to approve every third-party hook by hand, so the installer approves ccx's own hook (and only that one);
4. builds the ⇄ menu bar icon on your Mac and starts it at login;
5. adds a `ccx` command.

If Apple's Command Line Tools are missing, it opens Apple's installer first. Run the command again when that finishes.

安装脚本会做五件事：

1. 把 ccx 放到 `~/Library/Application Support/ccx`；
2. 把 ccx 插件装进 Claude 和 Codex。两边的插件都用一个"发消息前"的 hook 做**双向**同步：你每发一条消息，就把另一边的新进展带过来；
3. 在 Codex 里启用这个 hook。Claude Code 装好插件后，插件的 hook 自动生效；但 Codex 要求每个第三方 hook 都由用户手动批准，所以安装脚本会替你批准 ccx 自己的 hook，而且只批准这一个；
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

The ⇄ menu lists recent projects and both sides' sessions: ○ new, not linked yet (click to import and link); ✓ linked (click to open the linked conversation); ↻ updated, with progress the other side hasn't received yet. The menu can be shown in English or Chinese (Language / 语言).

⇄ 菜单按项目列出两边的会话：○ 未关联（点一下导入并关联）；✓ 已关联（点一下打开关联的会话）；↻ 有更新，这边有对面还没收到的新进展。菜单可以切换成英文或中文（Language / 语言）。

## FAQ · 常见问题

**Can it carry a big, complex task, or one that stopped because usage ran out?** Yes, that's the main use case. Both apps write every message and tool call to disk as they go, so a conversation cut off by a usage limit is complete up to the moment it stopped. ccx brings over every user message and reply, condensed tool calls and output, the latest task list in full (Claude's todos or Codex's plan), a note when the other side stopped mid-step, and `git status`. The code is already on your disk. Limits: tool output is truncated per call, Codex's encrypted reasoning can't be carried, and a very long first import keeps the most recent ~60k characters plus every user request and the task list.

**能不能迁移复杂任务，或者因为额度用完而中断的会话？** 能，这正是主要用途。两个 app 每说一句话、每调用一次工具都会立刻写到磁盘，所以额度用完那一刻之前的内容都在。ccx 会带过去：所有用户消息和回复、压缩后的工具调用和输出、完整的最新任务清单（Claude 的待办或 Codex 的计划）、对面是否停在某一步中间的提示，以及 `git status`。代码本来就在你的磁盘上。限制：每次工具输出会截断；Codex 加密的推理内容带不过去；很长的会话第一次导入时，只保留最近约 6 万字符，加上你所有的提问和任务清单。

**Why can one message after switching back cost a lot of usage?** Not because of ccx: syncing adds only the condensed new progress (a few thousand tokens). But a conversation that has grown very long (hundreds of thousands of tokens) and sat idle for over an hour, while you worked in the other app, has lost its prompt cache, so the next message there re-reads all of it. ccx watches for this: the ⇄ menu offers a **new, linked conversation** instead (about 20–30k tokens of condensed progress), and if you type into such a conversation directly, ccx pauses that one message once and explains your options (send again to go ahead, `/compact`, or a new conversation). You can turn this off in the menu.

**Does clicking a conversation again send everything again?** No. Each update is delivered once. After every click a window says what happened: imported (with the estimated tokens Codex reads on its first reply), linked with N new updates that arrive with your next message, or **already in sync, nothing added**. Before a long import, the dialog compares the full import with a condensed new conversation (for example ~215k vs ~25k tokens). When the conversation you transfer *to* is itself huge and idle, it shows both numbers separately: what the transfer adds (often just a few thousand tokens) and what the next message there re-reads (the whole conversation, because its cache has expired), next to the cost of a new, linked conversation. You choose. ccx also recognizes Claude Code's own compaction (including the idle compaction in 2.1.299+), so a conversation that has already been compacted isn't treated as huge.

**为什么切回来之后，一条消息可能消耗很多额度？** 原因不在 ccx：同步只带压缩后的新进展（几千 token）。真正的成本在于：一个已经很长的对话（几十万 token），在你去另一个 app 干活时闲置了一个多小时，缓存就过期了，下一条消息会把它整个重新读一遍。ccx 会处理这种情况：⇄ 菜单会建议你**新开一个关联的对话**（只带约 2–3 万 token 的压缩进展）；如果你直接在这种对话里发消息，ccx 会先拦一次并说明几种选择（再发一次照常继续、先运行 `/compact`，或者新开对话）。这个提醒可以在菜单里关闭。

**重复点击同一个会话，会不会把内容再堆一遍？** 不会，每条进展只送一次。每次点击后都会弹窗说明结果：已导入（附 Codex 第一次回复大约要读多少 token）、已关联且有 N 条新进展（你下一条消息时带入），或者**已同步，没有新内容，这次没有追加任何数据**。导入一个很长的对话前，弹窗会对比完整导入和新开压缩对话的消耗（例如约 215k 对比约 25k token）。如果要传去的那个对话本身已经很长又闲置了很久，弹窗会把两个数字分开写清楚：这次传输新增多少（常常只有几千 token），以及你在那边发下一条消息时要重新读多少（缓存过期，整个对话重读），再和新开一个关联对话的消耗放在一起，由你来选。ccx 也能识别 Claude Code 自己的压缩（包括 2.1.299 起的闲置自动压缩），已经压缩过的对话不会被当成超长对话。

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

A Claude session A and a Codex thread T form a pair, and each side keeps a cursor of how much the other side has received. When you send a message in A, the prompt hook adds T's new progress to that message and moves the cursor, to avoid repeatedly forwarding the same entries. This is a best-effort context handoff, not an exactly-once delivery guarantee; use the history reader to recover omitted text. Saying "continue X from …" links the conversation you're in to X; the menu bar and `/to-…` use the apps' native import instead. Session titles are searched across all projects, so a typed name or a screenshot is enough.

Claude 会话 A 和 Codex 线程 T 组成一对，两边各记一个"对面已经收到多少"的位置。你在 A 里发消息时，hook 会把 T 的新进展加到这条消息里，然后移动位置。这样可以避免重复转发同一批记录；这是尽力交接上下文，并不保证严格的只送达一次。省略的文字可通过历史阅读工具补读。在对话里说"从 … 接着 X 干"，会把当前对话和 X 关联起来；菜单栏和 `/to-…` 则用两个 app 自带的导入功能。会话标题会在所有项目里搜索，所以说出名称或给一张截图就够了。

## History and project grouping · 历史与项目归属

On transfer to Codex, ccx first registers the working folder in the desktop through its bundled `codex app <folder>` command and waits until it appears in the saved project index. It then attaches the thread to that desktop project's mapped server ID. Creating only an app-server project is insufficient on some Codex versions—even after restarting. Existing user-assigned projects are kept, and reopening an older ccx pair repairs backend-only membership without importing another conversation.

发到 Codex 时，ccx 会先通过桌面版自带的 `codex app <目录>` 命令登记工作文件夹，等待桌面项目索引确认，再把会话关联到该项目映射的后端 ID。部分版本只创建后端项目并不足够，重启也不会自动补齐。已有的手动项目归属会保留；重新打开旧关联会话也会修复只存在于后端的归属，不会再导入一份。

Some Codex versions import legacy history but use the newer item-pagination API to expand older turns. This causes a permanent “Retry” button. ccx uses Codex's own targeted `migrate-rollouts` command before opening new imports and verifies item paging afterwards. If an older thread still has an active writer, ccx queues the migration and retries from the menu bar every minute. It never kills Codex or rewrites a live database: quit Codex when convenient, leave ccx running, and reopen Codex after the “History repair pending” notice disappears. `ccx repair` retries manually.

部分 Codex 版本导入的是旧历史格式，界面却用新分页接口展开旧消息，导致始终显示“重试”。ccx 会在打开新导入会话前调用 Codex 自带的定向历史迁移，并验证分页可读。如果旧会话仍被进程占用，就排队并通过菜单栏每分钟重试，不会杀掉 Codex 或改写正在使用的数据库。方便时退出 Codex，保留 ccx 运行，等“历史修复待完成”提示消失后再打开 Codex。也可运行 `ccx repair` 手动重试。

**Sync is task context, not a mirrored chat UI.** Progress arriving through a prompt hook is available to the model but does not become additional native chat bubbles. The full record stays in each app; when a condensed handover leaves something out, the model can page through the other side with `read_session` (just ask it to look up the earlier discussion). Tool output remains condensed. Images you pasted travel as the path of the app's own cached copy (`[image: /path]`), so the other app can open them when it needs to; they cost nothing until opened. ccx stores no copies: once the system cleans that cache, the image is gone. Rollout file size is never used to skip updates: paginated history may change only in Codex's database.

**同步的是任务上下文，并非聊天界面的逐条镜像。** Hook 带来的进展模型能读取，但不会变成新的原生聊天气泡。完整记录仍在各自的 app 里；压缩交接时省略的内容，模型可以用 `read_session` 到对面分页补读（让它“查一下之前的讨论”即可）。工具输出仍有压缩。你贴的图片会以该 app 自己缓存的本地路径带过去（`[image: /路径]`），对面需要时直接打开，不打开就不消耗额度。ccx 不另存副本：系统清理了缓存，图片就没了。同步不再按旧记录文件大小跳过检查，因为新历史数据可能只写入 Codex 数据库。

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

## Author · 作者

Made by Aaron, [@aaron0x10](https://x.com/aaron0x10) on X. Feedback and ideas are welcome there or in [Issues](https://github.com/aaronwong1999/ccx/issues).

作者 Aaron，X（推特）：[@aaron0x10](https://x.com/aaron0x10)。欢迎在那里或 [Issues](https://github.com/aaronwong1999/ccx/issues) 反馈和提建议。

## License · 许可

MIT. If ccx saves you time, a ⭐ at [github.com/aaronwong1999/ccx](https://github.com/aaronwong1999/ccx) helps others find it.

MIT 许可。如果 ccx 帮你省了时间，欢迎到 [github.com/aaronwong1999/ccx](https://github.com/aaronwong1999/ccx) 点个 ⭐，让更多人看到它。
