# MCP 客户端 Tasks

## 文件清单

| 操作 | 文件                                  | 职责 |
|---|-------------------------------------|---|
| 修改 | `pyproject.toml`                    | 声明 MCP SDK 运行依赖。 |
| 修改 | `src/mewcode/config.py`             | Provider 固定发现用户级配置。 |
| 修改 | `src/mewcode/cli.py`                | 在 TUI 生命周期中装配和关闭 MCP Manager。 |
| 修改 | `src/mewcode/permission/rule.py`    | 支持 MCP 工具名称的 Server 级通配规则。 |
| 新建 | `src/mewcode/mcp/__init__.py`       | 导出 MCP 客户端公共接口。 |
| 新建 | `src/mewcode/mcp/config.py`         | 加载并校验用户级 MCP 配置。 |
| 新建 | `src/mewcode/mcp/tool.py`           | 将远端 MCP 工具适配为既有 Tool 协议。 |
| 新建 | `src/mewcode/mcp/manager.py`        | 建立、保有和关闭 MCP Server 会话。 |
| 修改 | `tests/test_config.py`              | 验证 Provider 仅从用户级配置发现。 |
| 新建 | `tests/test_mcp_config.py`          | 验证 MCP 配置加载、展开、校验与降级。 |
| 新建 | `tests/test_mcp_tool.py`            | 验证远端工具适配与调用回灌。 |
| 新建 | `tests/test_mcp_manager.py`         | 验证连接并发、隔离、资源关闭与工具发现。 |
| 新建 | `.mewcode/mcp-servers.example.yaml` | 提供不含明文凭据的 MCP 配置示例。 |

## T1: 固定配置边界与 MCP 依赖

**文件：** `pyproject.toml`、`src/mewcode/config.py`、`tests/test_config.py`

**依赖：** 无

**步骤：**

1. 在运行依赖中添加官方 `mcp` SDK。
2. 移除 `MEWCODE_CONFIG` 与项目目录的 Provider 配置发现分支。
3. 将 Provider 配置发现固定为 `Path.home() / ".mewcode" / "config.yaml"`。
4. 保持既有 Provider 配置内容校验及错误提示行为。
5. 覆盖固定用户目录、忽略环境变量和忽略当前项目配置的发现行为。

**验证：** 运行 `python -m pytest -q tests/test_config.py`；Provider 配置测试全部通过。

## T2: MCP 配置加载与校验

**文件：** `src/mewcode/mcp/__init__.py`、`src/mewcode/mcp/config.py`、`tests/test_mcp_config.py`

**依赖：** T1

**步骤：**

1. 定义归一化的 Server 配置和 MCP 配置公共数据结构。
2. 仅加载 `~/.mewcode/mcp.yaml` 的 `mcp_servers` 段；缺失文件、缺失段或空段返回零 Server 配置。
3. 对 YAML 读取或解析失败输出不包含敏感值的告警，并返回零 Server 配置。
4. 校验 Server 名、传输类型、必填字段以及 `args`、`env`、`headers` 的完整类型约束；非法 Server 告警并跳过。
5. 只在 `env` 和 `headers` 的值中展开 `${VAR}`；未定义变量替换为空串并按 Server 和变量去重告警。
6. 导出 `Config`、`ServerConfig` 和 `load_config`。

**验证：** 运行 `python -m pytest -q tests/test_mcp_config.py`；覆盖空配置、非法 YAML、stdio/HTTP 校验、变量展开和非展开字段。

## T3: 远端工具适配

**文件：** `src/mewcode/mcp/tool.py`、`tests/test_mcp_tool.py`

**依赖：** T1

**步骤：**

