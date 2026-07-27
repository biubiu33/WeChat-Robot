# Hook 生命周期挂钩系统 Plan

## Architecture Overview

本章新增独立的 `hook` 包，负责 YAML 规则加载、条件求值、动作执行、会话内运行状态和
事件分派。权限模块继续拥有通用匹配器，Hook 只复用其结构化匹配能力，不参与权限裁决。

`cli` 在启动期加载 Hook 配置并构造单个 `HookEngine`，再注入 TUI。TUI 负责会话和用户
输入生命周期事件；Agent 负责请求、工具、停止和通知事件；ContextController 通过回调负责
压缩事件。各接入点只依赖一个异步分派接口，避免 Hook 包反向依赖 TUI、Agent 或 Context。

```text
YAML files -> HookCatalog -> HookEngine -> Hook action executors
                                   ^              |
cli -------------------------------|              v
TUI session/input -- Hook dispatcher callback -- HookSessionState
Agent request/tool/notification ----|              |
ContextController compact ----------|              v
                                      next-request reminder queue
```

## Core Data Structures

### Permission Pattern

`permission.rule.Pattern` 表示已校验、可复用的匹配表达式。

```python
@dataclass(frozen=True)
class Pattern:
    type: Literal["exact", "glob", "regex", "not"]
    value: str = ""
    inner: Pattern | None = None

    def matches(self, target: str, *, is_path: bool) -> bool: ...
```

`Rule` 持有 `Pattern | None` 而不是原始 pattern 字符串；空 Pattern 继续表示该工具的全匹配。
规则字符串解析保留既有 glob 写法，并支持 `=` 精确、`~` 正则和 `!` 反向包装。编译后的正则
保存在 Pattern 中，运行期不重复编译。

### Hook Model

```python
class HookEvent(str, Enum):
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"

@dataclass(frozen=True)
class Condition:
    field: str
    match: Pattern

@dataclass(frozen=True)
class ConditionGroup:
    mode: Literal["all_of", "any_of"]
    conditions: tuple[Condition, ...]

@dataclass(frozen=True)
class Action:
    type: Literal["shell", "prompt", "http", "subagent"]
    # 各动作经校验后的专属字段

@dataclass(frozen=True)
class Hook:
    name: str
    event: HookEvent
    condition: ConditionGroup | None
    action: Action
    only_once: bool = False
    asynchronous: bool = False
    timeout_seconds: float = 30.0
    source: Path = Path()
```

`HookContext` 包装通用字段与事件特化 payload。其 `payload` 为 JSON 可序列化映射，并提供点分
字段读取；不存在的路径返回空字符串。动作执行前将 payload 用 `json.dumps(..., sort_keys=True)`
序列化。

### Session State And Dispatch Result

```python
@dataclass
class HookSessionState:
    reserved: set[str] = field(default_factory=set)
    executed: set[str] = field(default_factory=set)
    reminders: list[str] = field(default_factory=list)
    background_tasks: set[asyncio.Task[None]] = field(default_factory=set)

@dataclass(frozen=True)
class HookDispatch:
    blocked_by: str = ""
    reason: str = ""

    @property
    def blocked(self) -> bool: ...
```

`HookSessionState` 由 `SessionRuntime` 持有，随新建、清空和恢复会话而更换。`only_once` 先写入
`reserved`；成功后移至 `executed`，失败则移除预留。异步任务完成时使用同一规则确认或释放。

### Public Runtime Interfaces

```python
class HookEngine:
    @classmethod
    def load(cls, root: Path, home: Path | None = None) -> HookEngine: ...

    async def dispatch(
        self, event: HookEvent, context: HookContext, state: HookSessionState
    ) -> HookDispatch: ...

    def take_reminders(self, state: HookSessionState) -> tuple[str, ...]: ...
    def snapshot(self) -> HookSnapshot: ...
    async def close_session(self, state: HookSessionState) -> None: ...
```

非阻塞分派返回空 `HookDispatch`；阻塞事件的第一个有效 block 结果返回 Hook 名和原因。调用方
根据该结果决定是否写入消息、执行工具或展示提示。

## Module Design

### `mewcode.permission.rule`

**Responsibility:** 解析和运行四种通用匹配语义，保持权限层的 deny/allow 和优先级不变。

**Changes:** 用 Pattern 取代字符串 glob；解析失败返回可诊断原因；设置加载器把失败规则和原因
写 stderr 后继续加载。`RuleSet` 的匹配接口保持工具调用方兼容。

**Dependencies:** 标准库 `re`；不依赖 Hook。

### `mewcode.hook.model` And `mewcode.hook.config`

**Responsibility:** 表达 Hook、动作、条件、事件、会话状态和可显示快照；读取两层 YAML 并集中
校验。

