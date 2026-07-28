# 子 Agent 与后台任务 Plan

## Architecture Overview

新增独立的 `mewcode.subagent` 子系统，负责角色目录、Fork 消息构造、子 Agent 运行时、工具作用域、文件读缓存、权限快照、后台任务及主 Agent 工具。它不创建第二套 ReAct 实现：子 Agent 继续复用扩展后的 `agent.Agent` 循环、现有 Provider、权限检查和 Hook 分派。

`MewCodeApp` 作为宿主组装共享依赖、注册主 Agent 专用工具、将子任务审批转发到现有 TUI 批准框，并在主请求前提供一次性任务通知。现有 Skill fork 改成 SubAgentHost 的兼容适配器，以保留 Slash Skill 的可见行为和摘要行为。

```text
主 Agent
  ├─ Agent / Task* 工具 ──> SubAgentHost
  │                         ├─ AgentCatalog / Definition
  │                         ├─ ChildRuntimeFactory
  │                         │    └─ Agent.run_to_completion(...)
  │                         └─ TaskManager
  └─ 下次请求 <── 一次性 task-notification ── TaskManager

SubAgentHost
  ├─ ScopedRegistry -> 共享 Registry（过滤、缓存）
  ├─ Child Engine -> 父 session 授权快照 + 共享永久规则
  ├─ Child HookSessionState -> 共享 HookEngine
  └─ ProviderResolver -> 共享 Provider 实例缓存

Skill fork ──> SkillForkAdapter ──> SubAgentHost
```

## Core Data Structures

### `Definition`

```python
class DefinitionSource(str, Enum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"
    PLUGIN = "plugin"

class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    BYPASS = "bypassPermissions"
    DONT_ASK = "dontAsk"

@dataclass(frozen=True)
class Definition:
    name: str
    description: str
    instruction: str
    tools: frozenset[str] | None
    disallowed_tools: frozenset[str]
    model_profile: str | None
    max_turns: int
    permission_mode: PermissionMode
    background: bool
    source: DefinitionSource
    path: Path
```

`None` 的 `tools` 表示不再额外收窄；空列表表示子 Agent 不可使用普通工具。解析时将 `name` 和 `subagent_type` 统一为小写 kebab-case，接受 `disallowedTools`、`maxTurns`、`permissionMode` 等定义文件字段，并拒绝未知或类型错误字段。

### `LaunchRequest` and `ChildRuntime`

```python
@dataclass(frozen=True)
class LaunchRequest:
    prompt: str
    description: str
    subagent_type: str | None
    model_profile: str | None
    run_in_background: bool
    name: str | None

@dataclass
class ChildRuntime:
    agent: Agent
    conversation: Conversation
    engine: Engine
    registry: ScopedRegistry
    hook_state: HookSessionState
    usage: TokenUsage
    cache: FileReadCache
    definition: Definition
    forked: bool
```

`ChildRuntimeFactory.create()` 统一构造定义式、Fork、Skill fork 三种运行时。定义式从空对话开始；Fork 使用深拷贝消息和 Fork Boilerplate；Skill fork 使用临时定义与空历史。三种路径都将 `Agent`、任务管理工具和 fork Skill 入口从实际工具集剔除。

### `BackgroundTask`

```python
class TaskStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class BackgroundTask:
    id: str
    name: str | None
    runtime: ChildRuntime
    task_text: str
    status: TaskStatus
    result: str = ""
    error: BaseException | None = None
    started_at: float = 0.0
    ended_at: float | None = None
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    run_task: asyncio.Task[None] | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    tool_count: int = 0
    last_activity: str = ""
```

`TaskManager` 维护 ID 索引、名称到最新任务的弱索引、已消费通知队列和待批准请求队列。所有终态对象保留到宿主进程退出。`SendMessage` 只能重新启动 `COMPLETED` 项，沿用其对话、运行时和 ID。

### `FileReadCache` and `ScopedRegistry`

