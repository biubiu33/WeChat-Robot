# MewCode 交互式对话 TUI 任务拆分

## 文件列表

| 动作 | 文件 | 职责 |
|------|------|------|
| 创建 | `pyproject.toml` | Python 3.12 包元数据、依赖、命令入口和测试配置 |
| 创建 | `README.md` | 中文项目说明、运行方式和配置示例 |
| 创建 | `examples/mewcode.yaml.example` | UTF-8 示例 YAML，多 provider profile |
| 创建 | `mewcode/__init__.py` | 包版本 |
| 创建 | `mewcode/__main__.py` | `python -m mewcode` 入口 |
| 创建 | `mewcode/models.py` | `ProviderProfile`、`ChatMessage`、`StreamChunk` |
| 创建 | `mewcode/errors.py` | 通用错误类型 |
| 创建 | `mewcode/config.py` | UTF-8 YAML 加载、配置校验、profile 选择 |
| 创建 | `mewcode/sse.py` | 通用 SSE 事件解析 |
| 创建 | `mewcode/http.py` | `httpx.Client` 创建 |
| 创建 | `mewcode/io.py` | 可测试终端 IO 封装 |
| 创建 | `mewcode/chat.py` | 中文交互式会话循环和流式打印 |
| 创建 | `mewcode/cli.py` | CLI 参数解析、错误处理和入口返回码 |
| 创建 | `mewcode/providers/__init__.py` | Provider 子包导出 |
| 创建 | `mewcode/providers/base.py` | Provider 协议和脱敏工具 |
| 创建 | `mewcode/providers/factory.py` | Provider 工厂 |
| 创建 | `mewcode/providers/openai.py` | OpenAI 兼容流式 Provider |
| 创建 | `mewcode/providers/anthropic.py` | Anthropic Claude 兼容流式 Provider |
| 创建 | `tests/test_config.py` | 配置加载和校验测试 |
| 创建 | `tests/test_sse.py` | SSE 解析测试 |
| 创建 | `tests/test_openai_provider.py` | OpenAI 请求和流式解析测试 |
| 创建 | `tests/test_anthropic_provider.py` | Anthropic 请求、thinking 和流式解析测试 |
| 创建 | `tests/test_chat.py` | 会话循环、多轮历史、中文 IO、退出行为测试 |
| 创建 | `tests/test_cli.py` | CLI 参数、错误输出和返回码测试 |
| 创建 | `tests/test_utf8.py` | 项目文本文件 UTF-8 解码测试 |

## T1: 创建项目骨架和包配置

**文件：** `pyproject.toml`、`README.md`、`examples/mewcode.yaml.example`、`mewcode/__init__.py`、`mewcode/__main__.py`、`mewcode/providers/__init__.py`

**依赖：** 无

**步骤：**
1. 创建 Python 包目录和 Provider 子包目录。
2. 在 `pyproject.toml` 中设置 Python 版本为 `>=3.12`。
3. 声明运行依赖 `httpx`、`PyYAML`，测试依赖 `pytest`。
4. 配置命令行入口 `mewcode = "mewcode.cli:main"`。
5. 添加最小中文 `README.md` 和 UTF-8 示例配置。
6. 添加 `python -m mewcode` 入口，调用 `mewcode.cli.main`。

**验证：** 运行 `python -m compileall mewcode`，期望所有已创建模块编译通过。

## T2: 定义核心模型和错误类型

**文件：** `mewcode/models.py`、`mewcode/errors.py`

**依赖：** T1

**步骤：**
1. 定义 `ProviderProfile`、`ChatMessage`、`StreamChunk` dataclass。
2. 使用 Python 3.12 类型标注表达协议、角色和可选 thinking。
3. 定义 `MewCodeError`、`ConfigError`、`ProviderError`、`StreamProtocolError`。
4. 确保模型层不包含 provider 具体协议逻辑。

**验证：** 运行 `python -m compileall mewcode`，期望编译通过。

## T3: 实现配置加载和校验

**文件：** `mewcode/config.py`、`tests/test_config.py`

**依赖：** T2

**步骤：**
1. 实现 `load_profiles(path: Path) -> list[ProviderProfile]`，按 UTF-8 读取 YAML。
2. 校验顶层 `providers` 必须是列表。
3. 校验必填字段、字段类型、非空 `name`、不重复 `name`、合法 `protocol`。
4. 将省略的 `thinking` 规范化为 `False`。
5. 实现 `select_profile(profiles, name)`。
6. 编写测试覆盖多 profile、缺失字段、重复名称、未知 protocol、缺失 profile 和 API Key 不泄露。

**验证：** 运行 `pytest tests/test_config.py`，期望全部通过。

## T4: 实现 SSE 解析器

**文件：** `mewcode/sse.py`、`tests/test_sse.py`

**依赖：** T2

**步骤：**
1. 定义 `SSEEvent` dataclass。
2. 实现 `iter_sse_events(lines: Iterable[str])`。
3. 支持 `event:` 字段、单行和多行 `data:`、空行结束事件。
4. 忽略注释行和无效空白行。
5. 编写测试覆盖多行 data、注释行、没有 event 的 data、末尾无空行的事件。

**验证：** 运行 `pytest tests/test_sse.py`，期望全部通过。

## T5: 定义 Provider 基础接口和 HTTP 客户端

**文件：** `mewcode/providers/base.py`、`mewcode/http.py`

**依赖：** T2、T4

**步骤：**
1. 定义 `ChatProvider` Protocol。
2. 实现 `redact_secret(text, secret)`，用于从错误信息中脱敏 API Key。
3. 实现 `create_http_client()`，返回适合流式响应的 `httpx.Client`。
4. 保持 base 层不依赖具体 OpenAI 或 Anthropic 模块。

