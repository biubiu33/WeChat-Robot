# Slash 命令注册与分发系统 Plan

## 架构概览

本章采用独立命令域模块，将命令元数据、输入解析、注册冲突校验、补全匹配、分发和十二个内置命令从 Textual TUI 中拆出。命令域只依赖一个界面控制协议，不导入或查询具体 Widget；TUI 通过适配器把协议方法映射到现有会话、权限、上下文、时间线和 Agent 回合能力。

用户提交输入时先经过统一解析：空输入结束，普通文本进入现有 Agent 提交流程，Slash 输入进入命令分发器。提示词类命令最终复用同一个“发送用户消息并启动回合”入口，确保标题、档案、上下文、Token 和取消行为与普通消息一致。

实时补全分为两层：命令域按规范名称和别名返回去重、排序后的规范命令候选；TUI 在输入框下方维护一个内联候选列表，随文本变化刷新。候选列表不夺取输入焦点，也不执行命令。

会话统计继续使用 JSONL 作为事实来源。每次 API usage 写入一个增量事件；会话回合数直接由档案中的用户消息计数恢复，因为普通消息、`/do` 和 `/review` 都通过同一入口写为用户消息。TUI 只保存当前会话的内存统计镜像，用于状态栏和命令查询。

## 核心数据结构

### `CommandKind`

```python
class CommandKind(Enum):
    LOCAL = "local"
    UI = "ui"
    PROMPT = "prompt"
```

只用于命令元数据、帮助展示和测试分类。是否进入 Agent 由对应处理函数决定，不由 TUI 使用条件分支重复判断。

### `Command`

```python
@dataclass(frozen=True)
class Command:
    name: str
    aliases: tuple[str, ...]
    description: str
    usage: str
    kind: CommandKind
    handler: CommandHandler
    argument_hint: str = ""
    hidden: bool = False
```

名称和别名内部不含 `/`；渲染帮助、错误和补全结果时再添加。默认注册表只给 `help` 配置 `h`、给 `clear` 配置 `c`。

### `ParsedInput`

```python
class InputKind(Enum):
    EMPTY = "empty"
    MESSAGE = "message"
    COMMAND = "command"

@dataclass(frozen=True)
class ParsedInput:
    kind: InputKind
    text: str = ""
    command_name: str = ""
    argument: str = ""
```

`text` 保存清理后的普通消息；命令输入使用小写 `command_name` 和首个空格后的清理参数。

### 命令查询快照

```python
@dataclass(frozen=True)
class StatusSnapshot:
    mode: str
    input_tokens: int
    output_tokens: int
    tool_count: int
    memory_count: int
    model: str
    working_directory: str

@dataclass(frozen=True)
class MemorySnapshot:
    project: tuple[str, ...]
    user: tuple[str, ...]

    @property
    def total(self) -> int: ...

@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    archive_path: str
```

快照只携带命令输出允许展示的数据，不暴露记忆正文、Provider 配置、工具参数或 API Key。

### `CommandControl`

```python
class CommandControl(Protocol):
    async def show_message(self, text: str) -> None: ...
    async def send_user_message(self, text: str) -> None: ...
    async def compact_context(self) -> None: ...
    async def resume_session(self) -> None: ...
    async def clear_session(self) -> None: ...
    async def exit_app(self) -> None: ...

    def set_mode(self, mode: Mode) -> None: ...
    def refresh_status(self) -> None: ...
    def status_snapshot(self) -> StatusSnapshot: ...
    def memory_snapshot(self) -> MemorySnapshot: ...
    def session_snapshot(self) -> SessionSnapshot | None: ...
```

命令域的处理函数只接收该协议。TUI 适配器持有应用引用并完成实际映射，命令测试使用纯内存 fake control。

### `CommandContext` 与 `CommandHandler`

```python
@dataclass(frozen=True)
class CommandContext:
    registry: CommandRegistry
    control: CommandControl

CommandHandler = Callable[[CommandContext, str], Awaitable[None]]
```

分发器为每次调用创建上下文。内置 `/help` 由此查询正在使用的同一注册表；其他处理函数通过 `context.control` 操作应用。这样帮助、补全和实际分发不会维护三份元数据。

