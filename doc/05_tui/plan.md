# TUI 展示优化 Plan

## 架构概览

本次改造把主对话区从不可交互的连续日志替换为可组合的时间线容器。每个用户消息、助手回复、工具结果、错误与通知都成为独立的 TUI 条目；工具结果使用 Textual 原生可折叠组件，既支持鼠标点击也不需要改变 Agent 事件。

```text
MewCodeApp / stream.consume_stream
  -> 时间线追加 API
     -> Timeline (VerticalScroll)
        -> UserEntry / AssistantEntry / ToolResultEntry / NoticeEntry / ErrorEntry
  -> StreamingActivity (临时动态区)
  -> PromptInput + StatusBar (固定底部)
```

`Agent.run()` 的事件类型、事件顺序和对话写入保持不变。TUI 继续消费 `Event.text`、`Event.tool`、`Event.usage`、`Event.notice`、`Event.err` 和 `Event.done`，但不再直接向 `RichLog` 写入 renderable。

## 核心数据结构与接口

### `Timeline`

新增一个基于 `VerticalScroll` 的 TUI 容器，负责追加条目与条件自动滚动：

```python
class Timeline(VerticalScroll):
    async def append(self, entry: Widget) -> None: ...
    def is_near_bottom(self) -> bool: ...
```

- `is_near_bottom()` 以当前纵向偏移和最大偏移判断用户是否位于底部或底部附近。
- `append()` 在挂载条目前记录跟随状态，挂载完成后仅在原本处于底部时，通过布局刷新回调滚到末尾。
- 用户已向上查看历史时，`append()` 不调用滚动 API，保留当前位置。

### `ToolRun`

新增仅属于 TUI 的运行中工具展示记录：

```python
@dataclass(frozen=True)
class ToolRun:
    name: str
    args: str
```

它替代现有 `list[tuple[str, str]]` 的展示用途，仍按 Agent 事件给出的顺序入队和出队，不影响工具执行或会话历史。

### 时间线条目工厂

`view.py` 提供用于构造 Textual Widget 的纯展示函数：

```python
def user_entry(text: str) -> Static: ...
def assistant_entry(reply: str, elapsed_seconds: int) -> Static: ...
def tool_result_entry(
    name: str, args: str, result: str, is_error: bool
) -> Collapsible: ...
def notice_entry(text: str) -> Static: ...
def error_entry(err: Exception) -> Static: ...
def activity_block(...) -> RenderableType: ...
```

- 条目使用 CSS class 表达语义，不依赖 Agent 状态修改样式。
- `tool_result_entry()` 的标题只用现有安全参数预览；`bash` 显示命令，`write_file` 不显示 `content`。
- `Collapsible` 初始 `collapsed=True`，正文使用现有结果摘要逻辑并保留成功/错误色彩。

## 模块设计

### `src/mewcode/tui/timeline.py`

**职责：** 提供可滚动、可追加、可条件自动跟随的时间线组件。

**实现要点：**

1. 继承 `VerticalScroll`，设置垂直滚动与稳定的条目间距。
2. 在 `append()` 调用前读取 `is_near_bottom()`；使用 `await mount(entry)` 挂载子组件。
3. 若需要跟随，使用 `call_after_refresh()` 调度无动画 `scroll_end()`，确保新条目参与布局后再滚动。
4. 底部判断使用小的行级容差，而不是只比较绝对相等，避免用户在接近底部时丢失跟随。

### `src/mewcode/tui/view.py`

**职责：** 定义各语义条目的文本、摘要规则和样式 class。

**改造：**

- 将现有 `user_block`、`assistant_block`、`error_block`、`notice_block` 和工具结果渲染改造为可挂载条目工厂。
- 保留 `_argument_preview()` 作为唯一安全参数摘要来源；补充工具标题中的成功/失败状态。
- 保留 `status_bar()`、`selecting_status()`、token 紧凑格式化逻辑，避免影响会话状态栏。
- 将英文活动文字替换为中文，活动区显示等待、回复、运行工具、耗时和迭代轮次。

### `src/mewcode/tui/app.py`

**职责：** 组织固定布局，并为流式消费者提供时间线追加入口。

**布局改造：**

```text
#main
├── Timeline (#timeline, height: 1fr)
├── Static (#streaming, height: auto, max-height: 12)
├── PromptInput (#input, 固定高度)
└── Static (#statusbar, 固定高度)
```

**改造：**

- 用 `Timeline` 替换 `RichLog`，所有主区条目经 `append_timeline()` 追加。
- 提供异步 `append_timeline(entry)` 供输入提交、模式通知与流式消费者调用。
- 用户消息使用高亮条目替代普通 cyan 文本；启动横幅作为中性系统条目写入时间线。
- 维持现有输入锁定、焦点恢复、Provider 选择、模式切换和状态栏更新代码路径。
- CSS 使用低饱和背景、细边框、稳定间距和语义 class；不添加侧栏、浮动卡片或装饰背景。

