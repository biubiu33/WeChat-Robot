# 系统提示工程化 Plan

> 技术栈：Python 3.12+；`anthropic`（`AsyncAnthropic`）、`openai`（`AsyncOpenAI`）。SDK 缓存 API 行为以官方文档为准（见技术决策表）。

## 架构概览

ch05 在三层叠加，**不改 ch04 的 Agent Loop 控制流**：

- **prompt 包（重写）**：从「单个常量字符串」升级为「模块化装配 + 环境采集 + 补充消息构造」。对外产出三类文本——**稳定系统提示**（可缓存）、**环境信息段**（不缓存）、**system-reminder 包裹的补充指令**。prompt 包不依赖 llm 包（避免循环依赖）。
- **llm 包（改造）**：`Provider.stream` 入参从位置参数改为 `Request` dataclass，承载 `messages / tools / system{stable, environment} / reminder`。Anthropic 把 stable 块打缓存断点、env 块不打；OpenAI 把 stable 置于系统消息前缀。`Usage` 增加缓存写/读字段。两 provider 把 `reminder` 按各自协议安全地织入消息通道（N3）。
- **agent 包（改造）**：每次 `run` 开始采集环境、装配稳定系统提示；每轮迭代按 `mode + iter` 计算本轮 reminder（规划模式按轮次详略），组装 `Request` 发起请求；把缓存用量透传到 `Event.usage`。
- **smoke（改造）**：打印每轮用量的缓存写/读字段，作为缓存策略生效的验证手段（TUI 状态栏不变）。

数据流：`agent.run` → `prompt.build_system_prompt()`（稳定） + `prompt.gather_environment().render()`（环境） + `prompt.plan_reminder(full)`（本轮补充） → 组装 `llm.Request` → `provider.stream` → Anthropic/OpenAI 各自装配缓存通道与消息通道 → 流式事件回到 agent → `Event(usage=Usage(..., cache_write, cache_read))` → smoke 打印。

## 核心数据结构

### `prompt.Module`（新增）
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Module:
    name: str       # 模块标识（身份、系统约束 …），仅用于可读性与测试断言
    priority: int   # 数值越小优先级越高、排越前；固定模块 10..70，可选模块 80..100
    content: str    # 模块正文；为空则装配时跳过（可选空槽）
```

### `prompt.Environment`（新增）
```python
import os, runtime, time  # 实际用 os / platform / datetime
from dataclasses import dataclass

@dataclass
class Environment:
    working_dir: str   # os.getcwd()
    platform: str      # sys.platform 或 platform.system().lower()
    date: str          # datetime.date.today().isoformat()
    git_status: str    # `git status --porcelain` 摘要；非 git 目录/取不到则留空
    version: str       # 应用版本（从 agent 透传）
    model: str         # provider.model
```

### `llm.System`（新增）
```python
from dataclasses import dataclass

@dataclass
class System:
    stable: str = ""       # 可缓存：装配好的稳定系统提示（工具定义随 tools 一并进缓存前缀）
    environment: str = ""  # 不缓存：环境信息段
```

### `llm.Request`（新增，替换 stream 位置参数）
```python
from dataclasses import dataclass, field

@dataclass
class Request:
    messages: list[Message] = field(default_factory=list)        # 持久对话历史（不含本轮 reminder）
    tools: list[ToolDefinition] = field(default_factory=list)    # 本轮工具集（普通=全量 / 规划=只读）
    system: System = field(default_factory=System)               # 稳定系统提示 + 环境段
    reminder: str = ""                                           # 本轮 system-reminder 内容（已含标签；空=不注入）
```

### `llm.Usage`（扩展）
```python
@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0   # Anthropic: cache_creation_input_tokens；OpenAI: 恒 0（自动缓存无写计数）
    cache_read: int = 0    # Anthropic: cache_read_input_tokens；OpenAI: prompt_tokens_details.cached_tokens
