# 上下文管理与记忆系统 Tasks

> 执行环境：所有 Python 验证使用 `conda run -n mewcode ...`。在 T1-T18 全部完成前不得宣告本章实现完成；T19 是完整集成与回归验证。

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/mewcode/config.py` | `context_window` 配置与校验 |
| 修改 | `src/mewcode/llm/__init__.py` | 动态系统上下文字段 |
| 新建 | `src/mewcode/llm/generation.py` | 无工具文本生成器 |
| 修改 | `src/mewcode/llm/anthropic_provider.py` | 序列化动态系统上下文 |
| 修改 | `src/mewcode/llm/openai_provider.py` | 序列化动态系统上下文 |
| 修改 | `src/mewcode/conversation.py` | 追加归档回调与 Prompt Context 替换 |
| 新建 | `src/mewcode/session/__init__.py` | 会话包公开接口 |
| 新建 | `src/mewcode/session/paths.py` | 会话 ID、目录与 gitignore |
| 新建 | `src/mewcode/session/archive.py` | JSONL 事件和安全追加 Writer |
| 新建 | `src/mewcode/session/repository.py` | 会话扫描、恢复、清理 |
| 新建 | `src/mewcode/session/runtime.py` | 活动会话和异步标题 |
| 新建 | `src/mewcode/memory/__init__.py` | 记忆包公开接口 |
| 新建 | `src/mewcode/memory/instructions.py` | 三层项目指令与 include |
| 新建 | `src/mewcode/memory/store.py` | 笔记和索引存储 |
| 新建 | `src/mewcode/memory/update.py` | 无工具的异步记忆更新 |
| 修改 | `src/mewcode/prompt/__init__.py` | 指令/记忆模块注入 |
| 新建 | `src/mewcode/context/__init__.py` | 上下文包公开接口 |
| 新建 | `src/mewcode/context/budget.py` | Token 近似估算 |
| 新建 | `src/mewcode/context/artifact.py` | 工具大结果缓存 |
| 新建 | `src/mewcode/context/compact.py` | 九段摘要、失败熔断 |
| 新建 | `src/mewcode/context/controller.py` | 请求前归档/压缩编排与恢复 |
| 修改 | `src/mewcode/agent/__init__.py` | 上下文预处理、usage、自然结束事件 |
| 修改 | `src/mewcode/cli.py` | 启动装配和清理生命周期 |
| 修改 | `src/mewcode/tui/app.py` | 本地命令、状态、会话切换 |
| 修改 | `src/mewcode/tui/stream.py` | 自然结束触发记忆 |
| 修改 | `src/mewcode/tui/timeline.py` | 清空与分块重放 |
| 新建 | `src/mewcode/tui/replay.py` | JSONL 可见事件重放 |
| 新建 | `src/mewcode/tui/resume.py` | 会话筛选与选择屏 |
| 新建 | `tests/test_context_budget.py` | 估算与阈值测试 |
| 新建 | `tests/test_context_artifact.py` | 归档阈值与引用测试 |
| 新建 | `tests/test_context_compact.py` | 摘要、保留尾部与熔断测试 |
| 新建 | `tests/test_session_archive.py` | JSONL Writer/事件/标题测试 |
| 新建 | `tests/test_session_repository.py` | 恢复、列表、清理和手动删除测试 |
| 新建 | `tests/test_memory_instructions.py` | 指令优先级与 include 安全测试 |
| 新建 | `tests/test_memory_store.py` | 笔记、索引和路径安全测试 |
| 新建 | `tests/test_memory_update.py` | 记忆异步更新协议测试 |
| 新建 | `tests/test_tui_resume.py` | `/resume`、筛选、删除与重放测试 |
| 修改 | `tests/test_config.py` | `context_window` 覆盖 |
| 修改 | `tests/test_conversation.py` | 回调和整体替换覆盖 |
| 修改 | `tests/test_prompt.py` | 自定义指令与长期记忆模块覆盖 |
| 修改 | `tests/test_llm_helpers.py` | `System.context` 两 Provider 覆盖 |
| 修改 | `tests/test_agent.py` | Context 注入、usage、natural 事件覆盖 |
| 修改 | `tests/test_tui.py` | 既有交互回归覆盖 |

## T1: 扩展 Provider 配置、请求系统上下文与无工具生成

**文件：** `src/mewcode/config.py`、`src/mewcode/llm/__init__.py`、`src/mewcode/llm/generation.py`、`src/mewcode/llm/anthropic_provider.py`、`src/mewcode/llm/openai_provider.py`、`tests/test_config.py`、`tests/test_llm_helpers.py`

**依赖：** 无

**步骤：**

1. 为 `ProviderConfig` 增加正整数 `context_window`，未提供时默认为 `1_000_000`，非法类型或非正值报现有 `ConfigError`。
2. 给 `llm.System` 增加 `context` 字段，并让两种 Provider 在稳定提示与环境提示之后以系统级内容序列化它。
3. 新增 `generate_text()`：以空工具列表调用既有 `Provider.stream()`，收集文本、拒绝工具调用、透传脱敏后的失败；供标题、摘要和记忆使用。
4. 保持既有无 `context` 请求的序列化结果不变，补充配置默认/边界和两种 Provider 的单测。

**验证：** `conda run -n mewcode pytest tests/test_config.py tests/test_llm_helpers.py -q`

## T2: 让 Conversation 支持档案回调与 Prompt Context 整体替换

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`

