# 系统提示工程化 Tasks

> 包名：`mewcode`（Python 3.12+）。源码位于 `src/mewcode/`，内部模块以 `mewcode.xxx` 导入。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/mewcode/prompt/modules.py` | `Module` 类型；`fixed_modules()` 七固定模块、`optional_modules()` 三空槽的内容常量 |
| 改   | `src/mewcode/prompt/__init__.py` | `assemble_system`/`build_system_prompt`；删旧 `SYSTEM_PROMPT`/`PLAN_MODE_REMINDER`/`EXECUTE_DIRECTIVE` 常量（迁移）；保留 banner |
| 新建 | `src/mewcode/prompt/environment.py` | `Environment` 结构、`gather_environment`、`Environment.render` |
| 新建 | `src/mewcode/prompt/reminder.py` | `system_reminder` 标签包裹、`plan_reminder(full)`、规划提醒完整/精简常量、`EXECUTE_DIRECTIVE` |
| 新建 | `tests/test_prompt.py` | 装配顺序、跳空槽、N1 确定性、双重强化文本断言 |
| 改   | `src/mewcode/tool/edit_file.py` | `DESCRIPTION` 补「编辑前先 `read_file`」 |
| 改   | `src/mewcode/tool/bash.py` | `DESCRIPTION` 补「优先用专用工具而非 bash 拼凑」 |
| 改   | `src/mewcode/llm/__init__.py` | `System` / `Request` dataclass；`Usage` 加缓存字段；`Provider.stream(req)`；删 `_effective_system` 与 prompt import |
| 改   | `src/mewcode/llm/anthropic_provider.py` | 两块 system（稳定块打断点 + env 块）、缓存用量解析、reminder 并入末条 user |
| 改   | `src/mewcode/llm/openai_provider.py` | 单条 system（stable+env 拼接）、`cached_tokens` 解析、reminder 追加尾部 user |
| 改   | `src/mewcode/agent/agent.py` | `__init__(+version)`；`run` 采集环境/装配系统；按轮次 reminder；缓存用量透传 |
| 改   | `tests/test_agent.py` | 断言 Request 装配（system 两段、规划按轮次 reminder）、缓存用量透传；修既有用例适配新签名 |
| 新建 | `tests/test_anthropic_system.py` | 序列化稳定块带 `cache_control`、环境块不带（守护回归） |
| 改   | `src/mewcode/tui/stream.py` | `Agent(...)` 传 `self.version` |
| 改   | `examples/smoke.py` | 打印缓存用量；`Agent(p, registry, "dev")` |

---

## T1: prompt 模块化装配

**文件：** `src/mewcode/prompt/modules.py`、`src/mewcode/prompt/__init__.py`
**依赖：** 无
**步骤：**
1. 在 `modules.py` 定义 `@dataclass(frozen=True) class Module: name: str; priority: int; content: str`。
2. `def fixed_modules() -> list[Module]` 返回七个固定模块，内容内置（中英按现有 `SYSTEM_PROMPT` 风格，英文为主）：
   - 身份(10)：MewCode 是终端编码 Agent。
   - 系统约束(20)：操作边界——在工作目录约定内行事、不外泄密钥、对破坏性操作谨慎。
   - 任务模式(30)：ReAct——多步推进、读后再改、完成才给终答。
   - 动作执行(40)：何时调工具、连续只读可并发、有副作用谨慎。
   - 工具使用(50)：**优先用 `read_file`/`glob`/`grep` 而非 bash 拼凑；编辑文件前必先 `read_file`**（F5）。
   - 语气风格(60)：简洁、直接、不奉承。
   - 文本输出(70)：必要时用 Markdown（代码块/列表），终答精炼。
3. `def optional_modules() -> list[Module]` 返回三个空槽：自定义指令(80)、已激活 Skill(90)、长期记忆(100)，`content` 均为 `""`。
4. 在 `prompt/__init__.py`：
   - `def assemble_system(mods: list[Module]) -> str`：按 `priority` 升序稳定排序、**跳过 `content == ""`**、以 `"\n\n"` 连接。
   - `def build_system_prompt() -> str`：`assemble_system(fixed_modules() + optional_modules())`。
   - 删除旧 `SYSTEM_PROMPT`、`PLAN_MODE_REMINDER` 常量（内容迁至模块/reminder）；`EXECUTE_DIRECTIVE` 迁至 `reminder.py`。保留 `CAT_BANNER`/`READY_HINT`/`render_banner`。

**验证：** `python -c "from mewcode.prompt import build_system_prompt; print(build_system_prompt())"` 观察七模块按序、空槽不留空行；`ruff check src/mewcode/prompt/` 无告警。

## T2: 环境采集与渲染

**文件：** `src/mewcode/prompt/environment.py`
**依赖：** 无
**步骤：**
1. 定义 `@dataclass class Environment: working_dir: str; platform: str; date: str; git_status: str; version: str; model: str`。
2. `def gather_environment(version: str, model: str) -> Environment`：
   - `working_dir = os.getcwd()`（捕获 `OSError` 留空）、`platform = sys.platform`（或 `platform.system().lower()`）、`date = datetime.date.today().isoformat()`。
   - `git_status`：用 `subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=2.0)`；返回码非零/`FileNotFoundError`/`TimeoutExpired`/非 git 目录 → `""`；有输出则取摘要（如「N 个文件改动」或前几行）。同步实现即可（外调耗时已被 2s 超时收口；如需 async 调用方可包 `asyncio.to_thread`）。
   - `version=version`、`model=model`。**不读任何环境变量**（N5）。
3. `Environment.render(self) -> str`：渲染为「环境信息」段——逐行 `Key: Value`，空值项省略。

**验证：** 单测在临时非 git 目录 `gather_environment` 得 `git_status == ""` 且不抛异常；`render()` 含 cwd/platform/date。

## T3: 补充消息与规划提醒构造

**文件：** `src/mewcode/prompt/reminder.py`
**依赖：** 无
**步骤：**
1. `def system_reminder(body: str) -> str`：返回 `f"<system-reminder>\n{body}\n</system-reminder>"`。
2. 规划提醒常量：`_PLAN_REMINDER_FULL`（完整版，含「仅可用只读工具调研、产出分步计划、等 `/do` 批准」）、`_PLAN_REMINDER_CONCISE`（精简版，一两句）。
3. `def plan_reminder(full: bool) -> str`：`system_reminder(_PLAN_REMINDER_FULL if full else _PLAN_REMINDER_CONCISE)`。
4. `EXECUTE_DIRECTIVE`（从 `prompt/__init__.py` 迁来）：`/do` 注入的用户消息文案。

**验证：** 单测断言 `plan_reminder(True)` 含 `<system-reminder>` 与完整文案；`plan_reminder(False)` 用精简文案。

## T4: prompt 单测

**文件：** `tests/test_prompt.py`
**依赖：** T1, T2, T3
**步骤：**
1. 装配顺序：断言 `build_system_prompt()` 中身份段出现在工具使用段之前；模块以空行分隔。
2. 跳空槽：在 `assemble_system` 传入含空 `content` 的模块，断言其不出现、不产生连续多空行。
3. **N1 确定性**：连续两次 `build_system_prompt()` 结果 `==`。
4. **F5 双重强化**：`build_system_prompt()` 文本含「编辑」与「先读」之意、含「优先」与专用工具名。
5. 环境与 reminder：见 T2/T3 验证（合并到本文件或拆分）。

**验证：** `pytest tests/test_prompt.py` 通过。

## T5: 工具描述双重强化

**文件：** `src/mewcode/tool/edit_file.py`、`src/mewcode/tool/bash.py`
**依赖：** 无
**步骤：**
1. `edit_file.DESCRIPTION` 末补：「编辑前请先用 `read_file` 读取目标文件，确认 `old_string` 唯一。」
2. `bash.DESCRIPTION` 末补：「读文件、找文件、搜内容请优先用 `read_file`/`glob`/`grep`，不要用 bash 拼凑。」
3. 不改 schema、不改 `execute` 行为。

**验证：** `pytest tests/test_tool.py` 仍通过；`ruff check src/mewcode/tool/` 无告警。

## T6: llm 接口改造

**文件：** `src/mewcode/llm/__init__.py`
**依赖：** 无（但 T7/T8/T9 依赖本任务）
**步骤：**
1. 新增 `@dataclass class System: stable: str = ""; environment: str = ""`、`@dataclass class Request: messages: list[Message] = field(default_factory=list); tools: list[ToolDefinition] = field(default_factory=list); system: System = field(default_factory=System); reminder: str = ""`。
2. `Usage` 加 `cache_write: int = 0`、`cache_read: int = 0`。
3. `Provider.stream` 改为 `def stream(self, req: Request) -> AsyncIterator[StreamEvent]`；更新 Protocol 文档字符串。
4. 删除 `_effective_system` 函数与对 `mewcode.prompt` 的 import。
5. `new_provider` 工厂保持。

**验证：** `python -c "from mewcode.llm import Request, System, Usage, Provider"` 不报错；anthropic/openai 适配器在 T7/T8 修复前会 import 失败，预期。

## T7: Anthropic 适配缓存通道 + reminder

**文件：** `src/mewcode/llm/anthropic_provider.py`
**依赖：** T6
**步骤：**
1. `async def stream(self, req: Request) -> AsyncIterator[StreamEvent]`：
   - 构造 `system: list[dict] = []`：`req.system.stable` 非空 → `{"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}}`；`req.system.environment` 非空 → `{"type": "text", "text": environment}`（无 `cache_control`）。
   - `messages = _to_anthropic_messages(req.messages)`；`req.reminder` 非空 → 调 `_append_reminder_anthropic(messages, req.reminder)`：把 `{"type": "text", "text": reminder}` 追加到**最后一条消息**的 `content`（确保 `content` 为 list 形态后追加）；末条非 user 时新起一条 user 消息。
   - `tools = _to_anthropic_tools(req.tools)`（不另打断点）。
   - thinking 逻辑沿用（`_assistant_used_tools(req.messages)`）。
2. Usage 解析：`Usage(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens, cache_write=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0, cache_read=getattr(resp.usage, "cache_read_input_tokens", 0) or 0)`。

**验证：** `python -c "from mewcode.llm.anthropic_provider import AnthropicProvider"` 不报错（配合 T8）；smoke anthropic 跑两轮见 `cache_read > 0`（次轮）。

## T8: OpenAI 适配缓存通道 + reminder

**文件：** `src/mewcode/llm/openai_provider.py`
**依赖：** T6
**步骤：**
1. `_to_openai_messages(req)`：首条 system 消息 = `req.system.stable`（若 `environment` 非空则拼为 `stable + "\n\n" + environment`）；随后映射历史；`req.reminder` 非空 → 追加 `{"role": "user", "content": req.reminder}`。
2. `async def stream(self, req: Request)` 改用 `req`；`params["tools"] = _to_openai_tools(req.tools)`。
3. Usage 解析：`cache_read = getattr(getattr(resp.usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0`、`cache_write = 0`。

**验证：** import 不报错；smoke openai 兼容端点跑两轮，`cached_tokens` 字段被打印（端点支持则 >0）。

## T9: agent 改造

**文件：** `src/mewcode/agent/agent.py`
**依赖：** T1, T2, T3, T6
**步骤：**
1. `Agent.__init__(self, provider, registry, version: str)` 加 `self._version = version` 字段。
2. 加常量 `PLAN_REMINDER_INTERVAL = 4`。
3. `run` 起始：`env = prompt.gather_environment(self._version, self._provider.model)`；`sys = prompt.build_system_prompt()`；`defs` 按 mode 选择（规划=`READ_ONLY_DEFINITIONS`，普通=`DEFINITIONS`）——**移除 suffix 变量**。
4. 每轮迭代算 reminder：
   ```python
   reminder = ""
   if mode == PlanMode.PLAN:
       full = iter_idx == 1 or (iter_idx - 1) % PLAN_REMINDER_INTERVAL == 0
       reminder = prompt.plan_reminder(full)
   ```
5. `_stream_once` 签名改为接收 `sys`、`env_text`、`defs`、`reminder`，内部组装 `llm.Request(messages=conv.messages(), tools=defs, system=llm.System(stable=sys, environment=env_text), reminder=reminder)` 调 `self._provider.stream(req)`。
6. `agent.Usage` 加 `cache_write/cache_read`；`run` 透传 `Event(usage=Usage(input, output, cache_write, cache_read))`。

**验证：** `python -c "from mewcode.agent.agent import Agent"` 不报错（配合 T10/T11）。

## T10: TUI 与 smoke 接线

**文件：** `src/mewcode/tui/stream.py`、`examples/smoke.py`
**依赖：** T9
**步骤：**
1. `stream.py` 中改 `Agent(self.provider, self.registry, self.version)`；`/do` 注入仍用 `prompt.EXECUTE_DIRECTIVE`（已迁至 `reminder.py`，但通过 `mewcode.prompt` 包顶层重导出，import 路径不变）。
2. `examples/smoke.py`：`Agent(p, tool.new_default_registry(), "dev")`；消费 `Event.usage` 时打印 `input/output/cache_write/cache_read`；可改为连发两条消息观察次轮 `cache_read`。

**验证：** `python -m mewcode` 在合法配置下正常启动；`python examples/smoke.py` 能跑通。

## T11: agent 单测适配

**文件：** `tests/test_agent.py`
**依赖：** T9
**步骤：**
1. 修 fake provider：`stream(req)` 实现新签名；记录收到的 `req`（`system.stable/environment`、`tools`、`reminder`）。
2. 既有 ch04 场景（A 自然完成、B 上限、C 未知工具、D 并发、E 取消、F 规划只读工具）适配新签名；`Agent(...)` 传 version。
3. 新增断言：
   - 规划模式下 `req.system.stable` 非空且**普通/规划一致**；`req.system.environment` 非空。
   - 规划模式 iter1 的 `req.reminder` 含完整提醒、含 `<system-reminder>`；iter2 为精简版（构造一个让循环多轮的脚本）。
   - 规划模式 `req.tools` 仅只读；普通模式全量。
   - reminder **不写入 conv 持久历史**（`conv.messages()` 不含 reminder 文本）。
   - 缓存用量透传：fake 发 `Usage(cache_write=X, cache_read=Y)` → 收到的 `Event.usage` 携带 X/Y。

**验证：** `pytest tests/test_agent.py` 通过；`pytest -p no:randomly tests/test_agent.py`（如启用 randomly 插件）。

## T12: 全量编译测试与规范

**文件：** —
**依赖：** T1–T11
**步骤：**
1. `ruff format --check .`（统一格式）。
2. `ruff check .`（import 分组、无告警）。
3. `pytest`（全量单测通过）。
4. （可选）`mypy src/mewcode` 通过子集检查。
5. `python -m mewcode` 能正常启动。

**验证：** 全部通过；检索输出无 api_key 明文。

## 执行顺序

```
T1 ─┐
T2 ─┼─→ T4(prompt 单测)
T3 ─┘
T5(工具描述，独立)

T6(接口) ─┬─→ T7(anthropic) ─┐
          └─→ T8(openai)    ─┤
T1,T2,T3,T6 ─→ T9(agent) ────┼─→ T10(tui/smoke)
                              └─→ T11(agent 单测)

全部 ─→ T12(format/check/test)
```
