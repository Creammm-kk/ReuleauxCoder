# ReuleauxCoder TUI

独立的 React + Ink 终端前端，与 `reuleauxcoder-agent/` 同级。Python 后端拥有 Agent、命令、审批策略和会话保存；界面通过双向 JSON-RPC 收发数据。

## 运行

需要 Node.js 22+，以及本仓库已安装依赖的 Python 环境。沿用 `rcoder` 的模型和 API 配置。在仓库根目录执行：

```sh
npm --prefix reuleauxcoder-tui ci
npm --prefix reuleauxcoder-tui run build
node reuleauxcoder-tui/dist/cli.js
```

默认启动仓库 `.venv/bin/python -m reuleauxcoder --rpc-stdio`；没有该环境时使用 `python3`。工作目录默认是启动前端时的目录。

```sh
node reuleauxcoder-tui/dist/cli.js --cwd /path/to/project
node reuleauxcoder-tui/dist/cli.js --config /path/to/config.yaml --model model-name
node reuleauxcoder-tui/dist/cli.js --resume session-id
node reuleauxcoder-tui/dist/cli.js --python /path/to/venv/bin/python
```

开发时运行 `npm --prefix reuleauxcoder-tui run dev -- --cwd /path/to/project`。构建后的包也提供 `rcoder-tui` bin。当前 `rcoder` 入口仍使用原有界面。

## 主题

界面采用统一的终端工作台风格：顶部品牌色带、SESSION 会话区，以及共用底部空间的 COMMANDS / REVIEW / YOU 操作区。横向分隔线和左侧色轨区分层级；强调色指引当前操作，审批使用提醒色。选中项的标题与说明共享底色，聊天记录使用一致的角色标记，长内容仍可展开。窄窗口自动收紧布局。

```sh
node reuleauxcoder-tui/dist/cli.js --theme ocean
node reuleauxcoder-tui/dist/cli.js --theme ember
node reuleauxcoder-tui/dist/cli.js --theme /path/to/theme.json
```

内置 `terminal`（默认，使用终端自身配色）、`ocean`（冷蓝）、`ember`（暖琥珀）。后两种适合深色终端；窗口背景和正文颜色由终端控制。

项目默认主题保存在前端工作目录的 `.rcoder/tui-theme.json`。可以直接写 `"ember"`，也可以继承主题并覆盖颜色：

```json
{
  "extends": "ocean",
  "accent": "#80CBC4",
  "muted": "#8B98AA",
  "success": "#A8C977",
  "warning": "#E8BA70",
  "error": "#F08080",
  "selectionBackground": "#253B45",
  "selectionText": "#E6F4F1"
}
```

颜色支持 `#RRGGBB`，以及 `black`、`red`、`green`、`yellow`、`blue`、`magenta`、`cyan`、`white`、`gray`、`default`。`muted: "default"` 使用终端弱化样式。优先级为 `--theme` > 项目主题文件 > `terminal`，启动时读取；错误配置会给出文件和字段信息。主题定义与配色逻辑集中在 `src/ui/theme.ts`，加载逻辑在 `theme-config.ts`。

## 交互

