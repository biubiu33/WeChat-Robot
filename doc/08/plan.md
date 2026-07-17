# 上下文管理与记忆系统 Plan

> 技术栈：Python 3.12+、Textual、现有 Provider 抽象与标准库。新增 `context`、`session`、`memory` 三个子包；不引入 tokenizer、数据库、向量检索或新的网络依赖。JSONL 是会话唯一持久事实来源，`Conversation` 只保存当前可发送给模型的 Prompt Context 消息。

## 架构概览

- **`mewcode.context`（新增）**：管理 Token 近似估算、工具结果落盘、自动/手动摘要和压缩熔断。它只修改内存中的 Prompt Context，并将归档引用、压缩检查点和失败状态追加到会话 JSONL；绝不删除或改写可见档案消息。
- **`mewcode.session`（新增）**：创建 `YYYYMMDD-HHMMSS-xxxx` 会话、维护 `.mewcode/sessions/<id>.jsonl` 与 `.mewcode/cache/<id>/`、串行追加 JSONL、扫描/清理/恢复会话。读取器向 TUI 提供完整可见事件，向 Context 恢复器提供最新压缩检查点和归档引用。
- **`mewcode.memory`（新增）**：启动时一次性加载三层 `MEWCODE.md`；读取和异步更新用户级/项目级 `MEMORY.md` 索引与 Markdown 笔记。项目指令在进程内不可变，记忆索引在下一次 Agent 请求前生效。
- **`Conversation`（改造）**：持有当前 Prompt Context 的 `llm.Message` 列表，新增安全的整体替换能力和追加回调。正常新增消息先写入 JSONL 再进入后续上下文处理；压缩替换不回写原始消息。
- **`Agent`（改造）**：每次 Provider 请求前调用 Context 预处理器，再以“稳定系统提示 + 隐式会话上下文 + 当前消息”组装 `Request`。标题、摘要、记忆更新均复用同一 Provider 的空工具请求；它们不会进入 Agent 工具循环。
- **`MewCodeApp`（改造）**：将 `/compact`、`/resume` 识别为本地命令；增加恢复状态和会话选择屏；在恢复时替换会话运行时、重放档案，并继续向原 JSONL 追加。

请求链：

```text
TUI 输入
  -> Conversation.add_*() -> ArchiveWriter.append_message()   # 原始可见事件
  -> Agent.run()
       -> ContextController.prepare_request()
            -> ToolArtifactStore.spill_if_needed()
            -> Compactor.compact_if_needed()
            -> ArchiveWriter.append(tool_archive / compact / compact_failure)
       -> Provider.stream(Request)
       -> Conversation.add_*()
  -> TUI 完成自然回合后异步触发 MemoryManager.update()
```

恢复链：

```text
/resume
  -> SessionRepository.cleanup_expired() + list_sessions()
  -> ResumeScreen 选择会话
  -> ArchiveReader.read()
       -> TimelineReplayer 重放所有可见事件（长档案分块加载）
       -> ContextController.restore() 读取最新检查点、归档引用、熔断状态
  -> 新 Conversation(prompt_messages) + 原 JSONL 的追加 Writer
```

## 核心数据结构

### `mewcode.session` 档案与路径

```python
@dataclass(frozen=True)
class SessionPaths:
    root: Path
    session_id: str
    archive_path: Path              # <root>/.mewcode/sessions/<id>.jsonl
    cache_dir: Path                 # <root>/.mewcode/cache/<id>/

@dataclass(frozen=True)
class ArchiveEvent:
    type: Literal[
        "message", "notice", "error", "title", "tool_archive",
        "compact", "compact_failure"
    ]
    ts: int
    data: dict[str, object]

@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    title: str
    last_active: datetime
    message_count: int
    model: str
    size_bytes: int

@dataclass(frozen=True)
class RestoredArchive:
    visible_events: list[ArchiveEvent]
    messages: list[Message]         # 完整原始模型消息，供 Context 重建
    latest_checkpoint: CompactCheckpoint | None
    artifact_refs: list[ArtifactRef]
    failed_compactions: int
```