**Validation:** 顶层仅接受 `hooks` 数组；未知字段、重复 name、非法 event、条件组混用、错误
Pattern、缺失动作字段、非法超时、`prompt + async` 和阻塞事件 `async` 都产生诊断并跳过当前
Hook。加载顺序固定为项目级文件、用户级文件，后加载的同名 Hook 跳过。缺失文件静默，坏文件
和坏顶层仅输出 stderr。

**Dependencies:** `permission.rule.Pattern`、`yaml`、标准库路径和时间解析。

### `mewcode.hook.actions`

**Responsibility:** 对已验证 Action 执行 shell、prompt、HTTP 或 subagent 占位，并统一返回成功、
失败或阻塞结果。

**Shell:** 通过异步子进程执行命令，将稳定排序 JSON 写入 stdin；捕获 stdout、stderr、退出码与
超时。阻塞事件只将退出码 2 解释为 block，其余非零失败记录后放行。

**Prompt:** 立即把原样 `text` 追加到会话 reminder 队列，不启动后台任务，也不表达 block。

**HTTP:** 使用标准库 HTTP 客户端在线程中执行，默认 JSON body；显式 body 使用受限
`str.format_map` 渲染。阻塞事件只接受 2xx JSON block 响应，网络、解析和超时错误均失败放行。

**Subagent:** 校验完成后固定输出
`[hook subagent] not yet implemented, skipped: <name>`，视为成功占位动作。

### `mewcode.hook.engine`

**Responsibility:** 按 catalog 顺序筛选事件和条件、管理 once 预留、同步或后台分派动作、收集
提醒、输出失败日志并返回拦截决定。

**Execution Rules:** 同步 Hook 依次运行；命中 block 后停止本次阻塞事件的剩余 Hook。非阻塞
`async` Hook 建立受跟踪任务，不等待其完成；同步失败只记录日志。关闭会话时取消并收集仍在运行
的后台任务，`CancelledError` 继续向调用方传播。

### `mewcode.session.runtime`

**Responsibility:** 为每个 SessionRuntime 新增 `HookSessionState`，使 once 标记、提醒和后台任务
严格随活动会话生命周期创建、恢复和销毁。

### `mewcode.agent`

**Responsibility:** 通过注入的 Hook dispatcher 在 Agent Loop 内触发 `PreUserMessage`、
`PreToolUse`、`PostToolUse`、`Stop` 和 `Notification`。

**Integration:**

- 每次构造 Provider 请求前分派 `PreUserMessage`，随后取出 reminder 队列并拼接在既有 plan
  reminder 之后。
- 对可执行工具在权限 `check` 前分派 `PreToolUse`；若 block，构造带 `[hook <name>]` 原因的
  错误 ToolResult，跳过权限与真实工具。
- 每个工具结果（包括权限拒绝）在 PhaseEnd 前分派 `PostToolUse`。
- 权限 Ask 生成 ApprovalRequest 前、Provider 流错误上报前分别分派 `Notification`。
- 自然完成路径在 `done=True` 之前分派 `Stop`。

Agent 只接收由 TUI 提供的事件上下文与分派回调，不导入 Hook 的配置或 TUI 类型。

### `mewcode.context.controller`

**Responsibility:** 增加可选压缩观察回调，在自动、紧急和手动压缩尝试前后分派 Hook。

**Integration:** 每次请求前先计算预算：达到或超过 `context_window` 使用 `emergency`，仅超过
安全余量使用 `auto`；`compact_now()` 使用 `manual`。回调获取 trigger 及压缩前后估算 Token，
不负责持久化 Hook 数据。无观察者时保持当前上下文行为。

### `mewcode.tui.app`, `mewcode.tui.command`, And `mewcode.tui.stream`

**Responsibility:** 提供通用 Hook 上下文工厂，连接会话状态、Agent dispatcher、压缩观察者和
Slash 命令。

**Integration:**

- 首次创建 SessionRuntime 后、用户消息入档前触发 `SessionStart`；每个普通 TUI 输入在入档前
  触发 `UserPromptSubmit`。被 block 时显示原因、保留输入、且不创建用户消息。
- `/clear`、`/resume` 和退出关闭旧会话前触发 `SessionEnd`；恢复与重放完成后触发
  `SessionResume`。隔离 fork Skill 不进入主会话 Hook 生命周期。
- 手动压缩通过 ContextController 回调触发 `PreCompact`/`PostCompact`。
- 命令控制协议增加 Hook 快照；内置命令注册 `/hooks` 并按事件输出 Hook 摘要和来源。
- stream 消费器构造 Agent 时注入 Hook dispatcher、当前会话状态和 reminder 供应器。

