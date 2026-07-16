# MCP 客户端 Spec

## 背景

mewcode 已经是一个能自主多轮干活、且有五层安全护栏的 coding agent。但**工具集是写死的 6 个内置工具**（读 / 写 / 改文件、命令执行、按模式找文件、搜内容）——想让它会用 GitHub、查数据库、调内部服务，只能改源码、重新打包，能力边界锁死在编译期。

MCP（Model Context Protocol）是一套开放标准，用统一的 JSON-RPC 协议把"提供工具的一方（server）"与"使用工具的一方（client）"解耦，社区已有大量现成 server（GitHub、Slack、SQLite、文件系统……）。给 mewcode 装上 **MCP 客户端**：启动时按配置自动发现并连接外部 server，把它们的工具包装成 mewcode 已有的工具抽象、注册进工具中心，Agent 调用时与内置工具**完全无感**，并自动复用已有的权限护栏。这是从"工具集固定"到"工具生态可插拔"的一跃——给 mewcode 装上扩展坞。

## 目标

- **配置驱动的自动发现**：启动时从配置声明的 server 列表自动连接、列出工具、注册进工具中心，无需改代码。
- **两种传输**：本地 server 走子进程标准输入输出管道（stdio）；远程 server 走 Streamable HTTP。
- **标准三步会话**：每个 server 一次连接经过 初始化握手 → 列出工具 → 按需调用工具（协议细节由官方 Python SDK `mcp`（`pip install mcp`）承载，不自研协议栈）。
- **无感适配**：发现到的远端工具包装成与内置工具一致的抽象，Agent 编排层与 provider 适配层均无需感知其来自远端。
- **命名空间隔离**：远端工具统一加 `mcp__<server>__<tool>` 前缀，杜绝与内置工具及多 server 间的重名冲突，并保留来源可追溯。
- **多 server 生命周期管理**：每个连接各自独立缓存与管理；单个 server 连接 / 初始化 / 列工具失败只跳过它自身，不影响其它 server、不影响启动；程序退出时统一、干净地关闭全部连接（含终止 stdio 子进程）。
- **独立用户级配置**：Provider 固定从用户级配置读取；MCP Server 固定从单独的用户级 MCP 配置读取，两者互不干扰。
- **凭据不落盘**：配置中环境变量与请求头的值支持从宿主环境变量展开（`${VAR}`），密钥不写进配置文件。
- **复用权限**：MCP 工具走已有的「规则 → 模式兜底 → 人在回路」链路，默认按命令执行类每次确认，自报只读（`readOnlyHint`）的按只读类放行并可并发；仅扩展规则匹配以支持 `mcp__<server>__*`，其余权限行为不变。
- **不破坏既有能力**：已有的会话、Loop、流式、缓存、规划、权限五层等行为不退化。

## 功能需求

- **F1: MCP YAML 配置加载**
  仅从用户级 `~/.mewcode/mcp.yaml` 读取 `mcp_servers` 段（map：key 为 server 名，value 为 server 定义）。文件缺失、`mcp_servers` 顶层不存在或为空时，视为零个 MCP server 并正常进入 TUI；文件格式非法时 stderr 告警并忽略 MCP 配置，绝不致启动失败或抛未捕获异常。

- **F1a: Provider 配置发现范围**
  Provider 仅从用户级 `~/.mewcode/config.yaml` 读取，不再支持 `MEWCODE_CONFIG`，也不读取任何项目级配置。该文件仍必须包含有效且非空的 `providers` 列表；MCP 配置位于独立的 `~/.mewcode/mcp.yaml`，不影响 Provider 配置加载。

- **F2: server 类型与必填字段**
  每个 server 定义自带 `type` 字段（**显式**：`stdio` 或 `http`），不靠字段嗅探判定类型。
  - `stdio` 类型必填 `command`（字符串）；可选 `args`（字符串数组）、`env`（字符串 map）。
  - `http` 类型必填 `url`（字符串）；可选 `headers`（字符串 map）。
  字段缺失或 `type` 非法时**跳过该 server 并 stderr 告警**，不影响其它 server 加载。

- **F3: 环境变量展开**
  `env` 与 `headers` 的**值**支持 `${VAR}` 形式从宿主环境变量取值；展开发生在配置加载阶段、不污染原始配置文件。**未定义的 `${VAR}` 展开为空串并 stderr 告警**，但不阻断该 server 启动（让 server 自行决定无凭据时是否报错）。`command` / `args` 与 server 名、工具名**不做展开**（避免命令/名字被环境间接影响产生隐性歧义）。