**依赖：** T1

**步骤：**

1. 支持以恢复后的初始消息创建 `Conversation`。
2. 为全部 `add_*` 方法提供可选、同步的追加回调，确保新增原始消息恰好回调一次；无回调时维持现有行为。
3. 新增 `replace_messages()`，仅替换内存 Prompt Context，不触发原始消息追加回调。
4. 覆盖初始消息、防御性副本、每类追加、回调异常隔离和整体替换。

**验证：** `conda run -n mewcode pytest tests/test_conversation.py -q`

## T3: 实现会话路径、Git 忽略规则与 JSONL 追加 Writer

**文件：** `src/mewcode/session/__init__.py`、`src/mewcode/session/paths.py`、`src/mewcode/session/archive.py`、`tests/test_session_archive.py`

**依赖：** T2

**步骤：**

1. 生成 `YYYYMMDD-HHMMSS-xxxx` 会话 ID，初始化 `.mewcode/sessions/<id>.jsonl` 与 `.mewcode/cache/<id>/` 路径。
2. 幂等追加项目 `.gitignore` 中的 sessions、cache、memory 忽略规则，保留已有内容与换行风格。
3. 定义 JSONL 事件序列化/反序列化：消息、可见 notice/error、title、tool archive、compact、compact failure，并完整编码现有 ToolCall/ToolResult 字段。
4. 实现带锁 Writer，追加后 `flush + fsync`；写入失败只记录日志，关闭或重复关闭安全。
5. 验证首条用户消息模型字段、标题事件、草稿不可能写入事件、并发追加不交错及坏尾行容忍。

**验证：** `conda run -n mewcode pytest tests/test_session_archive.py -q`

## T4: 实现会话扫描、恢复和过期清理

**文件：** `src/mewcode/session/repository.py`、`src/mewcode/session/__init__.py`、`tests/test_session_repository.py`

**依赖：** T3

**步骤：**

1. 扫描新格式 JSONL，从事件流提取最新标题、模型、最后活动时间、消息数和文件大小，并按活动时间倒序返回。
2. 恢复时跳过坏 JSON 行，构建完整可见事件、完整原始消息、工具归档引用、最新有效压缩检查点和失败次数。
3. 检查末尾工具调用与工具结果的配对；发现孤立 assistant 工具调用时截断不完整尾部。
4. 基于会话 ID 清理超过 30 天的 JSONL 及同名 cache；旧格式或无法解析的目录不展示也不清理，单项错误隔离。
5. 实现选中会话的手动删除：仅删除新格式 ID 的 JSONL 与同名 cache；不删除项目级或用户级 memory，删除失败返回可处理结果。
6. 覆盖标题回退、检查点不隐藏早期 TUI 事件、坏行、孤立工具、过期会话、旧格式保护、手动删除与单个删除失败。

