# 发布与安装策略

## 结论

**现阶段用安装脚本（`curl … | sh`），不做 DMG，也不需要买 Apple 开发者证书。** 等用户量上来、想做给不熟悉终端的人用时，再买证书、出 DMG。

## 为什么脚本够用

| | 安装脚本（现在） | DMG（以后） |
|---|---|---|
| 开发者证书 | **不需要**。菜单栏程序是在用户电脑上用 `swiftc` 现场编译的，本地编译的程序不会被 macOS 的安全检查拦截 | 需要 Apple Developer ID（每年 99 美元），还要做公证，否则用户第一次打开会被拦下，得去"系统设置 → 隐私与安全性"手动放行 |
| 用户要做什么 | 在终端粘贴一行命令 | 下载、拖进"应用程序"、打开 |
| 依赖 | 命令行开发者工具（git / python3 / swiftc）。用 Claude Code 或 Codex 写代码的人几乎都装过；没装的话，脚本会弹出系统安装窗口 | 可以把 Python 运行环境打包进 app，不依赖命令行开发者工具 |
| 自动更新 | ✅ 见下文 | 需要再接入 Sparkle 这类更新框架 |
| 适合 | 开发者（目标用户本来就是用 AI 写代码的人） | 普通用户 |

目标用户本身就在用 Claude Code 和 Codex 写代码，所以"命令行开发者工具"基本都已经有了，脚本安装的门槛很低。

## 安装做了什么（`ccx setup`）

1. ccx 的代码放在 `~/Library/Application Support/ccx/src`，是这个 GitHub 仓库的一份 git 克隆。
2. **Claude**：用 Claude 桌面版自带的 Claude Code CLI（在 `~/Library/Application Support/Claude/claude-code/<版本>/`）运行
   `plugin marketplace add aaronwong1999/ccx` 和 `plugin install ccx@ccx`。
3. **Codex**：用 Codex 桌面版自带的 CLI（在 `ChatGPT.app/Contents/Resources/codex-cli/`）运行
   `plugin marketplace add aaronwong1999/ccx` 和 `plugin add ccx@ccx`。
4. 编译菜单栏程序到 `~/Applications/ccx.app`，并写一个登录启动项（LaunchAgent）。
5. 把 `ccx` 命令链接到 `~/.local/bin/ccx`。
6. 在 Codex 里信任 ccx **自己的**两个 hook。用的是 Codex 自己的 hooks 设置页同样调用的接口（`config/batchWrite` 写入 `hooks.state."<key>".trusted_hash`），只针对 `ccx@ccx` 插件；每次更新后 hook 的哈希会变，`ccx update` 会再信任一次。
7. 清理改名前的旧版本（`claudecodex`）。

用户**不需要**另外安装 Claude Code 或 Codex 的命令行工具。

## 自动更新

- **插件**：两个 app 都把这个 GitHub 仓库当作插件市场，更新插件的机制由 app 自己提供。
- **ccx 本身**：菜单栏程序每天自动运行一次 `ccx update --quiet`，它会：
  1. `git pull` 拉取新代码；
  2. 让两个 app 刷新插件市场并更新插件；
  3. 如果菜单栏程序的源码变了，就重新编译并重启它。

  菜单里也有手动的"检查更新"。
- 发新版的流程：改代码 → 修改 `plugins/ccx/lib/ccx/__init__.py` 和两个 `plugin.json` 里的版本号 → 推送到 `main`。

## 私有仓库阶段

仓库是 private 时，安装命令里的 `raw.githubusercontent.com` 地址和 `git clone` 都需要 GitHub 登录。可以用的办法有：

- 自己和受邀的人：先运行 `gh auth login` 和 `gh auth setup-git`，然后 `gh repo clone aaronwong1999/ccx /tmp/ccx && /tmp/ccx/install.sh`。插件市场同样通过 git 拉取，所以也需要已经登录。
- 公开以后，README 里那一行 `curl … | sh` 就能直接用。

## 以后要做 DMG 时

1. 买 Apple Developer ID，用它签名 `ccx.app`，并用 `notarytool` 公证。
2. 把 python-build-standalone 打包进 `ccx.app/Contents/Resources/python`，启动脚本优先用它，这样连命令行开发者工具都不需要。
3. app 第一次打开时自动执行 `ccx setup`（安装两边的插件、设置登录启动）。
4. 自动更新改用 Sparkle，再加上现在已有的插件市场更新。
5. 也可以提供 `brew install --cask ccx`（Homebrew 要求 cask 必须经过公证）。

## 名称和商标

- 项目名、仓库名、插件名都用 **ccx**，没有用"claudecodex"：Claude 和 Codex 都是商标，放进产品名有暗示官方背书的风险。
- 介绍里可以写"for Claude Code and Codex"这类描述用途的话，同时要注明"与 Anthropic、OpenAI 无关"。
- 只使用两个 app 公开提供的插件机制、导入接口和深链接，只读写本机文件，不碰账号和登录信息。