### `src/mewcode/tui/stream.py`

**职责：** 将既有 Agent 事件映射为时间线与活动区展示。

**改造：**

1. 所有向 `RichLog.write()` 的调用改为 `await app.append_timeline(...)`。
2. `_start_tool()` 在已有助手 preamble 时先提交助手条目，再把工具记录加入运行中队列。
3. `_finish_tool()` 从队列取回对应工具信息，追加默认折叠的工具结果条目；不再直接显示结果正文。
4. `finish_with_assistant()`、`finish_with_error()`、notice 和 error 分别追加对应语义条目。
5. `refresh_streaming_view()` 只更新临时活动区，不对时间线强制滚动；回合结束清空活动区并恢复输入焦点。
6. 保持取消、用量累计、事件循环、工具结果顺序与会话历史写入逻辑原样不变。

### `tests/test_tui.py`

**职责：** 覆盖展示条目、展开交互、滚动策略和既有 TUI 工作流。

**新增或调整测试：**

- 用户条目具有高亮 class 和完整文本。
- 助手、错误、通知和工具条目使用不同 class 或状态文本。
- 工具结果条目默认折叠，标题不泄漏 `write_file.content`，展开后能读取截断摘要和错误样式。
- 时间线在底部追加后滚动到末尾；手动滚到历史位置后追加条目不改变当前偏移。
- 正常结束、错误和取消后输入框仍可编辑且获得焦点。
- 保留当前普通对话、计划/执行切换、取消、恢复与 token 用量测试。

## 模块交互

### 用户提交

```text
submit_current_input()
  -> Conversation.add_user()              # 保持既有逻辑
  -> await append_timeline(user_entry())  # 高亮展示
  -> 锁定输入并启动 consume_stream()
```

### 工具回合

```text
Event.tool(START)
  -> 提交已累积的助手文本
  -> ToolRun 入队
  -> 更新活动区

Event.tool(END)
  -> ToolRun 出队
  -> await append_timeline(tool_result_entry(..., collapsed=True))
  -> 更新活动区
```

### 自动滚动

```text
append_timeline(entry)
  -> Timeline 记录 is_near_bottom
  -> 挂载 entry
  -> 原先在底部：布局刷新后 scroll_end()
  -> 原先在历史位置：不滚动
```

## 文件组织

```text
src/mewcode/tui/
├── app.py          # 修改：主布局改为 Timeline，提供追加入口和 CSS
├── stream.py       # 修改：Agent 事件映射到时间线条目
├── timeline.py     # 新建：VerticalScroll 条件自动滚动组件
└── view.py         # 修改：语义化条目、折叠工具结果和活动区渲染

tests/
└── test_tui.py     # 修改：展示、折叠、滚动和既有交互回归测试
```

## 技术决策

| 决策 | 选择 | 原因 |
|---|---|---|
| 主区容器 | `VerticalScroll` 替换 `RichLog` | `RichLog` 不能承载可点击的独立工具结果组件；前者可挂载交互子组件。 |
| 工具详情 | Textual `Collapsible`，默认收起 | 内置鼠标点击与展开状态，无需自绘点击逻辑或新增依赖。 |
| 工具详情内容 | 展开后显示既有截断摘要 | 保持当前体量控制与错误信息，同时避免默认噪声。 |
| 自动滚动 | 追加前记录底部状态，布局刷新后条件滚到末尾 | 不干扰用户浏览历史，且避免新组件尚未计算高度时滚动失败。 |
| 流式回复 | 保留独立活动区，最终回复再写入时间线 | 避免在每个 token 更新时反复挂载历史条目，减少渲染抖动。 |
| 输入区 | `Timeline` 占用唯一 `1fr` 高度 | 活动区、输入和状态栏保持在底部，不随历史增长移动。 |
| 视觉风格 | 低饱和语义色 + 细边框 + 间距 | 适合连续编码任务扫描，满足克制的终端工具风格。 |
| Agent 边界 | 只改 `tui` 与其测试 | 不改变 Agent、Provider、工具、Conversation 或 API 行为。 |

## 验证策略

- 使用 Textual `run_test()` 检查时间线组件、条目 class、折叠默认状态、鼠标/组件展开以及输入焦点恢复。
- 在测试中创建足够多的时间线条目，分别验证处于底部和已向上滚动时的追加后偏移。
- 运行现有 Agent 与 Provider 测试，确保展示层改造不影响工具执行顺序、取消和会话历史。
- 执行 `python -m compileall src/mewcode`、`pytest`、`ruff format --check .` 和 `ruff check .`；在可用环境运行 `mypy src/mewcode`。
- 手工以窄终端和常见桌面终端检查：三轮对话、长工具结果、`/plan`、`/do`、错误和取消场景中的布局与滚动。
