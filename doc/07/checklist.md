# MCP 客户端 Checklist

> 每项必须以测试、命令输出或可观察的运行结果验证，并在验收报告中记录实际证据。

## 配置与发现

- [ ] Provider 仅从 `~/.mewcode/config.yaml` 加载，`MEWCODE_CONFIG` 与项目目录中的配置文件不会改变 Provider 选择。
  验证：运行 `python -m pytest -q tests/test_config.py`，并覆盖用户目录、环境变量和项目目录三种输入。

- [ ] MCP 仅从 `~/.mewcode/mcp.yaml` 加载；文件缺失、`mcp_servers` 缺失或为空时不注册 MCP 工具且应用仍能启动。
  验证：运行 `python -m pytest -q tests/test_mcp_config.py`，观察零 Server 配置和无未捕获异常。

- [ ] `~/.mewcode/mcp.yaml` 解析失败时只输出不包含凭据的 stderr 告警，随后以零 MCP Server 降级。
  验证：向临时用户目录写入非法 YAML，运行 MCP 配置测试并检查错误输出与返回配置。

- [ ] stdio 与 HTTP Server 的必填字段和所有可选字段类型均被校验；非法 Server 被跳过且不会影响有效 Server。
  验证：运行 `python -m pytest -q tests/test_mcp_config.py`，覆盖缺少 `command` / `url`、非法 `type`、非字符串 `args` 项和非法映射值。

- [ ] `${VAR}` 仅在 `env` 与 `headers` 的值中展开；未定义变量替换为空串且每个 Server / 变量仅告警一次；`command`、`args` 和名称保持原文。
  验证：运行 `python -m pytest -q tests/test_mcp_config.py`，检查展开结果、告警次数和未展开字段。

- [ ] 配置示例位于 `.mewcode/mcp-servers.example.yaml`，包含 stdio 与 HTTP Server，且所有凭据均使用 `${VAR}` 引用。
  验证：检查示例文件并运行 `git grep -n -E "(api[_-]?key|token|authorization):[[:space:]]+[^$]" -- .mewcode/mcp-servers.example.yaml`，确认无明文凭据。

## 远端工具适配

- [ ] 每个已发现远端工具均可通过现有 `Tool` 协议调用，名称为 `mcp__<server>__<tool>`，描述非空，输入 JSON Schema 可供 Provider 使用。
  验证：运行 `python -m pytest -q tests/test_mcp_tool.py`，检查名称、描述和 schema。

- [ ] 含非 `[A-Za-z0-9_-]` 字符的完整 MCP 工具名被跳过并产生告警；不同 Server 的同名工具保持隔离。
  验证：运行 `python -m pytest -q tests/test_mcp_tool.py tests/test_mcp_manager.py`。

- [ ] MCP 工具继续接收现有调用链传入的 JSON 字符串；无效 JSON 或非对象参数返回既有结构化参数错误，不调用远端 Server。
  验证：运行 `python -m pytest -q tests/test_mcp_tool.py`，检查调用记录和 `Result.is_error`。

- [ ] 远端文本内容按顺序以换行拼接；远端 `isError` 映射为 `Result.is_error`；非文本内容被丢弃并对每个工具仅告警一次。
  验证：运行 `python -m pytest -q tests/test_mcp_tool.py`，覆盖 TextContent、混合内容和远端错误。

- [ ] 远端调用的超时或协议异常转换为结构化错误结果回灌，Agent Loop 可继续后续回合。
  验证：运行 `python -m pytest -q tests/test_mcp_tool.py tests/test_agent.py`，检查超时/异常结果和后续 Agent 行为。

## 连接与生命周期

- [ ] stdio Server 完成初始化、工具列举和调用，配置 `env` 会覆盖子进程同名宿主环境；退出时子进程被清理。
  验证：运行 `python -m pytest -q tests/test_mcp_manager.py`，使用测试 Server 检查握手、环境值和进程收尾。

- [ ] Streamable HTTP Server 完成初始化、工具列举和调用，配置 `headers` 出现在请求中；退出时会话关闭。
  验证：运行 `python -m pytest -q tests/test_mcp_manager.py`，使用本地测试端点检查请求头和关闭行为。

- [ ] Server 连接、初始化或列工具失败时只跳过该 Server；其他 Server 和六个内置工具仍可用。
  验证：运行 `python -m pytest -q tests/test_mcp_manager.py`，用成功与失败 Server 并发连接并检查最终工具集。

- [ ] 每个 Server 启动序列在 30 秒内超时，失败资源立即关闭；成功工具按全名稳定排序，同一 Server 重复工具名仅保留最后一个并告警。
  验证：运行 `python -m pytest -q tests/test_mcp_manager.py`，在测试中缩短超时并检查资源关闭、排序和去重结果。

- [ ] 应用退出时 Manager 在总计五秒内关闭已成功建立的会话；关闭异常或超时不会阻塞退出。
  验证：运行 `python -m pytest -q tests/test_mcp_manager.py`，在测试中缩短关闭超时并确认返回与告警。

## 集成与权限

- [ ] CLI 在创建权限引擎和 TUI 前完成 MCP 注册；TUI 运行期间工具集保持稳定；退出时无论正常或异常均执行 Manager 关闭。
  验证：运行 `python -m pytest -q tests/test_config.py tests/test_mcp_manager.py`，检查启动顺序、注册结果和 `finally` 清理。

- [ ] MCP 只读工具按现有权限链路视为读取操作并可并发；其他 MCP 工具默认请求确认；精确规则和 `mcp__<server>__*` 规则均可生效。
  验证：运行 `python -m pytest -q tests/test_permission.py tests/test_agent.py`，增加 MCP 名称、只读标记和规则匹配场景。

- [ ] 黑名单与路径沙箱不误用于 MCP 工具；MCP 工具仍由规则和模式兜底保护。
  验证：运行 `python -m pytest -q tests/test_permission.py`，检查未知工具目标提取、默认 Ask 与 bypass 行为。

- [ ] Anthropic 与 OpenAI Provider 使用相同的 MCP 工具定义和调用路径，Provider 模块无 MCP 专用改动。
  验证：运行 `python -m pytest -q tests/test_anthropic_system.py tests/test_llm_helpers.py`，并检查 `git diff -- src/mewcode/llm` 无差异。

## 回归与端到端

- [ ] 端到端场景：用户配置一个有效 MCP Server 后启动 MewCode，成功发现的工具与六个内置工具同时出现在工具中心；模型调用 MCP 工具后文本结果回灌会话。
  验证：运行包含测试 MCP Server 的集成测试，或手动启动 MewCode 并记录发现工具及工具结果。

- [ ] 端到端边界场景：MCP 配置文件非法或某个 Server 超时，MewCode 记录告警并仍以可用的 Provider、内置工具和其他成功 MCP 工具进入 TUI。
  验证：运行 `python -m pytest -q tests/test_mcp_config.py tests/test_mcp_manager.py`，检查 stderr 与最终工具列表。

- [ ] 所有测试、编译和静态检查通过，且不会产生格式差异。
  验证：依次运行：

```powershell
python -m pytest -q
python -m compileall src\mewcode examples
python -m ruff check .
python -m ruff format --check .
```
