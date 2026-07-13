# 工具系统 Tasks

> 基于最新版 `doc/03/spec.md` 与 `doc/03/plan.md`。所有实现使用 Python 3.12，中文文本与源码文件统一采用 UTF-8。本任务清单不改变现有配置格式，也不实现权限确认、路径白名单或多轮 Agent Loop。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `src/mewcode/llm/__init__.py` | 增加工具调用、工具结果、工具定义、工具角色与扩展流事件 |
| 修改 | `src/mewcode/llm/openai_provider.py` | OpenAI 工具定义注入、流式调用拼接、工具历史序列化 |
| 修改 | `src/mewcode/llm/anthropic_provider.py` | Anthropic 工具定义注入、tool_use 提取、工具历史序列化与 thinking 兼容 |
| 修改 | `src/mewcode/conversation.py` | 保存 assistant 工具调用回合与工具结果回合 |
| 修改 | `src/mewcode/prompt.py` | 将纯聊天提示更新为 Agent 工具使用约定 |
| 新建 | `src/mewcode/tool/__init__.py` | Tool/Result/Registry 抽象、执行保护、默认注册中心和公共上限 |
| 新建 | `src/mewcode/tool/read_file.py` | 带行号和截断的 UTF-8 文件读取工具 |
| 新建 | `src/mewcode/tool/write_file.py` | UTF-8 文件创建与覆盖工具 |
| 新建 | `src/mewcode/tool/edit_file.py` | 原文唯一匹配替换工具 |
| 新建 | `src/mewcode/tool/bash.py` | 异步 shell 命令、输出采集与进程终止 |
| 新建 | `src/mewcode/tool/glob_tool.py` | 文件模式查找工具 |
| 新建 | `src/mewcode/tool/grep_tool.py` | 正则内容搜索工具 |
| 新建 | `src/mewcode/agent/__init__.py` | 单轮工具闭环、Agent 事件与工具执行编排 |
| 修改 | `src/mewcode/tui/app.py` | 注入注册中心并启动 Agent 消费任务 |
| 修改 | `src/mewcode/tui/stream.py` | 消费 Agent 文本、工具、完成和错误事件 |
| 修改 | `src/mewcode/tui/view.py` | Claude Code 风格工具行、结果摘要和执行中视图 |
| 修改 | `src/mewcode/cli.py` | 创建默认注册中心并注入 TUI |
| 修改 | `tests/test_llm_helpers.py` | 验证两种协议的工具定义转换、消息转换和流式拼接辅助逻辑 |
| 修改 | `tests/test_conversation.py` | 验证文本、工具调用和工具结果的历史顺序 |
| 修改 | `tests/test_prompt.py` | 验证 Agent 身份和工具使用约定 |
| 新建 | `tests/test_tool.py` | 注册中心及六个工具的成功、失败、超时和截断测试 |
| 新建 | `tests/test_agent.py` | 单轮闭环、多工具顺序、结果回灌和续答上限测试 |

## T1: 扩展协议无关 LLM 数据模型

**文件：** `src/mewcode/llm/__init__.py`

**依赖：** 已批准的 `doc/03/plan.md`

**步骤：**
1. 增加 `ROLE_USER`、`ROLE_ASSISTANT`、`ROLE_TOOL` 常量，并把 `Message.role` 扩展到工具角色。
2. 新增 `ToolCall`、`ToolResult`、`ToolDefinition` dataclass，字段和默认值与 plan 一致。
3. 扩展 `Message`，增加独立的 `tool_calls` 与 `tool_results` 列表，使用 `default_factory` 避免共享可变默认值。
4. 扩展 `StreamEvent`，增加一次性承载完整工具调用列表的字段，同时保留 `text`、`done`、`err`。
5. 将 `Provider.stream()` 签名改为接收 `list[ToolDefinition]`，并更新公共导出列表。
6. 保留 `new_provider()` 与 API key 脱敏行为不变。

**验证：** 运行 `python -m compileall src\mewcode\llm`，期望编译通过；运行针对 dataclass 默认列表独立性的测试，期望实例之间互不影响。