界面采用固定输入区、可滚动会话记录、就近打开的菜单和审批面板。参考了 [Codex CLI 的命令弹窗与确认反馈](https://developers.openai.com/codex/cli/slash-commands)，组件与终端生命周期由 [Ink](https://github.com/vadimdemedes/ink) 管理。

输入 `/` 筛选一级菜单，回车进入。例如 `/model` 打开模型面板，然后选择会话模型、子 Agent 模型或默认配置；`/ps` 打开进程面板，然后选择进程和操作。额外操作放在 **More actions…**，参数逐项填写。前端不会把菜单选择拼成 slash 文本发送。

一级入口来自后端 ActionCatalog，覆盖目前全部 44 个内置操作：

| 菜单 | 操作 |
| --- | --- |
| `/model`、`/mode` | 模型配置、主/子 Agent 模型与默认值；当前模式和模式切换 |
| `/thinking` | 上轮 reasoning、显示方式、reasoning effort |
| `/approval` | 审批策略及会话授权管理 |
| `/mcp`、`/skills` | 列表、状态及后端提供的管理操作 |
| `/agents` | 子 Agent 列表、结果、消息、恢复、取消、清理 |
| `/ps` | 后台进程、轮询、打断、终止、密文输入 |
| `/session`、`/save`、`/new` | 浏览、恢复、保存、新建会话 |
| `/reset`、`/compact`、`/quit` | 清空、压缩、保存退出 |
| `/help`、`/config`、`/tokens`、`/status`、`/debug` | 帮助、配置、token、性能与调试 |

`View all details` 展示视图的全部字段。命令帮助里保留的旧 CLI 语法是后端参考信息；新版输入区的 slash 用于打开一级菜单。

| 内容/交互 | 新版位置 |
| --- | --- |
| assistant 流式输出、Markdown、代码、表格 | 会话记录；生成结束后格式化 |
| reasoning、工具参数、滚动输出、最终结果 | 会话记录；F4 展开保留的完整内容 |
| diff、stdout/stderr、诊断、耗时、退出码、截断说明、归档位置与校验值 | 工具记录展开视图；模型输出截断不会截断界面数据 |
| 已批准的相同 diff | 完成后折叠为执行摘要，完整 diff 仍可展开 |
| 计划、进度、子 Agent、后台进程、诊断、启动信息、状态和排队输入 | 顶部摘要及 F2 会话详情；对应命令面板提供操作 |
| 确认、单选、文本、密文输入 | 输入区上方的交互面板，聊天草稿保留 |
| 工具审批、会话授权范围、拒绝反馈、队列和超时 | 审批面板；键盘分页查看长 diff |
| 运行时追加指令、中断、命令排队、会话保存/恢复 | 后端处理；前端显示结果和状态 |
| 后端报错、断线 | 保留已有记录和草稿，显示错误；退出以失败状态返回 |

### 快捷键

| 按键 | 功能 |
| --- | --- |
| Enter | 发送、进入菜单、确认选择 |
| Alt+Enter / Shift+Enter | 换行；Shift+Enter 取决于终端是否发送独立键码 |
| `/` / Ctrl+P | 命令菜单；Ctrl+P 保留草稿 |
| Esc | 返回、关闭菜单或取消交互 |
| ↑↓ | 菜单选择；输入为空时滚动会话，否则浏览输入历史 |
| Alt+↑↓ | 浏览输入历史，包括空输入时 |
| PgUp / PgDn | 滚动当前内容；长菜单翻页 |
| Home / End | 空输入时跳到会话开头 / 跟随最新输出；编辑时移动光标 |
| F1 / Ctrl+G | 快捷键帮助 |
| F2 / Ctrl+O | 会话、计划、进程、子 Agent 和启动详情 |
| F4 / Ctrl+R | 切换整个会话记录的详细视图：工具参数/完整输出、reasoning |
| Ctrl+A/E、Ctrl+U/K/W | 移动光标及删除文本 |
| Ctrl+C | 依次取消交互、关闭菜单、清空草稿、中断运行、确认退出；停止期间再次按下退出 |
| Ctrl+D | 空草稿时保存退出 |

F4 作用于当前会话中所有已保留的记录：展开工具调用参数、完整收到的 stdout/stderr、diff、诊断与归档信息；显示模型已返回的 reasoning。再按一次恢复工具摘要和折叠视图。展开后可以用 PgUp/PgDn 查看前面的内容。快捷键说明统一放在输入栏下方，顶部显示当前是否处于详细视图。

紧凑视图把连续工具调用合为一组，显示数量和最新工具的一行摘要；读取类使用后端提供的行数、字符数或匹配数，不显示正文。shell 执行时仅预览最后 3 行，结束后收起。并行调用优先显示仍在运行的工具，失败摘要持续保留。模型的可见说明会分隔工具组，隐藏的 reasoning 不占位也不打断分组。F4 按原始顺序展开全部记录，折叠不会删除内容。

展开的 reasoning 使用 Markdown 渲染，保留标题、列表、代码和主题配色，整体降低亮度，与正式回答区分。

命令面板和详情页只在交互区域显示，关闭后不在主会话中留下副本或菜单选择记录。实际执行结果与错误提示仍保留在会话中。

输出区底部的动态状态行显示等待模型响应、思考中、输出中或正在执行的工具，并显示当前阶段用时；折叠 reasoning 和工具输出时仍可见。等待确认时改成静态输入提示，任务结束后自动消失，不写入会话历史。动画只刷新状态行，不重新排版历史内容。

排队中的 Prompt 和 Command 在输入栏上方的 `QUEUED` 区域显示内容预览；F2 会话详情可查看完整文本及全部队列。队列由后端快照驱动，执行或取消后自动移除，队列清空后隐藏整个区域。

审批：`y` / Enter 批准一次，`n` 拒绝，`s` 选择会话授权范围，`f` 输入拒绝反馈。单选支持数字 1–9。

支持 bracketed paste、中文和组合 emoji。密文输入仅显示圆点，不进入前端输入历史；历史保存在本地工作目录 `.rcoder/tui-history.jsonl`。终端原生选择/复制仍可用；支持 alternate scroll 的终端可通过滚轮滚动空输入状态下的会话。`--no-alt-screen` 使用主终端缓冲区。

## 远端后端

`--backend` 启动任意提供相同 stdio 协议的程序，`--` 后的参数原样交给它。例如用 SSH 承载协议：

```sh
node reuleauxcoder-tui/dist/cli.js --backend ssh -- -T devbox \
  'cd /work/project && exec /opt/ReuleauxCoder/.venv/bin/python -m reuleauxcoder --rpc-stdio'
```

在 VS Code Remote 的终端内直接启动时，前后端都在远端工作区运行。也可以在本机启动 TUI，通过 SSH 子进程连接远端。输入历史属于前端本地目录，会话文件和工具文件属于后端工作区。

一条连接拥有一个后端进程。关闭前端会要求后端中断、保存并退出；断线后可通过 `--resume` 恢复已保存会话。目前没有驻留服务、自动重连或多客户端共享会话。Go 工具执行 peer 的 relay 协议独立于这条 UI 连接。

## 结构与验证

```text
src/cli.tsx          启动参数、子进程和终端生命周期
src/protocol/        JSON 编解码、双向 peer、运行时客户端
src/state/           会话记录、输入编辑、历史、菜单与交互状态
src/ui/              React 布局、内容窗口、面板与格式化
test/                Python 实际运行时、跨语言协议、Ink 和 PTY 验证
```

后端命令参数 dataclass 是表单字段的单一来源；`preview` 显式声明安全的菜单预览。命令面板由对应 Python 命令模块构建。前端只拥有选择、过滤、草稿、折叠和滚动状态。

记录内容全部保留在会话状态中，只有当前可见行进入 React；未变化的记录缓存 Markdown/折行结果。事件携带会话代数，恢复历史与后到的快照不会互相覆盖。JSON-RPC 返回错误和异常断线会解除挂起请求。

```sh
npm --prefix reuleauxcoder-tui run check
npm --prefix reuleauxcoder-tui test
```

测试使用真实 Python CommandService、RuntimeServer、codec 和 stdio，替换 LLM 循环以避免外部模型调用。涵盖全部命令目录和预览入口、参数表单、四类反向交互、工具完整信息、队列/中断、失败保存、恢复会话、Unicode、密文遮盖，以及实际 PTY 中的缩放和终端恢复。PTY 测试在 Windows 跳过。用 `RCODER_TUI_PYTHON` 指定测试 Python 环境；它必须安装本仓库 Python 包及依赖。

Ink 7 的 `useInput` 不暴露 F1、F2、F4，适配集中在 `src/ui/terminal.ts`；升级锁定的 Ink 版本时运行终端测试。Ctrl+G/O/R 同时提供替代键位。