JSONL 每行都是一个 `ArchiveEvent`。共同字段为 `type` 和 Unix 秒级 `ts`。`message` 事件保存 `role`、`content`、`tool_calls`、`tool_results`，首条用户消息额外保存 `model`；`title` 保存异步标题或回退标题；`tool_archive` 保存工具结果的消息序号、结果序号、预览、缓存相对路径和原长度；`compact` 保存正式摘要、摘要所覆盖的原始消息边界以及保留消息边界。`compact_failure` 只保存失败计数，不保存草稿或模型错误详情。

`ArchiveWriter` 使用单把 `threading.Lock` 串行化所有路径的追加操作；每次写一行后执行 `flush()` 与 `fsync()`。写入异常只记录到 stderr，绝不让消息追加、工具执行或 TUI 崩溃。`close()` 在 App 退出或切换会话时关闭句柄；再次恢复同一会话时以追加模式重新打开。

### `mewcode.context` Prompt Context

```python
@dataclass
class PromptContext:
    messages: list[Message] = field(default_factory=list)
    summary: str = ""
    retained_from: int = 0
    boundary_notice: str = ""
    staleness_notice: str = ""
    auto_failure_count: int = 0
    auto_circuit_open: bool = False

@dataclass(frozen=True)
class CompactCheckpoint:
    summary: str
    compacted_through: int           # 原始 Message 序列的排他边界
    retained_from: int

@dataclass(frozen=True)
class ArtifactRef:
    message_index: int
    result_index: int
    relative_path: str
    preview: str
    original_length: int

class ContextController:
    async def prepare_request(
        self, conv: Conversation, request_shape: RequestShape
    ) -> list[str]: ...
    async def compact_now(self, conv: Conversation, request_shape: RequestShape) -> str: ...
    def restore(self, archive: RestoredArchive) -> list[Message]: ...
    def system_context(self) -> str: ...
    def record_usage(self, input_tokens: int, request_chars: int) -> None: ...
```

`PromptContext.messages` 只含仍需原文发送给模型的消息。摘要、压缩边界提醒和超过七天的恢复提醒由 `system_context()` 以独立系统上下文提供，不伪装成用户或助手消息。最近原文保留规则为“约 10,000 Token 或至少五条消息”，从尾部回溯计算。

`TokenEstimator` 保存最近一次 Provider 实际输入 Token 与当时请求的字符量。下一次估算以该 usage 为锚，加减请求字符量的变化（按固定字符比例近似），不引入 tokenizer。估算对象包括稳定提示、隐式会话上下文、工具定义和消息；当估算超过 `context_window - reserve` 时触发压缩。Provider 的 `context_window` 未配置时为 `1_000_000`，自动触发 reserve 为 `13_000`，`/compact` 为 `3_000`。

### `mewcode.memory` 指令与笔记

```python
@dataclass(frozen=True)
class InstructionBundle:
    content: str
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class NoteOperation:
    action: Literal["create", "update"]
    level: Literal["user", "project"]
    type: Literal["user", "feedback", "project", "reference"]
    title: str
    filename: str
    content: str

class InstructionLoader:
    def load_once(self) -> InstructionBundle: ...

class MemoryManager:
    def prompt_index(self) -> str: ...
    async def update_after_turn(
        self, turn_messages: list[Message], provider: Provider
    ) -> None: ...
```

指令按项目根 `MEWCODE.md`、项目 `.mewcode/MEWCODE.md`、用户 `~/.mewcode/MEWCODE.md` 的顺序拼接。`InstructionLoader` 使用整行匹配 `@include <relative_path>`，按当前文件目录解析，使用已解析绝对路径集合检测环路，最大深度五层。路径经 `resolve()` 后必须仍在对应信任根下；缺失、越界、循环、深度超限和前 512 字节含 NUL 的文件被跳过并记录警告。它只在 CLI 启动时执行一次，结果传入 App 后不再读盘。

