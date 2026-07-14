# MewCode

MewCode 是一个使用 Python 3.12+ 开发的终端 Coding Agent。它支持 Anthropic Claude 与 OpenAI 兼容协议，能够在 TUI 中流式对话、调用本地工具并通过 ReAct Loop 自主推进多步任务。

## 功能

- Anthropic Claude 和 OpenAI 兼容 API，支持多 Provider 配置与启动时选择。
- 流式输出、多轮会话、工具调用、Token 用量和迭代进度显示。
- ReAct Agent Loop：模型调用工具、读取结果并继续下一轮，直到任务完成或触发安全停止条件。
- 六个核心工具：`read_file`、`write_file`、`edit_file`、`bash`、`glob`、`grep`。
- `/plan` 计划模式：仅允许读取、查找和搜索；`/do` 切回执行模式并按计划推进。
- Esc 或流式状态下 Ctrl+C 取消当前任务；空闲状态下 Ctrl+C 退出。
- 模块化中文系统提示：环境信息、会话历史与临时约束分层注入，模型默认按用户语言回答。
- 提示缓存：Anthropic 使用稳定 system 块缓存；OpenAI 保持稳定 system 前缀并读取端点返回的缓存 token。

## 环境

- Python 3.12+
- 运行依赖：`textual`、`rich`、`anthropic`、`openai`、`pyyaml`
- 开发依赖：`pytest`、`ruff`、`mypy`

## 安装

推荐在 Python 3.12 的虚拟环境或 conda 环境中安装：

```powershell
pip install -e .
```

安装开发依赖：

```powershell
pip install pytest ruff mypy
```

如果使用 `uv`：

```powershell
uv sync
```

安装完成后，`mewcode` 会注册到当前 Python 环境。激活该环境后可以在任意目录执行：

```powershell
mewcode
```

## 配置

配置文件采用 UTF-8 YAML，顶层字段为 `providers`。启动时依次查找：

1. `MEWCODE_CONFIG` 环境变量指定的路径。
2. 当前目录的 `.mewcode/config.yaml`。
3. 用户目录的 `.mewcode/config.yaml`。

建议将默认配置放在用户目录，这样可以在任意工作目录启动。

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "$HOME\.mewcode"
notepad "$HOME\.mewcode\config.yaml"
```

临时指定配置文件：

```powershell
$env:MEWCODE_CONFIG = "D:\path\to\config.yaml"
mewcode
```

配置示例：

```yaml
providers:
  - name: claude
    protocol: anthropic
    api_key: sk-ant-your-key
    model: claude-3-5-sonnet-latest
    base_url: https://api.anthropic.com
    thinking: true

  - name: openai
    protocol: openai
    api_key: sk-your-key
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
```

字段说明：

| 字段 | 说明 |
|---|---|
| `name` | Provider 标识名和界面显示名。 |
| `protocol` | `anthropic` 或 `openai`。 |
| `api_key` | API 密钥，不会在 MewCode 界面中回显。 |
| `model` | 模型名。 |
| `base_url` | 可选的自定义或兼容端点；省略时使用 SDK 默认端点。 |
| `thinking` | 可选，仅 Anthropic 生效。工具调用历史存在后会自动关闭扩展思考，以保持工具循环兼容。 |

## 使用

```powershell
mewcode
```

也可以直接运行模块：

```powershell
python -m mewcode
```

只有一个 Provider 时会直接进入对话；有多个 Provider 时使用方向键选择后按 Enter 确认。

| 操作 | 行为 |
|---|---|
| Enter | 提交当前输入。 |
| Alt+Enter | 在输入框插入换行。 |
| `/plan` | 进入计划模式；随后发送任务时只开放 `read_file`、`glob`、`grep`。 |
| `/do` | 退出计划模式并发送执行指令，恢复全部工具。 |
| Esc / 流式状态 Ctrl+C | 取消当前 Agent Loop，保留会话继续对话。 |
| 空闲状态 Ctrl+C / `/exit` | 退出程序。 |

## 工具与执行方式

模型会根据任务自行选择工具。系统提示会要求优先使用专用工具，例如读取文件使用 `read_file`、查找文件使用 `glob`、搜索内容使用 `grep`，而不是用 shell 拼凑同类操作。

对已有文件进行编辑前，模型应先调用 `read_file` 获取当前内容；`edit_file` 采用 `old_string` 唯一匹配替换，匹配不到或匹配多处都会返回结构化错误。每个工具调用默认有 30 秒超时，错误结果会回灌给模型以便调整后续动作。

连续只读工具调用可以并发执行；写文件、编辑文件和执行命令会按模型返回的顺序串行处理。当前版本不提供权限确认、路径沙箱或会话持久化，因此应仅在你信任的工作目录与配置下运行。

## 系统提示与缓存

每轮请求由以下部分组成：

1. 稳定系统提示：身份、系统约束、任务模式、动作执行、工具使用、语气风格和文本输出模块。
2. 动态环境信息：工作目录、平台、日期、Git 状态、应用版本与模型。
3. 持久对话历史与工具结果。
4. 临时 `<system-reminder>`：用于计划模式等运行时约束，不写入会话历史。

Anthropic 请求会将稳定 system 块标记为可缓存，环境信息保持为后续动态块。OpenAI 请求将稳定提示与环境信息发送为两条连续的 system 消息，稳定提示始终处于请求前缀。是否命中缓存仍取决于模型、端点和供应商策略。

可用 smoke 脚本发送两轮真实请求并打印 input、output、缓存写入与缓存读取 token：

```powershell
python examples\smoke.py --profile claude
```

`--profile` 对应配置中的 `name`。该脚本会产生真实 API 请求与费用。

## 开发验证

```powershell
python -m pytest -q
python -m compileall src\mewcode examples
python -m ruff check .
python -m ruff format --check .
```

## 当前限制

- 不支持项目级指令文件、自动长期记忆、真实 MCP 连接或 Skill 自动发现。
- 不进行上下文压缩、历史裁剪或会话持久化。
- 不提供工具权限确认、执行沙箱或路径白名单。
- 不提供运行中切换 Provider/模型的命令。
- 缓存命中由 Provider 决定，OpenAI 兼容端点可能不返回 `cached_tokens`。