### `SessionStats`

```python
@dataclass
class SessionStats:
    input_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0
```

新会话从零创建；恢复结果携带汇总后的统计。usage 只接受非负整数增量；回合数等于完整恢复档案中的合法用户消息数，因此旧版 Chapter 08 档案无需迁移也能恢复回合数。坏行和非法 usage 事件沿用会话恢复的安全跳过策略。

## 模块设计

### 命令模型与控制协议

**职责：** 定义命令类型、命令元数据、输入类型、查询快照和界面控制协议。

**公共接口：** `CommandKind`、`Command`、`ParsedInput`、`StatusSnapshot`、`MemorySnapshot`、`SessionSnapshot`、`CommandControl`、`CommandContext`、`CommandHandler`。

**依赖：** 仅标准库与既有权限模式类型；不依赖 Textual。

### 命令注册中心

**职责：** 注册命令、建立规范名称和别名索引、启动期冲突校验、精确解析、公开命令排序与补全候选计算。

**公共接口：**

```python
class CommandRegistry:
    def register(self, command: Command) -> None: ...
    def resolve(self, name: str) -> Command | None: ...
    def public_commands(self) -> tuple[Command, ...]: ...
    def completions(self, prefix: str) -> tuple[Command, ...]: ...
```

**校验规则：** 名称和别名清理后不能为空；统一小写建立单一占用索引；同一命令内部重复别名也视为冲突；任何名称/别名已被占用均抛出含双方来源的配置错误。注册表不提供覆盖接口。

**补全规则：** 仅公开命令参与；规范名称或任一别名以前缀开头即命中；同一命令只返回一次；最终按规范名称排序。

### 输入解析与命令分发

**职责：** 区分空输入、普通消息和 Slash 命令；解析命令名与参数；执行未知命令和参数错误的统一处理；调用命令处理函数。

**公共接口：**

```python
def parse_input(text: str) -> ParsedInput: ...

class CommandDispatcher:
    def __init__(self, registry: CommandRegistry) -> None: ...
    async def dispatch(
        self, parsed: ParsedInput, control: CommandControl
    ) -> None: ...
```

分发器解析出命令后创建 `CommandContext(registry, control)` 并传给 handler。

**参数策略：** 分发器对 `argument_hint` 为空的命令统一拒绝非空参数并显示 `usage`；`help` 自行校验参数必须是零个或一个名称。未知命令使用相同本地消息通道显示错误和 `/help` 引导。

### 内置命令集合

**职责：** 构造十二个 `Command`，提供固定描述、用法、类型和处理函数；渲染帮助、状态、记忆、权限与会话文本；实现计划切换和提示词注入顺序。

**公共接口：**

```python
REVIEW_PROMPT: Final[str]

def new_default_command_registry() -> CommandRegistry: ...
```

**关键行为：**

- `help` 从传入分发上下文中的同一注册表读取元数据，不维护第二份命令清单。
- `plan` 设置 `Mode.PLAN`、刷新状态并显示本地 notice。
- `do` 严格先设置 `Mode.DEFAULT`、刷新状态，再发送既有执行指令。
- `review` 只发送批准的固定文本，不读取工作区。
- `status`、`memory`、`permission`、`session` 只读取快照并显示文本。
- `clear`、`compact`、`resume`、`exit` 委托控制协议执行。

### TUI 命令控制适配器

**职责：** 将 `CommandControl` 映射到 `MewCodeApp`，是命令域与 Textual 的唯一连接点。

**公共接口：**

```python
class TuiCommandControl(CommandControl):
    def __init__(self, app: MewCodeApp) -> None: ...
```

**行为映射：**

