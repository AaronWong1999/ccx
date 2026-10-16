# ccx

**在 Claude 和 Codex 之间接着干同一个任务。** 一边额度用完，就到另一边接着干；回来的时候还是原来那个会话，不会新建。

> ccx 是独立的开源项目，与 Anthropic、OpenAI 均无关联。"Claude"、"Claude Code"、"Codex" 是各自公司的商标。

English summary: ccx pairs a Claude Code session with a Codex thread on your Mac. Whichever app you continue in, the other side's new progress is injected into the conversation you are in, so you can switch back and forth on the same task without starting over. It installs as a local plugin in both desktop apps plus a menu bar icon. MIT licensed.

## 安装

需要：macOS 13 及以上，Claude 桌面版和/或 Codex 桌面版。**不需要另外安装 Claude Code 或 Codex 的命令行工具**，ccx 用的是两个桌面版自带的那一份。

```bash
curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh
```

这条命令会：

1. 把 ccx 放到 `~/Library/Application Support/ccx`；
2. 把 ccx 插件装进 Claude 和 Codex（从这个 GitHub 仓库装，以后两个 app 会自己更新它）；
3. 在你本机编译右上角菜单栏里的 ⇄ 图标，并设为登录时自动启动；
4. 装一个终端命令 `ccx`。

如果电脑上还没有"命令行开发者工具"（git、python3 都靠它），安装脚本会先弹出系统的安装窗口，装好后再运行一次就行。

**最后一步（只需一次）**：在 Codex 里信任 ccx 的 hook。打开 Codex 桌面版 → 设置 → Hooks → 找到 ccx → 信任；终端版 Codex 里输入 `/hooks`。不信任也能用，只是在 Codex 里要说一句"接着 Claude 继续"才会同步；Claude 那边不需要这一步。

## 怎么用

| 你想 | 怎么做 |
|---|---|
| Claude 额度用完了，到 Codex 接着干 | 在 Codex 新开一个对话，说「**从 Claude 把 XX 那个会话导入，接着干**」。也可以贴一张 Claude 会话的截图，说"接着这个干"。或者点菜单栏 ⇄ → 项目 → 选那个会话 |
| Codex 也用完了，回到 Claude | 打开**原来那个** Claude 会话，随便说一句（比如"继续"），Codex 的新进展会自动带进来 |
| 再回到 Codex | 打开原来那个 Codex 对话，说「接着 Claude 继续」；信任 hook 之后，随便说一句也会自动同步 |
| 主动同步一下 | Claude 里说 `/from-codex`，Codex 里说 `$from-claude` |
| 把当前对话交给另一边 | Claude 里说 `/to-codex`，Codex 里说 `$to-claude`，或者点菜单栏 ⇄ |

菜单栏 ⇄ 会按项目列出两边的会话：

- ○ 未关联：点一下就导入到另一边并配对。
- ✓ 已关联：点一下就打开另一边配对的那个会话。
- ↻ 有新进展：这边有新内容，对面还没收到。

终端里也可以用：`ccx ls`、`ccx ls -q 关键词`、`ccx to-codex`、`ccx to-claude`、`ccx doctor`、`ccx update`、`ccx uninstall`。

## 原理

所有处理都在你本机进行，没有服务器，也不上传任何东西。

```
 Claude 桌面版                                    Codex 桌面版
 ┌─────────────────────┐                        ┌─────────────────────┐
 │ ccx 插件             │                        │ ccx 插件             │
 │  · skill：/from-codex │                        │  · skill：$from-claude│
 │  · MCP 工具           │──┐                ┌──│  · MCP 工具           │
 │  · 发消息前的 hook    │  │                │  │  · 发消息前的 hook    │
 └─────────────────────┘  │                │  └─────────────────────┘
        读 ~/.claude/projects/*.jsonl      通过 Codex 自带的 app-server 接口
                          │                │   读线程、导入会话
                          ▼                ▼
                   ~/.ccx/pairs.json（配对记录：A ↔ T，两边各同步到第几条）
                          ▲
                 菜单栏 ⇄ 和 `ccx` 命令（同一套代码）
```

- **配对**：一个 Claude 会话和一个 Codex 线程配成一对，两边各记一个"已经送到对面的位置"。
- **写回**：从来不修改正在使用的会话文件。你在 A 里发消息时，hook 检查 T 有没有新内容，有的话就把这些新内容（你说的话、它的回复、工具调用的摘要）作为上下文注入到这条消息里，然后把位置往前推。所以每条进展只送一次，也不会来回反弹。
- **第一次导入**：
  - 在对话里说"从 X 导入"：把**当前这个对话**直接和那个会话配对。
  - 从菜单栏或 `/to-…` 操作：导入到 Codex 用的是 Codex 自带的导入接口；导入到 Claude 是写一个会话文件，再通过 Claude 自带的 `claude://resume` 打开。
- **按名称找会话**：在所有项目里按标题搜索，所以截图或口述里的会话名称都能找到。
- **工作目录**：代码只有一份，就在你的磁盘上，所以不需要同步文件。如果两边的工作目录不一样，ccx 会在上下文里写明，让模型先问你：是切换到那个目录接着干，还是只拿来参考。如果是同一个仓库的不同 worktree，还会附上两边的分支和 git 状态。
- **两个 app 开着就能用**：Codex 的数据只通过 Codex 自己的接口读写；同步时只注入上下文，不碰会话文件，所以不会和正在运行的 app 冲突。
- **限制**：同步过去的是压缩版。你说的话和它的回复都完整保留，工具输出会截断成摘要；Codex 的推理内容是加密的，带不过去。内容太长时只保留最近的部分，更早的只保留你说过的话。

## 卸载

```bash
ccx uninstall          # 移除两边的插件、菜单栏图标和 ccx 命令（配对记录保留）
ccx uninstall --purge  # 连 ~/.ccx 里的配对记录一起删
```

## 开发

```bash
git clone https://github.com/aaronwong1999/ccx && cd ccx
./install.sh --dev                      # 插件从这个本地目录安装
python3 -m unittest discover -s tests   # 不需要 Claude 或 Codex 也能跑
```

代码结构：`plugins/ccx/` 是插件本体，里面同时放了 `.claude-plugin` 和 `.codex-plugin` 两套清单，`lib/ccx/` 是只用 Python 标准库写的核心代码；`menubar/` 是 Swift 写的菜单栏程序。发布方式见 [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md)。

## 许可

MIT
