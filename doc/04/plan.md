# Agent Loop Plan

> 基于已批准的 spec.md。本文档与语言相关（Python 3.12+）。SDK 类型已对 `anthropic`（AsyncAnthropic）、`openai`（AsyncOpenAI）的官方 Python SDK 核对。

## 架构概览

ch04 不新增包，在 ch03「tool / agent / llm / conversation / prompt / tui」之上**扩展**：

- **`mewcode.agent`（重写 run）**：把 ch03 的「请求#1 → 执行 → 请求#2 → 停」改为真正的 ReAct 循环——`for` 迭代直到自然完成 / 上限 / 取消 / 连续未知工具 / 出错。新增保序分批并发执行、迭代进度与用量事件、终止时的历史一致性收尾、Plan/Normal 两种模式。
- **`mewcode.llm`（扩展）**：`StreamEvent` 增 `usage` 字段；`Provider.stream` 增 `system_suffix: str` 形参（Plan Mode 系统提示后缀）；两适配器在流结束后上抛本轮 token 用量、把 `system_suffix` 拼到内置系统提示后；OpenAI 打开 `stream_options={"include_usage": True}`。
- **`mewcode.tool`（扩展）**：`Tool` Protocol 增 `read_only: bool` 属性；6 个工具各实现；`Registry` 增 `read_only_definitions()` 与 `is_read_only(name)`。
- **`mewcode.conversation`（扩展）**：增 `last_role()`（终止收尾判断角色尾巴）。
- **`mewcode.prompt`（扩展）**：增 `PLAN_MODE_REMINDER`（计划态系统后缀）与 `EXECUTE_DIRECTIVE`（`/do` 触发执行的用户消息）；`SYSTEM_PROMPT` 增补「持续工作直到任务完成」的 Agent 循环约定。
- **`mewcode.tui`（扩展）**：`submit` 识别 `/plan`、`/do`；引入 per-turn 取消事件；事件泵处理用量 / 进度 / 通知 / 多个并发工具；按键处理拆分 Esc / Ctrl+C；状态栏显示模式与累计用量、动态区显示迭代轮次。

依赖方向不变、无环：`tool → llm`；`conversation → llm`；`agent → {llm, tool, conversation}`；`tui → {agent, tool, conversation, llm, prompt}`；`llm → {config, prompt}`。

## 核心数据结构

### `mewcode.llm`（扩展）

```python
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Protocol

# Usage 协议无关地承载一轮请求的 token 用量。
@dataclass
class Usage:
    input_tokens: int = 0   # 本轮请求输入（含完整历史）token 数
    output_tokens: int = 0  # 本轮响应输出 token 数

# StreamEvent 扩展：在 text / tool_calls / done / err 之外，turn 结束时一次性上抛 usage。
@dataclass
class StreamEvent:
    text: str = ""
    tool_calls: list["ToolCall"] | None = None
    usage: Usage | None = None       # 非空：本轮 token 用量（done 之前一次性发出）
    done: bool = False
    err: Exception | None = None

class Provider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def model(self) -> str: ...
    # system_suffix 非空时拼接到内置 SYSTEM_PROMPT 之后（Plan Mode 计划态约束）；
    # 为空即普通模式。
    def stream(
        self,
        msgs: list["Message"],
        tools: list["ToolDefinition"],
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]: ...
```

`Message`/`ToolCall`/`ToolResult`/`ToolDefinition` 与 role 常量沿用 ch03，不变。

### `mewcode.tool`（接口扩展）

```python
# Tool Protocol 新增 read_only：True=只读工具（可并发执行 & Plan Mode 放行）。
class Tool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict[str, object]: ...
    @property
    def read_only(self) -> bool: ...   # 新增
    async def execute(self, args: dict[str, object]) -> "ToolResult": ...
```

只读分类（依据语义）：`read_file` / `glob` / `grep` → `True`；`write_file` / `edit_file` / `bash` → `False`（`bash` 可执行任意副作用命令，保守归为有副作用、串行执行）。

`Registry` 新增：

