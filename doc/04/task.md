# Agent Loop Tasks

> 基于已批准的 spec.md + plan.md。任务有序，每步留绿编译。验证一律「先跑命令看输出，再下结论」。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `src/mewcode/llm/__init__.py` | 新增 `Usage` 类型；`StreamEvent` 加 `usage`；`Provider.stream` 加 `system_suffix` 形参 |
| 修改 | `src/mewcode/llm/anthropic_provider.py` | `_effective_system(suffix)`；流结束上抛 usage |
| 修改 | `src/mewcode/llm/openai_provider.py` | `stream_options={"include_usage": True}`；`_to_openai_messages` 拼 suffix；上抛 usage |
| 修改 | `src/mewcode/tool/__init__.py` | `Tool` Protocol 加 `read_only` 属性 |
| 修改 | `src/mewcode/tool/registry.py` | `read_only_definitions`、`is_read_only` |
| 修改 | `src/mewcode/tool/{read_file,write_file,edit_file,bash,glob,grep}.py` | 各加 `read_only` 属性 |
| 修改 | `src/mewcode/conversation.py` | `last_role()` |
| 修改 | `src/mewcode/prompt.py` | `PLAN_MODE_REMINDER`、`EXECUTE_DIRECTIVE`；`SYSTEM_PROMPT` 增循环约定 |
| 重写 | `src/mewcode/agent/__init__.py` | ReAct 循环、`Mode`、`execute_batched`、`usage/iter/notice` 事件、历史收尾 |
| 重写 | `tests/test_agent.py` | 多轮 fake provider、并发分批、停止条件、Plan 工具集 |
| 修改 | `tests/test_conversation.py` | `last_role` 断言 |
| 修改 | `src/mewcode/tui/{app,stream,view}.py` | `mode`、per-turn cancel、Esc/Ctrl+C、`/plan` `/do`、`usage/iter/notice`/多工具、状态栏、动态区 |

## T1: llm 新增 Usage 类型（纯增量）

**文件：** `src/mewcode/llm/__init__.py`
**依赖：** 无
**步骤：**
1. 新增 `@dataclass class Usage(input_tokens: int = 0, output_tokens: int = 0)`（带中文注释：本轮输入/输出 token 数）。
2. 给 `StreamEvent` 增字段 `usage: Usage | None = None`（非空即本轮用量），更新 `StreamEvent` 文档注释补「`usage` 非空：本轮 token 用量，`done` 之前一次性发出」。

**验证：** `python -c "from mewcode.llm import Usage, StreamEvent; print(StreamEvent(usage=Usage(1,2)))"` 通过；`ruff check src/mewcode/llm/__init__.py` 无告警（纯增字段，向后兼容，不改 Protocol 签名）。

## T2: tool 只读分类

**文件：** `src/mewcode/tool/__init__.py`、`src/mewcode/tool/registry.py`、`src/mewcode/tool/{read_file,write_file,edit_file,bash,glob,grep}.py`
**依赖：** 无
**步骤：**
1. `__init__.py`：`Tool` Protocol 加 `read_only: bool` 属性（注释：True=只读，可并发执行 & Plan Mode 放行）。
2. 6 个工具各加一行属性：`read_file` / `glob` / `grep` → `read_only = True`；`write_file` / `edit_file` / `bash` → `read_only = False`。
3. `registry.py`：
   - `read_only_definitions() -> list[ToolDefinition]`：仿 `definitions()` 按注册顺序遍历，仅收 `self._tools[name].read_only is True` 的项。
   - `is_read_only(name: str) -> bool`：`t = self.get(name); return t is not None and t.read_only`。

**验证：** `pytest tests/test_tool.py`（若已存在）不回归；`python -c "from mewcode.tool.registry import Registry"` 不报错；`ruff check src/mewcode/tool` 无告警。

## T3: conversation.last_role

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`
**依赖：** 无
**步骤：**
1. `conversation.py`：新增 `def last_role(self) -> str`——空历史返回 `""`，否则返回 `self._messages[-1].role`。
2. `test_conversation.py`：补一组断言——空会话 `last_role() == ""`；`add_user` 后 `== "user"`；`add_tool_results` 后 `== "tool"`；`add_assistant` 后 `== "assistant"`。

**验证：** `pytest tests/test_conversation.py` 通过。

## T4: prompt 计划态提示与循环约定

**文件：** `src/mewcode/prompt.py`
**依赖：** 无
**步骤：**
1. `SYSTEM_PROMPT` 增补一句 Agent 循环约定：持续调用工具推进任务，直到任务完成后再给出最终简洁答复（不要每步都停下来等用户）。
2. 新增 `PLAN_MODE_REMINDER`：计划模式系统后缀——当前为计划模式，只能用只读工具（读文件 / 按模式找文件 / 搜内容）调研并产出一份分步执行计划；不得写文件、改文件或执行命令；计划写完即停，等用户用 `/do` 批准后再执行。
3. 新增 `EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"`。
4. （可选）`READY_HINT` 增提 `/plan`、`/do`。