**验证：** `conda run -n mewcode pytest tests/test_session_repository.py -q`

## T5: 组合活动会话运行时与异步标题生成

**文件：** `src/mewcode/session/runtime.py`、`src/mewcode/session/__init__.py`、`tests/test_session_archive.py`、`tests/test_session_repository.py`

**依赖：** T1、T3、T4

**步骤：**

1. 组合 `SessionPaths`、ArchiveWriter、当前 `Conversation`、Provider 配置和后续 ContextController 所需状态。
2. 在首条用户消息已写入档案后启动一次后台标题任务；标题请求禁止工具调用，成功或失败回退标题都写入 JSONL `title` 事件。
3. 标题任务失败不影响当前 Agent 回合；会话切换/退出时关闭 Writer 并取消仍依赖该运行时的标题任务。
4. 支持从 `RestoredArchive` 重建运行时并以追加模式继续写同一档案。
5. 覆盖标题仅生成一次、Provider 失败回退、恢复后追加和关闭时取消。

**验证：** `conda run -n mewcode pytest tests/test_session_archive.py tests/test_session_repository.py -q`

## T6: 实现一次性项目指令加载并接入系统提示

**文件：** `src/mewcode/memory/__init__.py`、`src/mewcode/memory/instructions.py`、`src/mewcode/prompt/__init__.py`、`tests/test_memory_instructions.py`、`tests/test_prompt.py`

**依赖：** T1

**步骤：**

1. 按项目根、项目 `.mewcode`、用户 `.mewcode` 优先级加载 `MEWCODE.md`，高优先级文本排在前面。
2. 实现独占行 `@include <relative_path>` 展开：路径解析、五层深度、环路集合、信任根、二进制和缺失文件降级。
3. 将指令结果作为不可变 `InstructionBundle`，仅在 CLI 启动时创建，后续 `/resume` 不触发重新读取。
4. 修改 `build_system_prompt(instructions, memory)`，在已有 priority 80/100 槽位填入非空内容且不影响空槽位的既有渲染。
5. 覆盖三层顺序、合法嵌套、六层拒绝、环路、路径逃逸、二进制、缓存语义和模块优先级。

**验证：** `conda run -n mewcode pytest tests/test_memory_instructions.py tests/test_prompt.py -q`

## T7: 实现用户级/项目级记忆存储与索引

**文件：** `src/mewcode/memory/store.py`、`src/mewcode/memory/__init__.py`、`tests/test_memory_store.py`

**依赖：** T3

**步骤：**

1. 初始化两级 memory 目录，读取/合并 `MEMORY.md`，以项目级在前、用户级在后生成可注入索引。
2. 渲染并原子写入带 type/title/created/updated frontmatter 的笔记，生成/验证安全 slug 文件名。
3. 实现 create/update、索引行维护和每级异步锁；拒绝类型与层级映射不符、路径穿越或删除操作。
4. 合并索引超过 25KB 时截断并标注；提供 200 行/25KB 阈值检测给更新器。
5. 覆盖四类型目标目录、frontmatter、索引顺序、路径安全、并发锁、阈值和原笔记不删除。

**验证：** `conda run -n mewcode pytest tests/test_memory_store.py -q`

## T8: 实现异步无工具记忆更新协议

**文件：** `src/mewcode/memory/update.py`、`src/mewcode/memory/__init__.py`、`tests/test_memory_update.py`

**依赖：** T1、T7

**步骤：**

