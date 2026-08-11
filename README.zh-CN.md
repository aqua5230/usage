<p align="center">
  <img src="docs/readme-logo.png" alt="usage 标志" width="128">
</p>

# usage

### 在 macOS 菜单栏和 Windows 系统托盘中查看 Claude Code、Codex 和 Antigravity 配额。

在会话中途耗尽配额的代价很高，尤其是在依赖 Claude Code 的长时间重构或调试期间。`usage` 会在你触及限额前显示 5 小时和每周限额，并始终保持可见。无需运行命令，也无需打开页面；答案就在你平时已经会看的位置。

[繁體中文](README.zh-TW.md) · 简体中文 · [English](README.md) · [日本語](README.ja.md) · [한국어](README.ko.md) &nbsp;|&nbsp; [Discussions](https://github.com/aqua5230/usage/discussions) &nbsp;|&nbsp; [官方介绍页](https://aqua5230.github.io/usage/)

[![GitHub stars](https://img.shields.io/github/stars/aqua5230/usage?style=flat)](https://github.com/aqua5230/usage/stargazers)
[![持续集成](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![最新版本](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![平台](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey.svg)](https://github.com/aqua5230/usage/releases/latest)
[![许可证：AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![OpenSSF 最佳实践](https://www.bestpractices.dev/projects/13538/badge)](https://www.bestpractices.dev/projects/13538)

<p align="center">
  <img src="docs/showcase.en.png" alt="usage — 固定在 macOS 菜单栏中的 Claude Code、Codex 与 Antigravity 配额" width="820">
</p>

Claude Code 和 Codex 的数值以被动方式从你电脑上已有的日志文件读取，因此**查看配额永远不会调用 Anthropic 或 OpenAI 的 LLM API**，也永远不会消耗你的 token。Antigravity 是唯一的例外：它的配额来自 Google 官方配额接口，使用的是 Antigravity CLI 本就保存在本机的登录身份——这只是一次元数据查询，同样不会消耗你的模型配额。

## 快速开始

```bash
brew install --cask aqua5230/usage/usage
```

它会自动安装到 Applications 文件夹。先右键点击一次 **Open** 以通过 Gatekeeper，然后点击菜单栏图标。想直接下载或查看完整设置流程？请参见下方的[安装](#安装)。

**快速跳转：** [功能一览](#功能一览) · [隐私与数据来源](#隐私与数据来源) · [系统要求](#系统要求) · [安装](#安装) · [Windows 支持](#windows-支持) · [主题图库](#主题图库) · [故障排除](#故障排除) · [对比](#对比) · [不适合谁](#不适合谁) · [开发](#开发)

## 功能一览

### 实时可见

- **常驻监视器：** 配额常驻菜单栏，以绿色到红色的颜色编码显示。需要完整的会话、每周和各项目明细时，点击即可查看。
- **Antigravity 支持：** Antigravity（Gemini）的会话与每周配额以第三张卡片出现在除了 World Cup 2026 以外的每一款面板（该款维持两队对战 HUD）。数值直接向官方配额 API 查询，使用的是 Antigravity CLI 本就保存在你机器上的登录身份——每隔几分钟自动刷新，重置倒计时实时递减。
- **服务状态警示：** Claude Code、Claude API 或 Codex API 发生故障或性能降级时，相关面板底部会显示橘红警示横幅，数值仅读取官方公开的 Statuspage.io 状态页——绝不调用 LLM 使用量 API。Antigravity 因没有可用的公开状态页，暂不支持。
- **上下文提醒与通知：** 当上下文窗口达到 70% 时，状态栏会提示你使用 `/clear` 或 `/compact`，避免浪费 token。你也可以选择接收关于配额限额和恢复的系统通知。
- **隐藏区块：** 没全都用？点击一次即可从菜单栏和面板中完全隐藏 Claude Code、Codex 或 Antigravity 区块。

### 工作流辅助

- **进度管家：** 打开新的 Claude Code 会话时，`usage` 会直接把你上次的进度交给 AI，包括上次请求、未提交的变更和未完成的待办事项。无需 `/resume`，无需回顾。完全本地运行，默认关闭。
- **Token 节省器：** 菜单栏开关会要求 Claude Code 和 Codex 在当前会话中更简洁地回答，在保持代码和错误信息逐字节不变的同时节省输出 token。轻量的逐消息提醒能避免长对话中的回复逐渐变得冗长——在真实会话的 A/B 测试中，对话后期回复维持缩短约 40%，而不是漂移变长 84%。
- **Token 浪费健康检查：** 每日后台诊断会扫描日志中的浪费问题，包括重复读取文件、污染目录和冗长的 Bash 输出。发现问题时会显示一行提示；对 AI 说“show me”，它会引导你完成修复。

### AI 协作

- **AI 人才市场：** 将现成的 AI 团队带入 Claude Code。浏览并立即将精选子代理角色安装到 `~/.claude/agents/`。通过随附 CLI 完全在本地运行。
- **AI 圆桌讨论：** 打开一个独立窗口，让 Claude Code、Codex、Antigravity 进行多轮讨论——自选参与者、模型与辩论风格，开始前就能看到大约会花多少 token。可以在轮间插话引导方向，共识计票看得出谁不同意，并让讨论在全体同意时提早收尾。位置可以戴上 AI 人才市场的专家角色，也能附上只读文件夹让参与者参考真实文件。
- **AI 更新日报：** 打开每天自动更新的公开[网页](https://aqua5230.github.io/ai-updates/)，涵盖 Claude Code、Codex、Antigravity 三套工具，保留完整历史。已审核的更新显示五语白话版，未审核的显示官方原文。

### 报告与洞察

- **深入 HTML 报告：** 可分享的 HTML 深度报告，展示每日和每周 token 趋势、项目排名和费用——包含带有贡献热图和“Wrapped”摘要的年度回顾。“最近在做什么”一区列出 Claude Code 为你近期对话取的名字，让数字有脉络可对。可导出为 .html、.csv 或 .png，完全离线，并可选择遮蔽项目名称，这些标题也会一并遮蔽。

### 体验与自定义

- **13 个视觉主题：** 可切换面板风格，包括 Classic、Matrix、Windows 95、Newspaper、Cloud Observation、Midnight Aquarium、Prism Arcade、Black Hole、World Cup 2026、Lepidoptera（蓝图）、彩绘玻璃、折纸和 Catppuccin（官方配色，四款 flavor 全支持）。
- **面板自由摆放：** 面板不再固定在菜单栏图标下方。在任何空白处按住即可拖动到你想要的位置，下次打开仍保留在原位。切换到其他 App 时也不会消失，再次点击菜单栏图标或按 Esc 键才会关闭。
- **拖拽排序：** 按住任意配额卡上下拖拽即可交换顺序——这一排列在所有包含配额卡的主题间共享（除 World Cup 2026 之外），并在重启后保留。
- **灵伴：** 一个小型动态白色剪影会出现在使用百分比旁边：Claude 是凤凰，Codex 是龙，Antigravity 是狮子。每个伙伴都会随各自工具的 token 消耗速率上升而动态加速。
- **自动本地化：** 界面文本提供繁体中文、简体中文、英语、日语和韩语，并自动匹配系统设置。

## 隐私与数据来源

- Claude Code 和 Codex 的数值**仅从本机本地日志文件**读取；读取这些数值**不会调用 Anthropic 或 OpenAI 的 LLM API**。
- Antigravity 配额需要联网，且只有你实际使用它才会发生：配额通过 Antigravity CLI 登录后保存的 OAuth 凭据，向 Google 官方配额接口查询——依 CLI 版本不同，该凭据读自 macOS 钥匙串、Windows 凭据管理器，或本地 token 文件。`usage` 只读取该凭据而不写回，任何刷新后的 access token 也只保留在内存中；该调用本身只读取配额信息，绝不消耗你的模型配额。
- 后台网络活动范围：上述 Antigravity 配额／token 接口、用于标记故障的 Claude 与 Codex 公开状态页、用于估算费用的公开模型价格表（离线时回退到内置价格），以及偶尔在 GitHub 检查新版本。Claude Code 与 Codex 的日志内容不会被上传。

## 系统要求

- macOS 12（Monterey）或更新版本，或 Windows 10/11
- 至少使用过一次 Claude Code、Codex 或 Antigravity（以便存在本地使用数据）。
- （仅限源代码运行）Python 3.13。

## 安装

### 1. Homebrew（推荐）

通过 Homebrew 安装后，只需一次 `brew upgrade --cask usage` 即可保持最新。

```bash
brew install --cask aqua5230/usage/usage
```

*（首次启动：在 Finder 中右键 `usage.app` → **Open** 以通过 Gatekeeper）。*

### 2. 下载 macOS App

1. 从 [GitHub Releases 页面](https://github.com/aqua5230/usage/releases/latest)下载最新的 `usage.app.zip`。
2. 解压后，将 `usage.app` 拖入 Applications 文件夹。
3. 首次启动：在 Finder 中右键 `usage.app` → **Open** → 确认 Open。

## Windows 支持

Windows 原生支持完整核心功能：系统托盘 UI、Claude Code 状态栏 hook 和 Codex 记录解析均可使用。从[最新 GitHub Release](https://github.com/aqua5230/usage/releases/latest)下载 `usage-windows.zip`，解压后直接运行 `usage.exe`，无需安装。系统托盘 UI 需要 Microsoft Edge WebView2 Runtime；Windows 10 和 11 通常已经内置。

系统托盘图标会随 Claude 配额百分比更新；提示文字会汇总 Claude 和 Codex 的各个窗口。左键通过 WebView2 打开与 macOS 相同的 13 款主题面板（Classic 加另外十二款）；右键可切换面板、刷新、设置开机自启、检查更新和退出。

Windows 的差异：面板显示在工作区右下角，而不是紧贴系统托盘图标；更新提示使用系统 Yes/No 对话框；AI 人才市场与 AI 圆桌讨论面板仅限 macOS。

### 首次启动：设置状态栏

如果你用过 Codex，`usage` 会自动读取其历史记录。对于 Claude Code，请在应用弹出面板中点击 **“Set Up Status Line”** 按钮以安装同步 hook。
之后重启相应工具（完全退出 Claude Code：Cmd+Q，然后重新打开）。

同一颗按钮在你装了 Antigravity CLI 时，也会一并帮它设置状态栏；没装的话什么都不会写入。你自己在那边设置过的状态栏会先备份起来，关掉开关时还原。

设置完成后，Claude Code 窗口底部会显示如下状态栏：

<p align="center">
  <img src="docs/statusline.en.png" alt="Claude Code 状态栏显示（英文）" width="640">
</p>

## 主题图库

直接在界面中切换 **13 个视觉主题**：

<p align="center">
  <img src="docs/classic.en.png" width="32%" alt="Classic 主题" />
  <img src="docs/matrix.en.png" width="32%" alt="Matrix 主题" />
  <img src="docs/win95.en.png" width="32%" alt="Windows 95 主题" />
  <img src="docs/newspaper.en.png" width="32%" alt="Newspaper 主题" />
  <img src="docs/cloud_observation.en.png" width="32%" alt="Cloud Observation 主题" />
  <img src="docs/aquarium.en.png" width="32%" alt="Aquarium 主题" />
  <img src="docs/prism_arcade.en.png" width="32%" alt="Prism Arcade 主题" />
  <img src="docs/black_hole.en.png" width="32%" alt="Black Hole 主题" />
  <img src="docs/world_cup.en.png" width="32%" alt="World Cup HUD 主题" />
  <img src="docs/lepidoptera.en.png" width="32%" alt="Lepidoptera 主题" />
</p>

## 故障排除

如果菜单栏显示 `--`，通常并非故障，只是尚无本地数据。

| 症状 | 可能原因 | 解决方法 |
|---------|--------------|-----|
| 菜单栏显示 `--` | 尚无数据，或 Claude Code hook 未刷新 | 进行一次 Codex 对话。对于 Claude Code，点击“设置状态栏”（源码安装则运行 `python3 main.py --setup`） |
| 运行 `usage.app` 里的 `main.py` 报 `ImportError` | 打包版的 `main.py` 需要 app 自带的解释器，无法手动运行 | 别运行那一份。改点 app 里的“设置状态栏”，或 clone 源码从源码运行 |
| 误点“Quit” | 进程已终止 | 从 Spotlight 或 Applications 重新启动 `usage.app`。（`launchctl start com.lollapalooza.usage` 仅在你开启过“开机自启”时有效。） |
| 状态显示“N minutes stale” | Claude Code 未运行 | 打开 Claude Code 并让它运行 |
| Codex 区块为空 | 未找到 Codex 历史记录 | 进行一次 Codex 对话以生成日志 |
| 今日费用显示 $0.00 | 缺少模型价格 | 删除 `~/.usage/pricing_cache.json`，或检查 `USAGE_DEBUG=1` |
| Antigravity 卡片未显示 | 未安装或未登录 Antigravity CLI | 安装并登录 Antigravity CLI；后台配额查询成功后卡片会自动出现 |
| App 无法打开 | macOS Gatekeeper 阻止了它 | 在 Finder 中右键 `usage.app` → Open |

## 对比

| 功能 | usage | ccusage | TokenTracker |
|---------|:-----:|:-------:|:------------:|
| 始终显示在屏幕上 | ✅ | — | ✅ |
| macOS 菜单栏 | ✅ | — | ✅ |
| Claude Code 与 Codex 用量 | ✅ | 仅 Claude | ✅ |
| Antigravity（Gemini）用量 | ✅ | — | — |
| Claude Code 与 Codex 服务状态警示 | ✅ | — | — |
| HTML 深度报告与界面 | ✅ | ✅ | — |
| AI 人才市场 | 仅限 macOS | — | — |
| AI 圆桌讨论 | 仅限 macOS | — | — |
| AI 更新日报 | ✅ | — | — |
| 进度管家与 Token 节省器 | ✅ | — | — |
| Token 浪费健康检查 | ✅ | — | — |
| 读取配额时不调用 LLM API | ✅ | ✅ | ✅ |
| 开源许可证 | AGPL-3.0 | MIT | — |

## 不适合谁

- 你完全生活在终端中，不想要任何后台运行的菜单栏图标——单次执行的 CLI 工具会更适合你。
- 你没有在使用 Claude Code、Codex 或 Antigravity——因为这样 `usage` 就没有可以读取的本地使用数据。
- 你使用的是 Linux——目前仅支持 macOS 和 Windows。

## 开发

从源码构建、配置自定义 Agent 或运行终端 TUI？请参阅**[开发文档](docs/DEVELOPMENT.md)**。

## 许可证

采用 AGPL-3.0-only 许可证（见 [LICENSE](LICENSE)）。如你 fork 或重新分发修改后的版本，请注明原作者并链接回：
https://github.com/aqua5230/usage