1. 定义可由测试替身实现的 MCP 调用会话协议。
2. 将远端工具转换为现有 `mewcode.tool.Tool` 接口，保留 `name()`、`description()`、`parameters()`、`read_only` 与 `execute(args: str)` 契约。
3. 生成合法命名空间名称 `mcp__<server>__<tool>`，跳过含非法字符的名称并告警。
4. 透传输入 JSON Schema，提供缺失描述和缺失 Schema 的安全兜底；仅把严格的 `readOnlyHint == True` 映射为只读。
5. 使用既有 `parse_arguments` 解析 JSON 字符串参数；解析失败返回现有结构化错误。
6. 调用远端工具并处理 30 秒超时、协议异常、远端错误标记和文本内容拼接；非文本内容只告警一次且不回灌。

**验证：** 运行 `python -m pytest -q tests/test_mcp_tool.py`；覆盖成功、参数错误、远端 isError、超时、异常、非法名称和非文本内容。

## T4: MCP 连接与生命周期管理

**文件：** `src/mewcode/mcp/manager.py`、`src/mewcode/mcp/__init__.py`、`tests/test_mcp_manager.py`

**依赖：** T2、T3

**步骤：**

1. 为 stdio 与 Streamable HTTP 配置使用官方 SDK 创建传输和 `ClientSession`。
2. 在单个 Server 的局部退出栈中完成初始化握手、工具列举和适配；只有完整成功后才将关闭回调转移给 Manager。
3. 并发连接全部 Server，每个连接流程应用 30 秒超时；失败、超时或握手异常仅告警并跳过该 Server。
4. 合并成功工具并按全名稳定排序；同一 Server 的重复远端工具名仅保留最后一个并告警。
5. 实现 `tools()` 副本返回，以及带五秒总超时的 `close()`，确保关闭异常或超时不阻塞程序退出。
6. 仅把成功会话保留在 Manager，确保失败连接的子进程或 HTTP 会话立即释放。

**验证：** 运行 `python -m pytest -q tests/test_mcp_manager.py`；覆盖连接成功、并发失败隔离、连接超时、工具排序/去重、失败资源释放和关闭超时。

## T5: CLI 装配与异步应用生命周期

**文件：** `src/mewcode/cli.py`、`src/mewcode/permission/rule.py`、`tests/test_config.py`、`tests/test_mcp_manager.py`、`tests/test_permission.py`

**依赖：** T1、T2、T4

**步骤：**

1. 为 `mcp__<server>__*` 规则启用仅限 MCP 工具名的 glob 匹配，保持其他工具规则的精确匹配语义。
2. 保留 Provider 配置错误的现有命令行错误处理和退出码。
3. 新增异步应用入口：创建默认工具中心，加载 MCP 配置，连接 Manager，并注册发现工具。
4. 在创建权限引擎和 TUI 前完成 MCP 注册，确保进入 TUI 后工具集合稳定。
5. 使用 `MewCodeApp.run_async()` 在同一事件循环中运行 TUI，并以 `try/finally` 调用 Manager 的关闭方法。
6. 用 `asyncio.run()` 从同步 CLI `main()` 进入异步生命周期，保留 KeyboardInterrupt 和运行错误的既有用户可见行为。

**验证：** 运行 `python -m pytest -q tests/test_config.py tests/test_mcp_manager.py tests/test_permission.py`；断言启动顺序、注册结果、退出关闭和 MCP 通配权限规则。

## T6: 配置示例与完整回归

**文件：** `.mewcode/mcp-servers.example.yaml`

**依赖：** T1、T2、T3、T4、T5

**步骤：**

1. 提供 `~/.mewcode/mcp.yaml` 的示例，展示一个 stdio Server 和一个 HTTP Server。
2. 在示例中仅以 `${VAR}` 引用环境中的 token 或密钥，不写入真实凭据。
3. 对照规格验收标准检查配置隔离、权限分类、错误回灌与清理行为。
4. 运行完整测试、编译和静态检查，修复所有回归或格式问题。

**验证：** 依次运行：

```powershell
python -m pytest -q
python -m compileall src\mewcode examples
python -m ruff check .
python -m ruff format --check .
```

## 执行顺序

```text
T1 -> T2 -> T4 -> T5 -> T6
      \-> T3 -/
```
