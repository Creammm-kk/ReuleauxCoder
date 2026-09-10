# 命令与交互面板开发指南

命令功能放在 `reuleauxcoder/extensions/command/builtin/<feature>.py`。
同一功能的参数模型、解析、处理、交互面板和注册声明应放在一起；
CLI、当前 prompt_toolkit mini-TUI 和后续完整 TUI 共用这些行为。

## 当前结构

| 位置 | 职责 |
| --- | --- |
| `extensions/command/builtin/<feature>.py` | Command、parser、handler、`command_panel_spec()`、`register_actions()` |
| `extensions/command/builtin/__init__.py` | 单一功能清单，将动作注册器与可选面板配对 |
| `app/commands/loader.py` | 创建实例并按清单顺序注册动作 |
| `app/commands/specs.py` | 动作、触发方式、能力和运行时执行策略 |
| `app/commands/models.py` | `CommandContext`、`CommandEffect` 和视图请求 |
| `app/commands/view_models.py` | CLI、TUI 与远端共用的结构化 ViewModel |
| `app/commands/panels.py` | 框架无关的面板树、菜单项和刷新策略 |
| `interfaces/tui/selection_host.py` | 当前 TUI 的选择、过滤、返回、焦点与命令提交 |
| `interfaces/cli/views/` | Rich 文本展示适配 |
| `interfaces/tui/view_text.py` | 当前 TUI 的非交互文本展示适配 |

注册使用显式贡献，不扫描包，不通过装饰器或导入副作用填充全局 ActionRegistry。

```text
_BUILTIN_COMMAND_FEATURES
  ├─ register_actions → create_builtin_action_registry()
  └─ panel            → create_builtin_command_panel_registry()

用户输入 → parser → Command → handler → CommandEffect
                                      ├─ 通知 / 状态变化
                                      ├─ ViewModel → 面板定义 → UI 适配器
                                      └─ 交互请求 → UIInteractor

面板选择 → PanelItem.command → 同一条命令解析和执行链
```

## 实现一个命令功能

以 [mode.py](../reuleauxcoder/extensions/command/builtin/mode.py) 为简单示例；
[model.py](../reuleauxcoder/extensions/command/builtin/model.py) 展示多级选择，
[skills.py](../reuleauxcoder/extensions/command/builtin/skills.py) 展示切换后保持打开的面板。

1. 用 dataclass 定义命令参数。无参数命令可以使用 `EmptyCommand`。
2. parser 通过 `match_template`、`matches_any` 和参数解析器识别输入，未匹配时返回 `None`。
3. handler 使用运行时服务处理业务，向 `ctx.effect` 写入通知、视图和状态，返回 `CommandEffect`。
4. `register_actions(registry)` 声明 `ActionSpec`，明确 action ID、功能分组、触发方式、能力和执行策略。
5. 有选择交互时，在同一文件提供 `command_panel_spec()`。

命令处理函数不创建 Rich、Textual 或 prompt_toolkit 控件。当前运行时存在的
`UIEventKind`、`UIProfile` 等语义类型可以继续使用，终端样式属于适配器。

打开和刷新视图通过 effect 表达，例如 `/mode` 使用：

```python
ctx.effect.open_view(
    view.view_type,
    title="Modes",
    view_model=view,
    reuse_key="mode_profiles",
)
return ctx.effect.finish(control="continue", state_changes=view.to_payload())
```

需要更新现有视图时调用 `ctx.effect.refresh_view(...)`。它生成不抢占焦点的刷新请求。
`view_type` 必须与 ViewModel 一致；ViewModel 提供 `to_payload()` 供状态投影使用。

## 交互面板由命令功能定义

`command_panel_spec()` 返回 `CommandPanelSpec(view_type, view_model_type, build)`。
`build(model, title)` 根据结构化数据返回不可变的 `PanelDefinition`，不执行命令或修改运行状态。

- `PanelItem` 声明标签、描述、当前状态和规范 slash 命令。
- `children` 声明子面板，条目标签用于查找对应子面板。
- `filterable` 控制是否允许过滤条目。
- `keep_open_on_submit` 用于 MCP、Skills 等连续切换操作。
- `return_to_parent_on_submit` 用于完成操作后返回上一层。
- `PanelRefreshPolicy.UPDATE` 更新当前面板；`ABSORB` 消费刷新而不重新打开面板。

选择后提交 `PanelItem.command`，由命令执行链统一处理校验、持久化和副作用。
不要在 UI 按钮或键盘回调中复制 handler 的业务逻辑。
密码输入、确认、审批等交互使用已有的 `UIInteractor` 请求模型。

## 把功能加入单一清单

在 `extensions/command/builtin/__init__.py` 显式导入贡献函数：

```python
from reuleauxcoder.extensions.command.builtin.mode import (
    command_panel_spec as mode_panel_spec,
    register_actions as register_mode_actions,
)
```

然后在 `_BUILTIN_COMMAND_FEATURES` 中加入一项：

```python
_CommandFeature(register_mode_actions, mode_panel_spec()),
```

没有选择面板的功能只传注册器，例如 `_CommandFeature(register_system_actions)`。
动作与面板的两个注册视图都从这份清单派生，保持显式、稳定的顺序。
普通 CLI 的文本 renderer 仍注册在 `interfaces/cli/views/builtin.py`；
当前 TUI 的文本展示仍由 `interfaces/tui/view_text.py` 适配。

## 执行策略与迁移边界

`ActionSpec.during_turn` 默认为 `DEFER_UNTIL_IDLE`。只有允许在模型执行期间立即运行的动作
才声明 `IMMEDIATE`；各界面应遵守同一份策略。会话级修改与持久化默认值修改由 handler
明确区分，不由面板控件决定。

迁移完整 TUI 时，复用 ActionSpec、CommandEffect、ViewModel、PanelDefinition 和交互请求。
替换布局、键盘、焦点和渲染适配即可开始接入，避免重新维护一套命令行为。
当前 prompt_toolkit 的 SelectionHost、文本展示适配和独立 Textual mockup 都是现存界面代码，
不能仅因未来要迁移就当成死代码删除。

## 验证

重点检查命令执行结果、面板生成的命令、刷新和返回行为。已有测试入口：

```bash
uv run pytest -q tests/app/commands tests/extensions/command
uv run pytest -q tests/interfaces/tui/test_application.py tests/interfaces/tui/test_selection_panel.py
uv run pytest -q tests/architecture
```

新增功能应补充实际行为测试；清理未使用的符号无需添加“文件必须不存在”一类测试。