笔记分别位于 `~/.mewcode/memory/` 与 `<root>/.mewcode/memory/`；每条笔记是带 `type`、`title`、`created`、`updated` frontmatter 的 Markdown。各目录的 `MEMORY.md` 使用 `- [<type>] <title> — <一句话描述>` 索引行。`MemoryManager` 使用异步锁保护同一目录的读取、笔记写入与索引重写；所有文件名经 slug 校验并解析在目标目录内，拒绝路径穿越。

记忆更新提示要求模型仅返回 JSON `create`/`update` 操作，包含两级现有索引和本轮从最后一条用户消息到最终助手消息的快照。模型负责分类与去重；实现层校验分类与层级的固定映射，拒绝 `delete`、未知字段、无效 JSON 或越界文件名。任一索引达到 200 行或 25KB 时，同一次更新请求要求模型返回缩短后的索引；原始笔记文件不删除。索引注入顺序为项目级在前、用户级在后，合并后的注入量超过 25KB 时截断并附带截断标记。

## 核心接口

```python
# conversation.py
class Conversation:
    def __init__(
        self,
        messages: Sequence[Message] = (),
        on_append: Callable[[Message], None] | None = None,
    ) -> None: ...
    def replace_messages(self, messages: Sequence[Message]) -> None: ...

# session/archive.py
class ArchiveWriter:
    def append_message(self, message: Message, *, model: str = "") -> None: ...
    def append_title(self, title: str) -> None: ...
    def append_tool_archive(self, ref: ArtifactRef) -> None: ...
    def append_compact(self, checkpoint: CompactCheckpoint) -> None: ...
    def append_compact_failure(self, failures: int) -> None: ...
    def append_visible(self, type: Literal["notice", "error"], text: str) -> None: ...
    def close(self) -> None: ...

# session/repository.py
class SessionRepository:
    def new_session(self) -> SessionPaths: ...
    def list_sessions(self) -> list[SessionSummary]: ...
    def restore(self, session_id: str) -> RestoredArchive: ...
    def delete(self, session_id: str) -> bool: ...
    def cleanup_expired(self) -> list[str]: ...

# llm/generation.py
async def generate_text(
    provider: Provider, *, system: str, prompt: str
) -> str: ...

# prompt/__init__.py
def build_system_prompt(instructions: str = "", memory: str = "") -> str: ...
```

`generate_text` 仅调用 `Provider.stream()`，传入空工具定义，并汇聚文本片段；出现工具调用、Provider 错误或空的必需结果均视为失败。标题、正式摘要和自动笔记共用它，但各自拥有独立提示和失败降级，草稿不会被写入任何档案。

`System` 新增 `context: str` 动态字段。Anthropic 与 OpenAI Provider 均将它作为稳定提示之后的系统内容，保证摘要、边界提醒、时间跨度提醒不成为聊天消息，也不会与可缓存的稳定系统提示混合。

## 模块设计

### `src/mewcode/context/`

- **`budget.py`**：`TokenEstimator`、窗口阈值、最近 usage 锚定与请求字符序列化估算。没有 usage 时退化为纯字符估算。
- **`artifact.py`**：`ToolArtifactStore` 将超 16,000 字符的结果写入当前会话 cache；单条 tool 消息累积超 32,000 时按结果由大到小继续写入。产物采用受控文件名、UTF-8 文本、原子写入；写入失败保留原 Prompt 内容并返回状态通知。
- **`compact.py`**：构建九段式摘要提示，要求“先草稿、后正式摘要”，解析并验证九个标题；保留最近尾部原文，生成 `CompactCheckpoint` 与边界提醒。自动失败三次写入失败事件并打开会话熔断；手动成功压缩清零并关闭熔断。
- **`controller.py`**：编排归档后再估算/压缩，维护 `PromptContext`，恢复时应用 `tool_archive` 引用并采用最新有效检查点。它将状态通知返回给 Agent/TUI，而不直接操作组件。

### `src/mewcode/session/`

