# MewCode 交互式对话 TUI 验收清单

> 每一项都必须通过运行代码、测试或观察行为验证。

## 实现完整性

- [ ] 项目可以作为 Python 3.12 本地包运行（验证：在 Python 3.12 环境执行 `python -m compileall mewcode` 成功）
- [ ] CLI 支持 `--profile <name>` 并按名称选择 provider profile（验证：运行 `pytest tests/test_cli.py::test_cli_uses_selected_profile` 通过）
- [ ] CLI 支持 `--config <path>` 并默认读取 `mewcode.yaml`（验证：运行 `pytest tests/test_cli.py` 通过）
- [ ] YAML 配置支持顶层 `providers` 列表和多个 profile（验证：运行 `pytest tests/test_config.py::test_loads_multiple_profiles` 通过）
- [ ] 每个 profile 支持 `name`、`protocol`、`model`、`base_url`、`api_key` 和可选 `thinking`（验证：运行 `pytest tests/test_config.py` 通过）
- [ ] 缺失配置、无效配置或不存在的 profile 会输出清晰中文错误并拒绝进入聊天循环（验证：运行 `pytest tests/test_config.py tests/test_cli.py` 通过）
- [ ] 终端对话循环支持中文欢迎语、中文提示符、中文错误信息和中文退出命令（验证：运行 `pytest tests/test_chat.py` 通过）
- [ ] 空输入不会发送给 Provider（验证：运行 `pytest tests/test_chat.py::test_empty_input_is_ignored` 通过）
- [ ] 用户输入 `/exit`、`/quit`、`退出` 或 `再见` 可以干净退出（验证：运行 `pytest tests/test_chat.py::test_exit_commands_stop_chat` 通过）
- [ ] 本阶段没有暴露工具调用、文件操作、代码编辑或 Shell 执行入口（验证：检查 `README.md` 范围说明，并运行 `pytest` 确认公共接口只覆盖纯对话）

## Provider 与流式协议

- [ ] Provider 层通过统一 `ChatProvider.stream_chat()` 接口向会话层暴露流式文本（验证：运行 `pytest tests/test_chat.py`，fake provider 与真实 provider 类型接口一致）
- [ ] OpenAI 兼容 Provider 使用 `POST {base_url}/chat/completions`、Bearer API Key 和 `stream: true`（验证：运行 `pytest tests/test_openai_provider.py::test_openai_request_shape` 通过）
- [ ] OpenAI 兼容 Provider 从 SSE chunk 中逐步产出 `choices[0].delta.content`（验证：运行 `pytest tests/test_openai_provider.py::test_openai_streams_text_chunks` 通过）
- [ ] Anthropic Provider 使用 `POST {base_url}/messages`、`x-api-key`、`anthropic-version` 和 `stream: true`（验证：运行 `pytest tests/test_anthropic_provider.py::test_anthropic_request_shape` 通过）
- [ ] Anthropic Provider 从 `content_block_delta` 的 `text_delta` 逐步产出可见文本（验证：运行 `pytest tests/test_anthropic_provider.py::test_anthropic_streams_text_chunks` 通过）
- [ ] `thinking: true` 的 Anthropic profile 会在请求中包含 extended thinking 配置（验证：运行 `pytest tests/test_anthropic_provider.py::test_anthropic_includes_thinking_when_enabled` 通过）
- [ ] Anthropic Provider 不向 TUI 输出 thinking delta 或 signature delta（验证：运行 `pytest tests/test_anthropic_provider.py::test_anthropic_ignores_non_text_deltas` 通过）
- [ ] SSE 解析器支持多行 data、event 字段、注释行和末尾无空行事件（验证：运行 `pytest tests/test_sse.py` 通过）

## 集成行为

- [ ] 用户消息会连同之前会话历史发送给 Provider（验证：运行 `pytest tests/test_chat.py::test_chat_sends_full_history_each_turn` 通过）
- [ ] 流式响应的每个文本片段都会立即写入终端并 flush（验证：运行 `pytest tests/test_chat.py::test_stream_chunks_are_flushed` 通过）
- [ ] 流成功完成后，完整助手回复会加入后续会话历史（验证：运行 `pytest tests/test_chat.py::test_successful_reply_is_saved_to_history` 通过）
- [ ] API 请求失败或流中断时，终端显示中文错误，用户仍可继续输入或退出（验证：运行 `pytest tests/test_chat.py::test_provider_error_allows_continuing` 通过）
- [ ] Provider 状态码错误、错误事件和 JSON 解析失败会转换为用户可理解的 Provider 错误（验证：运行 `pytest tests/test_openai_provider.py tests/test_anthropic_provider.py` 通过）
- [ ] API Key 不会出现在配置错误、Provider 错误、CLI 错误或测试捕获的输出中（验证：运行 `pytest tests/test_config.py tests/test_cli.py tests/test_openai_provider.py tests/test_anthropic_provider.py` 通过）
- [ ] Provider 工厂能根据 `protocol` 创建 OpenAI 或 Anthropic Provider（验证：运行 `pytest tests/test_cli.py` 或全量 `pytest` 通过）

## 构建与测试

- [ ] 所有 Python 模块编译通过（验证：运行 `python -m compileall mewcode` 成功）
- [ ] 全量测试套件通过（验证：运行 `pytest` 成功）
- [ ] 项目文本文件、示例配置和规格文档都可按 UTF-8 解码（验证：运行 `pytest tests/test_utf8.py` 通过）
- [ ] 项目文本文件不包含 Unicode replacement character（验证：运行 `pytest tests/test_utf8.py` 通过）
- [ ] `python -m mewcode` 入口可导入并调用 CLI 入口（验证：运行 `pytest tests/test_cli.py` 和 `python -m compileall mewcode` 成功）
- [ ] README 中的配置结构与实际配置加载逻辑一致（验证：对照 `README.md`、`examples/mewcode.yaml.example` 和 `pytest tests/test_config.py` 结果）

## 端到端场景

- [ ] 场景 1：给定包含 OpenAI 与 Claude 两个 profile 的 YAML，使用 `--profile openai` 启动后进入中文聊天流程（验证：使用 fake chat/CLI 测试运行，观察返回码为 0 且输出包含中文欢迎语）
- [ ] 场景 2：给定不存在的 profile 名称，启动时输出中文错误且不进入聊天循环（验证：运行 CLI 测试，观察非零返回码和中文错误）
- [ ] 场景 3：用户输入中文问题，fake OpenAI SSE 返回多个中文 chunk，终端逐步显示完整中文回复（验证：运行 OpenAI provider 流式测试和 chat 流式测试）
- [ ] 场景 4：用户输入中文问题，fake Anthropic SSE 返回多个 `text_delta`，终端逐步显示完整中文回复（验证：运行 Anthropic provider 流式测试和 chat 流式测试）
- [ ] 场景 5：Claude profile 启用 `thinking` 后，fake HTTP transport 捕获到 extended thinking payload，同时 TUI 不显示 thinking 内容（验证：运行 Anthropic thinking 测试）
- [ ] 场景 6：同一会话连续输入两轮中文问题，第二轮 Provider 收到第一轮用户消息和助手回复（验证：运行 chat history 测试）
- [ ] 场景 7：用户输入 `退出` 后程序返回 0，并且不再调用 Provider（验证：运行 chat exit 测试）
