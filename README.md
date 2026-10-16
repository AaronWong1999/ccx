# claudecodex (`ccx`)

一个命令把当前项目的对话在 **Claude Code ⇄ Codex** 之间互转，一边额度用完，另一边直接续上。

```bash
cd 你的项目
ccx            # 自动判断：最近用的是哪边，就转到另一边并直接打开
```

## 命令

| 命令 | 作用 |
|---|---|
| `ccx` / `ccx switch` | 取当前目录下两边最近的那个会话，转到另一边 |
| `ccx to-codex [id]` | Claude → Codex |
| `ccx to-claude [id]` | Codex → Claude |
| `ccx ls [-a]` | 列出当前项目（或全部项目）两边的会话 |
| `--open cli\|app\|none` | 转完后：在终端续上（默认）/ 打开桌面版 / 只转换 |
| `ccx install` | 安装 `ccx` 命令 + Claude 的 `/to-codex` skill + Codex 的 `to-claude` skill |

装好 skill 以后，在 app 里直接说"切到 codex" / "切到 claude"就行。

## 原理

- **Claude → Codex**：调用 Codex 自带的 app-server 导入器（`externalAgentConfig/import`，类型 `SESSIONS`），和官方 `codex-plugin-cc` 的 `/codex:transfer` 是同一个接口。导入是完整的，Codex 桌面版和 `codex resume` 都能看到。
- **Codex → Claude**：Claude Code 没有导入接口，所以 `ccx` 读 `~/.codex/sessions/**/rollout-*.jsonl(.zst)`，把对话压缩（保留所有用户消息和 assistant 回复，工具调用和输出截断成摘要），写成 `~/.claude/projects/<项目>/<新id>.jsonl`，再用 `claude --resume` 打开。末尾会附上导入时的 git 状态。

代码状态两边共享同一个工作区，不需要迁移。

## 要求

- Python ≥ 3.10（3.14 自带 zstd；更老的版本需要系统里有 `zstd` 命令）
- `codex` 和 `claude` 命令都已登录。Codex CLI 版本要能识别桌面版用的模型，太旧就 `codex update`。

## 已知限制

- Codex → Claude 是有损的：工具输出被截断，Codex 的推理内容是加密的不会带过去。
- Claude 桌面版侧边栏可能不显示 `ccx` 写入的会话，用 `claude --resume <id>` 打开。