```python
def read_only_definitions(self) -> list[ToolDefinition]:
    """Plan Mode：只导出 read_only==True 的工具定义，保留注册顺序。"""

def is_read_only(self, name: str) -> bool:
    """分批判定；未知工具返回 False（按串行处理）。"""
```

### `mewcode.agent`（事件模型扩展 + run 重写）

```python
from dataclasses import dataclass
from enum import IntEnum
from typing import AsyncIterator

# Usage 一轮请求的 token 用量（透传 llm.Usage 的语义）。
@dataclass
class Usage:
    input: int = 0
    output: int = 0

# Event 对外事件流元素，消费者据非默认字段分派渲染。
@dataclass
class Event:
    text: str = ""                # 模型文本增量（preamble 或最终答复）
    tool: "ToolEvent | None" = None   # 工具调用开始/结束（沿用 ch03）
    usage: Usage | None = None    # 本轮 token 用量（每轮 stream 结束后一次）
    iter: int = 0                 # >0：进入第 iter 轮迭代（进度提示）
    notice: str = ""              # 系统提示（停止原因等），仅用于 UI 展示，不入对话历史
    done: bool = False            # 本轮（整个 Loop）结束
    err: Exception | None = None  # 出错（不中断会话）

# Mode 区分普通模式与计划模式。
class Mode(IntEnum):
    NORMAL = 0
    PLAN = 1

class Agent:
    def __init__(self, provider: "Provider", registry: "Registry") -> None: ...
    # run 执行 Agent Loop，返回事件 async generator；mode 决定工具集与系统后缀。
    def run(
        self,
        conv: "Conversation",
        mode: Mode,
        cancel: "asyncio.Event",
    ) -> AsyncIterator[Event]: ...
```

`ToolEvent`、`Phase`（`PHASE_START` / `PHASE_END`）、`Agent`、构造器沿用 ch03。`run` 签名新增 `mode` 与 `cancel` 形参。

> `cancel` 替代 Go 版 `context.WithCancel`：调用方持有 `asyncio.Event`，触发 `cancel.set()` 即中断本轮；`Agent` 把该事件穿透给 streamOnce 与工具执行点。

`Agent.__init__` 沿用 ch03：注入 `provider` 与 `registry`。`mode` 为 `run` 的每次调用入参，不写入 `Agent` 状态（同一 `Agent` 可被不同 mode 复用）。

迭代、停止常量与提示文案（内置，不可配）：

```python
MAX_ITERATIONS: int = 25   # 迭代上限兜底（F2）
MAX_UNKNOWN_RUN: int = 3   # 连续「整轮只产生未知工具调用」的迭代数上限（F2）

# 停止/收尾提示文案——既作为 Event(notice=...) 推给 UI，也作为 ensure_assistant_tail 写入历史的兜底文本。
NOTICE_MAX_ITER       = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS  = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR     = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED      = "（已取消。）"
```

## 模块设计

### `mewcode.agent`（核心：run 重写）

**职责：** ReAct 循环编排（F1/F2）、保序分批并发执行（F5）、事件流（F3/F8/F9）、终止历史一致性（F6）、Plan/Normal 模式（F10）。
**对外接口：** `Agent`、`Agent.run(conv, mode, cancel)`、`Event`、`ToolEvent`、`Phase`、`Mode`、`Usage`。
**依赖：** `llm`、`tool`、`conversation`、`asyncio`（并发批 `asyncio.gather`）。

**run 算法（async generator）：**

1. 按 `mode` 取工具集与系统后缀：
   - `Mode.PLAN` → `defs = registry.read_only_definitions()`、`suffix = prompt.PLAN_MODE_REMINDER`。
   - `Mode.NORMAL` → `defs = registry.definitions()`、`suffix = ""`。