## T2: 扩展会话历史模型

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`

**依赖：** T1

**步骤：**
1. 保留现有 `add_user()`、`add_assistant()` 与 `messages()` 行为。
2. 新增 `add_assistant_with_tool_calls(text, calls)`，以 assistant 角色保存前置正文和调用列表副本。
3. 新增 `add_tool_results(results)`，以单个工具角色回合保存一组结果副本。
4. 若最新版 plan 要求 `__len__`，补充只读长度接口并保持现有调用兼容。
5. 扩展测试，验证普通文本回合、多个工具调用、多个工具结果及最终答复的顺序和字段。
6. 验证 `messages()` 返回列表副本，传入的调用/结果列表后续变化不会改写历史。

**验证：** 运行 `pytest tests/test_conversation.py`，期望全部通过。

## T3: 建立工具抽象与注册中心

**文件：** `src/mewcode/tool/__init__.py`

**依赖：** T1

**步骤：**
1. 定义 `Result`、runtime-checkable `Tool` Protocol 与 `DEFAULT_TIMEOUT = 30.0`。
2. 实现稳定顺序的 `Registry.register()`、`get()` 与 `definitions()`；重复名称返回清晰错误或拒绝注册。
3. 在 `definitions()` 中将每个工具转换为协议无关的 `ToolDefinition`。
4. 实现 `Registry.execute(name, args, timeout)`：未知工具、非法参数、超时和未预期异常均转成 `Result(is_error=True)`。
5. 将空参数字符串归一为合法 JSON 对象字符串 `"{}"`。
6. 提供公共文本截断辅助函数，截断时追加明确的 `[truncated]` 标记。
7. 先声明 `new_default_registry()` 的组装位置；六个工具完成后再在 T10 中接入实际注册，避免循环导入。

**验证：** 运行 `python -m compileall src\mewcode\tool`，期望编译通过；使用最小伪 Tool 验证注册、查找、导出、未知名称和异常兜底。

## T4: 实现读文件工具

**文件：** `src/mewcode/tool/read_file.py`、`tests/test_tool.py`

**依赖：** T3

**步骤：**
1. 定义工具名 `read_file`、中文描述及仅要求 `path` 字符串的 JSON Schema。
2. 解析 raw JSON，缺失、类型错误或空路径返回结构化参数错误。
3. 相对路径按进程当前工作目录解析，绝对路径直接使用；不增加 workspace 越界校验。
4. 以 UTF-8 读取普通文本文件，目录、不存在、不可读和解码失败分别返回清晰错误。
5. 为每行增加稳定行号，最多返回 2000 行且总量不超过 256KB，超限追加 `[truncated]`。
6. 在 `tests/test_tool.py` 增加中文内容、行号、不存在文件、目录、非 UTF-8 和大文件截断测试。

**验证：** 运行 `pytest tests/test_tool.py -k read_file`，期望全部通过。

## T5: 实现写文件工具

**文件：** `src/mewcode/tool/write_file.py`、`tests/test_tool.py`

**依赖：** T3

**步骤：**
1. 定义工具名 `write_file`、中文描述及 `path`、`content` 必填 Schema。
2. 校验 raw JSON、字段存在性和字符串类型，允许内容为空字符串。
3. 自动创建缺失的父目录，以 UTF-8 覆盖写入目标文件。
4. 成功结果返回规范化路径和 UTF-8 字节数；写入失败转成结构化错误。
5. 增加新文件、嵌套目录、已有文件覆盖、中文内容和非法参数测试。

**验证：** 运行 `pytest tests/test_tool.py -k write_file`，期望全部通过，并检查测试文件内容可按 UTF-8 正确读取。

## T6: 实现唯一匹配改文件工具

**文件：** `src/mewcode/tool/edit_file.py`、`tests/test_tool.py`

**依赖：** T3

**步骤：**
1. 定义工具名 `edit_file`、中文描述及 `path`、`old_string`、`new_string` 必填 Schema。
2. 校验参数，禁止空 `old_string`，允许空 `new_string` 表示删除。
3. 以 UTF-8 读取完整文件并统计 `old_string` 匹配次数。
4. 仅匹配一次时替换并写回；0 次返回“未找到匹配”，多次返回“匹配到 N 处”并建议提供更长上下文。
5. 文件访问、解码和写回异常均转成结构化结果，不向 Agent 抛出。
6. 增加唯一匹配、0 次、多次、删除文本、中文替换和非法空原文测试。

**验证：** 运行 `pytest tests/test_tool.py -k edit_file`，期望全部通过。

## T7: 实现异步命令工具

**文件：** `src/mewcode/tool/bash.py`、`tests/test_tool.py`

**依赖：** T3

**步骤：**
1. 定义工具名 `bash`、中文描述及 `command` 必填 Schema。
2. 使用 `asyncio.create_subprocess_shell()` 在当前工作目录执行命令，并同时捕获 stdout、stderr 和退出码。
3. 将 stdout/stderr 以 UTF-8 解码，非法字节使用替换策略，组合结果包含明确分区与 `exit_code`。
4. 对输出设置约 30000 字符的回灌上限，截断时追加标记。
5. 非零退出返回 `is_error=True`，但保留 stdout、stderr 与退出码供模型判断。
6. 在协程因 `Registry.execute()` 超时而取消时终止并回收子进程，避免遗留后台进程。
7. 增加成功命令、stderr、非零退出、长输出和短超时测试；测试命令按当前操作系统构造。

**验证：** 运行 `pytest tests/test_tool.py -k bash`，期望命令结果正确，超时测试在限定时间内结束且返回错误结果。

## T8: 实现 Glob 文件查找工具

**文件：** `src/mewcode/tool/glob_tool.py`、`tests/test_tool.py`

**依赖：** T3

**步骤：**
1. 定义工具名 `glob`、中文描述，以及 `pattern` 必填、`path` 可选的 Schema。
2. 默认从当前工作目录查找；指定 path 时支持绝对或相对目录，不增加路径越界限制。
3. 使用标准库递归模式匹配，只返回文件路径并按路径稳定排序。
4. 最多返回 100 条，超出时追加截断说明；无匹配返回正常的空结果说明，不标记执行错误。
5. 遍历期间分批让出事件循环，避免大量文件使 TUI 长时间失去响应。
6. 增加 `**/*.py`、指定搜索根、排序、无匹配和结果上限测试。

**验证：** 运行 `pytest tests/test_tool.py -k glob`，期望全部通过。

## T9: 实现 Grep 内容搜索工具

**文件：** `src/mewcode/tool/grep_tool.py`、`tests/test_tool.py`

**依赖：** T3

**步骤：**
1. 定义工具名 `grep`、中文描述，以及 `pattern` 必填、`path`/`glob` 可选的 Schema。
2. 使用 Python 正则编译搜索模式；非法表达式返回 `is_error=True` 的结构化结果。
3. 支持搜索单文件或递归目录，并用可选 glob 限定候选文件。
4. 按 UTF-8 逐行搜索，单个不可读或非 UTF-8 文件跳过并继续；命中格式为 `file:line:content`。
5. 最多返回 100 条并标注截断；无命中返回正常说明。
6. 对超长行采用分块或行长上限，明确标注“未完整搜索”，避免阻塞或误导。
7. 搜索过程中定期让出事件循环。
8. 增加中文命中、行号、路径范围、glob 过滤、非法正则、无命中、不可读文件和海量结果测试。

**验证：** 运行 `pytest tests/test_tool.py -k grep`，期望全部通过。

## T10: 组装默认工具注册中心

**文件：** `src/mewcode/tool/__init__.py`、`tests/test_tool.py`

**依赖：** T4、T5、T6、T7、T8、T9

**步骤：**
1. 在 `new_default_registry()` 中按固定顺序实例化并注册六个工具。
2. 确认工具名依次为 `read_file`、`write_file`、`edit_file`、`bash`、`glob`、`grep`。
3. 验证导出的六个 `ToolDefinition` 都包含名称、中文描述和完整 JSON Schema。
4. 增加重复注册、未知工具、非法 JSON、工具内部异常和超时统一转结果的测试。
5. 验证一个工具失败后注册中心仍可继续执行后续工具。

**验证：** 运行 `pytest tests/test_tool.py`，期望注册中心与六个工具测试全部通过。

## T11: 更新 OpenAI 消息与工具定义转换

**文件：** `src/mewcode/llm/openai_provider.py`、`tests/test_llm_helpers.py`

**依赖：** T1、T2

**步骤：**
1. 新增 `to_openai_tools()`，将协议无关定义转换为 Chat Completions function tools。
2. 新增或扩展 `to_openai_messages()`，保持 system prompt 首条消息，并转换普通 user/assistant 消息。
3. 将带工具调用的 assistant 回合转换为 `tool_calls` 数组，空正文使用兼容的 `None`。
4. 将工具结果回合展开为多条 `role="tool"` 消息，并正确关联 `tool_call_id`。
5. 保留文本消息原有格式，确保纯聊天历史不发生行为回归。
6. 增加六个工具定义、普通消息、多个调用和多个结果的转换测试。

**验证：** 运行 `pytest tests/test_llm_helpers.py -k openai`，期望转换结果与 OpenAI 请求格式一致。

## T12: 实现 OpenAI 流式工具调用拼接

**文件：** `src/mewcode/llm/openai_provider.py`、`tests/test_llm_helpers.py`

**依赖：** T11

**步骤：**
1. 扩展 `stream(msgs, tools)`，请求时注入转换后的 tools，并保持 `stream=True`。
2. 继续逐块产生正文 `StreamEvent(text=...)`。
3. 按 `delta.tool_calls[*].index` 建立缓冲，分别累积 ID、函数名和 arguments JSON 碎片。
4. 支持同一个响应中多个调用交错分片，流结束后按 index 顺序产生完整 `ToolCall` 列表。
5. 将空 arguments 归一为 `"{}"`，避免回灌非法 JSON。
6. 保持 `CancelledError` 向上传播，其他异常经过 API key 脱敏后作为流错误返回。
7. 使用伪 chunk 增加正文、单工具分片、多工具交错分片、空参数和错误脱敏测试。

**验证：** 运行 `pytest tests/test_llm_helpers.py -k openai`，期望流式工具名和 JSON 参数能够完整还原。

## T13: 更新 Anthropic 消息与工具定义转换

**文件：** `src/mewcode/llm/anthropic_provider.py`、`tests/test_llm_helpers.py`

**依赖：** T1、T2

**步骤：**
1. 新增 `to_anthropic_tools()`，将定义转换为包含 `input_schema` 的 Anthropic 工具对象。
2. 新增或扩展 `to_anthropic_messages()`，转换普通文本消息。
3. 将带工具调用的 assistant 回合转换为可选 text 块和多个 `tool_use` 块，JSON 参数解析失败时产生清晰错误。
4. 将一个工具结果回合转换为一条 user 消息中的多个 `tool_result` 块，并按 `is_error` 设置错误标志。
5. 确保纯文本历史格式与 ch02 兼容。
6. 增加六个工具定义、多个 tool_use、多个 tool_result、错误结果和空前置正文测试。

**验证：** 运行 `pytest tests/test_llm_helpers.py -k anthropic`，期望转换结果符合 Anthropic Messages 格式。

## T14: 实现 Anthropic 工具调用提取与 thinking 兼容

**文件：** `src/mewcode/llm/anthropic_provider.py`、`tests/test_llm_helpers.py`

**依赖：** T13

**步骤：**
1. 扩展 `stream(msgs, tools)`，请求参数中注入工具定义。
2. 继续只转发 `text_delta`，接收但不向上层展示 `thinking_delta` 和工具 JSON 增量。
3. 流结束后调用 SDK 的 `get_final_message()`，从完整 `tool_use` 块提取 ID、名称和 JSON 参数字符串。
4. 支持一次响应中多个 tool_use，并在 `done` 前产生一个完整调用列表事件。
5. 首次纯文本/工具请求按配置启用 extended thinking；历史已包含工具交互的续答请求关闭 thinking，避免缺失 thinking signature 导致协议错误。
6. 保持取消传播、API key 脱敏和普通文本流行为。
7. 使用伪 stream/final message 增加文本、thinking 丢弃、单工具、多工具、续答关闭 thinking 和错误脱敏测试。

**验证：** 运行 `pytest tests/test_llm_helpers.py -k anthropic`，期望工具调用完整提取且 thinking 开关符合 plan。

## T15: 实现单轮 Agent 编排

**文件：** `src/mewcode/agent/__init__.py`

**依赖：** T2、T10、T12、T14

**步骤：**
1. 定义 `Phase`、`ToolEvent`、`Event` 与 `Agent`，字段和默认值与 plan 一致。
2. 实现首次 Provider 请求：转发正文增量、累积前置正文、收集完整工具调用，并将流错误转换为 `Event(err=...)` 后停止。
3. 首次响应无工具调用时保存普通 assistant 回合并直接结束。
4. 有调用时保存 assistant 工具调用回合，按模型返回顺序依次发送 START 事件、执行工具、发送 END 事件。
5. 将每个成功或失败的 `Result` 转换为 `ToolResult`，全部保存到同一个工具结果回合；单个失败不得阻止后续调用。
6. 携带完整历史和工具定义发起第二次 Provider 请求，继续流式转发最终正文。
7. 第二次响应若再次请求工具，只忽略调用且绝不执行；若无最终正文或再次请求工具，补充明确的单轮上限提示，保证保存的 assistant 内容非空。
8. 第二次请求完成后保存最终 assistant 回合并产生 `done=True`。
9. 保持 `CancelledError` 向上传播，不把主动退出误显示为普通错误。

**验证：** 运行 `python -m compileall src\mewcode\agent`，期望编译通过。

## T16: 测试 Agent 单轮闭环

**文件：** `tests/test_agent.py`

**依赖：** T15

**步骤：**
1. 构造可记录请求历史和工具定义的 fake Provider，以及可记录执行顺序的 fake Tool。
2. 测试纯文本回复只请求一次、正文保持流式事件且会话只增加最终 assistant。
3. 测试“读文件并总结”链路：请求#1 调用工具、结果回灌、请求#2 返回总结。
4. 测试一次响应中多个工具按顺序执行，所有结果回灌后才发起续答。
5. 测试第一个工具失败后第二个工具仍执行，错误结果以 `is_error=True` 保存。
6. 测试续答再次返回工具调用时没有第二批执行，并产生单轮上限提示。
7. 测试续答正文为空、Provider 首次/续答报错及任务取消。
8. 检查每次 Provider 请求均带六个工具定义，第二次请求历史包含 tool call 与对应 result。

**验证：** 运行 `pytest tests/test_agent.py`，期望单轮闭环、顺序和上限测试全部通过。

## T17: 更新 Agent System Prompt

**文件：** `src/mewcode/prompt.py`、`tests/test_prompt.py`

**依赖：** T10

**步骤：**
1. 移除“只进行纯文本对话、不使用工具”的旧阶段说明。
2. 说明 MewCode 是可使用工具完成编码任务的终端 AI 助手。
3. 说明应选择合适工具、依据真实工具结果作答、工具失败时读取错误并给出可执行反馈。
4. 不宣称具备权限确认、路径隔离、持久化或自动多轮 Agent Loop。
5. 保持优先使用用户语言和简洁清晰回答的约定。
6. 更新测试，确认 Agent 身份和工具约定存在，旧纯聊天限制不存在。

**验证：** 运行 `pytest tests/test_prompt.py`，期望全部通过。

## T18: 增加工具调用与结果视图

**文件：** `src/mewcode/tui/view.py`

**依赖：** T15

**步骤：**
1. 新增工具调用行渲染，显示 `● name(关键参数)`，工具名和关键参数来自受控预览而非完整内容。
2. 为 `read_file`/`write_file`/`edit_file` 优先展示 path，为 `bash` 展示 command，为 `glob`/`grep` 展示 pattern。
3. 单行截断参数预览，避免超长文件内容、换行或潜在敏感值撑开界面。
4. 新增工具结果摘要，最多约 8 行；成功与错误使用可区分样式，截断时明确标记。
5. 新增执行中视图，显示当前工具行和 `Running...`/耗时状态；无工具执行时保留现有流式回答视图。
6. 保持普通 user、assistant、error、status bar 渲染不变。

**验证：** 运行 `python -m compileall src\mewcode\tui\view.py`；用最小调用样例检查工具行、错误样式和摘要截断的 Rich plain text 输出。

## T19: TUI 接入 Agent 事件流

**文件：** `src/mewcode/tui/app.py`、`src/mewcode/tui/stream.py`

**依赖：** T15、T18

**步骤：**
1. 扩展 `MewCodeApp` 构造参数，保存版本与 `Registry`，并增加当前工具显示状态。
2. 保持单/多 Provider 选择流程不变，选择完成后仍能正常 focus 输入框。
3. 将原先直接消费 `provider.stream()` 的逻辑改为构造 `Agent(provider, registry)` 并消费 `Agent.run(conv)`。
4. 文本事件继续增量更新 `#streaming`；工具 START 前将已有 preamble 写入 scrollback 并清空动态正文。
5. 工具 START 显示执行中视图；工具 END 按顺序写入工具调用行和结果摘要，然后清除执行状态。
6. done 时只提交尚未写入的最终正文，避免 preamble 重复，并调用统一 `_finish_turn()` 恢复输入。
7. err 时写入错误块并恢复输入；确保工具失败事件本身不走致命错误分支。
8. tick 同时刷新模型思考耗时和工具执行中状态。
9. 保留退出时取消 `_stream_task`，并确保第一轮后输入框仍恢复 `read_only=False`。

**验证：** 运行 `python -m compileall src\mewcode\tui`，期望编译通过；使用 fake Agent 事件序列验证 preamble、工具行、结果与最终答复不重复且顺序一致。

## T20: CLI 注入默认注册中心

**文件：** `src/mewcode/cli.py`

**依赖：** T10、T19

**步骤：**
1. 导入 `new_default_registry()` 与项目版本。
2. 配置加载成功后创建本次进程使用的固定六工具注册中心。
3. 按最新版 `MewCodeApp` 构造签名注入 providers、version 和 registry。
4. 保持任意路径配置发现、中文错误输出、退出码与 Ctrl+C 行为不变。
5. 不新增配置字段或命令行开关。

**验证：** 运行 `python -m compileall src\mewcode\cli.py src\mewcode\__main__.py`，期望编译通过；导入 CLI 时不提前创建 SDK 客户端或执行工具。

## T21: 协议请求与回灌集成测试

**文件：** `tests/test_llm_helpers.py`、`tests/test_agent.py`

**依赖：** T12、T14、T16

**步骤：**
1. 使用 mock OpenAI 客户端捕获首次和续答请求体，确认均携带六个 function tools。
2. 确认 OpenAI 续答历史包含 assistant.tool_calls 和逐条 role=tool 结果，ID 一一对应。
3. 使用 mock Anthropic 客户端捕获首次和续答请求体，确认均携带六个 input_schema 工具定义。
4. 确认 Anthropic 续答历史包含 assistant tool_use 块和同一 user 消息中的多个 tool_result 块。
5. 确认 Anthropic 含工具历史时关闭 thinking，普通首次请求仍服从 profile 的 thinking 配置。
6. 检查两种协议在上层都输出相同的 `ToolCall`、Agent 工具事件和结构化错误语义。

**验证：** 运行 `pytest tests/test_llm_helpers.py tests/test_agent.py`，期望两种协议的请求结构和上层行为测试全部通过。

## T22: 全量回归与 UTF-8 验证

**文件：** 无

**依赖：** T1 至 T21

**步骤：**
1. 运行 `python -m compileall src\mewcode tests`，确认所有 Python 文件编译通过。
2. 运行 `pytest`，确认 ch01/ch02 原有纯文本对话、配置发现和本章工具测试全部通过。
3. 若开发环境可用 Ruff，运行 `ruff check src tests` 并修复本章引入的问题。
4. 对 `src/mewcode`、`tests`、`doc/03` 下文本执行严格 UTF-8 解码与替换字符检查。
5. 检查 API key 不出现在工具调用预览、工具结果、Provider 异常或测试输出中。
6. 手工启动 `mewcode`，连续验证普通聊天、读取文件并总结、一次多工具、工具失败后继续对话。
7. 分别使用 OpenAI 与 Anthropic profile 验证同一工具任务；Anthropic thinking 开启时验证首次请求仍可正常触发工具并完成续答。
8. 构造第二次模型响应再次调用工具的场景，确认没有第二批工具执行并显示单轮上限提示。

**验证：** 编译、测试、可用的 lint 和 UTF-8 检查全部通过；两种协议的手工链路行为符合 `doc/03/spec.md` 的 AC1 至 AC13。

## 执行顺序

```text
T1
 ├─> T2
 └─> T3
      ├─> T4 ─┐
      ├─> T5  │
      ├─> T6  │
      ├─> T7  ├─> T10 ─> T17
      ├─> T8  │
      └─> T9 ─┘

T1 + T2 ─> T11 ─> T12 ─┐
         └> T13 ─> T14 ─┼─> T15 ─> T16 ─> T21
T10 ────────────────────┘

T15 ─> T18 ─> T19
T10 + T19 ─> T20

T1..T21 ─> T22
```

允许在不破坏依赖的前提下并行处理：T4-T9、T11-T14、T17-T18。开发时每完成一个任务，先执行该任务的验证命令，再进入依赖它的后续任务。
