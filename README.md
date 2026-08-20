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

如需运行本地微信机器人，在同一个 MewCode 环境中安装 Windows 可选依赖：

```powershell
pip install -e ".[wechat]"
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

### 本地微信机器人

V1 通过 Windows UIAutomation 接入一个已经登录的微信桌面客户端，仅兼容微信 `4.0.5.15`。微信配置由 MewCode 自己维护，不读取其他项目的配置、控件选择器或操作节拍。

在现有 `~/.mewcode/config.yaml` 中增加顶层 `wechat`：

```yaml
wechat:
  enabled: true
  provider: claude
  allowed_contacts:
    - 专用测试好友
  system_prompt: |
    你是通过微信与好友聊天的个人助手。简洁、自然地回答；你没有任何本地工具。
  task_timeout_seconds: 180
  max_reply_chars: 1500
  log_level: INFO
  info_tools:
    enabled: true
    tavily_api_key: ${TAVILY_API_KEY}
    nominatim_user_agent: MewCode-WeChat/0.1
    nominatim_proxy: ${HTTPS_PROXY}
```

`provider` 必须引用 `providers` 中已有的 `name`。`allowed_contacts` 使用微信会话显示名精确匹配；重名会话会安全拒绝。每名好友使用独立并持久化的 MewCode Session，但微信好友始终没有 Bash、文件、MCP、Skills、Sub-agent、Hook 或长期记忆能力。

`info_tools.enabled` 默认是 `false`。启用后，微信侧只增加三个只读公共信息工具：本机／地点当前时间、Tavily 网页搜索和公开网页正文读取；不会继承终端 Coding Agent 的任何本地工具。建议只通过环境变量提供 Tavily Key：

```powershell
$env:TAVILY_API_KEY = "tvly-your-key"
mewcode-wechat
```

网页搜索固定使用 Tavily 免费套餐的 Basic 模式，每轮最多搜索两次、每次最多五条，本地按自然月最多预留 1,000 credits，不启用 Advanced、自动付费回退或其他搜索源。缺少或失效的 Key 会让网页搜索及依赖搜索的天气查询返回配置错误，时间和用户提供的公开链接直读仍可使用。网页直读每轮最多五页，仅接受公网 HTTP(S) 的 HTML／纯文本，单页最多 2 MiB、正文最多 50,000 字符；不启动浏览器、不执行 JavaScript、不读取登录态，并在每次重定向时重新检查 SSRF 边界。

地点时间把国家名称解释为该国首都；具体城市由本地缓存和低频公共 Nominatim 解析，公共请求最多每秒一次并标注 OpenStreetMap。省略 `nominatim_proxy` 时 Nominatim 直连且不继承系统代理；配置 `${HTTPS_PROXY}` 或 HTTP(S) 代理 URL 后，只有 Nominatim 使用该代理，Tavily 和公开网页读取仍保持直连。显式代理环境变量缺失、地址非法或连接失败时，远程地点解析安全失败，不会绕过代理直连；本机时间、内置国家首都和已有地点缓存仍可用。代理地址及凭据不会提供给模型或写入运行数据。Nominatim、地点缓存和该代理只服务地点时间，不参与天气网页查询。

当前天气、天气预报、降雨、温度、风力、穿衣和出行天气建议会自动使用 Tavily Basic 网页搜索，无需再次确认普通联网；摘要不足时可在既有安全边界内读取公开静态页面。天气与其他网页问题共享每轮搜索、页面读取、等待时间、缓存和每月免费 credit 限额，不存在专用天气接口、状态或缓存。机器人只发送必要的地点、日期范围和天气关键词；地点缺失且当前好友对话中没有唯一地点时会先追问，不根据好友身份、IP、本机位置或其他好友会话猜测。

天气回答会标明地点、日期并附本回合实际使用的网页来源，优先采用气象部门、政府公共服务和可识别的主流天气服务；官方预警、台风和灾害信息优先引用官方来源。来源冲突时会说明差异。Tavily Key 缺失、免费额度耗尽、搜索失败或没有可靠来源时，机器人会明确说明暂时无法查询，不编造天气，也不回退到付费服务、其他搜索源或动态浏览器。

内置国家名称与首都坐标数据由 [mledoze/countries](https://github.com/mledoze/countries) 和 [GeoNames](https://www.geonames.org/) 生成，来源记录保存在随包发布的 `country_capitals.json` 中。

每轮都会向模型注入本机当前日期时间和 IANA 时区。网页与地点缓存保存在当前项目的 `.mewcode/wechat.sqlite3`，不带好友或 Session 标识；网页缓存最长保留七天，地点缓存可长期复用并在过期后重新验证。外部请求的原始参数、网页正文和搜索返回体不会写入好友 JSONL、`.mewcode/cache` 或长期记忆，好友档案只保留用户消息、实际发送成功的回复及已净化的工具结构。使用网页或 Nominatim 后，回复末尾会追加当前回合实际来源或数据署名。

启动前保持 Windows 桌面已解锁、微信主窗口可用且只运行一个已登录账号。先执行只读控件检查：

```powershell
mewcode-wechat --probe
```

确认输出版本为 `4.0.5.15`，并包含 `session_list`、`chat_message_list` 和 `chat_input_field` 后启动：

```powershell
mewcode-wechat
```

机器人只处理启动后到达的白名单私聊文字消息。每名好友停止发送 7 秒后，连续消息会合并为一个意图并进入全局 FIFO；多名好友的模型处理和回复发送仍按入队顺序串行执行，不会交错。若同一好友在排队、工具执行或气泡发送期间又发来普通消息，当前任务和未发送气泡会立即停止，新旧消息重新进入 7 秒合并窗口；其他好友的新消息不会打断当前任务。

闲聊回答可使用模型生成的 `<|bubble|>` 边界拆成最多 7 个语义气泡，按内容长度使用 0.4～2 秒的有限间隔逐条发送；专业回答保持完整纯文本，仅在超过微信单条长度限制时按自然段或句子拆分。调用时间或网页工具时，机器人会在同一工具阶段只发一次简短状态，网页正文完成后再单独发送实际来源。可见消息会移除加粗、二级标题和代码围栏等 Markdown 包装，但保留 Windows 路径、反斜线、`#`、`*`、下划线和代码内容。