2. `unknown_run = 0`。
3. `for it in range(1, MAX_ITERATIONS + 1):`
   1. `yield Event(iter=it)`（进度，F9）；若 `cancel.is_set()` → `finish_cancelled(conv)`；return。
   2. `text, calls, usage, ok = await stream_once(conv, defs, suffix, cancel, push)`。
      - `not ok` 且 `cancel.is_set()`（取消）→ `finish_cancelled(conv)`、return。
      - `not ok` 且 `not cancel.is_set()`（流出错，err 已在 stream_once 内 yield）→ `ensure_assistant_tail(conv, NOTICE_STREAM_ERR)`、return。
   3. `if usage is not None: yield Event(usage=Usage(usage.input_tokens, usage.output_tokens))`（F8）。
   4. **无工具** `not calls`：`conv.add_assistant(ensure_final(text))`；`yield Event(done=True)`；return（自然完成，F2-1）。
   5. **有工具**：`conv.add_assistant_with_tool_calls(text, calls)`。
   6. 统计未知工具：`unknown_run = unknown_run + 1 if all_unknown(calls) else 0`。
   7. `results, completed = await execute_batched(calls, cancel, push)`（保序分批并发，F5）。
   8. `conv.add_tool_results(results)`（无论是否取消都回灌，含已取消占位，F6）。
   9. `if not completed`（执行中被取消）→ `ensure_assistant_tail(conv, "（已取消）")`、return。
   10. `if unknown_run >= MAX_UNKNOWN_RUN` → `yield Event(notice=NOTICE_UNKNOWN_TOOLS)`；`ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)`；`yield Event(done=True)`；return（F2-4）。
4. 循环正常走完（触达上限）：`yield Event(notice=NOTICE_MAX_ITER)`；`ensure_assistant_tail(conv, NOTICE_MAX_ITER)`；`yield Event(done=True)`（F2-2）。

> 实际实现里 `yield` 直接由 `run` 自己完成，`stream_once` / `execute_batched` 通过把 `push: Callable[[Event], Awaitable[None]]` 注入实现「子流程往同一个 generator 推事件」的效果——Python 等价于 Go 版的 channel emit。最简洁的写法是把 `stream_once` / `execute_batched` 都改为 async generator，再用 `async for` 转发。

**stream_once(conv, defs, suffix, cancel) → (text, calls, usage, ok)：**
`async for ev in provider.stream(conv.messages(), defs, suffix):`
- `ev.err is not None` → `yield Event(err=ev.err)`、`return "", [], None, False`。
- `ev.usage is not None` → 记录 `usage = ev.usage`（不立即 yield，由 run 在拿到后统一 yield）。
- `ev.tool_calls` → `calls.extend(ev.tool_calls)`。
- `ev.text` → 累积 `text` 并 `yield Event(text=ev.text)`。
- 每次循环前后判 `cancel.is_set()`：True 即 `return "", [], None, False`。

循环后 `if cancel.is_set(): return "", [], None, False`；否则 `return text, calls, usage, True`。

**execute_batched(calls, cancel) → (results, completed)：**
保序分批（F5）。`results = [None] * len(calls)`；从 `i=0` 逐段扫描：

- 当前 `calls[i]` 只读 → 向前吃连续只读得最长区间 `[i, j)`（`j` 为首个非只读或末尾），**并发**执行该批：用 `asyncio.gather(*[run_one(k) for k in range(i, j)])`；`run_one(k)` 内 `try: result = await asyncio.wait_for(registry.execute(call.name, call.args), tool.DEFAULT_TIMEOUT)`（超时回灌结构化结果），把结果写入**自己下标** `results[k]`（互不重叠，单线程模型下无需锁）。`i = j`。
- 当前 `calls[i]` 非只读 → **串行**执行单个 `calls[i]`（同样 `asyncio.wait_for(..., tool.DEFAULT_TIMEOUT)`），写 `results[i]`。`i += 1`。
- 每段开始执行前先判 `cancel.is_set()`（取消）：给区间内尚未执行的 call 填「已取消」结果（`ToolResult(is_error=True, content=NOTICE_CANCELLED)`），其余沿用已得结果，`return results, False`。
- 全部完成 `return results, True`。