- **`paths.py`**：会话 ID 生成、目录初始化、`.gitignore` 的幂等规则写入。仅向项目 `.gitignore` 添加 `.mewcode/sessions/`、`.mewcode/cache/`、`.mewcode/memory/` 缺失行，不改写用户已有规则。
- **`archive.py`**：JSON 安全序列化/反序列化、`ArchiveWriter` 与事件模型。工具调用和结果沿用现有 `llm` 数据结构的字段，避免 Provider 专用格式进入档案。
- **`repository.py`**：扫描 JSONL 得到列表元数据、跳过坏行、解析最新标题、恢复完整消息及检查点。恢复时若末尾 assistant 工具调用没有完整结果组，则移除该 assistant 消息及其后不完整部分；无法解析新格式 ID 的旧目录不展示也不删除。`delete(session_id)` 仅接受新格式 ID，删除对应 JSONL 与同 ID cache 目录；任一删除失败返回失败且不会触及项目级或用户级 memory 目录。
- **`runtime.py`**：组合 `SessionPaths`、Writer、ContextController、Provider 配置与后台标题任务。首条用户消息追加后异步生成标题；失败立即按清理截断文本写入回退标题。切换会话时关闭旧 Writer、安装恢复后的 Writer 和 Context，不删除旧档案。

会话清理在 CLI 启动后通过后台任务执行，并在打开 `/resume` 列表前再次执行。它只删除时间戳超过 30 天的 JSONL 与同 ID 缓存目录；单项失败记录后继续，不清理长期 memory 笔记。

### `src/mewcode/memory/`

- **`instructions.py`**：三层指令与 include 展开、信任根验证、二进制检测和一次性缓存。加载故障降级为空指令并输出脱敏警告。
- **`store.py`**：读取/合并索引、frontmatter 渲染、笔记/索引原子写入、文件名和路径验证、每级目录锁。
- **`update.py`**：构建无工具的结构化记忆更新提示，调用 `generate_text`，验证 JSON 操作后交给 Store 执行。失败只记录日志且不重试。

记忆任务由 TUI 在收到 `Agent` 的“自然完成”事件后创建。`Agent.Event` 增加 `natural: bool`，仅最终模型回复没有工具调用的成功终止标为真；取消、流错误、未知工具停止和最大迭代停止不会触发记忆任务。任务只接收消息快照，可以与下一轮输入、`/compact` 并发。

### `src/mewcode/prompt/` 与 `src/mewcode/llm/`

- `build_system_prompt(instructions, memory)` 将非空内容填入已有“自定义指令”（priority 80）与“长期记忆”（priority 100）模块，保留现有排序和空模块行为。
- `llm/generation.py` 提供标题/摘要/记忆的通用无工具文本生成器。
- `llm.System` 及两种 Provider 序列化器支持动态 `context` 系统文本；现有消息、工具和提示缓存逻辑保持兼容。
- `config.ProviderConfig` 增加正整数可选 `context_window`；YAML 未配置填入 `1_000_000`，非法值按配置错误处理。

### `src/mewcode/agent/__init__.py`

`Agent` 接收可选 `ContextController` 与稳定提示内容供应器。每个迭代在创建 `Request` 前执行 `prepare_request`，把返回通知按现有 `Event(notice=...)` 送给 TUI；Provider usage 返回后回写估算器。它把 `ContextController.system_context()` 置入 `System.context`。未传入控制器时完全保留当前行为，方便旧测试与独立使用。

### `src/mewcode/tui/`