**验证：** `python -c "from mewcode.prompt import PLAN_MODE_REMINDER, EXECUTE_DIRECTIVE; print(EXECUTE_DIRECTIVE)"` 通过；`pytest` 全量不回归。

## T5: llm Provider.stream 加 system_suffix + 用量上抛

**文件：** `src/mewcode/llm/__init__.py`、`src/mewcode/llm/anthropic_provider.py`、`src/mewcode/llm/openai_provider.py`、`src/mewcode/agent/__init__.py`（临时补参）
**依赖：** T1
**步骤：**
1. `llm/__init__.py`：`Provider.stream` 签名改为 `def stream(self, msgs, tools, system_suffix: str = "") -> AsyncIterator[StreamEvent]`，更新 Protocol 文档说明 `system_suffix` 语义（非空时拼到内置 `SYSTEM_PROMPT` 之后）。
2. `anthropic_provider.py`：
   - `stream` 加 `system_suffix` 形参；`params["system"]` 由硬编码改为 `_effective_system(system_suffix)`——`suffix == ""` 单段 `SYSTEM_PROMPT`；非空时单段 `SYSTEM_PROMPT + "\n\n" + suffix`。
   - 流正常结束（`async with client.messages.stream(...) as stream:` 上下文退出且未异常）后、`yield StreamEvent(done=True)` 之前：`final = await stream.get_final_message()`；`yield StreamEvent(usage=Usage(input_tokens=final.usage.input_tokens, output_tokens=final.usage.output_tokens))`。
3. `openai_provider.py`：
   - `stream` 加 `system_suffix`；请求参数加 `stream_options={"include_usage": True}`。
   - `_to_openai_messages(msgs, system_suffix)`：首条 system 消息文本 `SYSTEM_PROMPT`，`system_suffix` 非空时 `+ "\n\n" + system_suffix`（其调用处同步加实参）。
   - 流末尾会出现一个 `chunk.choices == []` 但带 `chunk.usage` 的 chunk：检测到则 `yield StreamEvent(usage=Usage(input_tokens=chunk.usage.prompt_tokens, output_tokens=chunk.usage.completion_tokens))`，跳过该 chunk 的 text 分支。
4. `src/mewcode/agent/__init__.py`：把现有 `stream_once` 里唯一的 `provider.stream(conv.messages(), defs)` 调用补成 `provider.stream(conv.messages(), defs, "")` 以匹配新签名——本步即让**非测试构建**保持绿（T6 会整体重写 agent）。

> 说明：`cli.py` 走 `agent.run`、不直接调 `stream`，本步不动它（其 `run` 调用在 T7 随 `mode` / `cancel` 形参一并更新）。`tests/test_agent.py` 的 `FakeProvider.stream` 也实现该 Protocol，本步之后它可能因签名不匹配让用例失败——这是预期的，T6 重写 `test_agent.py` 时一并补 `system_suffix` 形参；因此本步**不要**跑 `pytest tests/test_agent.py`。

**验证：** `python -c "from mewcode.llm.anthropic_provider import AnthropicProvider; from mewcode.llm.openai_provider import OpenAIProvider"` 不报错；`ruff check src/mewcode/llm` 无告警；`python -m mewcode` 发一条纯文本回复正常（用量已随流上抛，旧 agent 暂未消费）。

## T6: agent ReAct 循环重写