> 超时口径：每个工具各拿一个 `DEFAULT_TIMEOUT`（30s）`wait_for` 包装，互不相加——并发批的整体上限仍是单个 30s（N1）。`cancel` 在每个等待点被监听（通过 `asyncio.wait` 的多路等待或工具内自行 `cancel.is_set()` 早退），用户取消时尽快返回。

事件与顺序（满足 N3 顺序、N2 不阻塞、N6 无竞争）：
- 单个串行工具：`yield Event(tool=ToolEvent(PHASE_START, ...))` → 执行 → `yield Event(tool=ToolEvent(PHASE_END, ...))`（沿用 ch03 时序，动态区显示该工具 Running）。
- 并发批：**先**按序 `yield` 区间内每个工具的 PHASE_START（动态区列出多个在执行的工具行）→ 并发执行 → **再**按原始顺序 `yield` 每个工具的 PHASE_END（逐个把工具行 + 结果摘要提交 scrollback）。即「开始事件按序、结束事件按序」，并发只发生在执行环节，事件顺序始终是调用序，scrollback 不交错。
- 并发安全：asyncio 单线程模型下，`await` 切换点是唯一的并发边界；每个并发 task 只写自己下标的 `results[k]`（不同下标互不重叠），不触碰 `conv`；`conv.add_tool_results` 由 run 主流程在 `gather` 汇合后串行调用。Token 用量累计在 TUI 侧串行处理。

**辅助函数：**
- `all_unknown(calls)`：对每个 call 用 `registry.get(call.name)` 判断，**全部** `None` 才返回 True；任一已注册即 False（混入已知工具视为有进展，计数重置）。不能用 `is_read_only`（未知工具它也返回 False，会与有副作用工具混淆）。
- `ensure_final(text)`：沿用 ch03——`text` 非空原样返回；为空则 yield 占位提示并返回占位文本（避免空 assistant 回合破坏下一轮请求）。
- `ensure_assistant_tail(conv, fallback)`：若 `conv.last_role() != "assistant"`（含空历史、末尾为 user 或 tool 角色），`conv.add_assistant(fallback)`，保证历史以 assistant 文本回合收尾（F6：取消/出错/上限后角色仍交替，下一轮请求不报 400）。
- `finish_cancelled(conv)`：取消路径统一收尾——`ensure_assistant_tail(conv, NOTICE_CANCELLED)`、return（**不 yield notice**，因 cancel 已被消费方感知；generator 终结即视为本轮结束）。

> 终止优先级：执行中取消（`completed is False`）是**最高优先级**终止——立即 `ensure_assistant_tail` 并 return，**跳过**未知工具计数与迭代上限检查。

### `mewcode.llm`（扩展）

**职责：** 协议无关请求/响应 + 两协议工具调用全流程（沿用 ch03）+ 本轮用量上抛（F8）+ 系统后缀（F10）。

**`__init__.py`：** 新增 `Usage` 类型；`StreamEvent` 增 `usage: Usage | None`；`Provider.stream` 增 `system_suffix: str = ""` 形参（更新接口文档）。

**`anthropic_provider.py`：**
- 系统提示：`params["system"]` 由硬编码 `prompt.SYSTEM_PROMPT` 改为 `_effective_system(suffix)`——`suffix == ""` 时单段 `SYSTEM_PROMPT`；非空时拼成 `SYSTEM_PROMPT + "\n\n" + suffix`（保持单段字符串，避免多块边界差异）。
- 用量：流正常结束（`async with client.messages.stream(...)` 上下文退出且未异常）后，在 `yield StreamEvent(done=True)` 之前先 `yield StreamEvent(usage=Usage(input_tokens=final.usage.input_tokens, output_tokens=final.usage.output_tokens))`——`final = await stream.get_final_message()` 或直接读流上下文的 `usage` 累加器（SDK 在流结束后聚合可用）。
- 历史含工具交互时 thinking 已自动关闭（ch03 既有逻辑），多轮续答沿用，无需改动。