```python
@dataclass(frozen=True)
class CachedRead:
    modified_ns: int
    size: int
    result: Result

class FileReadCache:
    async def get(self, path: Path) -> Result | None: ...
    def put(self, path: Path, result: Result) -> None: ...
    def invalidate(self, path: Path) -> None: ...

class ScopedRegistry:
    def definitions(self, allowed_tools=None) -> list[ToolDefinition]: ...
    def read_only_definitions(self, allowed_tools=None) -> list[ToolDefinition]: ...
    def get(self, name: str) -> Tool | None: ...
    def is_read_only(self, name: str) -> bool: ...
    def is_system(self, name: str) -> bool: ...
    async def execute(self, name, args, timeout, allowed_tools=None) -> Result: ...
```

`ScopedRegistry` 保留对共享 Registry 的引用，不复制工具。它只暴露计算后的许可集，并在执行时再次检查范围。它在成功的 `read_file` 上使用当前运行时缓存；在成功的 `write_file` 或 `edit_file` 上失效同运行时缓存。缓存键采用权限解析后的规范文件路径，命中前通过 `mtime_ns` 与大小验证，不缓存错误结果。

### Approval Bridge

```python
@dataclass
class SubAgentApproval:
    task_id: str | None
    child_name: str
    request: ApprovalRequest
    return_state: SessionState
```

每个子 Agent 的 `ApprovalRequest` 经宿主的异步队列转发。主 TUI 将同一 `Future[Outcome]` 渲染为带 `[来自 SubAgent <name>]` 的批准框；选择结果回填原 Future。流式执行阶段的 ESC 由宿主解除等待者并将相应运行时交给后台任务；批准框中的 ESC 只填写 `DENY_ONCE`。

## Module Design

### `mewcode.subagent.model`

**Responsibility:** 定义角色、来源、权限模式、请求、运行时用量、任务状态和面向工具的摘要结构。

**Public Interface:** `Definition`、`DefinitionSource`、`PermissionMode`、`LaunchRequest`、`TaskStatus`、`TokenUsage`、`TaskSummary`。

### `mewcode.subagent.catalog`

**Responsibility:** 加载、验证、覆盖、查询和呈现角色目录。

**Public Interface:**

```python
class AgentCatalog:
    @classmethod
    def load(root: Path, ...) -> AgentCatalog: ...
    def resolve(self, name: str) -> Definition | None: ...
    def effective(self) -> tuple[Definition, ...]: ...
    def prompt_listing(self) -> str: ...
    def diagnostics(self) -> tuple[AgentDiagnostic, ...]: ...
```

目录按内置、用户、项目顺序读取以实现后者覆盖前者；插件位置作为恒为空的第四来源加入排序。内置 Markdown 通过 `importlib.resources` 读取，并由包构建显式包含。

### `mewcode.subagent.policy`

**Responsibility:** 计算实际工具能力并杜绝嵌套。

**Public Interface:**

```python
ALL_AGENT_DISALLOWED_TOOLS = frozenset({"Agent", "TaskList", "TaskGet", "TaskStop", "SendMessage"})
ASYNC_AGENT_ALLOWED_TOOLS = frozenset({...})

def allowed_tools(base: Registry, definition: Definition, *, background: bool) -> frozenset[str]: ...
def child_safe_skill_mode(skill: Skill) -> Result | None: ...
```

算法从父 Agent 当前许可集合与 Registry 可用普通/系统工具的交集开始，依次移除全局控制面、施加后台白名单、角色黑名单和角色白名单。即使基础 Registry 会自动暴露系统工具，`ScopedRegistry` 也必须最终过滤。子 Agent 的 `load_skill` 使用受限执行器：inline 正常，fork 返回 `nested_agent_denied`。

### `mewcode.subagent.runtime`

**Responsibility:** 创建隔离运行时、构造系统提示、Fork 历史和权限快照，并驱动子 Agent 到完成。

**Public Interface:**

```python
class SubAgentHost:
    def prepare(self, request: LaunchRequest, parent: ParentContext) -> ChildRuntime: ...
    async def run_inline(self, runtime: ChildRuntime, task: str) -> str: ...
    async def run_skill(self, skill: ActiveSkill, parent: ParentContext) -> ForkSummary: ...

def build_forked_messages(parent: Conversation, task: str) -> list[Message]: ...
def fork_boilerplate(task: str) -> str: ...
```

Fork 深拷贝全部消息；最后一个 assistant 的未配对工具调用补成占位错误工具结果后，才追加带 `<fork_boilerplate>` 的 user 消息。定义式使用角色正文作为子 Agent 系统提示，Fork 维持父级稳定系统提示并只在末尾追加用户消息，从而保持最大缓存前缀。

