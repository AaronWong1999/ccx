# claudecodex

在 **Claude 桌面版** 和 **Codex 桌面版** 之间互相导入会话。一边额度用完，就在另一边选中那个会话，接着干。之前导入过的只会同步新内容，不会重复导入。

## 怎么用

**核心概念：配对。** Claude 的一个会话 A 和 Codex 的一个线程 T 配成一对以后，两边就是同一个任务的两个窗口。在哪边干活，另一边下次打开时都能接上，**一直在 A 和 T 里继续，不会新建会话**。

| 场景 | 怎么做 |
|---|---|
| 第一次：A 在 Claude 里额度用完了 | 在 Codex 里新开一个对话，说「从 Claude 把 XX 那个会话导入，接着干」；或者点菜单栏 ⇄ → 项目 → 选 A |
| T 在 Codex 里也用完了，回到 Claude | 打开原来的 A，**随便说一句**（比如「继续」）。hook 会自动把 T 的新进展带进 A |
| A 又用完了，回到 Codex | 打开原来的 T，说「接着 Claude 继续」。在 Codex 里信任 claudecodex 的 hook 之后，随便说一句也会自动带上 |
| 想主动同步一下 | Claude 里说 `/from-codex` 或「接着 codex 继续」；Codex 里说 `$from-claude` 或「接着 claude 继续」 |
| 想把当前对话交给另一边 | Claude 里说 `/to-codex`；Codex 里说 `$to-claude`；或者点菜单栏 ⇄ |

**菜单栏 ⇄**：按项目列出两边的会话。○ 未关联（点一下导入并配对），✓ 已关联（点一下打开配对的那个会话），↻ 有新进展、对面还没收到。

### 写回是怎么实现的

不修改正在使用的会话文件。每对会话记两个游标，表示"对面已经同步到这一条"。同步时把对面游标之后的新内容（用户消息、回复、工具调用摘要）注入到当前对话的上下文里，然后推进游标，所以每条进展只会送达一次。我们自己的同步内容和工具调用会被过滤掉，不会再传回去。

- **Claude**：插件自带 `UserPromptSubmit` hook，你一发消息就自动注入，不需要额外操作。
- **Codex**：同一个 hook 也能用，但 Codex 要求你先信任它（在 Codex 的 hooks 设置里信任 claudecodex，或者在终端版 Codex 里用 `/hooks`）。没信任之前，说「接着 Claude 继续」也一样能拉取。
- 第一次配对：如果从菜单或 `/to-…` 操作，会用原生导入（Codex 自带的导入接口，或者写一个新的 Claude 会话文件）建立 T 或 A；如果在对话里说「从 X 导入…」，就**直接把当前这个对话**和那个会话配成一对。

## 安装

```bash
git clone <this repo> && cd claudecodex && ./install.sh
```

`install.sh` 会把这个仓库作为**本地插件市场**，加到 Claude Code 和 Codex 里，并安装 `claudecodex` 插件。插件是本地安装的，不经过任何商店审核。装完后新开的会话或线程里就能用。另外它还会装一个终端命令 `ccx`：

```bash
ccx            # 当前项目：最近用的那边 → 另一边，然后打开桌面版
ccx ls         # 两边的会话和同步状态
ccx to-codex [id] / ccx to-claude [id]
ccx --cli ...  # 在终端里续上，不打开桌面版
```

## 两个 app 开着也能用

不用先关掉任何一个 app。

- **→ Codex**：用的是 Codex 自带的导入接口（`externalAgentConfig/import`，Codex 桌面版自己的"从 Claude 导入"和官方 `codex-plugin-cc` 的 `/codex:transfer` 用的也是它），数据由 Codex 自己写。之后用 `codex://threads/<id>` 打开。
- **→ Claude**：写一个**新的** Claude Code 会话文件，再用 Claude 桌面版自带的 `claude://resume?session=<id>` 深链接，让 app 自己导入并打开。
- **同步**：配对之后不再碰任何会话文件，只往当前对话注入上下文，所以不会和正在运行的 app 冲突。

## 实现

- `plugins/claudecodex/`：一个插件目录，同时带有 `.claude-plugin/` 和 `.codex-plugin/` 两套清单。
- `lib/claudecodex/mcp_server.py`：只用 Python 标准库的 MCP 服务器，提供三个工具：`list_sessions`（只读）、`import_session`、`send_current_session`。
- `lib/claudecodex/sync.py`：判断该新导入、同步还是不用动，配对和游标记在 `~/.claudecodex/pairs.json`，hook 的运行记录在 `~/.claudecodex/hook.log`。导入状态也会读 Codex 自己的导入历史，所以 Codex app 或官方插件之前导入过的会话，也会显示为"已同步"。
- 需要 Python ≥ 3.9（macOS 自带的就够）。Codex 会话是 zstd 压缩的：Python 3.14 能直接读，更老的版本需要 `brew install zstd`。

## 限制

- Codex → Claude 的转换是有损的：保留所有用户消息和回复，工具调用和工具输出会截断成摘要，Codex 加密的推理内容不会带过去。
- `claude://resume` 深链接和 Claude Code 会话文件的格式都不是公开文档里的接口，Claude 以后更新可能会改。
- 所有数据只在本机处理，用的都是两个 app 自己提供的插件机制、导入接口和深链接，不碰账号和登录信息。
