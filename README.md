# MewCode

MewCode 是一个使用 Python 3.12+ 开发的终端 Coding Agent。它支持 Anthropic Claude 与 OpenAI 兼容协议，能够在 TUI 中流式对话、调用本地工具并通过 ReAct Loop 自主推进多步任务。

## 功能

- Anthropic Claude 和 OpenAI 兼容 API，支持多 Provider 配置与启动时选择。
- MCP 客户端：启动时从用户级配置发现 stdio 或 Streamable HTTP Server，并将远端工具注册到工具中心。
- 流式输出、多轮会话、工具调用、Token 用量和迭代进度显示。
- ReAct Agent Loop：模型调用工具、读取结果并继续下一轮，直到任务完成或触发安全停止条件。
- 六个核心工具：`read_file`、`write_file`、`edit_file`、`bash`、`glob`、`grep`。
- 统一 Slash 命令中心：本地命令绕过 Agent，支持帮助、别名、参数校验和 Tab 补全。
- `/plan` 计划模式：仅允许读取、查找和搜索；`/do` 切回执行模式并按计划推进。
- Esc 或流式状态下 Ctrl+C 取消当前任务；空闲状态下 Ctrl+C 退出。
- 模块化中文系统提示：环境信息、会话历史与临时约束分层注入，模型默认按用户语言回答。
- 提示缓存：Anthropic 使用稳定 system 块缓存；OpenAI 保持稳定 system 前缀并读取端点返回的缓存 token。

## 环境

- Python 3.12+
- 运行依赖：`textual`、`rich`、`anthropic`、`openai`、`mcp`、`pyyaml`
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

使用 Conda 时，先激活安装 MewCode 的环境，再进入要操作的项目根目录启动：

```powershell
conda activate mewcode
Set-Location D:\path\to\your-project
mewcode
```

项目根目录决定当前工作区、权限规则、项目指令、会话档案、缓存和项目级记忆的存放位置。

## 配置

Provider 配置采用 UTF-8 YAML，顶层字段为 `providers`，固定读取用户目录的 `~/.mewcode/config.yaml`。MCP Server 配置固定读取同一目录的 `~/.mewcode/mcp.yaml`，顶层字段为 `mcp_servers`。两份配置互不合并，也不读取项目目录或环境变量指定路径。

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "$HOME\.mewcode"
notepad "$HOME\.mewcode\config.yaml"
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
    context_window: 200000

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
| `context_window` | 可选，模型上下文窗口的 Token 上限；省略时为 `1000000`。Chapter 08 的压缩控制器将使用该值。 |

MCP 配置示例见 [`.mewcode/mcp-servers.example.yaml`](.mewcode/mcp-servers.example.yaml)。复制为 `$HOME\.mewcode\mcp.yaml` 后，按需设置其中引用的环境变量。每个 Server 必须显式声明 `type: stdio` 或 `type: http`；`env` 和 `headers` 的值支持 `${VAR}` 展开。

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
| 输入 `/` | 立即在输入框下方展开全部公开 Slash 命令，并随规范名称或别名前缀实时过滤。 |
| ↑ / ↓ | 命令菜单展开时移动高亮项，输入焦点仍留在输入框。 |
| Tab | 命令菜单展开时只把高亮项的规范名称填入输入框，不立即执行。 |
| Enter | 命令菜单展开时只填入高亮项；菜单关闭时提交，因此选择后需再次按 Enter 才执行。 |
| Alt+Enter | 在输入框插入换行。 |
| `/help`、`/h` | 按名称排序显示全部命令；`/help <命令名>` 显示单条详情。 |
| `/plan` | 进入计划模式；随后发送任务时只开放 `read_file`、`glob`、`grep`。 |
| `/do` | 退出计划模式并发送执行指令，恢复全部工具。 |
| `/compact` | 手动压缩当前模型上下文；TUI 历史和 JSONL 档案不会被改写。 |
| `/resume` | 打开历史会话列表；输入关键词筛选、方向键选择、Enter 恢复、Esc 取消。每条记录右侧的 `X` 可删除该会话。 |
| `/clear`、`/c` | 结束当前会话并立即开启新会话，清空时间线、消息和会话统计。 |
| `/status` | 显示权限模式、累计 Token、可用工具、记忆、模型和工作目录。 |
| `/memory` | 列出当前项目层与用户层记忆索引引用的文件名，不展开正文。 |
| `/permission` | 显示当前权限模式。 |
| `/session` | 显示当前 session ID 与 JSONL 档案路径。 |
| `/review` | 向对话注入固定代码审查请求并立即触发 Agent 回合。 |
| Esc | 命令菜单展开时关闭菜单并保留输入；否则取消当前 Agent Loop。 |
| 流式状态 Ctrl+C | 取消当前 Agent Loop，保留会话继续对话。 |
| 空闲状态 Ctrl+C / `/exit` | 退出程序。 |

所有以 `/` 开头的输入都由本地命令分发器处理，未知命令不会发送给模型。`/help`、`/status`、`/memory`、`/permission`、`/session` 等纯本地命令不创建会话、不写入模型上下文，也不消耗模型 Token。