子 Engine 由 `Engine.fork_for_subagent()` 创建：复制父 `session` 允许规则，使用新的 session `RuleSet`，共享或同步永久本地规则，复用不可绕过的黑名单和沙箱。`DONT_ASK` 仅改变未匹配规则的兜底为 Allow；Deny 仍然终止，其他 Ask 转 Approval Bridge。Allow Forever 通过宿主回调写入共享父 Engine 与本地配置，Allow Session 只写子 Engine。

### `mewcode.subagent.task`

**Responsibility:** 管理后台生命周期、前台转后台、终态通知、任务查询与续派。

**Public Interface:**

```python
class TaskManager:
    async def launch(self, runtime: ChildRuntime, task: str, name: str | None) -> BackgroundTask: ...
    async def await_or_detach(self, run: RunningChild, timeout: float) -> TaskSummary: ...
    def detach(self, run_id: str) -> TaskSummary: ...
    def get(self, task_id: str) -> BackgroundTask | None: ...
    def list(self) -> tuple[BackgroundTask, ...]: ...
    def stop(self, task_id: str) -> bool: ...
    async def send(self, name: str, message: str) -> BackgroundTask | None: ...
    def take_notifications(self) -> tuple[str, ...]: ...
```

前台运行从开始即由可转交的 `RunningChild` 句柄驱动，避免在 120 秒或 ESC 时取消并重启同一子 Agent。显式后台、角色后台和 Fork 直接持久化为 BackgroundTask；前台任务在超时或 ESC 时被原地接管并立即让 Agent 工具返回异步任务 ID。任务 runner 捕获所有异常，设置终态并排入一次性通知。`enable_subagent_background=False` 时禁止接管，Fork 在入口返回错误。

### `mewcode.subagent.tool`

**Responsibility:** 实现主 Agent 专用 `Agent`、`TaskList`、`TaskGet`、`TaskStop`、`SendMessage` 工具。

**Public Interface:** 每个工具实现现有 `Tool` 协议且标记为系统工具；`Agent` 的 JSON Schema 固定，包含 `prompt`、`description`、`subagent_type`、`model`、`run_in_background` 和 `name`。所有参数校验失败、未知角色、不可用模型、后台禁用 Fork 和嵌套拒绝均使用现有结构化 `error_result` 格式。

`AgentTool.execute()` 根据调用构造 ChildRuntime；前台等待最终文本或超时/ESC 的异步摘要，后台立即返回任务 ID。任务工具只由主 Registry 公开；子 ScopedRegistry 将其剔除。

### `agent`, `permission` and `tool` extensions

**Responsibility:** 让主/子 Agent 共享 ReAct 算法而不复制循环。

**Changes:**

- `Agent` 新增运行配置：最大轮次、可选稳定系统提示覆盖、一次性提醒供应器、审批转发器和用量观察器。
- 将现有循环抽取为共享内部驱动；保留 `run()` 的外部事件协议，并新增 `run_to_completion()`，它追加任务、消费相同事件/工具路径并返回最后文本或上限错误。
- 增加面向子 Agent 的 `DONT_ASK` 兜底；为 Engine 添加子会话克隆及永久授权宿主回调，保持黑名单和沙箱先于一切模式。
- 将 Registry 的可见性边界抽象为可包装协议，避免系统工具自动可见规则穿透子 Agent 作用域。

### TUI integration

**Responsibility:** 组装 SubAgentHost、显示转发审批、处理 ESC、消费通知，并维持主会话可交互性。

**Changes:**

- 启动时加载 AgentCatalog、创建 TaskManager 和 SubAgentHost，注册五个主 Agent 工具；关闭时取消/清理任务和子 Hook 状态。
- 主 Agent 的 prompt supplier 增加角色目录；提醒供应器在发起请求前取出 TaskManager 的一次性通知。
- 增加子任务执行与审批 UI 状态，审批块显示来源。执行期间 ESC 将当前可转交运行时后台化；审批期间 ESC 调用 `DENY_ONCE`。
- Provider 解析按 Provider 配置 `name` 查模型档案并缓存客户端；`inherit` 保持当前 Provider。

### Skill compatibility

**Responsibility:** 让现有 fork Skill 复用公共底座而不改变用户可见摘要流程。