**文件：** `src/mewcode/agent/__init__.py`、`tests/test_agent.py`
**依赖：** T1, T2, T3, T4, T5
**步骤：**
1. `agent/__init__.py`：
   - 模块 docstring 改为「ReAct 循环编排」。
   - 类型：保留 `Phase` / `ToolEvent` / `Agent`；新增 `@dataclass class Usage(input: int = 0, output: int = 0)`、`class Mode(IntEnum): NORMAL = 0; PLAN = 1`；`Event` 增字段 `usage: Usage | None`、`iter: int = 0`、`notice: str = ""`。
   - 常量：按 plan「迭代、停止常量与提示文案」原样落 `MAX_ITERATIONS` / `MAX_UNKNOWN_RUN` 与 `NOTICE_MAX_ITER` / `NOTICE_UNKNOWN_TOOLS` / `NOTICE_STREAM_ERR` / `NOTICE_CANCELLED`（文案以 plan 为准，T8 端到端按这些文案核对）。
   - `Agent.run(conv, mode, cancel)`：按 plan「run 算法」实现 async generator——按 `mode` 取 `defs`(`definitions` / `read_only_definitions`) 与 `suffix`(`""` / `prompt.PLAN_MODE_REMINDER`)；`yield iter` → `stream_once` → `yield usage` → 无工具自然完成 / 有工具 `add_assistant_with_tool_calls` → 统计 `unknown_run` → `execute_batched` → `add_tool_results`（无条件）→ **取消（`not completed`）最高优先级收尾** → 未知工具上限收尾 → 循环走完触达迭代上限收尾。
   - `stream_once(conv, defs, suffix, cancel) → (text, calls, usage, ok)`：`suffix` 为 ch04 新增形参，透传给 `provider.stream`；转发 text、收集 calls、记录 `ev.usage`、`err` 即 `yield Event(err=...)` 返回 `ok=False`。
   - `execute_batched(calls, cancel) → (results, completed)`：保序分批——从 `i=0` 扫描，`is_read_only(calls[i])` 为真则吃最长连续只读区间 `[i, j)` 用 `asyncio.gather` **并发**（每 task 内 `asyncio.wait_for(registry.execute(...), DEFAULT_TIMEOUT)`，只写自己下标 `results[k]`），否则**串行**单个；每段执行前判 `cancel.is_set()` 取消则填 `NOTICE_CANCELLED` 结果返 `completed=False`；事件「PHASE_START 按序、PHASE_END 按序」（见 plan）。
   - 辅助：`all_unknown(calls)`（每个 call 用 `registry.get` 判，全 `None` 才 True）、`ensure_final`（沿用 ch03）、`ensure_assistant_tail(conv, fallback)`、`finish_cancelled(conv)`、`args_preview`（沿用 ch03）。
2. `tests/test_agent.py`（**替换** ch03 的「单轮读再答」「单轮上限」用例——后者断言单轮已与 ch04 多轮矛盾）。`FakeProvider.stream` 签名补 `system_suffix: str = ""`（并在某用例里记录收到的 `tools` / `system_suffix` 供断言）；多轮靠 `scripts: list[list[StreamEvent]]` 逐次返回：
   - 场景 A（多轮链路 AC1）：脚本①返回 1 个 `read_file` 工具调用、脚本②返回纯文本 → 断言事件序列含 `iter=1`、`tool` start/end、`iter=2`、最终 `text`、`done=True`；`conv` 末尾为 assistant 文本，中间含 tool_use 回合 + tool 角色回合。
   - 场景 B（迭代上限 AC3）：用「每次 stream 都返回一个工具调用」的 fake（忽略脚本耗尽，恒返工具）→ 断言恰好 `MAX_ITERATIONS` 次请求后停（`fp.calls == MAX_ITERATIONS`）、收到 `notice == NOTICE_MAX_ITER`、`conv.last_role() == "assistant"`。
   - 场景 C（连续未知工具 AC4）：脚本连续返回未注册工具名 → 断言 `MAX_UNKNOWN_RUN` 轮后停并 `notice == NOTICE_UNKNOWN_TOOLS`；另一用例在其间混入一个 `read_file`，断言计数重置、不提前停。
   - 场景 D（保序分批 AC8）：构造**自定义 registry** 注册两个插桩工具——一个只读工具（`read_only=True`，`execute` 内用 `asyncio.Lock` / `atomic counter` 记录「同时在跑的并发数」峰值、并 `await asyncio.sleep(...)` 制造重叠）与一个有副作用工具（`read_only=False`，记录开始时刻）。脚本一轮返回 `[ro, ro, rw]` → 断言：两只读的并发峰值 ≥2（确实并发）、`rw` 的开始时刻晚于两只读完成、`add_tool_results` 写入历史的结果顺序与调用序一致（按结果内容/ID 比对，不依赖具体方法名）。
   - 场景 E（取消历史一致 AC9）：插桩工具在 `execute` 中 `await asyncio.sleep(...)` 阻塞，测试侧在执行期间 `cancel.set()` → 断言 `conv` 末尾配对合法（含 tool_results、最后是 assistant 文本 `NOTICE_CANCELLED`），无悬空 tool_use；随后再追加一轮纯文本脚本能正常跑（角色交替未坏）。
   - 场景 F（Plan 工具集 AC13）：`Agent.run(conv, Mode.PLAN, cancel)` → 断言 fake 收到的 `tools` 仅含只读工具定义、`system_suffix == prompt.PLAN_MODE_REMINDER`。

**验证：** `pytest tests/test_agent.py` 全通过；`pytest -p no:randomly tests/test_agent.py` 顺序稳定；并发分批用例多跑几次（如 `pytest --count=5 tests/test_agent.py::test_concurrent_batch`，需 `pytest-repeat`）无偶发失败（覆盖并发分批，N6）。