- **F4: stdio 传输**
  对 `stdio` 类型 server，以 `command` + `args` 启动子进程；通过子进程的标准输入输出按 JSON-RPC 帧通信（由 SDK 的 `stdio_client` + `StdioServerParameters` 完成）。`env` 与宿主进程环境合并后注入子进程（同名宿主变量被 `env` 覆盖，便于按 server 配置注入凭据）。子进程 `stderr` 透传给宿主 stderr 便于排查。子进程在 mewcode 退出时一并干净终止（关闭其 stdin → 等待 → 必要时发信号；由 SDK 的 `async with` 上下文管理器承载）。

- **F5: Streamable HTTP 传输**
  对 `http` 类型 server，以 `url` 为 endpoint 走 Streamable HTTP（由 SDK 的 `streamable_http_client` 完成）；配置中的 `headers` 注入每次 HTTP 请求（用于 `Authorization` 等鉴权头）。**不订阅服务器推送的独立 SSE 通道**（本章只用请求-响应式工具调用，无需 server 主动推送），减少长连接维护成本。

- **F6: 标准三步会话**
  每个 server 建立后依次完成 **`session.initialize()` 握手**（交换 protocolVersion 与 capabilities）→ **`session.list_tools()` 列出工具** → 进入按需 **`session.call_tool()` 调用**阶段。整个协议层（JSON-RPC 编解码、请求/响应 id 配对、握手细节、传输细节）**由官方 Python SDK 承载**，不自研协议栈。本章只覆盖工具能力，**不订阅 / 不实现** MCP 的资源（resources）、提示词（prompts）、采样（sampling）、引导（roots）等其它能力。

- **F7: 工具适配（远端工具 ↔ 内置 Tool 抽象）**
  把 server 返回的每个远端工具包装成一个实现 mewcode `Tool` 协议的对象，注册进工具中心：
  - **名字**：`mcp__<server>__<tool>`（见 F8）。
  - **描述**：直接取远端 `description`（空则给一个含 server 名的兜底说明）。
  - **参数 schema**：把远端 `inputSchema` 转成 mewcode 的 `dict[str, Any]` 形式（透传 JSON Schema），不二次裁剪。
  - **只读性**：远端 `annotations.readOnlyHint==True` → `read_only==True`；其余（含字段缺失/非法）→ `False`（安全默认按有副作用处理）。
  - **执行**：调用时通过该 server 的会话发 `call_tool`；远端返回的 `content` 中文本块（`TextContent`）的文本按顺序拼成 mewcode `ToolResult.content`，远端 `isError==True` 映射为 `ToolResult.is_error==True`；非 text 块（image / audio / resource_link / embedded_resource 等）静默丢弃并 stderr 告警一次；调用过程中协议错误（连接断、超时、传输错）也转成 `is_error==True` 的结构化错误**回灌给模型**（不向 Agent Loop 抛 Python 异常，复用不中断会话的契约）。Agent 与 provider 适配层不感知"该工具来自远端"。

- **F8: 工具命名空间**
  所有 MCP 工具统一以 `mcp__<server>__<tool>` 命名（`server` 与 `tool` 名按配置/远端原样保留）。命名空间用途双重：
  - **避免冲突**：同名远端工具在不同 server 互不干扰；与 6 个内置工具天然不重名。
  - **可追溯**：单看工具名能识别来源 server，便于日志、人在回路弹窗、权限规则书写。
  注册时若仍发生同名（同 server 自报多个同名工具的边界情形）则后注册者保留并 stderr 告警；若工具名经前缀拼接后含 LLM 工具名禁用字符（非 `[A-Za-z0-9_-]`），**跳过该工具并 stderr 告警**。

- **F9: 启动同步连接 + 单 server 30s 超时 + 失败隔离**
  在进入 TUI 之前**同步**对所有配置中的 server 发起连接 + 握手 + 列工具（实现并发用 `asyncio.gather` 缩短总时延）；**每个 server 的整个启动序列受 30s 超时约束**（内置不可配，用 `asyncio.wait_for`）。任一 server 的连接 / 握手 / 列工具失败或超时**只跳过它自身**：mewcode 启动不被阻断、其它 server 与内置工具集照常注册可用、stderr 给出该 server 的失败原因。所有 server 连接尝试结束后才进入 TUI；进入 TUI 时工具中心呈现的就是"内置 6 工具 + 成功连上的 server 工具"全集，Agent 在任意一轮看到的工具集稳定不变。

