# MewCode 交互式对话 TUI 技术设计

## 架构概览
MewCode 第一阶段采用轻量命令行架构，由 CLI 入口、配置加载、会话循环、Provider 抽象、两个协议实现和 SSE 解析组成。

主流程如下：

1. CLI 解析启动参数，读取 UTF-8 YAML 配置文件。
2. 配置层校验多个 provider profile，并按 `--profile <name>` 选择一个配置。
3. Provider 工厂根据 `protocol` 创建 OpenAI 兼容或 Anthropic Claude 兼容 Provider。
4. 会话循环显示中文提示，接收用户输入，维护当前进程内的消息历史。
5. 每次用户输入后，会话循环调用统一 Provider 接口。
6. Provider 使用 HTTP 流式请求读取 SSE 事件，把可见文本片段逐步产出。
7. 会话循环将文本片段立即写入终端并 flush，流结束后把完整助手回复加入历史。
8. 配置错误、请求错误、流式解析错误都转换为中文错误信息，并对 API Key 做脱敏。

本阶段不引入全屏 TUI 框架；终端界面使用标准输入输出实现，便于测试和保持首个里程碑稳定。

## 核心数据结构

### ProviderProfile
表示 YAML 中的单个 LLM 供应商配置。

```python
@dataclass(frozen=True)
class ProviderProfile:
    name: str
    protocol: Literal["openai", "anthropic"]
    model: str
    base_url: str
    api_key: str
    thinking: bool = False
```

字段含义：
- `name`：配置标识名，对应启动参数 `--profile`。
- `protocol`：协议类型，决定使用 OpenAI 兼容 Provider 或 Anthropic Provider。
- `model`：请求中的模型名称。
- `base_url`：API 基础地址，不在配置层自动猜测。
- `api_key`：认证密钥，只用于请求头，不进入普通输出。
- `thinking`：仅 Anthropic Provider 使用；为 `true` 时请求 Claude extended thinking。

### ChatMessage
表示会话历史中的一条可见消息。

```python
@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str
```

本阶段只保存同一次运行中的可见文本历史，不持久化到磁盘。

### StreamChunk
表示 Provider 流式产出的一个可见文本片段。

```python
@dataclass(frozen=True)
class StreamChunk:
    text: str
```

Provider 内部可以接收更多 SSE 事件类型，但统一接口只向会话层暴露需要打印的文本。

### ChatProvider
Provider 统一接口。

```python
class ChatProvider(Protocol):
    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[StreamChunk]:
        ...
```

约束：
- `messages` 必须包含当前用户消息和之前的会话历史。
- 只产出可见助手文本，不产出工具调用、文件操作或 shell 行为。
- 请求失败、状态码错误、流式协议异常统一抛出 `ProviderError`。

### MewCodeError
错误类型分层。

```python
class MewCodeError(Exception): ...
class ConfigError(MewCodeError): ...
class ProviderError(MewCodeError): ...
class StreamProtocolError(ProviderError): ...
```

用户可见错误由 CLI 层统一格式化为中文，并在格式化前对当前 profile 的 API Key 做脱敏。

## 模块设计

### `mewcode.cli`
**职责：** 命令行入口和启动参数解析。

**公开接口：**

```python
def main(argv: Sequence[str] | None = None) -> int
```

**启动参数：**
- `--profile <name>`：必填，选择 YAML 中的 provider profile。
- `--config <path>`：可选，默认读取当前目录的 `mewcode.yaml`。

**行为：**
- 成功启动时进入中文交互式会话。
- 配置或启动错误返回非零退出码。
- Ctrl-D、Ctrl-Z 输入结束或退出命令返回 0。

### `mewcode.config`
**职责：** 按 UTF-8 读取 YAML，校验 provider profile，按名称选择配置。

**公开接口：**

```python
def load_profiles(path: Path) -> list[ProviderProfile]
def select_profile(profiles: Sequence[ProviderProfile], name: str) -> ProviderProfile
```

**YAML 结构：**

```yaml
providers:
  - name: claude
    protocol: anthropic
    model: claude-sonnet-5
    base_url: https://api.anthropic.com/v1
    api_key: sk-ant-...
    thinking: true
  - name: openai
    protocol: openai
    model: gpt-5.5
    base_url: https://api.openai.com/v1
    api_key: sk-...
```

**校验规则：**
- 顶层必须包含 `providers` 列表。
- 每个 profile 必须包含 `name`、`protocol`、`model`、`base_url`、`api_key`。
- `thinking` 可省略，省略时为 `false`。
- `protocol` 只接受 `openai` 或 `anthropic`。
- `name` 不允许为空，且不允许重复。
- 错误信息不能包含原始 API Key。