**`openai_provider.py`：**
- 请求构造增 `stream_options={"include_usage": True}`（不开则流式 usage 块为空）。
- 系统提示：`_to_openai_messages` 接收 `suffix`，把首条 system 消息文本由 `SYSTEM_PROMPT` 改为拼接 `suffix`（非空时 `+ "\n\n" + suffix`）。
- 用量：流末尾会出现一个 `choices == []` 但带 `chunk.usage` 的 chunk（启用 `include_usage` 后由 SDK 透传），读 `chunk.usage.prompt_tokens` / `chunk.usage.completion_tokens` → `yield StreamEvent(usage=Usage(...))`。

### `mewcode.tool`（扩展）

- `Tool` Protocol 加 `read_only: bool` 属性；6 个工具各加一行实现（read/glob/grep 返回 True，write/edit/bash 返回 False）。
- `Registry.read_only_definitions()`：仿 `definitions()`，仅收 `tools[name].read_only is True` 的项，保持注册顺序。
- `Registry.is_read_only(name)`：`t = self.get(name); return t is not None and t.read_only`（未知工具 False）。
- `execute`、`DEFAULT_TIMEOUT`、6 工具的执行逻辑均不变。

### `mewcode.conversation`（扩展）

```python
def last_role(self) -> str:
    """返回最后一条消息的 role；空历史返回 ""。"""
    return self._messages[-1].role if self._messages else ""
```

其余沿用 ch03。

### `mewcode.prompt`（扩展）

```python
# PLAN_MODE_REMINDER：Plan Mode 系统提示后缀，拼接到 SYSTEM_PROMPT 之后。
PLAN_MODE_REMINDER = (
    "You are currently in PLAN MODE. You may use ONLY the read-only tools "
    "(read_file, glob, grep) to investigate the codebase. You must NOT write files, "
    "edit files, or run shell commands. Produce a clear, step-by-step plan for the task, "
    "then stop and wait for the user to approve it with /do before doing any work."
)

# EXECUTE_DIRECTIVE：/do 注入的用户消息——指示模型按上文已确认的计划开始执行，可使用全部工具。
EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"
```

`SYSTEM_PROMPT` 增补一句 Agent 循环约定（追加到现有文案）：`"Keep using tools across multiple steps to make progress, and only give your final concise answer once the task is complete."`（中文项目里保持英文 system prompt 风格，与 ch03 现有 `SYSTEM_PROMPT` 一致）。

### `mewcode.tui`（扩展）

**`MewCodeApp` 新增字段（`tui/app.py`）：**
- `mode: agent.Mode`——当前模式（默认 `Mode.NORMAL`），`/plan`、`/do` 切换，跨轮保持。
- `iter: int`——当前迭代轮次（进度显示），每轮 `iter` 事件更新，`finish_turn` 归零。
- `usage_in: int`、`usage_out: int`——会话累计 token 用量，每个 `usage` 事件累加。
- `cur_tools: list[ToolDisplay]`——替换 ch03 的单个 `cur_tool`，支持并发批多个在执行的工具行。
- `turn_cancel: asyncio.Event | None`——本轮取消事件，Esc / Ctrl+C 触发 `set()`；程序级退出仍由 `App.exit()`。

**`submit`（`tui/stream.py`）：**
1. `/exit` → 退出（沿用）。
2. `/plan` → `self.mode = Mode.PLAN`；写一行提示块到 `RichLog`（如「已进入计划模式（只读工具）」）；回 IDLE。
3. `/do` → `self.mode = Mode.NORMAL`；`self.conv.add_user(prompt.EXECUTE_DIRECTIVE)`；走与普通提交相同的启动流程（不把 `/do` 本身入历史）。
4. 普通文本 → `self.conv.add_user(text)`。
5. 启动：`self.turn_cancel = asyncio.Event()`；`self._stream_task = asyncio.create_task(self._consume_events(self.agent.run(self.conv, self.mode, self.turn_cancel)))`；`self.state = STREAMING`；`self.iter = 0`。用户输入块先 `RichLog.write` 再消费事件。

**`_consume_events`（`tui/stream.py`）分派顺序：**
对每个 `ev`：`err` → `tool` → `usage`（累加 `usage_in/usage_out`）→ `notice`（在 `RichLog` 写一行灰色系统提示块）→ `iter > 0`（`self.iter = ev.iter`）→ `done` → `text`（累积 `cur_reply`）。