```

### `agent.Usage`（扩展，对外事件）
```python
@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0    # 透传自 llm.Usage，供 smoke 打印
```

## 核心接口

### prompt 包
```python
def fixed_modules() -> list[Module]: ...                  # 七个固定模块（身份…文本输出），内容内置
def optional_modules() -> list[Module]: ...               # 三个可选空槽（自定义指令/已激活 Skill/长期记忆），content=""
def assemble_system(mods: list[Module]) -> str: ...       # 按 priority 升序、跳过空 content、以 "\n\n" 连接
def build_system_prompt() -> str: ...                     # = assemble_system(fixed_modules() + optional_modules())
def gather_environment(version: str, model: str) -> Environment: ...  # 采集环境；git/date 失败降级留空
class Environment:
    def render(self) -> str: ...                          # 渲染为「环境信息」第二段文本
def system_reminder(body: str) -> str: ...                # 用 <system-reminder>…</system-reminder> 包裹 body
def plan_reminder(full: bool) -> str: ...                 # 返回包好标签的规划模式提醒（full=完整 / 否=精简）
```

### `llm.Provider`（签名变更）
```python
from typing import Protocol, AsyncIterator

class Provider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def model(self) -> str: ...
    def stream(self, req: Request) -> AsyncIterator[StreamEvent]: ...  # 由 Request 承载全部入参