- **`resume.py`（新增）**：`ResumeScreen` 使用 `Input` + `OptionList` 展示会话标题、ID、相对时间、模型、消息数和文件大小；支持上下键、输入过滤、Enter 恢复、Esc 取消。列表项旁提供可点击删除按钮，点击后请求 Repository 删除该项 JSONL 与 cache，成功后刷新筛选结果；删除不影响 memory。
- **`replay.py`（新增）**：将 `RestoredArchive.visible_events` 映射为现有 timeline 条目，并按可见事件块分批加载。初次只挂载最新固定批次；顶部“加载更早记录”控件按需 prepend，避免超长档案一次创建全部 Widget。
- **`app.py` / `stream.py`（改造）**：增加 `RESUMING` 和 `COMPACTING` 状态；IDLE 输入路由识别 `/resume`、`/compact`。恢复过程中禁用 Agent 请求，流式/审批状态输入 `/resume` 返回等待提示。自然完成后调用 Runtime 触发记忆更新。退出时关闭 Writer、取消仅依赖当前会话的标题任务。
- **`timeline.py`（改造）**：增加清空、分块 prepend/replay 支持，保留现有自动跟随底部行为。

## 模块交互

```text
cli._run_app(root)
  ├─ InstructionLoader(root).load_once()                 # 进程内缓存
  ├─ MemoryManager(root).load_indexes()
  ├─ SessionRepository(root).ensure_layout_and_gitignore()
  ├─ create_task(SessionRepository.cleanup_expired())
  └─ MewCodeApp(..., session_repository, instructions, memory_manager)
       ├─ provider 选定 -> SessionRuntime.new(provider_config)
       ├─ 用户消息 -> Writer.message + Runtime.schedule_title_once()
       ├─ Agent.run(conv, ContextController, prompt_supplier)
       │    ├─ ContextController.prepare_request()
       │    ├─ build_system_prompt(instructions, memory.prompt_index())
       │    └─ Provider.stream(..., tools=现有工具集)
       ├─ natural done -> create_task(MemoryManager.update_after_turn(...))
       └─ /resume -> Repository.restore -> Runtime.from_archive -> TUI replay
```

摘要、标题与记忆的生成链：

```text
ContextController / SessionRuntime / MemoryManager
  └─ generate_text(provider, system, prompt)
       └─ Provider.stream(Request(tools=[], messages=[内部提示]))
            ├─ 收集文本
            └─ 任意 tool_calls / 错误 -> 调用方各自降级
```

## 文件组织

