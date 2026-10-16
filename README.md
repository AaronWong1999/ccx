# claudecodex

在 **Claude 桌面版** 和 **Codex 桌面版** 之间互相导入会话。一边额度用完，就在另一边选中那个会话，接着干。之前导入过的只会同步新内容，不会重复导入。

## 点哪里

**屏幕右上角菜单栏的 ⇄ 图标**。点开以后：

```
⇄
├─ synheart ▸   拿到 Claude 继续 · 来自 Codex
│               ○ 请你打开 baidu.com…          10-16 15:18
│               ↻ 微信支付接入…                10-16 10:53   ← 对面有新内容，点一下同步
│               ─────────
│               拿到 Codex 继续 · 来自 Claude
│               ✓ 百度登录页面                  10-16 14:59   ← 已同步，点一下直接打开
├─ robindex ▸
├─ …
├─ 登录时自动启动
└─ 刷新 / 退出
```

点一个会话：导入（已导入过的就只同步），然后自动在另一边的桌面版里打开。不用打字，也不用记命令。

## 在 app 里说一句也行

装好以后，两个 app 里都多了这几个命令：

| 在哪 | 说什么（或输入命令） | 效果 |
|---|---|---|
| Claude | `/from-codex` 或"导入 codex 的会话" | 弹出选择框，列出本项目的 Codex 会话 → 选一个 → 导入/同步 → 自动跳到那个会话 |
| Claude | `/to-codex` 或"切到 codex" | 把当前会话发到 Codex，并在 Codex 里打开 |
| Codex | `$from-claude` 或"导入 claude 的会话" | 列出本项目的 Claude 会话 → 选一个 → 导入/同步 → 在 Codex 里打开 |
| Codex | `$to-claude` 或"切到 claude" | 把当前线程发到 Claude，并在 Claude 桌面版里打开 |

列表里每个会话都会标出状态：**未导入**、**对面有新内容，可同步**、**已同步**。

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
- **同步**：
  - Codex → Claude：上次导入后，如果那个 Claude 会话没被动过（文件修改时间没变，也没有你自己加的对话），就原地更新；否则另建一个新会话，旧的不碰。
  - Claude → Codex：重新导入一份，旧线程如果没被继续聊过就归档。如果旧线程正在 Codex 里打开，Codex 会拒绝归档（"active writer"），这时旧线程保留不动。

## 实现

- `plugins/claudecodex/`：一个插件目录，同时带有 `.claude-plugin/` 和 `.codex-plugin/` 两套清单。
- `lib/claudecodex/mcp_server.py`：只用 Python 标准库的 MCP 服务器，提供三个工具：`list_sessions`（只读）、`import_session`、`send_current_session`。
- `lib/claudecodex/sync.py`：判断该新导入、同步还是不用动，导入关系记在 `~/.claudecodex/links.json`。导入状态也会读 Codex 自己的导入历史，所以 Codex app 或官方插件之前导入过的会话，也会显示为"已同步"。
- 需要 Python ≥ 3.9（macOS 自带的就够）。Codex 会话是 zstd 压缩的：Python 3.14 能直接读，更老的版本需要 `brew install zstd`。

## 限制

- Codex → Claude 的转换是有损的：保留所有用户消息和回复，工具调用和工具输出会截断成摘要，Codex 加密的推理内容不会带过去。
- `claude://resume` 深链接和 Claude Code 会话文件的格式都不是公开文档里的接口，Claude 以后更新可能会改。
- 所有数据只在本机处理，用的都是两个 app 自己提供的插件机制、导入接口和深链接，不碰账号和登录信息。