1. 从当前回合提取“最后 user 到最终 assistant”的消息快照，连同两级索引构建结构化更新提示。
2. 用 `generate_text()` 请求同一 Provider；明确禁止工具调用，要求模型按 `user`、`feedback`、`project`、`reference` 返回 create/update JSON。
3. 验证并执行合法操作；索引任一超限时在同次请求中采用模型返回的压缩索引，绝不删除原始笔记。
4. Provider、JSON、校验或写入失败只记录日志且不重试，不影响调用方。
5. 覆盖空操作、四类落点、去重 update、超限索引重写、工具调用拒绝和所有失败降级。

**验证：** `conda run -n mewcode pytest tests/test_memory_update.py -q`

## T9: 实现 Token 估算与工具结果预防归档

**文件：** `src/mewcode/context/__init__.py`、`src/mewcode/context/budget.py`、`src/mewcode/context/artifact.py`、`tests/test_context_budget.py`、`tests/test_context_artifact.py`

**依赖：** T1、T3

**步骤：**

1. 以最近 input usage 和请求字符数建立 Token 估算锚，缺少 usage 时退化为字符估算；支持自动/手动不同安全余量。
2. 实现单结果 16,000 字符和同一 tool 消息累计 32,000 字符两级策略，按结果大小从大到小归档。
3. 为每个成功落盘结果生成预览、相对路径和重新读取提示，替换 Prompt Context 中的结果，同时追加 `tool_archive` JSONL 事件；原始消息事件保持不变。
4. 落盘或序列化失败时保留原结果、产生状态通知而非中断请求。
5. 覆盖 usage 增量、默认 1M 窗口、13K/3K 阈值、16K/32K 边界、排序、多结果引用、写入失败和恢复引用。

**验证：** `conda run -n mewcode pytest tests/test_context_budget.py tests/test_context_artifact.py -q`

## T10: 实现九段摘要、保留尾部与熔断

**文件：** `src/mewcode/context/compact.py`、`tests/test_context_compact.py`

**依赖：** T1、T3、T9

**步骤：**

1. 构建要求“分析草稿后正式摘要”的无工具提示，正式摘要严格包含九个约定段落，且“所有用户消息”原文、“当前工作”详细。
2. 从消息尾部选择约 10,000 Token 或最少五条原文，形成摘要覆盖边界和独立 `System.context` 边界提醒。
3. 自动模式只在超过 `context_window - 13_000` 时调用；`/compact` 用 `context_window - 3_000` 并可主动尝试压缩。
4. 仅持久化正式摘要到 `compact` 事件；草稿、Provider 原始错误和临时提示均不进入 JSONL。
5. 自动连续失败写入计数，第三次打开熔断；手动成功压缩清零并恢复自动压缩。
6. 覆盖九段校验、无工具请求、保留边界、两种余量、草稿不持久化、三次失败和手动恢复。

**验证：** `conda run -n mewcode pytest tests/test_context_compact.py -q`

## T11: 编排 ContextController 的请求前处理和恢复

**文件：** `src/mewcode/context/controller.py`、`src/mewcode/context/__init__.py`、`tests/test_context_artifact.py`、`tests/test_context_compact.py`

**依赖：** T2、T4、T9、T10

**步骤：**

1. 按“工具归档 -> 请求估算 -> 自动压缩”的固定顺序实现 `prepare_request()`，只替换 `Conversation` 内存消息。
2. 实现 `/compact` 使用的 `compact_now()` 与可供 TUI 显示的成功/失败状态文本。
3. 从 `RestoredArchive` 应用所有归档引用、最新有效检查点和失败状态，产出当前 Prompt Context；TUI 可见事件永不交给控制器删除。
4. 超过七天恢复时加入独立、仅模型可见的时效提醒；恢复后首次请求继续遵守窗口预算。
5. 覆盖检查点后的 Context 重建、无检查点重建、TUI 原始消息不丢失、熔断状态恢复、过期提醒和归档后再压缩顺序。

