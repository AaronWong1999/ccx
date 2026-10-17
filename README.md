<p align="center">
  <img src="docs/hero.png" alt="ccx - claudecodex: sync task memory between Claude and Codex. Claude Code hits its usage limit, click ⇄ in the menu bar, Codex picks up where Claude stopped." width="100%">
</p>

<h1 align="center">ccx - claudecodex</h1>

<p align="center"><b>Sync task memory between Claude and Codex.</b><br>在 Claude 和 Codex 之间同步任务记忆。</p>

<p align="center">
  <a href="https://github.com/aaronwong1999/ccx/stargazers"><img src="https://img.shields.io/github/stars/aaronwong1999/ccx?style=social" alt="GitHub stars"></a>
  <a href="https://x.com/aaron0x10"><img src="https://img.shields.io/badge/follow-%40aaron0x10-000000?logo=x&logoColor=white" alt="Follow @aaron0x10 on X"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/macOS-13%2B-black?logo=apple" alt="macOS 13+">
</p>

<p align="center">
  Built by <a href="https://x.com/aaron0x10"><b>Aaron (@aaron0x10)</b></a>, who also made <a href="https://github.com/AaronWong1999/hermesclaw">HermesClaw</a> (featured in the official <a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a> README).
</p>

> ccx is an independent open-source project, not affiliated with Anthropic or OpenAI. "Claude", "Claude Code" and "Codex" are trademarks of their owners.

## Why ccx · 为什么需要它

<p align="center">
  <b>Hit your Claude Code usage limit? Keep going in Codex. Codex runs out? Back to Claude.</b><br>
  <b>Same task, same conversation, no waiting for the 5-hour reset.</b><br>
  撞上 Claude Code 的额度上限？切到 Codex 接着干；Codex 也用完了，再切回 Claude。同一个任务、同一段对话，不用干等 5 小时额度恢复。
</p>

| | Without ccx · 没有 ccx | With ccx · 有了 ccx |
|---|---|---|
| Usage limit hit<br>额度用完 | Wait for the 5-hour reset<br>干等恢复 | Continue in the other app<br>切到另一个继续干 |
| Switching apps<br>换 app | Re-explain all context<br>重新解释全部上下文 | The other side already knows<br>对面已经知道进展 |
| Coming back<br>切回来 | Start a new chat<br>新开对话 | Same conversation, same progress<br>原来的对话，同样的进展 |

ccx links a Claude Code session with a Codex thread on your Mac and keeps them in sync in both directions. It works inside both **desktop apps**, adds a ⇄ menu bar icon for one-click switching, and runs entirely on your Mac: no account, no server, no telemetry.

ccx 在你的 Mac 上把一个 Claude Code 会话和一个 Codex 线程关联起来，双向同步。它直接在两个**桌面版** app 里工作，菜单栏 ⇄ 图标一点就能切换；全部在本机运行：不用注册、没有服务器、不收集数据。

## Install · 安装

**You need:** a Mac with macOS 13 or later, and the **Claude** desktop app and/or the **Codex** desktop app. To move work between them you want both, but you can install ccx with one and add the other later. You don't need to install the Claude Code or Codex CLI, Homebrew, or anything with `sudo`: ccx uses the copies bundled inside the desktop apps.

**需要：** macOS 13 及以上的 Mac，以及 **Claude** 桌面版和/或 **Codex** 桌面版。要在两边之间来回切换当然需要两个都装，但先装一个也可以，另一个之后再装。不需要另外安装 Claude Code 或 Codex 的命令行工具、Homebrew，也不需要 `sudo`：ccx 用的是两个桌面版自带的那一份。