V1 不支持群聊、图片、语音、文件、主动发送、多账号、服务器部署或其他微信版本。

机器人通过微信键盘搜索切换到原好友，并聚焦输入框后按 Enter 发送，不移动或点击鼠标。该过程会激活微信并短暂占用键盘焦点，因此运行期间可以移动鼠标，但不要在机器人切换会话或发送的瞬间向其他窗口输入内容。若搜索焦点、唯一结果、聊天标题或输入框状态无法确认，机器人会拒绝发送。

首次收发验证应使用明确授权的专用普通好友。微信 4.0.5.15 的“文件传输助手”使用特殊页面，不暴露 V1 所需的标准消息列表和输入框，因此不作为测试会话；自动化测试不会连接或操作真实微信。

MCP 配置示例见 [`.mewcode/mcp-servers.example.yaml`](.mewcode/mcp-servers.example.yaml)。复制为 `$HOME\.mewcode\mcp.yaml` 后，按需设置其中引用的环境变量。每个 Server 必须显式声明 `type: stdio` 或 `type: http`；`env` 和 `headers` 的值支持 `${VAR}` 展开。

### Sub-agents

主 Agent 始终拥有固定的五个系统工具：`Agent`、`TaskList`、`TaskGet`、`TaskStop` 和 `SendMessage`。`Agent` 的 `subagent_type` 非空时运行预定义角色；省略该字段时 Fork 当前对话历史，并且始终转入后台。

角色文件采用 Markdown 加 YAML frontmatter，按项目、用户、内置（插件位当前为空）的优先级覆盖：

1. `<project>/.mewcode/agents/*.md`
2. `~/.mewcode/agents/*.md`
3. 安装包内置角色

```markdown
---
name: investigate-api
description: Inspect an API implementation without changing files.
tools: [read_file, glob, grep]
disallowedTools: [bash]
model: haiku
maxTurns: 20
permissionMode: plan
background: false
---

Work independently, use the available tools, and return a concise result.
```

`model` 是 `config.yaml` 中的 Provider `name`（或 `inherit`），不是硬编码模型 ID。内置角色包括 `general-purpose`、`explore` 和 `plan`。子 Agent 分别隔离消息、会话权限、文件读缓存、Token 用量与 Hook 会话状态；只有显式的 Allow Forever 会写入持久权限规则。

定义式任务可用 `run_in_background: true` 转后台，或在前台超过 120 秒后自动接管。Fork 必须后台。后台任务完成后会在主 Agent 下一次模型请求中以一次性的 `<task-notification>` 提醒提供结果；通知不写入对话或会话归档。`enable_subagent_background: false` 可禁用定义式后台，Fork 则会返回结构化错误。

子 Agent 看不到 Agent/Task 控制工具，且无法运行 fork Skill；它们可在独立上下文中加载 inline Skill。文件读缓存仅在各自子 Agent 内有效，文件外部变动或成功写入/编辑会使对应缓存失效。

### Hook

Hook 在 Agent 生命周期的固定时刻自动执行声明式动作。启动时依次读取并合并以下 UTF-8 YAML 文件；同一文件内按声明顺序执行，项目级规则在用户级规则之前：