### `mewcode.chat`
**职责：** 交互式对话循环、中文提示、会话历史维护、流式打印。

**公开接口：**

```python
def run_chat(provider: ChatProvider, profile_name: str, io: ConsoleIO | None = None) -> int
```

**行为：**
- 启动后显示中文欢迎信息和当前 profile 名称。
- 用户提示符使用中文，例如 `你> `。
- 助手输出前显示 `MewCode> `，随后逐块打印 Provider 产出的文本。
- 用户输入 `/exit`、`/quit`、`退出` 或 `再见` 时退出。
- 空输入不发送给后端。
- 每次请求前先追加用户消息；流成功完成后追加助手消息。
- 如果流式请求失败，打印中文错误，不追加失败的助手消息，并回到输入循环。

### `mewcode.io`
**职责：** 封装标准输入输出，便于测试中文输入和流式输出。

**公开接口：**

```python
@dataclass
class ConsoleIO:
    input: Callable[[str], str]
    write: Callable[[str], None]
    flush: Callable[[], None]
```

默认实现使用 `input()`、`sys.stdout.write()` 和 `sys.stdout.flush()`。

### `mewcode.providers.base`
**职责：** 定义 Provider 协议、通用异常和通用脱敏工具。

**公开接口：**

```python
def redact_secret(text: str, secret: str) -> str
```

### `mewcode.providers.factory`
**职责：** 根据 `ProviderProfile.protocol` 创建具体 Provider。

**公开接口：**

```python
def create_provider(profile: ProviderProfile) -> ChatProvider
```

### `mewcode.providers.openai`
**职责：** 实现 OpenAI 兼容 Chat Completions 流式协议。

**请求：**
- URL：`{base_url}/chat/completions`
- 方法：`POST`
- Header：`Authorization: Bearer <api_key>`
- Payload：

```json
{
  "model": "<model>",
  "messages": [{"role": "user", "content": "..."}],
  "stream": true
}
```

**流式解析：**
- 按 SSE `data:` 行解析。
- `data: [DONE]` 表示流结束。
- JSON chunk 中读取 `choices[0].delta.content` 作为可见文本。
- 忽略空 delta、usage chunk 和工具相关字段。

### `mewcode.providers.anthropic`
**职责：** 实现 Anthropic Claude Messages 流式协议。

**请求：**
- URL：`{base_url}/messages`
- 方法：`POST`
- Header：`x-api-key: <api_key>`、`anthropic-version`、`content-type: application/json`
- Payload：

```json
{
  "model": "<model>",
  "max_tokens": 4096,
  "messages": [{"role": "user", "content": "..."}],
  "stream": true
}
```

**thinking 行为：**
- 当 `thinking` 为 `true` 时，在 payload 中加入：

```json
{
  "thinking": {
    "type": "adaptive",
    "display": "omitted"
  }
}
```

这样会请求 Claude extended thinking，但 TUI 只显示最终助手文本，不显示 thinking 内容。

**流式解析：**
- 按 SSE event/data 解析。
- 只把 `content_block_delta` 中 `delta.type == "text_delta"` 的 `delta.text` 产出给会话层。
- 忽略 `thinking_delta`、`signature_delta`、usage 和 message 生命周期事件。
- 如果后端发送错误事件或响应状态码非 2xx，抛出 `ProviderError`。

### `mewcode.sse`
**职责：** 提供通用 SSE 行解析工具，不绑定具体供应商。

**公开接口：**

```python
@dataclass(frozen=True)
class SSEEvent:
    event: str | None
    data: str

def iter_sse_events(lines: Iterable[str]) -> Iterator[SSEEvent]
```

**行为：**
- 支持多行 `data:` 合并。
- 空行表示一个 SSE event 结束。
- 忽略注释行。
- 不解析 JSON；JSON 解析交给 Provider。

### `mewcode.http`
**职责：** 创建可注入的 HTTP 客户端，便于测试时替换 transport。

**公开接口：**

```python
def create_http_client() -> httpx.Client
```

默认超时使用较长 read timeout，以适配流式响应。

## 模块交互

```text
用户终端
  -> mewcode.cli.main
  -> mewcode.config.load_profiles
  -> mewcode.config.select_profile
  -> mewcode.providers.factory.create_provider
  -> mewcode.chat.run_chat
  -> ChatProvider.stream_chat
  -> httpx streaming request
  -> mewcode.sse.iter_sse_events
  -> Provider 解析文本 chunk
  -> mewcode.chat 逐块写入终端
```

## 文件组织