```text
mewcode/
├── src/mewcode/
│   ├── config.py                         — 改：ProviderConfig.context_window 校验
│   ├── conversation.py                   — 改：初始消息、append 回调、replace_messages
│   ├── cli.py                            — 改：初始化指令/记忆/会话生命周期
│   ├── agent/__init__.py                 — 改：请求前 Context、usage 回写、natural done
│   ├── prompt/__init__.py                — 改：接收 instructions / memory
│   ├── llm/
│   │   ├── __init__.py                   — 改：System.context
│   │   ├── generation.py                 — 新：无工具文本生成
│   │   ├── anthropic_provider.py         — 改：序列化动态系统上下文
│   │   └── openai_provider.py            — 改：序列化动态系统上下文
│   ├── context/
│   │   ├── __init__.py                   — 新：公开 ContextController / PromptContext
│   │   ├── budget.py                     — 新：近似 Token 估算
│   │   ├── artifact.py                   — 新：工具结果缓存和引用
│   │   ├── compact.py                    — 新：摘要生成、九段验证、熔断
│   │   └── controller.py                 — 新：归档/压缩编排与恢复
│   ├── session/
│   │   ├── __init__.py                   — 新：公开运行时与仓库
│   │   ├── paths.py                      — 新：ID、路径、gitignore
│   │   ├── archive.py                    — 新：JSONL 事件和 Writer
│   │   ├── repository.py                 — 新：扫描、恢复、清理
│   │   └── runtime.py                    — 新：活动会话与标题任务
│   ├── memory/
│   │   ├── __init__.py                   — 新：公开 InstructionLoader / MemoryManager
│   │   ├── instructions.py               — 新：三层指令和 include
│   │   ├── store.py                      — 新：笔记/索引读写
│   │   └── update.py                     — 新：结构化异步记忆更新
│   └── tui/
│       ├── app.py                        — 改：本地命令、状态、会话切换
│       ├── stream.py                     — 改：自然结束触发记忆
│       ├── timeline.py                   — 改：重放与分批加载
│       ├── resume.py                     — 新：恢复选择屏
│       └── replay.py                     — 新：档案到 Timeline 条目
├── tests/
│   ├── test_context_budget.py            — 新：usage 锚定、阈值、保留尾部
│   ├── test_context_artifact.py          — 新：16K/32K 归档、失败降级、恢复引用
│   ├── test_context_compact.py           — 新：九段摘要、手动/自动余量、熔断
│   ├── test_session_archive.py           — 新：JSONL、fsync 路径、标题、坏行、检查点
│   ├── test_session_repository.py        — 新：列表、恢复截断、过期/旧 ID 清理
│   ├── test_memory_instructions.py       — 新：优先级、include 深度/环路/越界/二进制/缓存
│   ├── test_memory_store.py              — 新：层级、索引限制、并发写、路径校验
│   ├── test_memory_update.py             — 新：无工具请求、JSON 操作、失败不重试
│   ├── test_tui_resume.py                — 新：命令路由、选择/过滤/取消/删除、TUI 重放
│   ├── test_agent.py                     — 改：预处理、动态系统上下文、natural event
│   ├── test_config.py                    — 改：context_window
│   ├── test_conversation.py              — 改：回调与 context replacement
│   ├── test_prompt.py                    — 改：指令/记忆模块注入
│   ├── test_llm_helpers.py               — 改：两 Provider 的 System.context
│   └── test_tui.py                       — 改：既有交互不退化
└── doc/08/
    ├── spec.md
    ├── plan.md
    ├── task.md                           — 后续阶段创建
    └── checklist.md                      — 后续阶段创建
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 会话唯一事实来源 | 追加式 JSONL，包含消息、标题、归档、压缩事件 | 不维护 meta/context 快照，避免双写同步问题 |
| JSONL 布局 | `.mewcode/sessions/<id>.jsonl`，缓存独立在 `.mewcode/cache/<id>/` | 遵循已确认目录职责；清理一个会话时可精确移除缓存 |
| 压缩持久化 | 保留完整消息，加 `compact` 检查点，不重写或截去旧 JSONL | TUI 可永远重放原始历史，Prompt Context 仍可高效恢复 |
| 隐式上下文表示 | 扩展 `System.context`，不构造成 `Message(role=user/assistant)` | 满足 TUI/Prompt 分离，兼容两种 Provider |
| Token 计数 | usage 锚定 + 请求字符增量近似 | 满足精度需求且不增加 tokenizer 依赖 |
| 摘要输出 | 固定九段正式摘要，草稿只在单次 LLM 响应中消费 | 保留用户原话与工作进度，避免草稿污染档案 |
| 工具大结果 | 原 JSONL 留完整结果；cache 留可读取产物；Prompt 留预览/路径 | 同时满足 TUI 追溯、模型窗口和文件再读取 |
| 标题持久化 | 标题与回退标题都写 JSONL `title` 事件 | 会话列表无需 meta，恢复后可一致展示 |
| 自动记忆触发 | 每次自然完成的 Agent Loop 异步触发 | 遵循已确认规则，不延迟下一轮输入 |
| 自动记忆动作 | 仅 create/update；索引可重写，原笔记不删除 | 保证“索引压缩不删原始笔记” |
| 指令刷新 | 进程启动加载一次并缓存 | 同进程规则一致；不实现热更新 |
| `/resume` UI | Modal `Input` + `OptionList`，状态机互斥 | 复用 Textual 能力，支持 Claude Code 式键盘筛选 |
| 手动删除会话 | 仅删除选中 JSONL 与同 ID cache，成功后刷新列表 | 满足用户主动清理需求，长期记忆不绑定单个会话，必须保留 |
| 过期清理 | 启动后台执行且 `/resume` 前补做；只清会话 JSONL 与匹配 cache | 不阻塞启动，不误删长期记忆或旧格式会话 |
| Provider 兼容 | ContextController、提示供应器均为可选注入 | 既有 Agent/TUI/Provider/MCP 单测可保持原行为 |