- `show_message` 添加命令输出时间线项，不写档案。
- `send_user_message` 调用统一 Agent 回合入口。
- `set_mode` 只修改当前运行时模式；`refresh_status` 立即更新状态栏。
- `status_snapshot` 在计划模式读取只读工具定义数量，其他模式读取全部工具定义数量，并组合当前会话统计、记忆计数、模型和工作目录。
- `memory_snapshot` 调用记忆管理器的索引快照接口。
- `session_snapshot` 在没有 runtime 时返回 `None`，不创建会话。
- `clear_session` 关闭旧 runtime，立即创建新 runtime，替换 conversation 和零值统计，清空时间线，添加并持久化指定 notice，最后恢复输入焦点和状态栏。
- 其余界面命令委托现有退出、压缩和恢复动作。

### TUI 提交入口

**职责：** 把现有硬编码 Slash 分支替换为统一解析与分发；抽取可由普通输入和提示词命令共同使用的回合启动入口。

**核心流程：**

```text
Enter
  -> 非 IDLE：忽略
  -> parse_input
      -> EMPTY：返回
      -> COMMAND：清空输入 -> dispatcher.dispatch -> 恢复焦点
      -> MESSAGE：start_user_turn

start_user_turn
  -> 确保 runtime
  -> 添加用户消息（自动写 JSONL）
  -> 当前内存会话回合数加 1
  -> 锁定输入并启动现有流式消费任务
```

命令分发不直接操作 TextArea。提示词处理函数经控制适配器进入 `start_user_turn`，从而不会复制 Agent 启动逻辑。

### TUI 内联命令菜单

**职责：** 在 Prompt 输入框下方显示公开命令候选，随输入实时过滤，并在不转移输入焦点的前提下处理键盘和鼠标选择。

**结构：**

```python
class CommandCompletionMenu(OptionList):
    def set_commands(self, commands: tuple[Command, ...]) -> None: ...
    def move_highlight(self, delta: int) -> None: ...
    def highlighted_name(self) -> str | None: ...
```

候选行显示规范名称和一句描述。Widget 放在 PromptInput 与状态栏之间，默认隐藏；显示时高度按候选数量自适应并限制最大高度，终端空间不足时内部滚动。

**应用状态与事件：**

```python
class MewCodeApp:
    _completion_commands: tuple[Command, ...]
    _completion_suppressed_text: str | None

    def refresh_command_menu(self) -> None: ...
    def move_command_menu(self, delta: int) -> None: ...
    def accept_command_menu(self, name: str | None = None) -> None: ...
    def dismiss_command_menu(self, *, suppress: bool = False) -> None: ...
```

- TextArea 内容变化时，在 IDLE 且文本是无参数 `/...` 命令前缀时调用注册表补全；`/` 的空前缀返回全部公开命令。
- 输入不再是命令前缀、已经出现参数、没有候选或应用离开 IDLE 时隐藏菜单。
- 菜单每次刷新默认高亮第一项，输入焦点仍停留在 PromptInput。
- PromptInput 在菜单可见时拦截上/下键移动高亮；Tab 或 Enter 接受高亮项；Esc 关闭菜单。菜单隐藏时 Enter 继续走正常提交，Shift+Tab 权限切换和 Alt+Enter 换行不变。
- 鼠标点击候选时由 OptionList 选择事件调用同一接受路径。
- 接受候选时先记录补全后的文本为 `_completion_suppressed_text`，再写回 `/<canonical>` 并关闭菜单。由此 TextArea 的程序化变更不会立刻重开菜单，下一次 Enter 可以提交；用户继续编辑后抑制状态自动失效并恢复实时过滤。
- Esc 关闭时抑制当前文本，直到用户再次编辑；无匹配只隐藏菜单，不向 Timeline 写提示。

### 会话统计档案

**职责：** 扩展 JSONL 事件以记录每次请求 usage 增量；恢复时汇总 usage，并以合法用户消息数恢复会话回合数，形成 `SessionStats`。

**事件格式：**

```json
{"type":"usage","ts":0,"input_tokens":120,"output_tokens":30}
```

**公共接口：**

```python
class ArchiveWriter:
    def append_usage(self, input_tokens: int, output_tokens: int) -> None: ...

@dataclass(frozen=True)
class RestoredArchive:
    ...
    stats: SessionStats
```