命令菜单是输入框下方的内联列表，不会夺取输入焦点。规范名称和别名都会参与前缀匹配，但选择结果始终写回规范名称；输入包含参数、没有匹配项、离开 Slash 输入或按 Esc 时菜单关闭。`/h`、`/c` 仍可作为别名直接提交执行。

### 会话与恢复

选定 Provider 本身不会创建会话档案；首次真正提交给 Agent 的用户消息后才创建新会话。首条用户消息提交后，MewCode 会在后台生成简短标题；生成失败时使用首条消息的清理截断文本。

输入 `/resume` 可切换到历史会话。列表按最后活动时间排序，展示标题、会话 ID、相对时间、消息数、模型和档案大小。恢复后：

- TUI 重放完整的原始用户、助手、工具和状态事件；已压缩的早期内容不会替代可见历史。
- 模型 Prompt Context 从压缩检查点和近期原文重建；恢复超过七天的会话时，模型会收到重新检查工作区状态的提醒。
- 后续消息继续追加到同一会话档案。

需要删除会话时，点击对应记录右侧的 `X`。该操作删除 JSONL 档案和同 ID 工具缓存，并立即刷新列表；不会删除项目级或用户级长期记忆。

会话和工具产物位于当前项目下，默认写入 `.gitignore`：

```text
.mewcode/
├── sessions/    # 每个会话一个 JSONL 档案
├── cache/       # 按会话存放的大型工具结果
└── memory/      # 项目级自动记忆与 MEMORY.md 索引
```

超过 30 天的会话档案和对应缓存会在启动后及打开 `/resume` 前自动清理；项目级长期记忆不会随会话清理删除。

每次 Agent 模型请求返回的 input/output Token usage 会以增量事件写入当前 JSONL。状态栏和 `/status` 显示当前会话累计值；使用 `/resume` 恢复后会从档案还原并继续累计。会话回合数由档案中的用户消息恢复，工具调用产生的内部续轮不会重复计数。

### 项目指令与记忆

启动时会一次性读取下列手写指令文件，并按从高到低的优先级注入模型上下文：

1. `<项目根>/MEWCODE.md`
2. `<项目根>/.mewcode/MEWCODE.md`
3. `~/.mewcode/MEWCODE.md`

指令支持独占行形式的 `@include <relative_path>`，最大嵌套五层；引用不能跳出项目根或用户 `.mewcode` 目录。修改指令后需重启 MewCode 才会生效。

自然完成的 Agent 回合会异步提取用户偏好、纠正反馈、项目知识和参考资料。用户级笔记存于 `~/.mewcode/memory/`，项目知识和参考资料存于项目 `.mewcode/memory/`；更新不会阻塞下一轮输入。

## 工具与执行方式

模型会根据任务自行选择工具。系统提示会要求优先使用专用工具，例如读取文件使用 `read_file`、查找文件使用 `glob`、搜索内容使用 `grep`，而不是用 shell 拼凑同类操作。

对已有文件进行编辑前，模型应先调用 `read_file` 获取当前内容；`edit_file` 采用 `old_string` 唯一匹配替换，匹配不到或匹配多处都会返回结构化错误。每个工具调用默认有 30 秒超时，错误结果会回灌给模型以便调整后续动作。

连续只读工具调用可以并发执行；写文件、编辑文件和执行命令会按模型返回的顺序串行处理。工具调用受权限模式、规则匹配和项目根路径沙箱保护；需要确认的操作会在 TUI 中等待用户审批。会话通过项目 `.mewcode/sessions/` 下的 JSONL 档案持久化。

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

## 项目进度

- 已完成：多 Provider 流式 Agent、内置文件/命令工具、权限控制、计划模式，以及 stdio 和 Streamable HTTP MCP 工具发现与注册。
- 已完成 Chapter 08 上下文与记忆系统：Provider `context_window`、隐藏系统上下文、工具结果缓存、九段式摘要和熔断、JSONL 会话档案、异步标题、三层项目指令、两级自动记忆、`/compact`、`/resume` 与会话重放。
- 已完成 Chapter 09 Slash 命令注册与分发系统：十二个内置命令、别名、帮助、参数校验、实时内联补全、界面控制抽象和会话 Token usage 持久化。
- 2026-07-20 已完成 Chapter 09 全量回归：`191 passed, 1 skipped`；编译、Ruff 检查和格式检查均通过。压缩检查点的多次恢复正确性仍列为已知技术债，见下方限制。

## 当前限制

- 不支持 Skill 自动发现。
- 不提供运行中切换 Provider/模型的命令。
- 缓存命中由 Provider 决定，OpenAI 兼容端点可能不返回 `cached_tokens`。
- 上下文压缩仍有两项已知限制：`/compact` 尚未按手动 3K Token 余量判定；摘要请求尚未包含工具结果正文。连续压缩后再恢复的检查点索引需要补充端到端回归与修复。