**Changes:** 用 `SkillForkAdapter` 替换 `ForkSkillRunner` 内部直接构造 Agent 的行为。适配器以临时定义表达 Skill 的工具白名单和模型，调用 SubAgentHost 的创建与 RunToCompletion 路径，随后继续使用既有摘要器和 Slash 调用回流。

## Module Interactions

### 定义式前台调用

```text
LLM Agent tool_call
  -> AgentTool validates and resolves Definition
  -> SubAgentHost creates isolated ChildRuntime
  -> RunningChild starts RunToCompletion
  -> normal completion: ToolResult(final text)
  -> 120s timeout / TUI ESC: TaskManager adopts same run
       -> ToolResult(task ID, async status)
       -> terminal notification queued
```

### Fork 后台调用

```text
LLM Agent tool_call (no subagent_type)
  -> build legal forked messages + boilerplate
  -> TaskManager.launch
  -> ToolResult(task ID, async_launched)
  -> later terminal state -> one-shot task notification
```

### 子 Agent 权限升级

```text
Sub Agent tool_call
  -> Hook pre-check
  -> child Engine: snapshot session -> permanent -> role mode
  -> Ask -> Approval Bridge queue -> TUI approval block
  -> Outcome completes original Future
  -> tool executes or returns permission_denied
```

### 任务通知

```text
TaskManager terminal task -> notification queue
  -> main Agent starts next request -> reminder supplier drains queue
  -> Provider receives <task-notification>
  -> queue entries are not archived or rendered
```

## File Organization

```text
src/mewcode/
├── subagent/
│   ├── __init__.py              - public subagent API
│   ├── model.py                 - definitions, requests, task records
│   ├── catalog.py               - Markdown role discovery and validation
│   ├── policy.py                - capability filtering and nested denial
│   ├── cache.py                 - agent-local file read cache
│   ├── runtime.py               - ChildRuntimeFactory, Fork and host
│   ├── task.py                  - BackgroundTask lifecycle manager
│   ├── tool.py                  - Agent and Task* tools
│   └── builtin/
│       ├── general-purpose.md
│       ├── explore.md
│       └── plan.md
├── agent/__init__.py            - shared run loop and RunToCompletion
├── permission/__init__.py       - child-only mode export
├── permission/engine.py         - cloned child Engine and durable callback
├── tool/__init__.py             - registry scope protocol support
├── skill/fork.py                - compatibility adapter to SubAgentHost
├── skill/tool.py                - child-safe inline-only Skill executor
├── config.py                    - background enable flag validation
├── cli.py                       - assemble catalog and task dependencies
└── tui/
    ├── app.py                   - host lifecycle, approval and ESC bridge
    ├── stream.py                - role listing and notification supplier
    └── view.py                  - subagent approval origin rendering

tests/
├── test_subagent_catalog.py
├── test_subagent_policy.py
├── test_subagent_cache.py
├── test_subagent_runtime.py
├── test_subagent_task.py
├── test_subagent_tool.py
└── existing agent/permission/skill/tui/config regression tests

doc/12/
├── spec.md
├── plan.md
├── task.md
└── checklist.md
```

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Feature boundary | New `subagent` package | Keeps role/task execution separate from reusable Skill SOPs. |
| ReAct execution | Extend `Agent` with shared completion runner | Prevents behavior drift between parent and child tool loops. |
| Tool isolation | Scoped view of shared Registry | Shares tool instances while enforcing child-specific visibility and cache behavior. |
| Permission isolation | Child Engine session snapshot; permanent local rules shared | Allows parent pre-approval without live session-rule leakage; preserves explicit Forever semantics. |
| Approval UX | Host queue and original approval Future | Reuses TUI's proven approval choices without making child tasks conversational. |
| Background handoff | Start through transferable run handle | Timeout/ESC continue the same task rather than cancelling/restarting it. |
| Model profiles | Provider configuration names | Avoids hard-coded model IDs and supports configured providers/endpoints. |
| Notification persistence | One-shot reminder queue | Delivers results to the next model turn without history/cache pollution. |
| Nested execution | Capability removal plus restricted Skill executor | Enforces the boundary in code rather than relying on boilerplate text. |
| File cache freshness | Per-agent cache with stat validation | Gains repeated-read performance without stale cross-agent results. |