流式消费收到 usage 时先更新内存统计，再追加 usage 事件并刷新状态栏。`start_user_turn` 在用户消息成功加入 conversation 和 JSONL 后只增加一次内存回合数；工具续轮不经过该入口，因此不会重复增加。恢复时对有效用户消息计数，包含普通输入及 `/do`、`/review` 注入文本，同时天然兼容没有新统计事件的历史档案。

### 记忆索引快照

**职责：** 从项目层和用户层 `MEMORY.md` 中提取索引注释引用的安全笔记文件名，为 `/memory` 和 `/status` 提供同一数据源。

**公共接口：**

```python
class MemoryStore:
    def indexed_files(self) -> dict[str, tuple[str, ...]]: ...

class MemoryManager:
    def indexed_files(self) -> dict[str, tuple[str, ...]]: ...
```

每层结果去重并按文件名字典序排列；只接受既有安全文件名格式，排除 `MEMORY.md`，不读取笔记正文，也不要求被引用文件当前存在。TUI 控制适配器把该通用结果转换成命令域的 `MemorySnapshot`，记忆模块不反向依赖命令模块。

### 状态栏与命令输出视图

**职责：** 将模式显示改为显式方括号标记，并提供适合多行帮助和状态文本的命令输出时间线项。

**显示规则：** 默认与计划模式分别显示 `[DEFAULT]`、`[PLAN]`；其他模式沿用现有大写友好名称并加方括号。Token 仍使用紧凑格式。命令输出项保留换行与空格，使帮助两列对齐。

### 启动组装

**职责：** 在进入 TUI 前构造默认命令注册表并注入应用。

命令注册表在连接 MCP 和启动 Textual 前完成构造；冲突异常进入现有顶层启动错误路径并以非零状态退出。测试直接构造应用时若未注入注册表，则使用同一默认构造函数，不维护测试专用命令集。

## 模块交互

### 普通消息

```text
PromptInput Enter
  -> parse_input(MESSAGE)
  -> MewCodeApp.start_user_turn
  -> SessionRuntime / Conversation / ArchiveWriter
  -> Agent.run
  -> consume_stream
      -> record usage event
      -> refresh status
```

### 纯本地命令

```text
PromptInput Enter
  -> parse_input(COMMAND)
  -> CommandDispatcher
  -> builtin handler
  -> TuiCommandControl snapshot + show_message
  -> Timeline only
```

### 提示词命令

```text
PromptInput Enter
  -> CommandDispatcher
  -> do/review handler
  -> optional mode change + refresh
  -> TuiCommandControl.send_user_message
  -> MewCodeApp.start_user_turn
  -> normal Agent path
```

### 实时内联补全

```text
PromptInput text changed to "/..."
  -> CommandRegistry.completions(prefix)
      -> 0: hide inline menu
      -> N: refresh CommandCompletionMenu below input

PromptInput key while menu visible
  -> Up/Down: move highlight
  -> Tab/Enter: fill canonical name + suppress immediate reopen
  -> Escape: hide + suppress until edit

CommandCompletionMenu mouse selection
  -> same canonical fill path
```

### 会话恢复

```text
/resume
  -> existing session list
  -> SessionRepository.restore
      -> messages/checkpoint/artifacts
      -> sum usage + turn events
  -> SessionRuntime.restore
  -> TUI replay visible events
  -> replace current SessionStats
  -> refresh status
```

## 文件组织

```text
src/mewcode/
|-- command/
|   |-- __init__.py       - 命令域公共导出
|   |-- model.py          - 元数据、快照与控制协议
|   |-- registry.py       - 注册、冲突校验与补全候选
|   |-- dispatcher.py     - 输入解析和命令分发
|   `-- builtin.py        - 十二个内置命令
|-- memory/
|   |-- store.py          - 增加记忆索引快照
|   `-- update.py         - 暴露记忆快照
|-- session/
|   |-- archive.py        - usage 事件与 SessionStats
|   `-- repository.py     - 恢复时汇总会话统计
|-- tui/
|   |-- app.py            - 提交分流、统一回合入口和命令组装
|   |-- command.py        - Textual 命令控制适配器
|   |-- completion.py     - 输入框下方的内联命令菜单
|   |-- stream.py         - usage 持久化
|   |-- timeline.py       - 清空时间线能力
|   `-- view.py           - 命令输出项和状态栏模式标记
`-- cli.py                - 启动期创建并注入命令注册表