- **F10: 工具调用超时**
  每次 `call_tool` 复用 30s 超时（与连接超时同值，**内置不可配**，用 `asyncio.wait_for`）；超时按 F7 转成 `is_error==True` 的结构化错误回灌给模型，Agent Loop 继续。

- **F11: 退出时统一关闭**
  mewcode 正常退出（用户主动退出、致命错收尾）时，对所有已建立的会话统一调用关闭逻辑：stdio server 的子进程被干净终止（先关 stdin、给 server 自然退出窗口、必要时发信号），HTTP server 的会话用 DELETE 通知 server 释放（由 SDK 处理）。退出**不**强行等待所有连接关闭完成超过若干秒（整体兜底 5s，避免某 server 卡住拖死整个程序退出）。

- **F12: 权限链路无感复用**
  MCP 工具走现有判定链路：
  - 黑名单仅作用于内置 `bash` 命令串，对 MCP 工具不命中（`extract_target` 对未知工具返回 target=""，自动跳过）。
  - 沙箱仅作用于内置文件类工具，对 MCP 工具不适用（`extract_target` 对未知工具返回 `is_file=False`，自动跳过）。
  - 规则引擎按 `mcp__<server>__<tool>` 作为友好名匹配（`friendly_name` 对未知名原样返回）；用户可用精确名 `mcp__github__create_issue` 或带 `*` 的 `mcp__github__*` 写 allow/deny 规则。
  - 模式兜底：`read_only==True` 的 MCP 工具归 `CategoryRead`，default 下直接放行、可并发；其余归 `CategoryExec`，default 与 acceptEdits 下每次触发人在回路 Ask；bypass 下放行。
  为支持 Server 级规则，权限规则匹配仅对以 `mcp__` 开头且含 `*` 的工具名启用通配匹配；其余权限分类、黑名单、沙箱与模式兜底行为保持不变。

## 非功能需求

- N1: 失败隔离不阻塞——单 server 任意阶段（连接 / 握手 / 列工具 / 调用）失败或卡住，只跳过它自身、不阻塞 mewcode 启动、不影响其它 server 与内置工具；连接卡住时 30s 超时强制收尾，绝不死锁。
- N2: 安全默认——`readOnlyHint` 缺失或非法 → 非只读（默认走 Ask）；`${VAR}` 未定义 → 空串（不替 server 拍板）；type 非法 / 字段缺失 → 跳过该 server（不静默放行未定义 server）。
- N3: 跨协议一致——MCP 工具行为与 provider（Anthropic / OpenAI）无关；provider 适配层零修改。
- N4: 权限兼容——MCP 工具走既有分类、黑名单、沙箱、规则优先级与模式兜底链路；仅扩展 `mcp__<server>__*` 工具规则的匹配能力。
- N5: 不破坏既有能力——会话、Loop、流式、缓存、规划、人在回路、并发、用户取消、保序回灌等既有能力不退化。
- N6: 凭据不落盘——api_key / token 不出现在配置文件；env / headers 通过 `${VAR}` 引用宿主环境；敏感值在日志/状态栏/任何输出中不回显。
- N7: 退出干净——程序退出时不泄漏子进程、不泄漏 asyncio task、不死锁；某 server 关闭卡住不阻塞整体退出（整体退出关闭兜底超时 5s）。
- N8: 代码规范——`ruff check` / `ruff format --check` / `mypy`（可选 strict 子集）/ `pytest` 全过（本项目为 Python，遵循 CLAUDE.md 等价规范）。
- N9: 配置隔离——Provider 只读取 `~/.mewcode/config.yaml`，MCP 只读取 `~/.mewcode/mcp.yaml`；任一配置的内容不会被另一配置解释。

## 不做的事

- **MCP 资源（resources）、提示词（prompts）、采样（sampling）、引导（roots）**——本章只覆盖工具能力。
- **tools/list 变更通知 / 调用进度通知**——不订阅独立 SSE 通道（SDK 默认开，本章显式关闭或不消费），工具集快照固定在启动时。
- **健康检查 / 自动重连 / 退避**——单连接挂掉就挂掉，留待后续章节。
- **配置热加载 / 运行时增减 server**——重启 mewcode 才能应用新配置。
- **项目级、环境变量或多层 MCP 配置**——不读取项目目录、环境变量或其他位置的 MCP Server 配置，也不进行配置合并。
- **`command` / `args` / 工具名 / server 名 的变量展开**——仅 env / headers 的值展开 `${VAR}`。
- **OAuth 完整鉴权流程**——仅支持 `headers` 直传静态 token；需要 OAuth 的 server 让用户自行预换 token 写入 headers。
- **自定义连接 / 调用超时**——30s 硬编码，不暴露配置项。
- **MCP 工具的黑名单与路径沙箱扩展**——这两层只对内置工具有意义，MCP 工具仅走规则 + 模式兜底 + 人在回路。
- **非文本内容块的回灌**——仅收集 `TextContent` 的内容块拼成 ToolResult；image / audio / resource_link / embedded_resource 等静默丢弃并 stderr 告警一次。
- **资源配额 / 速率限制 / 审计日志**。
- **MCP server 端的实现**——mewcode 仅作 client。