```text
Mewcode/
+-- pyproject.toml                     - Python 包元数据、依赖、测试配置
+-- README.md                          - 最小运行说明和配置示例
+-- spec.md                            - 已批准规格
+-- plan.md                            - 技术设计
+-- task.md                            - 后续任务拆分
+-- checklist.md                       - 后续验收清单
+-- examples/
|   `-- mewcode.yaml.example           - UTF-8 示例配置
+-- mewcode/
|   +-- __init__.py                    - 包版本
|   +-- __main__.py                    - `python -m mewcode` 入口
|   +-- cli.py                         - CLI 参数和入口返回码
|   +-- chat.py                        - 对话循环和流式打印
|   +-- config.py                      - YAML 加载和配置校验
|   +-- errors.py                      - 通用错误类型
|   +-- http.py                        - HTTP client 创建
|   +-- io.py                          - 可测试的终端 IO 封装
|   +-- models.py                      - ProviderProfile、ChatMessage、StreamChunk
|   +-- sse.py                         - SSE 解析
|   `-- providers/
|       +-- __init__.py
|       +-- base.py                    - Provider Protocol 和脱敏工具
|       +-- factory.py                 - Provider 工厂
|       +-- openai.py                  - OpenAI 兼容协议
|       `-- anthropic.py               - Claude 兼容协议
`-- tests/
    +-- test_config.py                 - 配置加载、校验、profile 选择
    +-- test_sse.py                    - SSE 解析
    +-- test_openai_provider.py        - OpenAI 流式解析和请求 payload
    +-- test_anthropic_provider.py     - Claude 流式解析、thinking payload
    +-- test_chat.py                   - 多轮历史、中文 IO、退出行为
    `-- test_cli.py                    - CLI 参数、错误返回码
```

## 技术决策

| 决策 | 选择 | 原因 |
|------|------|------|
| Python 版本 | Python 3.12 | 用户会使用 conda 创建 Python 3.12 环境；项目按 3.12 语法、类型和打包配置编写 |
| 终端界面 | 标准输入输出 | 本阶段只需简单交互和流式打印，不引入复杂 TUI 依赖 |
| HTTP 客户端 | `httpx` 同步流式客户端 | 支持 streaming、测试 transport 注入，避免 async 对首阶段造成额外复杂度 |
| YAML 解析 | `PyYAML` | 标准库不支持 YAML，依赖小且常见 |
| 配置结构 | 顶层 `providers` 列表 | 支持多个 profile，同时保持每个 profile 只有规格要求的字段 |
| OpenAI 协议 | Chat Completions + `stream: true` | OpenAI 兼容生态支持面更广，满足本阶段纯对话需求 |
| Claude 协议 | Messages API + SSE | 符合 Claude 当前消息接口和流式输出方式 |
| Claude thinking | `thinking: {"type": "adaptive", "display": "omitted"}` | 用布尔配置启用 extended thinking，同时避免在 TUI 暴露 thinking 内容 |
| Provider 接口 | 统一产出 `StreamChunk` | 会话层只关心可见文本，协议差异留在 Provider 内部 |
| 历史保存 | 进程内 `list[ChatMessage]` | 满足多轮记忆，不做跨启动持久化 |
| 测试策略 | 使用 fake provider 和 fake HTTP transport | 验证请求、SSE 和 TUI 行为，不依赖真实 API 或网络 |
| 编码 | 显式 UTF-8 读写项目文本 | 满足中文输入输出和文档编码要求 |

## 外部依赖

运行依赖：
- `httpx`
- `PyYAML`

开发测试依赖：
- `pytest`

首阶段不依赖 OpenAI 或 Anthropic 官方 SDK，避免 Provider 抽象被 SDK 类型绑定，并保留对兼容后端的控制。

项目运行目标为 Python 3.12。当前开发沙箱的 Python 版本不作为项目兼容性要求；后续实现只需保证代码逻辑正确，并能在 Python 3.12 环境中编译和测试通过。

## 验证策略

单元测试：
- 配置文件支持多个 profile，并能按名称选择。
- 缺失字段、重复名称、未知 protocol、缺失 profile 都产生中文错误。
- API Key 不会出现在格式化后的错误信息中。
- SSE parser 能处理多行 data、空行结束、注释行。
- OpenAI Provider 会构造正确 endpoint、header、payload，并从 SSE chunk 逐步产出中文文本。
- Anthropic Provider 会构造正确 endpoint、header、payload；`thinking: true` 时包含 thinking 配置；从 `text_delta` 逐步产出中文文本。
- Chat loop 会保存多轮历史、忽略空输入、支持中文退出命令，并在流式错误后继续循环。

集成级验证：
- 使用 fake provider 运行一次脚本化会话：输入中文问题，观察中文流式输出和历史传递。
- 使用 fake HTTP transport 分别模拟 OpenAI 和 Claude 的 SSE 响应，不访问真实网络。
- 运行测试套件并检查所有项目文本文件可按 UTF-8 解码。