tests/
|-- test_command.py       - 注册、解析、分发、内置命令与补全单测
|-- test_tui_command.py   - TUI 路由、补全、clear、状态与提示词集成
|-- test_memory_store.py  - 索引快照与条目计数
|-- test_session_archive.py    - usage 事件写入
|-- test_session_repository.py - 会话统计恢复
`-- test_tui.py           - 既有提交、模式和状态栏回归

doc/09/
|-- spec.md
|-- plan.md
|-- task.md
`-- checklist.md

README.md                 - 命令表、别名、补全和状态统计说明
```

`HANDOVER.md` 作为本章输入基线保留，不在实现过程中重写。

## 需求覆盖

| 需求 | 设计覆盖 |
|---|---|
| F1 | 命令模型、注册中心、启动组装 |
| F2 | 输入解析、命令分发、TUI 提交入口 |
| F3 | `CommandControl`、TUI 控制适配器 |
| F4-F5 | 分发参数策略、内置 help 处理函数 |
| F6 | 注册中心补全、TUI 内联命令菜单、PromptInput 事件路由 |
| F7 | 内置命令集合、控制适配器 |
| F8 | 状态快照、记忆快照、工具注册表查询、状态栏视图 |
| F9 | 会话统计事件、恢复汇总、统一回合入口、流式消费 |
| F10 | 控制适配器显示通道、统一回合入口、档案事件边界 |
| F11 | TUI 提交入口与既有状态锁 |

## 技术决策

| 决策 | 选择 | 原因 |
|---|---|---|
| 命令架构 | 独立命令域 + TUI 控制适配器 | 满足框架解耦，命令逻辑可纯单测，TUI 只负责能力映射。 |
| 注册时机 | TUI 启动前一次性构造 | 冲突立即终止，不把歧义带入运行时。 |
| 名称存储 | 内部不含 `/`，统一小写索引 | 简化名称、别名、帮助和补全的一致匹配。 |
| 冲突策略 | 任意占用冲突直接异常，不允许覆盖 | 对应启动安全要求，错误可定位。 |
| 命令处理 | 异步 handler + `CommandControl` 协议 | 同时支持纯本地和异步界面操作，不依赖 Textual。 |
| 提示词命令 | 复用普通用户消息回合入口 | 避免档案、标题、上下文和取消逻辑分叉。 |
| 补全容器 | 输入框下方的内联 OptionList | 不打断输入上下文，符合 Claude Code 风格，并可复用 Textual 的选择与滚动能力。 |
| 焦点策略 | 菜单可见时焦点仍在 PromptInput | 用户可以持续输入过滤；键盘选择由输入框转发。 |
| 二次 Enter | 用补全文本抑制标记阻止程序化写回后重开 | 第一次 Enter 只填充，第二次 Enter 才进入现有提交分流。 |
| 补全输出 | 总是写回规范名称 | 别名只负责匹配和调用，界面结果稳定、帮助一致。 |
| Token 持久化 | 每次 usage 写增量事件 | 保留请求粒度、追加安全、恢复时可简单求和。 |
| 回合持久化 | 复用 JSONL 用户消息作为回合事实 | 三类回合都写用户消息，工具续轮不写；可直接兼容 Chapter 08 历史档案，避免双重事实来源。 |
| 统计所有权 | JSONL 为事实来源，TUI 持当前会话镜像 | 与 Chapter 08 档案原则一致，同时保证状态栏快速更新。 |
| 记忆统计 | 解析两层索引中的安全文件引用 | 数量和 `/memory` 使用同一“已加载”定义，不读取正文。 |
| `/clear` 会话创建 | 立即创建 runtime 与空 JSONL | 严格满足“关闭旧档案、开启新档案”，不沿用首次消息懒创建。 |
| Chapter 08 技术债 | 不顺带修复 | 遵守本章范围，只保持已有恢复和压缩契约不退化。 |