**验证：** `conda run -n mewcode pytest tests/test_context_artifact.py tests/test_context_compact.py -q`

## T12: 将 Context、动态系统提示和自然结束接入 Agent

**文件：** `src/mewcode/agent/__init__.py`、`tests/test_agent.py`

**依赖：** T1、T11、T6、T8

**步骤：**

1. 为 `Agent` 增加可选 ContextController 与提示内容供应器，未提供时保持当前构造和请求行为。
2. 每个迭代创建 `Request` 前运行 Context 预处理，转发其状态 notice，并将隐式上下文填入 `System.context`。
3. 在收到 usage 时将实际输入 token 与当次请求字符量回写 TokenEstimator。
4. 为 `Event` 增加 `natural` 标记；仅最终模型回复无工具调用的成功终止置真，所有取消/错误/保护性停止为假。
5. 覆盖多轮请求前预处理、动态系统上下文、usage 锚、notice 顺序、natural 条件及既有工具/计划/取消行为。

**验证：** `conda run -n mewcode pytest tests/test_agent.py -q`

## T13: 在 CLI 装配进程级存储、指令与记忆服务

**文件：** `src/mewcode/cli.py`、`tests/test_tui.py`

**依赖：** T4、T6、T7

**步骤：**

1. 在现有 Provider/MCP/权限装配后初始化项目存储、一次性 InstructionBundle、MemoryManager、SessionRepository 和后台过期清理任务。
2. 将服务和项目根传给 `MewCodeApp`，不改变 MCP Manager 的注册与关闭顺序。
3. 启动或服务初始化降级时保留可用的 Provider/TUI 路径，清理任务单项失败仅记录日志。
4. 覆盖单/多 Provider 初始化、指令只读一次、清理后台化及既有 MCP/权限回归。

**验证：** `conda run -n mewcode pytest tests/test_tui.py tests/test_mcp_manager.py -q`

## T14: 在 App 中创建、切换和关闭活动会话

**文件：** `src/mewcode/tui/app.py`、`tests/test_tui.py`

**依赖：** T5、T11、T12、T13

**步骤：**

1. Provider 选定后创建 `SessionRuntime`，安装带 ArchiveWriter 回调的 `Conversation`，保存当前 ProviderConfig 的窗口大小。
2. 将 Runtime 的 ContextController 和稳定提示供应器传给每次 `Agent` 创建，确保首条用户消息只启动一次标题任务。
3. 退出和会话替换时关闭旧 Writer、取消依赖旧运行时的标题任务，保持流式取消和 MCP 退出语义。
4. 覆盖单/多 Provider 选定、新会话创建、标题任务安装、关闭和既有输入流程。

**验证：** `conda run -n mewcode pytest tests/test_tui.py -q`

## T15: 实现 Timeline 档案重放和分批加载

**文件：** `src/mewcode/tui/timeline.py`、`src/mewcode/tui/replay.py`、`tests/test_tui_resume.py`

**依赖：** T4

**步骤：**

1. 为 Timeline 增加清空、顶部插入和重放批次支持，保留实时输出时的自动跟随底部行为。
2. 将 message、tool call/result、notice、error 等可见 JSONL 事件映射为现有 Timeline 组件；压缩检查点和隐式上下文不产生条目。
3. 对长档案仅初始挂载最新批次，并提供可触发的“加载更早记录”控件以 prepend 更早事件。
4. 覆盖完整消息/工具重放、压缩检查点共存、顺序、清空、分批加载和无可见事件档案。

**验证：** `conda run -n mewcode pytest tests/test_tui_resume.py -q`

## T16: 实现 `/resume` 选择屏与恢复切换

**文件：** `src/mewcode/tui/resume.py`、`src/mewcode/tui/app.py`、`tests/test_tui_resume.py`

**依赖：** T4、T5、T14、T15

**步骤：**