**验证：** 运行 `python -m compileall mewcode`，期望编译通过。

## T6: 实现 OpenAI 兼容 Provider

**文件：** `mewcode/providers/openai.py`、`tests/test_openai_provider.py`

**依赖：** T3、T4、T5

**步骤：**
1. 创建 `OpenAIProvider`，接收 `ProviderProfile` 和可选 `httpx.Client`。
2. 将 `ChatMessage` 历史转换为 OpenAI Chat Completions `messages`。
3. 使用 `POST {base_url}/chat/completions`、`Authorization: Bearer <api_key>` 和 `stream: true`。
4. 解析 SSE 中的 `choices[0].delta.content`，逐步产出 `StreamChunk`。
5. 处理 `[DONE]`、非 2xx 响应、JSON 解析失败和错误事件。
6. 编写 fake HTTP transport 测试请求 URL、header、payload、中文流式文本和 API Key 脱敏。

**验证：** 运行 `pytest tests/test_openai_provider.py`，期望全部通过。

## T7: 实现 Anthropic Claude 兼容 Provider

**文件：** `mewcode/providers/anthropic.py`、`tests/test_anthropic_provider.py`

**依赖：** T3、T4、T5

**步骤：**
1. 创建 `AnthropicProvider`，接收 `ProviderProfile` 和可选 `httpx.Client`。
2. 将 `ChatMessage` 历史转换为 Anthropic Messages API `messages`。
3. 使用 `POST {base_url}/messages`、`x-api-key`、`anthropic-version`、`content-type` 和 `stream: true`。
4. 当 `thinking` 为 `True` 时，在 payload 中加入 extended thinking 配置。
5. 只产出 `content_block_delta` 中 `text_delta` 的可见文本。
6. 忽略 thinking delta、signature delta、usage 和 message 生命周期事件。
7. 处理非 2xx 响应、错误事件、JSON 解析失败和协议异常。
8. 编写 fake HTTP transport 测试请求 URL、header、payload、thinking 配置、中文流式文本和 API Key 脱敏。

**验证：** 运行 `pytest tests/test_anthropic_provider.py`，期望全部通过。

## T8: 实现 Provider 工厂

**文件：** `mewcode/providers/factory.py`

**依赖：** T6、T7

**步骤：**
1. 实现 `create_provider(profile: ProviderProfile) -> ChatProvider`。
2. `protocol == "openai"` 返回 `OpenAIProvider`。
3. `protocol == "anthropic"` 返回 `AnthropicProvider`。
4. 未知协议抛出中文 `ProviderError`，作为防御性逻辑。

**验证：** 运行 `python -m compileall mewcode`，期望编译通过。

## T9: 实现终端 IO 封装和对话循环

**文件：** `mewcode/io.py`、`mewcode/chat.py`、`tests/test_chat.py`

**依赖：** T5

**步骤：**
1. 实现 `ConsoleIO` 和默认标准输入输出封装。
2. 实现 `run_chat(provider, profile_name, io=None) -> int`。
3. 输出中文欢迎语、中文提示符和助手前缀。
4. 支持 `/exit`、`/quit`、`退出`、`再见` 退出。
5. 空输入不调用 Provider。
6. 每次用户输入后把完整历史发送给 Provider。
7. 流式打印每个 `StreamChunk.text` 并立即 flush。
8. 流成功后把完整助手回复加入历史。
9. Provider 失败时输出中文错误，保留用户继续输入的能力，不追加失败助手消息。
10. 编写 fake provider 和 fake IO 测试多轮历史、中文输入输出、退出、空输入、流式 flush 和错误后继续。

**验证：** 运行 `pytest tests/test_chat.py`，期望全部通过。

## T10: 实现 CLI 入口

**文件：** `mewcode/cli.py`、`mewcode/__main__.py`、`tests/test_cli.py`

**依赖：** T3、T8、T9

**步骤：**
1. 使用 `argparse` 实现 `main(argv=None) -> int`。
2. 支持必填 `--profile <name>`。
3. 支持可选 `--config <path>`，默认 `mewcode.yaml`。
4. 读取配置、选择 profile、创建 Provider、进入 `run_chat`。
5. 配置或 Provider 创建失败时输出中文错误并返回非零退出码。
6. 确保错误输出不包含 API Key。
7. 编写测试覆盖缺失 profile 参数、配置文件不存在、profile 不存在、成功调用 chat、`python -m mewcode` 入口可编译。

**验证：** 运行 `pytest tests/test_cli.py`，期望全部通过。

## T11: 完善中文文档和示例配置

**文件：** `README.md`、`examples/mewcode.yaml.example`

**依赖：** T10

**步骤：**
1. 在 README 中说明 Python 3.12、安装方式、启动方式和退出命令。
2. 说明 YAML 顶层 `providers` 列表和六个配置字段。
3. 说明 OpenAI 与 Claude profile 示例。
4. 明确本阶段不支持工具调用、文件操作、代码编辑和 Shell 执行。
5. 确认示例配置中使用占位 API Key，不包含真实密钥。

**验证：** 运行 UTF-8 检查脚本，期望 README 和示例配置可按 UTF-8 解码。

## T12: 增加 UTF-8 和全量回归测试

**文件：** `tests/test_utf8.py`

**依赖：** T1 到 T11

**步骤：**
1. 编写测试扫描项目中的 `.py`、`.md`、`.toml`、`.yaml`、`.example` 文本文件。
2. 对每个文本文件执行 UTF-8 解码。
3. 检查文本中不包含 Unicode replacement character。
4. 运行全量测试套件。
5. 运行 `python -m compileall mewcode`。

**验证：** 运行 `pytest` 和 `python -m compileall mewcode`，期望全部通过。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12
```