- `ToolEvent.PHASE_START`：若 `cur_reply` 非空先把 preamble 提交 `RichLog` 并清空；`self.cur_tools.append(ToolDisplay(name, args))`。
- `ToolEvent.PHASE_END`：**FIFO 弹出队首** `self.cur_tools.pop(0)`（因 agent 保证 PHASE_START 与 PHASE_END 都按调用序发出，结束序 == 入队序，弹首即对应工具，无需按 name 匹配，重名工具也不会错位）；用其 args 定型工具行 → `RichLog.write(tool_line)` → `RichLog.write(tool_result_summary)`。

**按键（`MewCodeApp.on_key` 或 `BINDINGS`，全局优先）：**
- `ctrl+c`：`STREAMING` → `self.turn_cancel.set()`（取消本轮，不退出）；否则 `self.exit()`。
- `escape`：`STREAMING` → `self.turn_cancel.set()`；其余忽略。

**`view.py`：**
- `status_bar`：左侧在 provider 名后附模式标记（`Mode.PLAN` 显示「PLAN」徽标）；右侧在 model 名旁附累计用量 `↑{in} ↓{out} tok`（数值用紧凑格式，如 `1.2k`）。保持单行。
- 流式动态区：`cur_tools` 非空时逐行渲染 `● name(args)` + Running…（多个并发工具多行）；否则渲染「Imagining… (Ns · 第 N 轮)」（`self.iter > 0` 时附轮次）。
- `tool_line` / `tool_result_summary` 沿用 ch03。

**`finish_turn`（`tui/stream.py`）：** 清 `cur_reply`、`cur_tools = []`、`_stream_task = None`、`iter = 0`、`turn_cancel = None`，回 IDLE（`mode`、`usage_in/usage_out` 不清——跨轮保持）。

## 模块交互

```
用户提交 /do 或普通文本
  └─ tui.submit:
       ├─ /plan → mode=PLAN，回 IDLE
       ├─ /do   → mode=NORMAL; conv.add_user(EXECUTE_DIRECTIVE)
       ├─ 文本  → conv.add_user(text)
       └─ turn_cancel = asyncio.Event()
          stream_task = create_task(_consume_events(agent.run(conv, mode, turn_cancel)))
            └─ agent.run (async generator, ReAct 循环):
                 for it in range(1, MAX_ITERATIONS+1):
                   ├─ yield iter
                   ├─ 请求: provider.stream(conv.messages(), defs(mode), suffix(mode))
                   │     └─ 适配器: 注入 tools + (SYSTEM_PROMPT+suffix) → 流式拼接
                   │          → StreamEvent(text=...) / (tool_calls=...) / (usage=...) / (done|err)
                   │     → agent 转发 text(preamble)、收集 calls、记录 usage
                   ├─ yield usage
                   ├─ 无 calls → conv.add_assistant(final); yield done; 停
                   └─ 有 calls:
                        ├─ conv.add_assistant_with_tool_calls(preamble, calls)
                        ├─ execute_batched: 连续只读 asyncio.gather / 有副作用 await 单个
                        │     （PHASE_START 按序 → 执行 → PHASE_END 按序）
                        ├─ conv.add_tool_results(results)
                        └─ 下一轮 it
  └─ tui._consume_events: text→cur_reply；tool→cur_tools/RichLog；usage→累加；
       iter→self.iter；notice→灰提示；done→提交最终答复+finish_turn
  └─ Ctrl+C / Esc（streaming）→ turn_cancel.set() → agent.run 收尾历史 → generator 结束 → finish_turn → IDLE
```

并发模型：`conv` 任一时刻只被 `run` 的主协程触碰（`submit` 在交给 `run` 前 `add_user`，之后不再触碰；执行批的并发 task 只写各自 `results[k]`，不碰 `conv`）。`messages()` 返回副本。asyncio 单线程模型下 `await` 之间无中断，配合独立下标写入即可保证 N6。