### Documentation

`README.md` 增加 Hook 配置位置、最小 YAML 示例、11 个事件、条件匹配、四种动作、拦截约定、
async/only_once 限制和 `/hooks` 使用说明；不暴露用户私有配置内容。

## Module Interactions

### Startup

```text
cli -> registry + permission engine -> HookEngine.load(root)
    -> MewCodeApp(..., hook_engine)
```

配置诊断写 stderr；有效 Hook 在整个进程中保持静态，直到重启。

### Message And Request

```text
TUI normal input
  -> ensure SessionRuntime -> SessionStart (first time)
  -> UserPromptSubmit -> [block: restore input and show reason]
  -> Conversation.add_user -> Agent.run
  -> PreUserMessage -> take hook reminders
  -> plan reminder + hook reminders -> provider.stream
```

### Tool Execution

```text
tool call -> ToolStart -> PreToolUse
  -> [block: Hook error ToolResult]
  -> permission check -> approval or registry execution
  -> PostToolUse -> ToolEnd -> next Agent iteration
```

Read-only calls retain existing parallel real-tool execution; each call completes its own pre-check before being
admitted to the parallel batch, and emits its post event before its end event.

### Context And Session

```text
request budget -> PreCompact(trigger) -> compact attempt -> PostCompact(trigger)
/clear | /resume | quit -> SessionEnd -> cancel hook tasks -> close runtime
restore complete -> new HookSessionState -> SessionResume
```

## File Organization

```text
src/mewcode/
├── hook/
│   ├── __init__.py          # Hook 公共类型与工厂导出
│   ├── model.py             # 事件、条件、动作、Hook、会话状态、快照
│   ├── config.py            # 两层 YAML 读取、集中校验和诊断
│   ├── actions.py           # shell/prompt/http/subagent 执行器
│   └── engine.py            # 分派、once、后台任务、提醒和拦截结果
├── permission/
│   ├── rule.py              # 改：四种共享匹配模式与规则解析
│   └── settings.py          # 改：报告无效权限规则
├── agent/__init__.py        # 改：请求、工具、停止、通知 Hook 接入
├── context/controller.py    # 改：自动/紧急/手动压缩 Hook 回调
├── session/runtime.py       # 改：持有 HookSessionState
├── tui/app.py               # 改：会话、用户提交、上下文工厂与 Hook 装配
├── tui/stream.py            # 改：向 Agent 注入 Hook 分派能力
├── tui/command.py           # 改：实现 Hook 命令控制快照
├── command/model.py         # 改：增加 HookSnapshot 控制协议
├── command/builtin.py       # 改：注册并实现 /hooks
├── cli.py                   # 改：启动期加载并注入 HookEngine
└── README.md                # 改：用户配置与使用说明

tests/
├── test_permission.py       # 改：四种规则匹配与诊断回归
├── test_hook_config.py      # 新：YAML、来源、校验、冲突和条件解析
├── test_hook_actions.py     # 新：shell、HTTP、prompt、subagent、超时和失败
├── test_hook_engine.py      # 新：条件、once 两阶段、async、提醒和拦截分派
├── test_agent.py            # 改：请求、工具、通知、停止和拒绝回灌
├── test_tui.py              # 改：提交拦截、会话事件、恢复和退出
├── test_tui_command.py      # 改：/hooks 路由和显示
└── test_context_artifact.py # 改：三种压缩触发来源和 payload
```

## Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| 通用匹配器归属 | `permission.rule.Pattern` | 权限规则与 Hook 条件复用同一实现，不引入循环依赖。 |
| Hook 配置范围 | 项目级后用户级，规则累加 | 遵循批准规格；同名后加载规则跳过并有诊断。 |
| Hook 运行状态 | `SessionRuntime` 持有 `HookSessionState` | 满足 once 与提醒严格随会话清空/恢复的要求。 |
| 系统集成 | 注入分派回调 | Agent/Context 不依赖 Hook 配置、TUI 或会话实现，易于单测。 |
| Prompt 提醒 | 队列在下一 Provider 请求前消费 | 保持隐藏、一次性、无档案污染，并能覆盖 SessionStart 与 PostToolUse。 |
| 工具拦截 | shell exit 2 / HTTP 2xx block | 同时允许脚本与外部策略服务提供可解释拒绝原因。 |
| HTTP 实现 | 标准库在线程执行 | 不新增依赖，保留明确的超时和取消边界。 |
| 紧急压缩 | 预算达到 `context_window` | 与安全余量自动压缩可观察地区分，不引入 Provider 错误重试。 |
| 异步 once | 预留后由任务完成确认 | 避免并发重复，同时让失败 Hook 在后续事件重试。 |
