<p align="center">
  <img src="docs/readme-logo.png" alt="usage 标志" width="128">
</p>

# usage

### 在 macOS 菜单栏中查看 Claude Code、Codex 和 Antigravity 配额。

工作时持续查看 Claude Code、Codex 和 Antigravity 配额。`usage` 将会话限额、每周限额和费用背景信息显示在 macOS 菜单栏中，让你能在配额中断会话前主动管理使用量。

[繁體中文](README.zh-TW.md) · 简体中文 · [English](README.md) · [日本語](README.ja.md) · [한국어](README.ko.md) &nbsp;|&nbsp; [Discussions](https://github.com/aqua5230/usage/discussions) &nbsp;|&nbsp; [官方介绍页](https://aqua5230.github.io/usage/)

[![持续集成](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![最新版本](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![平台](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![许可证：AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![OpenSSF 最佳实践](https://www.bestpractices.dev/projects/13538/badge)](https://www.bestpractices.dev/projects/13538)

<p align="center">
  <img src="docs/showcase.en.png" alt="usage — 固定在 macOS 菜单栏中的 Claude Code 与 Codex 配额" width="820">
</p>

`usage` 将你的 **Claude Code、Codex 和 Antigravity** 配额固定显示在屏幕右上角，并以颜色区分，让你一眼辨识警示等级。所有数值都以被动方式从你电脑上已有的本地文件读取。它**从不调用 Anthropic / OpenAI API**，也**从不读取钥匙串**，因此这个监视器本身不会增加你的 token 使用量。

## 为什么选择 usage？

在会话中途耗尽配额的代价很高，尤其是在依赖 Claude Code 的长时间重构或调试期间。`usage` 会在你触及限额前显示 5 小时和每周限额，并始终保持可见。无需运行命令，也无需打开页面；答案就在你平时已经会看的位置。

## 快速开始

```bash
brew install --cask aqua5230/usage/usage
```

它会自动安装到 Applications 文件夹。先右键点击一次 **Open** 以通过 Gatekeeper，然后点击菜单栏图标。想直接下载或查看完整设置流程？请参见下方的[安装](#安装)。

## 功能一览

### 实时可见

- **常驻监视器：** 配额常驻菜单栏，以绿色到红色的颜色编码显示。需要完整的会话、每周和各项目明细时，点击即可查看。
- **Antigravity 支持：** Antigravity（Gemini）的会话与每周配额以第三张卡片出现在每一款面板。数值来自后台定期运行官方 CLI 的 `/quota` 命令——与你自己输入一次完全相同，并带有 15 分钟缓存。
- **上下文提醒与通知：** 当上下文窗口达到 70% 时，状态栏会提示你使用 `/clear` 或 `/compact`，避免浪费 token。你也可以选择接收关于配额限额和恢复的系统通知。
- **隐藏区块：** 没全都用？点击一次即可从菜单栏和面板中完全隐藏 Claude Code、Codex 或 Antigravity 区块。

### 工作流辅助

- **进度管家：** 打开新的 Claude Code 会话时，`usage` 会直接把你上次的进度交给 AI，包括上次请求、未提交的变更和未完成的待办事项。无需 `/resume`，无需回顾。完全本地运行，默认关闭。
- **Token 节省器：** 菜单栏开关会要求 Claude Code 和 Codex 在当前会话中更简洁地回答，在保持代码和错误信息逐字节不变的同时节省输出 token。轻量的逐消息提醒能避免长对话中的回复逐渐变得冗长（A/B 测试：对话后期回复仍可缩短约 40%）。
- **Token 浪费健康检查：** 每日后台诊断会扫描日志中的浪费问题，包括重复读取文件、污染目录和冗长的 Bash 输出。发现问题时会显示一行提示；对 AI 说“show me”，它会引导你完成修复。

### 报告与洞察

- **深入 HTML 报告：** 即时生成可分享的 HTML 深度报告，展示每日和每周 token 趋势、项目排名和费用。包含汇总近期变更的**AI 工具更新摘要**，以及带有贡献热图和“Wrapped”摘要的**年度回顾**。一键保存为 **.html、.csv 或 .png 图像**，完全离线，并可选择遮蔽项目名称。
- **TUI 与 CLI：** 更偏好终端？运行功能丰富的 TUI 仪表板：`python3 main.py --tui`，或通过 `python3 usage_cli.py report` 生成深度分析。

### 体验与自定义

- **10 个视觉主题：** 可切换面板风格，包括 Classic、Matrix、Windows 95、Newspaper、Cloud Observation、Midnight Aquarium、Prism Arcade、Black Hole、World Cup 2026 和 Lepidoptera（蓝图）。
- **拖拽排序：** 按住任意配额卡上下拖拽即可交换顺序——这一排列在所有主题间共享，并在重启后保留。
- **AI 人才市场：** 将现成的 AI 团队带入 Claude Code。浏览并立即将精选子代理角色安装到 `~/.claude/agents/`。通过随附 CLI 完全在本地运行。
- **灵伴：** 一个小型动态白色剪影会出现在使用百分比旁边：Claude 是凤凰，Codex 是龙，Antigravity 是狮子。每个伙伴都会随各自工具的 token 消耗速率上升而动态加速。
- **自动本地化：** 界面文本提供繁体中文、简体中文、英语、日语和韩语，并自动匹配系统设置。

## 隐私与数据来源

- 使用量数值**仅从本机本地日志文件**读取。
- 它**从不调用 Anthropic / OpenAI API**，也**从不读取钥匙串**（macOS 的密码保险库）。
- Antigravity 配额通过在本地运行官方 Antigravity CLI 自带的 `/quota` 命令获取——与你自己输入时完全相同。`usage` 绝不直接接触它的 API 或 token。
- 唯一的网络活动：获取公开的模型价格表以估算费用（离线时回退到内置价格），以及偶尔在 GitHub 检查新版本。**绝不会上传任何内容。**

## 系统要求

- macOS
- 至少使用过一次 Claude Code、Codex 或 Antigravity（以便存在本地使用数据）。
- （仅限源代码运行）Python 3.13。

## 安装

### 1. Homebrew（推荐）

通过 Homebrew 安装后，只需一次 `brew upgrade --cask usage` 即可保持最新。

```bash
brew install --cask aqua5230/usage/usage
```

*（首次启动：在 Finder 中右键 `usage.app` → **Open** 以通过 Gatekeeper）。*

### 2. 下载 App

1. 从 [GitHub Releases 页面](https://github.com/aqua5230/usage/releases/latest)下载最新的 `usage.app.zip`。
2. 解压后，将 `usage.app` 拖入 Applications 文件夹。
3. 首次启动：在 Finder 中右键 `usage.app` → **Open** → 确认 Open。

### 首次启动：设置状态栏

如果你用过 Codex，`usage` 会自动读取其历史记录。对于 Claude Code，请在应用弹出面板中点击 **“Set Up Status Line”** 按钮以安装同步 hook。
之后重启相应工具（完全退出 Claude Code：Cmd+Q，然后重新打开）。

设置完成后，Claude Code 窗口底部会显示如下状态栏：

<p align="center">
  <img src="docs/statusline.en.png" alt="Claude Code 状态栏显示（英文）" width="640">
</p>

## 主题图库

直接在界面中切换 **10 个视觉主题**：

<p align="center">
  <img src="docs/matrix.en.png" width="32%" alt="Matrix 主题" />
  <img src="docs/win95.en.png" width="32%" alt="Windows 95 主题" />
  <img src="docs/world_cup.en.png" width="32%" alt="World Cup HUD 主题" />
  <img src="docs/newspaper.en.png" width="32%" alt="Newspaper 主题" />
  <img src="docs/aquarium.en.png" width="32%" alt="Aquarium 主题" />
  <img src="docs/black_hole.en.png" width="32%" alt="Black Hole 主题" />
</p>

## 故障排除

如果菜单栏显示 `--`，通常并非故障，只是尚无本地数据。

| 症状 | 可能原因 | 解决方法 |
|---------|--------------|-----|
| 菜单栏显示 `--` | 尚无数据，或 Claude Code hook 未刷新 | 进行一次 Codex 对话。对于 Claude Code，点击“Set Up Status Line”或运行 `python3 main.py --setup` |
| 误点“Quit” | 进程已终止 | 从 Spotlight / Applications 启动 `usage.app`，或运行 `launchctl start com.lollapalooza.usage` |
| 状态显示“N minutes stale” | Claude Code 未运行 | 打开 Claude Code 并让它运行 |
| Codex 区块为空 | 未找到 Codex 历史记录 | 进行一次 Codex 对话以生成日志 |
| 今日费用显示 $0.00 | 缺少模型价格 | 删除 `~/.usage/pricing_cache.json`，或检查 `USAGE_DEBUG=1` |
| Antigravity 卡片未显示 | 未安装或未登录 Antigravity CLI | 安装并登录 Antigravity CLI；后台 `/quota` 探测成功后卡片会自动出现 |
| App 无法打开 | macOS Gatekeeper 阻止了它 | 在 Finder 中右键 `usage.app` → Open |
| App 立即崩溃（arm64） | 旧版本中的 py2app 打包 bug | 升级到 **v0.11.1 或更高版本** |

## 对比

| 功能 | usage | ccusage | TokenTracker |
|---------|:-----:|:-------:|:------------:|
| 始终显示在屏幕上 | ✅ | — | ✅ |
| macOS 菜单栏 | ✅ | — | ✅ |
| Claude Code 与 Codex 用量 | ✅ | 仅 Claude | ✅ |
| Antigravity（Gemini）用量 | ✅ | — | — |
| HTML 深度报告与界面 | ✅ | ✅ | — |
| AI 人才市场 | ✅ | — | — |
| 进度管家与 Token 节省器 | ✅ | — | — |
| Token 浪费健康检查 | ✅ | — | — |
| 零 API 调用 | ✅ | ✅ | ✅ |
| 开源许可证 | AGPL-3.0 | MIT | — |

## 开发

想运行终端 TUI、配置自定义代理或自行构建 App？请查看**[开发文档](docs/DEVELOPMENT.md)**。

## 许可证

采用 AGPL-3.0-only 许可证（见 [LICENSE](LICENSE)）。如你 fork 或重新分发修改后的版本，请注明原作者并链接回：
https://github.com/aqua5230/usage

## Star 历史

<a href="https://star-history.com/#aqua5230/usage&Date">
  <img src="https://api.star-history.com/svg?repos=aqua5230/usage&type=Date" alt="usage Star 历史图表" width="600">
</a>