## 文件组织

```
mewcode/
├── src/mewcode/
│   ├── llm/
│   │   ├── __init__.py            — 修改：新增 Usage；StreamEvent 加 usage；Provider.stream 加 system_suffix 形参
│   │   ├── anthropic_provider.py  — 修改：_effective_system(suffix)；流结束上抛 usage
│   │   └── openai_provider.py     — 修改：stream_options={"include_usage": True}；_to_openai_messages 拼 suffix；上抛 usage
│   ├── tool/
│   │   ├── __init__.py            — 修改：Tool Protocol 加 read_only
│   │   ├── registry.py            — 修改：read_only_definitions、is_read_only
│   │   └── {read_file,write_file,edit_file,bash,glob,grep}.py — 修改：各加 read_only 属性
│   ├── agent/
│   │   ├── __init__.py            — 重写：ReAct 循环、Mode、execute_batched、usage/iter/notice 事件、历史收尾
│   │   └── 单测见 tests/test_agent.py
│   ├── conversation.py            — 修改：last_role()
│   ├── prompt.py                  — 修改：PLAN_MODE_REMINDER、EXECUTE_DIRECTIVE；SYSTEM_PROMPT 增循环约定
│   └── tui/
│       ├── app.py                 — 修改：状态字段 mode/iter/usage/cur_tools/turn_cancel；按键拆分 Esc/Ctrl+C
│       ├── stream.py              — 修改：submit 识别 /plan /do + per-turn cancel；_consume_events 处理 usage/iter/notice/多工具
│       └── view.py                — 修改：状态栏模式徽标+累计用量；动态区迭代轮次+多并发工具行
└── tests/
    ├── test_agent.py              — 扩展：多轮 fake provider、并发分批、停止条件、Plan 工具集
    ├── test_conversation.py       — 扩展：last_role 断言
    └── test_tool.py               — 扩展：read_only_definitions、is_read_only（如已存在则补断言）
```

> 注：`cli.py` 已在 ch03 注入 registry，ch04 无需改动；`mode` 状态存于 TUI，不经 cli。

### 签名变更的调用方清单

ch04 改了两个签名，必须同步所有调用方/实现方，否则导入即报错：

- **`Provider.stream` 增 `system_suffix: str = ""`（第 3 形参，给默认值方便逐步迁移）**：
  - 实现方：`mewcode/llm/anthropic_provider.py`、`mewcode/llm/openai_provider.py`。
  - 调用方：`mewcode/agent/__init__.py` 的 `stream_once`（唯一直接调用方）。
  - 测试实现方：`tests/test_agent.py` 的 `FakeProvider.stream`（也实现该 Protocol，签名须同步）。