1. 新增 `RESUMING` 状态和基于 `Input`/`OptionList` 的选择屏，展示标题、ID、相对时间、模型、消息数与文件大小。
2. 实现上下键、输入过滤、Enter 选择和 Esc 取消；扫描前再次运行过期清理。
3. 选择后关闭旧 Writer、从 `RestoredArchive` 创建运行时/Conversation，恢复 Context 并交给重放器；恢复时检查并注入七天时效提醒。
4. Agent 运行或审批时 `/resume` 返回等待提示，恢复状态中拒绝新 Agent 请求。
5. 为每个会话项提供可点击删除按钮；删除成功后刷新当前筛选列表，失败显示状态，不允许该操作删除 memory。
6. 覆盖列表排序、标题回退、筛选、取消、删除成功/失败、坏行恢复、旧 Writer 关闭、Prompt 重建与状态互斥。

**验证：** `conda run -n mewcode pytest tests/test_tui_resume.py tests/test_tui.py -q`

## T17: 实现 `/compact` 本地命令与状态机

**文件：** `src/mewcode/tui/app.py`、`tests/test_tui_resume.py`、`tests/test_tui.py`

**依赖：** T11、T14

**步骤：**

1. 在 IDLE 输入路由中优先识别 `/compact`，绝不将其加入 Conversation 或发送到 Provider 工具循环。
2. 增加 `COMPACTING` 状态，调用活动 ContextController 的手动压缩；期间禁用普通输入和其他本地命令。
3. 成功、无需压缩和失败均渲染明确状态 notice，失败后保留原 Prompt Context 并回到 IDLE。
4. 覆盖 3K 余量、熔断恢复、命令不入档案消息、流式/审批互斥和输入焦点恢复。

**验证：** `conda run -n mewcode pytest tests/test_tui_resume.py tests/test_tui.py -q`

## T18: 在 TUI 自然完成后异步触发自动记忆

**文件：** `src/mewcode/tui/stream.py`、`src/mewcode/tui/app.py`、`tests/test_tui.py`、`tests/test_memory_update.py`

**依赖：** T8、T12、T14

**步骤：**

1. 在收到 `Event(done=True, natural=True)` 后获取 Conversation 的不可变快照，创建 MemoryManager 后台任务。
2. 保证记忆任务不阻塞 `_finish_turn()`、下一条输入、`/compact` 或 `/resume`；非自然结束、取消和错误不触发。
3. 在任务失败时记录错误但不追加伪聊天消息，不改变 TUI 会话状态。
4. 覆盖自然完成触发一次、带先前工具的最终自然回复触发、取消/错误不触发和下一输入无需等待。

**验证：** `conda run -n mewcode pytest tests/test_tui.py tests/test_memory_update.py -q`

## T19: 全量集成、静态检查与验收前回归

**文件：** 全部本章改动、全部测试文件

**依赖：** T1-T18

**步骤：**

1. 运行全量测试，修复新增模块对 Provider、MCP、权限、流式、取消和规划模式的回归。
2. 运行 Ruff、Mypy 与格式检查，消除类型/导入/未使用代码问题。
3. 用临时项目完成一次端到端演练：生成新会话与标题、工具结果归档、手动压缩、退出后 `/resume` 重放、注入指令与记忆索引。
4. 对照 `doc/08/checklist.md`（批准后创建）记录可观察证据，不添加范围外功能。

**验证：**

```powershell
conda run -n mewcode pytest -q
conda run -n mewcode ruff check src tests
conda run -n mewcode mypy src
```

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5
T1 -> T6
T3 -> T7 -> T8
T1 -> T9 -> T10
T2 + T4 + T9 + T10 -> T11 -> T12
T4 + T6 + T7 -> T13
T5 + T11 + T12 + T13 -> T14
T4 -> T15
T4 + T5 + T14 + T15 -> T16
T11 + T14 -> T17
T8 + T12 + T14 -> T18
T1..T18 -> T19
```