```

## 模块设计

### prompt 包
**职责：** 模块化装配稳定系统提示；采集并渲染环境信息；构造 system-reminder 与规划模式提醒。
**对外接口：** 见上。
**关键点：**
- 七个固定模块按优先级排：**身份(10) → 系统约束(20) → 任务模式(30) → 动作执行(40) → 工具使用(50) → 语气风格(60) → 文本输出(70)**；可选空槽：**自定义指令(80) → 已激活 Skill(90) → 长期记忆(100)**（`content=""` 跳过）。
- **F5 双重强化**写在「工具使用(50)」模块：明确「优先用专用工具（`read_file`/`glob`/`grep`）而非用 bash 拼凑」「编辑文件前必须先 `read_file` 读取」；同时同义强化到 `edit_file`、`bash` 工具描述（见 tool 包改动）。
- `assemble_system` 只用常量内容 → 跨轮逐字节一致（**N1**）；环境与时间相关内容只进 `Environment`，绝不进稳定模块。
- `gather_environment`：git 状态用一条 `git status --porcelain` 带短超时执行（`asyncio.create_subprocess_exec` 或 `subprocess.run(timeout=2)`），失败/非 git 目录则 `git_status=""`；不读取任何环境变量（**N5**）。
**依赖：** 标准库（`os`/`sys`/`platform`/`datetime`/`asyncio`/`subprocess`）；不依赖 llm。

### llm 包（`__init__.py` / `anthropic_provider.py` / `openai_provider.py`）
**职责：** 把 `Request` 装配为各协议请求，分离缓存通道与消息通道，解析缓存用量，安全织入 reminder。
**对外接口：** `stream(req: Request) -> AsyncIterator[StreamEvent]`。
**关键点：**
- 删除原 `_effective_system` 辅助函数与对 `mewcode.prompt` 的 import（系统提示改由 agent 传入）。
- **Anthropic**：构造 `system` 入参为 `list[dict]`：`req.system.stable` 非空 → `{"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}}`（断点，默认 5m TTL）；`req.system.environment` 非空 → `{"type": "text", "text": environment}`（无 `cache_control`）。请求顺序 tools→system→messages，断点打在稳定块 → **缓存前缀 = 全部工具 + 稳定块**；env 与历史在断点后不缓存，env 每轮变化不影响前缀命中。`usage.cache_write = response.usage.cache_creation_input_tokens`、`cache_read = response.usage.cache_read_input_tokens`。
  - reminder 织入：`req.reminder` 非空时，把一个文本块 `{"type": "text", "text": reminder}` **追加到最后一条消息的 content 块**（循环中最后一条恒为 user 或 tool_result→user，追加文本块仍是合法 user 消息，保 N3 角色交替）；极端情形（末尾为 assistant）则新起一条 user 消息。
- **OpenAI**：系统消息 = `req.system.stable`（若 `environment` 非空则拼为 `stable + "\n\n" + environment` 单条 system 消息——兼容端点对多条 system 消息支持不一，统一单条）；stable 居前缀 → 端点前缀缓存命中稳定部分。`usage.cache_read = response.usage.prompt_tokens_details.cached_tokens`、`cache_write = 0`。
  - reminder 织入：`req.reminder` 非空时**追加一条尾部 user 消息**（OpenAI 容忍连续 user / tool 后接 user）。
- **N6**：缓存字段缺失即零值（`getattr(..., None) or 0`），不额外校验、不抛异常。

### agent 包（`agent.py`）
**职责：** 采集环境、装配系统提示、按轮次构造 reminder、组装 Request、透传缓存用量。
**关键点：**
- `Agent.__init__(provider, registry, version: str)` 增加 `version` 字段（供环境段）；`model` 取 `provider.model`。
- `run` 起始：`env = prompt.gather_environment(self._version, self._provider.model)`、`sys = prompt.build_system_prompt()`（稳定，普通/规划模式一致——规划提醒已移出系统通道）。
- 每轮迭代计算 reminder：`mode == PlanMode.PLAN` → `prompt.plan_reminder(full)`，`full = (iter == 1 or (iter - 1) % PLAN_REMINDER_INTERVAL == 0)`；否则 `""`。`PLAN_REMINDER_INTERVAL = 4`（内置常量）。
- `_stream_once` 组装 `llm.Request(messages=conv.messages(), tools=defs, system=llm.System(stable=sys, environment=env.render()), reminder=reminder)` 调 `provider.stream`。
- 删除 `suffix` / `READ_ONLY_DEFINITIONS` 的「系统后缀」用法；**只读工具集仍按 mode 选择**（规划=`READ_ONLY_DEFINITIONS`），原 `PLAN_MODE_REMINDER` 常量从系统后缀迁移为 `prompt.plan_reminder` 的内容。
- 缓存用量透传：`Event(usage=Usage(input, output, cache_write, cache_read))`。

### smoke（`src/mewcode/smoke.py` 或 `examples/smoke.py`）
**职责：** 端到端验证缓存生效。
**关键点：** 消费 `Event.usage` 时打印 `input/output/cache_write/cache_read`；跑两轮（或多轮）观察次轮 `cache_read > 0`。`Agent(provider, registry, version="dev")`。

### tool 包（描述微调，F5）
- `edit_file.DESCRIPTION`：补「编辑前请先用 `read_file` 读取目标文件，确认 `old_string` 唯一」。
- `bash.DESCRIPTION`：补「读文件/找文件/搜内容请优先用 `read_file`/`glob`/`grep`，不要用 bash 拼凑」。
- 仅改描述文本，不改行为、不改 schema（N2）。

## 模块交互

```
TUI/smoke ─run(ctx, conv, mode)→ agent
  agent.run:
    env  = prompt.gather_environment(version, provider.model)
    sys  = prompt.build_system_prompt()
    for iter:
      reminder = prompt.plan_reminder(full(iter)) if mode == PLAN else ""
      req = llm.Request(messages=conv.messages(),
                        tools=defs(mode),
                        system=llm.System(stable=sys, environment=env.render()),
                        reminder=reminder)
      async for ev in provider.stream(req):
          # StreamEvent: text / tool_calls / usage(+cache) / done / err
          ...
    Event(usage=Usage(..., cache_write, cache_read)) ──→ smoke 打印 / TUI 状态栏（忽略 cache 字段）
```

依赖方向（无环）：`agent → {prompt, llm, conversation, tool}`；`llm → config`（不再 import prompt）；`prompt → 标准库`。

## 文件组织

```
mewcode/
├── src/mewcode/prompt/
│   ├── __init__.py        — 改：导出 Module/装配/build_system_prompt；保留 banner（CAT_BANNER/render_banner/READY_HINT）
│   ├── modules.py         — 新：fixed_modules()/optional_modules() 七固定+三空槽的内容常量
│   ├── environment.py     — 新：Environment / gather_environment / Environment.render
│   └── reminder.py        — 新：system_reminder / plan_reminder（完整版/精简版常量）/ EXECUTE_DIRECTIVE
├── src/mewcode/llm/
│   ├── __init__.py        — 改:Request/System dataclass；Usage 加缓存字段；Provider.stream 签名；删 _effective_system
│   ├── anthropic_provider.py — 改：两块 system（断点+env）、缓存用量解析、reminder 织入
│   └── openai_provider.py    — 改：单条 system（stable+env）、cached_tokens 解析、reminder 尾部注入
├── src/mewcode/agent/
│   └── agent.py           — 改：__init__(+version)、run 采集环境/装配系统、按轮次 reminder、缓存透传
├── src/mewcode/tool/
│   ├── edit_file.py       — 改：DESCRIPTION 补强化
│   └── bash.py            — 改：DESCRIPTION 补强化
├── src/mewcode/tui/
│   └── stream.py          — 改：Agent(...) 传 version（m.version 已有）
├── examples/smoke.py      — 改：打印缓存用量；Agent(p, registry, "dev")
└── tests/
    ├── test_prompt.py     — 新：装配顺序/跳空槽/N1 确定性/双重强化文本断言
    ├── test_anthropic_system.py — 新：序列化稳定块带 cache_control、环境块不带（守护回归）
    └── test_agent.py      — 改：断言 Request 装配（system 两段、规划按轮次 reminder）、缓存用量透传
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 系统提示组织 | 模块化（`Module(name, priority, content)` + `assemble_system`） | 满足 F1「挂载即扩展」；优先级排序使顺序确定（N1） |
| 环境信息归属 | system 通道独立第二块（用户拍板） | 结构上接系统提示之后；物理上与稳定块分离，不进缓存 |
| Anthropic 缓存断点 | 仅在稳定 system 块打 `cache_control: ephemeral`（默认 5m） | 请求序 tools→system→messages，断点在稳定块即缓存「工具+稳定块」整段前缀；env 在其后不缓存，env 变化不冲前缀命中 |
| 工具是否单独打断点 | 否 | 稳定块断点的前缀已含全部工具，无需再给 tool 单独标 cache_control |
| OpenAI 环境信息 | 拼入单条 system 消息（stable 在前） | 兼容端点对多条 system 支持不一；stable 居前缀，端点前缀缓存自动命中稳定部分。代价：env 居 system 尾，OpenAI 工具可能不进缓存前缀——本章 OpenAI 缓存为尽力而为、不强制（F8） |
| 缓存用量字段 | `Usage` 加 `cache_write` / `cache_read` | Anthropic 取 `cache_creation_input_tokens`/`cache_read_input_tokens`；OpenAI 取 `prompt_tokens_details.cached_tokens` |
| stream 入参 | 改 `Request` dataclass | 入参从 4 个增至含 `system`/`reminder`，dataclass 更清晰、后续扩展不再改签名（N8） |
| reminder 注入位置 | Anthropic 并入末条 user 消息 content 块；OpenAI 追加尾部 user 消息 | Anthropic 严格角色交替——并入避免连续 user 触发 400（N3）；OpenAI 容忍连续 user |
| reminder 持久化 | 不写入 conversation（用户拍板） | 每轮动态构造；不污染缓存、不破坏历史可恢复性 |
| 规划提醒节奏 | `iter == 1` 或 `(iter - 1) % 4 == 0` → 完整，否则精简（per `run` 内 iter） | 实现 F7「首轮完整、间隔重复、其余精简」；复用已有 iter 计数 |
| 缓存验证呈现 | smoke/调试打印（用户拍板） | 不动 TUI 状态栏；`Usage` 携带字段供打印 |
| prompt↔llm 依赖 | 系统提示由 agent 传入，llm 不再 import prompt | 打破潜在循环依赖；职责更清晰 |
| 子进程外调 git | `asyncio.create_subprocess_exec("git", "status", "--porcelain")` + `asyncio.wait_for(..., timeout=2.0)`；同步路径回退 `subprocess.run(timeout=2)` | 不阻塞 event loop（N4）；超时/失败均降级为空字符串 |