1. `<项目根目录>/.mewcode/hooks.yaml`
2. `~/.mewcode/hooks.yaml`

文件缺失不提示；YAML、字段或单条规则错误会写入 stderr 并跳过出错项，不会阻止启动。Hook 名称用于日志与 `only_once` 跟踪，必须全局唯一；后加载的同名规则会被跳过。配置在启动期加载，编辑后需重启。

每条规则由 `event`、可选 `if` 和 `action` 组成。条件组只能选择 `all_of` 或 `any_of` 之一；`field` 使用点分路径，缺失值按空字符串匹配。`match` 与权限规则共用 `exact`、`glob`、`regex` 和递归 `not` 四种模式。

```yaml
hooks:
  - name: block-lockfile-write
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: {type: exact, value: write_file}
        - field: tool_input.path
          match: {type: regex, value: ".*package-lock\\.json"}
    action:
      type: shell
      command: "echo package-lock.json 应由 npm install 生成 >&2; exit 2"

  - name: format-python
    event: PostToolUse
    if:
      all_of:
        - field: tool_name
          match: {type: exact, value: write_file}
        - field: tool_input.path
          match: {type: glob, value: "**/*.py"}
    action:
      type: shell
      command: "python scripts/format_hook.py"
    async: true
    timeout: 5s

  - name: reply-in-chinese
    event: SessionStart
    action:
      type: prompt
      text: "使用 zh-CN 回复。"

  - name: notify-done
    event: Stop
    action:
      type: http
      url: http://127.0.0.1:9999/done
      method: POST
      body: '{"event":"{event}","session":"{session_id}"}'
```

支持的事件为 `SessionStart`、`SessionEnd`、`SessionResume`、`UserPromptSubmit`、`Stop`、`PreUserMessage`、`PreToolUse`、`PostToolUse`、`PreCompact`、`PostCompact` 和 `Notification`。所有事件都带有 `event`、`session_id`、`cwd`、`mode`；工具事件另带 `tool_name`、`tool_input`、`tool_result` 和 `is_error`，消息事件带 `prompt`，压缩事件带 `trigger` 和 Token 估算。

动作类型与约束：

- `shell.command` 通过 shell 执行，并从标准输入接收按键排序的单行事件 JSON；不支持 `$EVENT`、`$TOOL_ARGS.xxx` 等变量替换。
- `prompt.text` 原样加入下一次模型请求的隐藏 reminder，排在计划模式 reminder 之后；不写入可见对话、JSONL、长期记忆或压缩历史。`PreUserMessage` 的提示会直接影响当前请求。
- `http` 支持 `url`、可选 `method`、`headers` 和 `body`；缺省 body 为事件 JSON，显式 body 仅支持 `{field}` 的 `str.format_map` 插值。
- `subagent` 需给出 `agent_name` 和 `prompt`，当前仅写固定的未实现日志，不启动子 Agent。

`PreToolUse` 与 `UserPromptSubmit` 可拦截：同步 shell 以退出码 `2` 拦截并使用 stderr（或 stdout）作为原因；同步 HTTP 在 2xx 响应体为 `{"decision":"block","reason":"..."}` 时拦截。工具拦截会把 `[hook <name>] <reason>` 作为错误工具结果回灌模型，用户提交拦截则保留输入且不写入会话。其他 Hook 失败仅以 `[hook <name>] <event> failed: <reason>` 写 stderr 并放行。

`only_once: true` 在当前会话首次匹配时预留，动作成功后才确认；失败会释放，以便后续事件重试。`async: true` 让 shell、HTTP 或 subagent 在后台运行；拦截事件和 `prompt + async` 都是加载错误。`timeout` 为 shell/HTTP 的最长时长，默认 `30s`。`only_once` 不跨进程持久化，Hook 没有显式优先级、热更新、依赖或重试。

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
| `/skill` | 列出当前可用与已激活的 Skill、来源和诊断摘要，不显示 SOP 正文。 |
| `/hooks` | 按事件列出启动期加载的 Hook、动作、`[once]` / `[async]` 标记和配置来源；没有规则时显示 `No hooks loaded.`。 |
| `/<name> [参数]` | 执行发现到的 Skill；内置 `/commit`、`/review`、`/test` 与第三方 Skill 使用同一入口。 |
| Esc | 命令菜单展开时关闭菜单并保留输入；否则取消当前 Agent Loop。 |
| 流式状态 Ctrl+C | 取消当前 Agent Loop，保留会话继续对话。 |
| 空闲状态 Ctrl+C / `/exit` | 退出程序。 |

所有以 `/` 开头的输入都由本地命令分发器处理，未知命令不会发送给模型。`/help`、`/status`、`/memory`、`/permission`、`/session` 等纯本地命令不创建会话、不写入模型上下文，也不消耗模型 Token。