## 验收标准

- AC1: MCP 配置加载——仅 `~/.mewcode/mcp.yaml` 中的 `mcp_servers` 被加载；文件缺失、`mcp_servers` 缺失或为空时不注册 MCP 工具且正常启动；文件非法时 stderr 告警并继续启动。（F1/N1）
- AC1a: Provider 配置发现范围——Provider 仅从 `~/.mewcode/config.yaml` 成功加载；设置 `MEWCODE_CONFIG` 或在项目目录放置配置文件均不会改变实际加载的 Provider 配置。（F1a/N9）
- AC2: 字段校验——stdio 类型缺 command、http 类型缺 url、type 非法或缺失时，该 server 被跳过并 stderr 告警，其它 server 不受影响。（F2/N2）
- AC3: 变量展开——env / headers 的值 `${VAR}` 从宿主环境取值；未定义变量展开为空串并告警；command / args / 工具名 / server 名不展开。（F3/N2/N6）
- AC4: stdio 启动 + 子进程终止——能拉起一个 stdio MCP server 子进程，握手 + 列工具成功；env 注入生效；mewcode 退出时子进程被终止、无僵尸。（F4/F6/F11/N7）
- AC5: HTTP 连接 + 自定义 headers——能对一个 HTTP MCP server 完成握手 + 列工具；`headers` 注入到 HTTP 请求中。（F5/F6/N6）
- AC6: 工具适配与命名——同一 server 的工具列出后注册进 registry，名字符合 `mcp__<server>__<tool>`，描述非空，参数 schema 透传；调用时远端 text content 拼接为 `ToolResult.content`，远端 isError 映射到 `ToolResult.is_error`；非 text 块静默丢弃。（F6/F7/F8）
- AC7: 命名空间隔离——同名工具来自不同 server 不互相覆盖；与 6 个内置工具天然不重名；前缀拼接后含 LLM 工具名禁用字符（非 `[A-Za-z0-9_-]`）的工具被跳过并告警。（F8）
- AC8: 启动失败隔离 + 30s 超时——单 server 连接 / 握手 / 列工具失败或超时，只跳过它自身，其它 server 与内置工具集照常注册；失败原因 stderr 可见；启动总时延上界受 30s 约束（并发实现）。（F9/N1）
- AC9: 调用超时与错误回灌——`call_tool` 30s 超时或协议错误转为 `is_error==True` 的结构化错误结果回灌给模型，Agent Loop 不中断，可在后续轮调整。（F7/F10/N5）
- AC10: 退出干净——程序退出时所有 stdio 子进程被终止、HTTP 会话被关闭；关闭过程不泄漏 task、不卡死（总超时 5s 兜底）。（F11/N7）
- AC11: 权限链路自然命中——`mcp__<server>__*` 形式的 allow / deny 规则正确作用到对应 MCP 工具；未写规则时 `readOnlyHint==True` 的 MCP 工具按只读类放行并可并发，其余按命令执行类触发人在回路 Ask；bypass 模式下放行（黑名单 / 沙箱对 MCP 工具不命中，自动跳过）。（F12/N4）
- AC12: 跨协议一致——同一 MCP server 在 Anthropic 与 OpenAI 两种 provider 下行为一致；provider 适配层零 diff。（N3）
- AC13: 不破坏既有能力——既有所有测试通过；多轮连环、用户取消、流出错恢复、历史一致、缓存命中、规划按轮次注入、五层权限等行为不退化。（N5）
- AC14: 凭据不落盘——配置示例与说明均用 `${VAR}` 引用密钥；`git grep` 在配置文件中无 token 明文命中。（N6）
- AC15: 代码规范——`ruff format --check .` 无 diff；`ruff check .` 无告警；`pytest`（含 `tests/test_mcp_*.py`）通过；`pytest -m "asyncio"` 在 `tests/test_mcp_*.py` 下无悬挂 task / 死锁。（N8）