## T7: tui 接入 Agent Loop + 收尾 run 调用方

**文件：** `src/mewcode/tui/app.py`、`src/mewcode/tui/stream.py`、`src/mewcode/tui/view.py`
**依赖：** T4, T6
**说明：** T6 改了 `Agent.run` 签名（加 `mode` 与 `cancel`），其调用方 `tui/stream.py` 在此步同步更新——本步完成后 `python -m mewcode` 才在**仓库级**重新可启动（T6 后只保证 agent 模块及其测试绿）。
**步骤：**
1. `app.py`：
   - `MewCodeApp` 新增字段：`mode: agent.Mode = Mode.NORMAL`、`iter: int = 0`、`usage_in: int = 0`、`usage_out: int = 0`、`cur_tools: list[ToolDisplay] = []`（移除单个 `cur_tool`）、`turn_cancel: asyncio.Event | None = None`。
   - 按键拆分：`ctrl+c` → `STREAMING` 时 `self.turn_cancel.set()`（不退出，等 generator 收尾）/ 否则 `self.exit()`；新增 `escape` → `STREAMING` 时 `self.turn_cancel.set()`。
2. `stream.py`：
   - `submit`：识别 `/exit`（退出）、`/plan`（`mode = Mode.PLAN`、提示块、回 IDLE）、`/do`（`mode = Mode.NORMAL`、`conv.add_user(prompt.EXECUTE_DIRECTIVE)`、走启动流程）、普通文本（`conv.add_user`）。启动处：`self.turn_cancel = asyncio.Event()`；`self._stream_task = asyncio.create_task(self._consume_events(self.agent.run(self.conv, self.mode, self.turn_cancel)))`；`self.iter = 0`；`self.state = STREAMING`。
   - `_consume_events` 按 plan 分派顺序处理 `err` / `tool` / `usage`(累加 `usage_in/usage_out`) / `notice`(灰提示块) / `iter`(set `self.iter`) / `done` / `text`；`tool.phase == PHASE_START` 追加 `cur_tools`（首个工具前先提交 preamble）、`PHASE_END` 从 `cur_tools` 弹首并 `RichLog.write(tool_line)` + `RichLog.write(tool_result_summary)`。
   - `finish_turn`：清 `cur_reply` / `cur_tools` / `_stream_task` / `iter` / `turn_cancel`，回 IDLE（保留 `mode`、`usage_in/usage_out`）。
3. `view.py`：
   - `status_bar`：左侧 provider 名后在 `Mode.PLAN` 时附「PLAN」徽标；右侧 model 名旁附 `↑{in} ↓{out} tok`（紧凑数字，如 `1.2k`）。
   - 流式动态区：`cur_tools` 非空逐行渲染 `● name(args)` Running…；否则「Imagining… (Ns · 第 N 轮)」（`self.iter > 0` 附轮次）。

**验证：** `python -m mewcode`（仓库级可启动）；`ruff format --check src/mewcode/tui`、`ruff check src/mewcode/tui` 无告警。

## T8: 全量验证与端到端冒烟

**文件：** 无（验证）
**依赖：** T1–T7
**步骤：**
1. `ruff format --check .`、`ruff check .`、`pytest`、（可选）`mypy src/mewcode`。
2. 端到端（openai 兼容端点，用 `.mewcode/config.yaml`）：
   - 多轮（AC1）：问「读 `docs/ch03/spec.md`，再据其内容新建 `docs/ch03/summary.txt` 写一句话摘要」→ 观察 `read_file` → `write_file` 跨多轮自动连环、状态栏用量增长、动态区轮次递增、最终答复。
   - 取消（AC10）：发一个会跑多步的任务，中途按 Esc / Ctrl+C → 回空闲态不退出 → 再正常发一条继续对话（验证历史未坏）。
   - 流出错（AC5）：临时改坏 `base_url` 或断网发一条 → 错误提示、程序不退出、改回后继续。
   - Plan Mode（AC13）：`/plan` → 问「给登录功能加单测的方案」→ 观察只出现 read/glob/grep 类工具与计划文本、无写/执行 → `/do` → 切回全工具按计划执行。
3. （可选）若有 anthropic 配置，重复多轮场景验证跨协议一致（AC14）。

**验证：** 全部命令通过、端到端各场景符合预期；密钥不回显（通读输出，AC/N7）。

## 执行顺序

```
T1 ─┬─ T5 ─┐
T2 ─┤      │
T3 ─┼──────┼─ T6 ─┬─ T7 ─┐
T4 ─┘      │      │      │
           └──────┘      └─ T8
```
（T1–T4 互相独立可并行；T5 依赖 T1；T6 依赖 T1/T2/T3/T4/T5；T7 依赖 T4/T6；T8 收尾全部。）