命令菜单是输入框下方的内联列表，不会夺取输入焦点。规范名称和别名都会参与前缀匹配，但选择结果始终写回规范名称；输入包含参数、没有匹配项、离开 Slash 输入或按 Esc 时菜单关闭。`/h`、`/c` 仍可作为别名直接提交执行。

### Skill

Skill 用于把可复用的 AI 工作流封装为 Markdown 能力包。MewCode 启动时只把每个有效 Skill 的名称和一句说明注入给 Agent；模型需要执行时调用系统工具 `load_skill`，完整 SOP 才会进入后续每轮请求最前部的动态环境。

Skill 按以下三层位置发现，同名时前者覆盖后者：

1. `<项目根目录>/.mewcode/skills/`
2. `~/.mewcode/skills/`
3. MewCode 安装包内置目录

根目录下的 `*.md` 是单文件 Skill。目录型 Skill 的入口固定为 `<skill-dir>/SKILL.md`，同目录可放模板、示例、参考文档和辅助脚本；这些附属文件不会被当作独立 Skill 发现或自动执行。

每个入口以 YAML frontmatter 开始，正文是发给模型的 SOP。`{{args}}` 会被调用参数做字面替换：

```markdown
---
name: review-api
description: 审查指定 API 改动并报告风险
allowed_tools: [read_file, glob, grep]
mode: inline
fork_history: none
model: null
---

审查与“{{args}}”相关的改动，按严重程度报告问题和测试缺口。
```

`name`、`description`、`allowed_tools`、`mode` 和 `fork_history` 为必填字段。名称只能使用小写 ASCII 字母、数字和连字符；`mode` 为 `inline` 或 `fork`，当前 `fork_history` 固定为 `none`；`model` 可省略或指定模型名。格式错误的单个文件会出现在 `/skill` 的诊断摘要中，但不会阻断其他 Skill。

`inline` 在当前主对话中执行，参数、工具过程和结果会保留在会话历史与 JSONL 档案中。`fork` 使用隔离 Agent 执行，不携带任何主对话历史，只接收 `/<name>` 后的参数；完成后只向主会话写入调用事件和简短摘要。

激活 inline Skill 后，模型只能看到其 `allowed_tools` 声明的普通工具；`load_skill` 和 `install_skill` 是系统工具，不受该白名单影响，现有计划模式和权限规则仍然生效。启动时若任何有效 Skill 声明了不存在的普通工具，MewCode 会在进入 TUI 前报错。`/clear`、切换 Provider、恢复会话和退出程序都会清除已激活的 Skill。

每个有效 Skill 都会自动注册 `/<name>`，并出现在 `/help` 与补全菜单。目录内容变更、安装成功和新回合开始时会自动刷新，无需重启。内置样板包含：`commit`（提交前检查与提交）、`review`（代码审查）和 `test`（隔离测试执行）。

模型可通过 `install_skill` 从 HTTPS URL 或本地 ZIP 安装目录型 Skill 到用户级目录。安装拒绝明文 HTTP、非 ZIP 本地文件、路径穿越、绝对路径和符号链接，且不会执行包内脚本；同名已安装 Skill 不会被覆盖。本阶段不提供 Skill 市场、远程浏览、发布、评分或版本管理。

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

1. 稳定系统提示：身份、系统约束、任务模式、动作执行、工具使用、语气风格、可用 Skill 名称与说明，以及文本输出模块。
2. 动态环境信息：已激活 Skill 的完整 SOP、工作目录、平台、日期、Git 状态、应用版本与模型。
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
- 已完成 Chapter 09 Slash 命令注册与分发系统：本地命令、别名、帮助、参数校验、实时内联补全、界面控制抽象和会话 Token usage 持久化。
- 已完成 Chapter 10 Skill 系统：三层发现与覆盖、两阶段 SOP 加载、inline/fork 执行、工具白名单、动态 Slash 命令、HTTPS/本地 ZIP 安装与内置 `commit`、`review`、`test` 样板。
- 2026-07-20 已完成 Chapter 09 全量回归：`191 passed, 1 skipped`；编译、Ruff 检查和格式检查均通过。压缩检查点的多次恢复正确性仍列为已知技术债，见下方限制。

## 当前限制

- 不提供运行中切换 Provider/模型的命令。
- 缓存命中由 Provider 决定，OpenAI 兼容端点可能不返回 `cached_tokens`。
- 上下文压缩仍有两项已知限制：`/compact` 尚未按手动 3K Token 余量判定；摘要请求尚未包含工具结果正文。连续压缩后再恢复的检查点索引需要补充端到端回归与修复。