- Claude: [claude.com/download](https://claude.com/download). Open it once and click **Code**, so it downloads Claude Code.<br>下载后打开一次并点 **Code**，让它下载 Claude Code。
- Codex: [openai.com/codex](https://openai.com/codex) (the Codex / ChatGPT desktop app).<br>Codex / ChatGPT 桌面版。

**The easy way:** paste this into Claude Code or Codex. It runs the installer for you.<br>**最简单：** 把下面这段话贴给 Claude Code 或 Codex，它会帮你运行安装命令。

```
Install ccx for me: run `curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh` (it needs network access and writes to my home folder), then run `~/.local/bin/ccx doctor` and tell me the result.
```

**Or run it yourself** in Terminal.<br>**或者自己在终端运行：**

```bash
curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh
```

### What you may be asked · 可能出现的确认

| When · 时机 | What you see · 你会看到 | What to do · 怎么做 |
|---|---|---|
| Installing through Claude Code or Codex<br>让 Claude Code 或 Codex 帮你安装 | The app asks to run the command; Codex may ask to run it outside the sandbox or with network access.<br>app 询问是否运行这条命令；Codex 可能询问是否在沙盒外运行或允许联网 | Allow it.<br>允许 |
| Apple's Command Line Tools are missing (git, python3, swiftc)<br>缺少苹果命令行工具 | A macOS window: "The xcode-select command requires the command line developer tools".<br>macOS 弹窗："xcode-select 命令需要命令行开发者工具" | Click **Install**, accept the license, wait 5–10 minutes, then run the install command again.<br>点**安装**、同意许可，等 5–10 分钟后再运行一次安装命令 |
| The menu bar icon is set to start at login<br>菜单栏图标设为登录时启动 | A macOS notice: "Background Items Added".<br>macOS 通知："已添加后台项目" | Nothing; keep it on (System Settings → General → Login Items).<br>不用管，保持开启（系统设置 → 通用 → 登录项） |
| ccx shows a result or update notice<br>ccx 显示同步结果或更新提示 | A request to allow notifications (may show as "Script Editor").<br>请求允许通知（可能显示为"脚本编辑器"） | Allow, so you see sync results.<br>允许，这样能看到同步结果 |
| ccx opens a project in Codex for the first time<br>ccx 第一次在 Codex 里打开某个项目 | Codex: "Trust this folder?"<br>Codex："信任此文件夹吗？" | Trust it if it's your project; this is Codex's own check.<br>是你自己的项目就信任；这是 Codex 自己的检查 |

Nothing else asks for passwords, admin rights or accessibility access.<br>除此之外，不会要求密码、管理员权限或辅助功能权限。

### What the installer does · 安装脚本做了什么

1. Checks macOS, the desktop apps and Apple's Command Line Tools; with neither app installed it stops and changes nothing.<br>检查系统版本、两个桌面版和苹果命令行工具；两个 app 都没装就停下，不做任何改动。
2. Downloads the newest release of ccx to `~/Library/Application Support/ccx`.<br>把 ccx 的最新正式版下载到 `~/Library/Application Support/ccx`。
3. Installs the ccx plugin into Claude and Codex from that copy. Its prompt hook brings the other side's new progress into a linked conversation whenever you send a message, and never blocks a message.<br>用这份副本把 ccx 插件装进 Claude 和 Codex。它的 hook 在已关联的对话里每发一条消息就带入对面的新进展，从不拦截消息。
4. Turns that hook on in Codex, which asks for every third-party hook to be approved; the installer approves ccx's own hook and only that one.<br>在 Codex 里启用这个 hook：Codex 要求手动批准第三方 hook，安装脚本只批准 ccx 自己的这一个。
5. Builds the ⇄ menu bar icon on your Mac (nothing downloaded needs a signature) and starts it at login.<br>在本机编译菜单栏 ⇄ 图标（不下载任何需要签名的程序），并设为登录时启动。
6. Adds a `ccx` command in `~/.local/bin`, and puts that folder on your PATH in `~/.zprofile` if needed.<br>在 `~/.local/bin` 加一个 `ccx` 命令，必要时把这个目录写进 `~/.zprofile` 的 PATH。

### If something's missing · 缺东西时会怎样

- **Only one app installed:** ccx sets that one up; install the other later and the menu bar icon finishes setup by itself.<br>**只装了一个 app：** 先装好这一个；之后装上另一个，菜单栏图标会自动补装。
- **Claude installed but Code never opened:** open Claude and click **Code** once; ccx then finishes setup by itself.<br>**装了 Claude 但没点过 Code：** 打开 Claude 点一次 **Code**，ccx 会自动补装。
- **Neither app:** the installer stops with download links and changes nothing.<br>**两个都没装：** 安装脚本给出下载链接后停下，不做任何改动。
- **Anything else:** `ccx doctor` lists what's missing, `ccx setup` repairs, and re-running the install command is always safe.<br>**其他情况：** `ccx doctor` 列出缺什么，`ccx setup` 修复，重复运行安装命令总是安全的。

## Use · 使用

| You want to · 你想 | Do this · 怎么做 |
|---|---|
| Claude ran out; continue in Codex<br>Claude 额度用完，到 Codex 接着干 | Click ⇄ → project → session. Or in a new Codex conversation say **"continue the ‹name› session from Claude"**, or paste a screenshot and say "continue this".<br>点 ⇄ → 项目 → 会话。或者在 Codex 新开对话说**"从 Claude 把 ‹名称› 那个会话导入，接着干"**，也可以贴截图说"接着这个干" |
| Codex ran out too; back to Claude<br>Codex 也用完了，回到 Claude | Open the **same** Claude conversation and send anything ("continue"); Codex's progress comes in.<br>打开**原来那个** Claude 对话随便说一句（比如"继续"），Codex 的进展会自动带进来 |
| Back to Codex again<br>再回到 Codex | Open the same Codex conversation and send anything.<br>打开原来那个 Codex 对话，随便说一句 |
| Pull progress now<br>立刻同步一下 | Claude: `/from-codex` · Codex: `$from-claude` |
| Hand this conversation over<br>把当前对话交给另一边 | Claude: `/to-codex` · Codex: `$to-claude` · or click ⇄ · 或点 ⇄ |

The ⇄ menu lists recent projects and both sides' sessions: ○ not linked yet (click to import and link), ✓ linked (click to open the partner), ↻ has progress the other side hasn't received. English or Chinese via Language / 语言.

⇄ 菜单按项目列出两边的会话：○ 未关联（点一下导入并关联），✓ 已关联（点一下打开对面），↻ 有对面还没收到的新进展。可在 Language / 语言 里切换中英文。

## FAQ · 常见问题

**What do I do when Claude Code hits its usage limit (or Codex hits its rate limit)?** Click ⇄ in the menu bar and pick the conversation: it continues in the other app with the task, the plan and the progress so far. When the first app's limit resets, open the original conversation and send anything; the other side's work comes back with it.

**Claude Code 额度用完（或者 Codex 到了速率上限）怎么办？** 点菜单栏的 ⇄，选中这个对话，它就会在另一个 app 里带着任务、计划和进度继续。原来那边额度恢复后，打开原来的对话随便说一句，另一边做的事就带回来了。

**Does it bypass usage limits?** No. You use your own Claude and ChatGPT/Codex plans, each within its own limits; ccx only moves the task between them.

**这是在绕过额度限制吗？** 不是。你用的是自己的 Claude 和 ChatGPT/Codex 订阅，各自在各自的额度内；ccx 只是在两边之间搬运任务。

**What exactly is carried over?** Every user message and reply, condensed tool calls and output, the latest task list (Claude's todos or Codex's plan), a note when the other side stopped mid-step, your unfinished `/goal`, pasted images (as the path of the app's own cached copy), and `git status`. The code is already on your disk. It arrives as context for the model, not as new chat bubbles; a very long first handover keeps the most recent ~60k characters plus every request, and the model can page through the rest with `read_session`. ccx never sets a `/goal` for you: when one is unfinished, the result window puts the `/goal …` command on your clipboard.

**具体会带过去什么？** 所有用户消息和回复、压缩后的工具调用和输出、最新任务清单（Claude 的待办或 Codex 的计划）、对面是否停在某一步中间、未完成的 `/goal`、你贴的图片（以该 app 自己缓存的路径），以及 `git status`。代码本来就在你的磁盘上。这些内容作为上下文交给模型，不会变成新的聊天气泡；很长的会话第一次交接时保留最近约 6 万字符和你所有的提问，其余部分模型可以用 `read_session` 补读。ccx 从不替你设置 `/goal`：有未完成的目标时，结果弹窗会把 `/goal …` 指令放到剪贴板。

**How much usage does a transfer cost? Does clicking again send everything again?** Each update is delivered once, usually a few thousand tokens; clicking again with nothing new says **already in sync** and adds nothing. The real cost is elsewhere: a very long conversation that sat idle for over an hour has lost its prompt cache, so the next message there re-reads all of it. Before a long import or a resume like that, the menu shows both numbers (for example ~215k for a full import vs ~25k for a new, linked conversation with the condensed progress) and lets you choose. ccx never interrupts a conversation you simply keep using, and it recognizes Claude Code's own compaction.

**传输一次花多少额度？重复点击会不会再发一遍？** 每条进展只送一次，通常几千 token；没有新内容时再点会显示**已同步**，不追加任何东西。真正的成本在别处：一个很长的对话闲置一个多小时后缓存过期，下一条消息会把它整个重读一遍。遇到这种长导入或长对话，菜单会先把两个数字列出来（例如完整导入约 215k，新开一个带压缩进展的关联对话约 25k），由你来选。你在自己的对话里正常继续时，ccx 从不打断；它也能识别 Claude Code 自己的压缩。

**Do I have to close an app first? Is anything uploaded?** No and no. Codex data goes only through Codex's own app-server API, sync only adds context to the conversation you're in, and everything runs on your Mac.

**要先关掉某个 app 吗？会上传什么吗？** 都不用。Codex 的数据只通过 Codex 自己的 app-server 接口读写，同步只是往当前对话里加上下文，全部在本机运行。

**What if the two sides work in different folders?** ccx says so, and the model asks whether to switch folders or use the progress as reference. For two worktrees of one repo it shows both branches.

**两边的工作目录不一样怎么办？** ccx 会写明这一点，模型会先问你：切换到那个目录接着干，还是只拿来参考。同一个仓库的两个 worktree 还会显示两边的分支。

**An imported Codex conversation isn't under its project, or shows "Retry" on older history?** ccx files each imported thread under its project in the Codex sidebar, and runs Codex's own history migration so older turns open. If Codex still has that thread open, the repair waits until you quit Codex (the menu shows "History repair pending"); `ccx repair` retries by hand. ccx never kills Codex or edits its database.

**导入到 Codex 的对话没归到项目下，或者旧消息一直显示"重试"？** ccx 会把导入的对话归到 Codex 侧边栏对应的项目下，并调用 Codex 自带的历史迁移让旧消息能展开。如果 Codex 正开着那个对话，修复会等你退出 Codex 后进行（菜单显示"历史修复待完成"）；也可以运行 `ccx repair` 手动重试。ccx 从不强行关闭 Codex，也不改它的数据库。

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

A Claude session A and a Codex thread T form a pair, and each side keeps a cursor of how much the other side has received. When you send a message in A, the prompt hook adds T's new progress to that message and moves the cursor, to avoid repeatedly forwarding the same entries. This is a best-effort context handoff; the model can page through anything omitted with `read_session`. Saying "continue X from …" links the conversation you're in to X; the menu bar and `/to-…` use the apps' native import instead. Session titles are searched across all projects, so a typed name or a screenshot is enough.

Claude 会话 A 和 Codex 线程 T 组成一对，两边各记一个"对面已经收到多少"的位置。你在 A 里发消息时，hook 会把 T 的新进展加到这条消息里，然后移动位置。这样可以避免重复转发同一批记录；这是尽力交接上下文；省略的内容模型可以用 `read_session` 补读。在对话里说"从 … 接着 X 干"，会把当前对话和 X 关联起来；菜单栏和 `/to-…` 则用两个 app 自带的导入功能。会话标题会在所有项目里搜索，所以说出名称或给一张截图就够了。

## Updates · 更新

When a new release is published (checked every 3 hours), the ⇄ app installs it automatically and notifies you. You can switch this off in the menu, and then you get a notification and an "Update to x.y.z" item instead. `ccx update` does the same by hand.

GitHub 上发布新版本后（每 3 小时检查一次），⇄ 菜单栏程序会自动安装并通知你。可以在菜单里关掉自动安装，关掉后只会收到通知，菜单里出现"更新到 x.y.z"。手动更新用 `ccx update`。

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

## Star History

<a href="https://www.star-history.com/#aaronwong1999/ccx&Date">
  <img src="https://api.star-history.com/svg?repos=aaronwong1999/ccx&type=Date" alt="Star History Chart" width="600">
</a>

## Author · 作者

Made by Aaron, [@aaron0x10](https://x.com/aaron0x10) on X. Feedback and ideas are welcome there or in [Issues](https://github.com/aaronwong1999/ccx/issues).

作者 Aaron，X（推特）：[@aaron0x10](https://x.com/aaron0x10)。欢迎在那里或 [Issues](https://github.com/aaronwong1999/ccx/issues) 反馈和提建议。

## License · 许可

MIT. If ccx saves you time, a ⭐ at [github.com/aaronwong1999/ccx](https://github.com/aaronwong1999/ccx) helps others find it.

MIT 许可。如果 ccx 帮你省了时间，欢迎到 [github.com/aaronwong1999/ccx](https://github.com/aaronwong1999/ccx) 点个 ⭐，让更多人看到它。