- **`Agent.run` 增 `mode: Mode` 与 `cancel: asyncio.Event`**：
  - 调用方：`mewcode/tui/stream.py`（`submit` 内）、`tests/test_agent.py`（各用例）。两者都要补 `mode` 与 `cancel` 实参（旧用例传 `Mode.NORMAL` + 一个未触发的 `asyncio.Event()`）。

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Loop 放哪 | 重写 `Agent.run` 为循环，签名加 `mode` / `cancel` | 循环编排天然属 agent 模块；TUI 维持纯渲染器。run 已是 async generator，循环只是把单轮的两次 `stream_once` 推广为 `for`，改动收敛在一个模块。 |
| 不用 SDK 内置 tool-runner | 坚持手写循环 + stable streaming | 沿用 ch03 决策；自写循环才能精确控制停止条件、保序分批、取消与历史收尾，SDK 的自动 runner 把这些黑盒化。 |
| 停止条件之「连续未知工具」 | 连续 `MAX_UNKNOWN_RUN=3` 轮「整轮只产生未知工具调用」即停 | 单次未知工具靠 registry 的「未知工具」结构化错误回灌即可让模型纠偏；只有连续多轮全错才说明在对幻觉工具空转，需兜底。混入任一已注册工具即重置计数（视为有进展）。 |
| 迭代上限值 | `MAX_ITERATIONS=25`，内置常量 | 兜底安全网，避免失控烧 token；25 足够覆盖正常多步任务。spec 明确不配置化，与 ch03 超时不配化一致。 |
| 并发分批粒度 | 「连续只读」合批并发，有副作用单个串行，保持调用序 | 用户选定的「保序分批」：read 之后的 write 不会被提前；相邻只读才并发加速。`bash` 保守归有副作用（可含任意写操作）。 |
| 并发的事件顺序 | 开始事件按序、结束事件按序，并发只在执行环节 | 满足 N3（scrollback 不交错）：UI 看到的工具行顺序始终是模型调用序；并发对用户透明，只体现为更快。每个 task 只写自己下标的 `results[k]`，asyncio 单线程模型下无锁亦无竞争（N6）。 |
| 取消机制 | per-turn `asyncio.Event`，TUI 持有；Esc / Ctrl+C(streaming) 触发 `set()`，Ctrl+C(idle) 退出 | 程序级 App 退出不动，新增每轮事件才能「取消本轮但不退程序」。`cancel.is_set()` 在 stream 循环与每个工具等待点被检查，自然停。 |
| 取消后历史一致 | 已发起工具补「已取消」结果 + `ensure_assistant_tail` 收尾 | F6：取消可能停在「assistant 含 tool_use 但缺 tool_result」或「user 之后无 assistant」处；补齐工具结果 + 保证 assistant 文本尾巴，下一轮请求才不会因悬空 tool_use / 连续同角色被 API 拒（400）。 |
| 用量提取位置 | 适配器在流结束后从 SDK 累加器/末尾 chunk 读 usage 并经 `StreamEvent(usage=...)` 上抛 | 两 SDK 的流式 usage 都只在流结束后完整可用（Anthropic 上下文退出后的 `get_final_message()` 或累加器；OpenAI 需 `include_usage=True` 后在末尾 chunk 读 `chunk.usage`）；逐 delta 不含。统一在 done 前发一次。 |
| 累计用量口径 | 状态栏显示「会话累计计费 token」= 每轮 input+output 之和 | 多轮 Loop 每轮都重发完整历史，各轮 input 重复计费；按轮累加正是实际消耗/成本口径，对用户最有意义。 |
| Plan Mode 系统提示注入 | `Provider.stream` 加 `system_suffix: str = ""` 形参 | 系统提示在适配器内注入，要让计划态约束生效必须穿过 stream。加一个字符串形参最小且显式；备选「请求 options dataclass」更可扩展但改动面更大，YAGNI 下不引入。 |
| Plan Mode 工具集 | 计划态只注入 `read_only_definitions()` | 物理上不给模型写/执行工具，即便提示被忽略也无法改动；只读分类靠 `Tool.read_only`。 |
| `/do` 语义 | 切回 Normal + 注入 `EXECUTE_DIRECTIVE` 用户消息 + 立即启动 Loop | 用户选定「切回全工具并立即执行」；复用已在历史里的计划，`/do` 不入历史，只把执行指令作为用户消息驱动模型开干。 |
| 模式状态存放 | 存于 TUI `MewCodeApp`，不进 `Conversation` | `Conversation` 是历史、`messages()` 返回副本，放不住可变模式；模式是会话级 UI 状态，跨轮保持，归 TUI 最自然。 |
| 多并发工具的 UI | `cur_tools: list[ToolDisplay]` 取代单个 `cur_tool` | 并发批同时有多个工具在跑，动态区需多行展示；结束事件按序逐个落 `RichLog`。 |
| 进度事件 | 每轮起始 `yield Event(iter=n)`，UI 显示「第 N 轮」 | F9 让用户感知多轮推进；用非零 `iter` 字段分派，与 ch03 的零值分派惯例一致。 |
| 通知 vs 历史 | 上限/未知工具的提示同时 yield `notice`（UI 灰字）并写入 assistant 历史 | UI 要让用户看到为何停；写入历史是为满足 `ensure_assistant_tail`（角色交替），二者用同一文案，避免历史里留空 assistant 回合。 |
