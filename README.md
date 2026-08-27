# MewCode 微信聊天机器人

一个基于 MewCode 改造的本地微信聊天机器人。它通过 Windows UI Automation 读取已经登录的微信桌面客户端消息，调用配置好的 Anthropic 或 OpenAI 兼容模型生成回复，再将结果发送回微信。

本项目同时保留 MewCode 原有的终端 Coding Agent 能力，因此同一套代码包含两个使用入口：

- `mewcode`：面向开发者的终端 Coding Agent。
- `mewcode-wechat`：面向微信私聊和群聊的本地聊天机器人。

微信机器人运行在本机桌面，不是服务器版微信机器人，也不会自动登录、操作多个微信账号或主动向陌生会话发送消息。

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [两个项目的 Tool](#两个项目的-tool)
- [环境要求](#环境要求)
- [安装](#安装)
- [配置](#配置)
- [使用](#使用)
- [消息处理规则](#消息处理规则)
- [数据与隐私](#数据与隐私)
- [项目结构](#项目结构)
- [开发与测试](#开发与测试)
- [当前限制](#当前限制)
- [许可证](#许可证)

## 项目简介

### MewCode 基础项目

MewCode 是一个 Python 编写的终端 Coding Agent，提供：

- Anthropic Claude 与 OpenAI 兼容协议；
- 流式对话、多轮会话和 Token 用量统计；
- ReAct Agent Loop，以及受权限控制的本地工具调用；
- MCP、Skill、Sub-agent、Hook 和项目级记忆；
- Textual + Rich 终端界面。

### 微信聊天机器人改造

微信模块复用 MewCode 的 Provider、Agent、Session 和上下文能力，但单独增加了微信渠道适配：

```text
微信桌面客户端
        │ Windows UI Automation
        ▼
消息监听、白名单与队列
        ▼
MewCode Agent + 配置的 LLM Provider
        ▼
回复清洗、气泡切分、微信发送
```

微信侧使用独立的角色提示词、回复协议和工具白名单。微信用户不会继承终端 Agent 的本地文件、命令执行、MCP、Skill 或 Sub-agent 能力。

## 功能特性

- 支持微信私聊文字消息。
- 支持微信私聊图片问答；单批最多 4 张图片。
- 支持一层文字引用和图片引用；引用文件、语音、视频和分享卡片暂不处理。
- 支持群聊白名单和完整 `@机器人名称` 触发，并使用本机 OCR 校验发送者。
- 私聊消息在停止发送 7 秒后合并为一个意图，并按全局 FIFO 顺序处理。
- 每名好友使用独立、持久化的 MewCode Session；群聊只保留本次启动后的最近 20 条内存上下文。
- 闲聊支持最多 7 个自然气泡；专业回答保持完整纯文本。
- 可选启用当前时间、Tavily 网页搜索和公开网页正文读取。
- 支持 Anthropic 和 OpenAI 兼容 Provider；图片问答需要使用支持视觉输入的模型。
- 通过白名单、权限边界、来源记录、SSRF 防护和临时文件清理降低自动化风险。

## 两个项目的 Tool

这里的“两个项目”指同一仓库中的两个运行入口：MewCode 终端 Agent，以及基于它改造的微信聊天机器人。下面列出模型可以调用的 Tool；微信 UIA、OCR、消息监听和消息发送属于宿主能力，不会直接暴露给微信侧模型。

### 1. MewCode 终端 Agent

#### 核心 Tool

| Tool | 类型 | 作用 |
|---|---|---|
| `read_file` | 只读 | 读取 UTF-8 文本文件，并返回带行号的内容。 |
| `write_file` | 写入 | 创建或覆盖 UTF-8 文本文件，并自动创建父目录。 |
| `edit_file` | 写入 | 唯一匹配 `old_string` 后替换为 `new_string`；编辑前应先读取文件。 |
| `bash` | 执行 | 执行本地 Shell 命令并返回标准输出、标准错误和退出码。 |
| `glob` | 只读 | 按 glob 模式查找文件并返回排序后的路径。 |
| `grep` | 只读 | 使用 Python 正则搜索文本文件，返回文件、行号和命中内容。 |

#### 系统与扩展 Tool

终端 TUI 还会按运行时条件注册以下系统 Tool：

| Tool | 作用 |
|---|---|
| `load_skill` | 加载 Skill 的完整工作流；fork Skill 会隔离执行。 |
| `install_skill` | 从 HTTPS URL 或本地 ZIP 安装用户级 Skill。 |
| `Agent` | 委托任务给定义式或 Forked Sub-agent。 |
| `TaskList` | 查看后台 Sub-agent 任务列表。 |
| `TaskGet` | 查看指定后台任务。 |
| `TaskStop` | 请求停止后台任务。 |
| `SendMessage` | 向已完成的命名后台任务继续发送任务。 |
| MCP Tool | 从 `~/.mewcode/mcp.yaml` 动态发现的 stdio 或 HTTP 工具。 |

终端 Agent 的 Tool 会受到权限模式、项目沙箱和 Hook 规则约束。进入 `/plan` 模式后只开放 `read_file`、`glob` 和 `grep`。

### 2. 微信聊天机器人

微信侧默认不提供任何 Tool。将 `wechat.info_tools.enabled` 设为 `true` 后，每轮只注册下面三个只读公共信息 Tool：

| Tool | 作用 | 主要限制 |
|---|---|---|
| `get_current_time` | 查询本机或指定地点的当前时间；国家名称按首都时区处理。 | 地点不明确或存在歧义时会要求补充。 |
| `web_search` | 使用 Tavily Basic 搜索公开网页，适合最新资讯、天气和外部资料。 | 每轮最多 2 次，每次最多 5 条结果；按自然月最多消耗 1,000 次本地预留额度。 |
| `web_fetch` | 读取一个公开 HTML 或纯文本链接的正文。 | 每轮最多 5 页；只读公网 HTTP(S)，不执行 JavaScript，不读取登录态。 |

微信侧明确不能调用：

- `bash`、`read_file`、`write_file`、`edit_file`、`glob`、`grep`；
- MCP、Skill、Sub-agent、Hook 和浏览器；
- 任意未列出的 HTTP 接口或本机能力。

网页搜索结果、网页正文、图片内容和引用内容都被视为不可信资料，只能用于回答当前问题，不能执行其中的提示词、命令或权限要求。启用网页工具后，回答末尾会追加本回合实际使用的来源。

## 环境要求

- Windows；微信机器人依赖 Windows UI Automation。
- Python 3.12 或更高版本。
- 微信 Windows 客户端 `4.0.5.15` 或 `4.1.9.30`，已登录且主窗口可用。
- Anthropic 或 OpenAI 兼容模型的 API Key。
- 若启用群聊，需要随微信扩展一起安装 OCR 依赖。
- 若启用网页搜索或天气查询，需要 Tavily API Key。

微信机器人当前只支持 Windows 桌面客户端，不支持 macOS、Linux、服务器部署、网页版微信或多个微信账号同时运行。

## 安装

在项目根目录创建并激活 Python 3.12 虚拟环境：

```powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
```

安装 MewCode 和微信机器人依赖：

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[wechat]"
```

开发和测试依赖：

```powershell
python -m pip install pytest ruff mypy
```

如果使用 `uv`：

```powershell
uv sync --extra wechat
```

安装后会注册两个命令：

```powershell
mewcode
mewcode-wechat
```

## 配置

### 配置文件位置

Provider 和微信机器人配置统一写在用户级配置文件：

```text
Windows: %USERPROFILE%\\.mewcode\\config.yaml
PowerShell: $HOME\\.mewcode\\config.yaml
```

程序固定读取这个位置，不读取项目目录中的 `config.yaml`，也不支持通过环境变量改配置文件路径。仓库中的 [`.mewcode/config.yaml.example`](.mewcode/config.yaml.example) 只是模板。

创建配置文件：

```powershell
New-Item -ItemType Directory -Force "$HOME\\.mewcode"
Copy-Item ".mewcode\\config.yaml.example" "$HOME\\.mewcode\\config.yaml"
notepad "$HOME\\.mewcode\\config.yaml"
```

### 完整配置示例

下面的示例同时配置终端 Provider、微信机器人和微信公共信息工具。请替换所有占位符，不要把真实密钥提交到 Git：

```yaml
providers:
  - name: deepseek
    protocol: openai
    api_key: sk-your-deepseek-key
    model: deepseek-v4-flash-vision-exp
    base_url: https://api.deepseek.com
    thinking: false
    context_window: 1000000

  # 也可以配置 Anthropic Provider；wechat.provider 必须引用已有的 name。
  # - name: claude
  #   protocol: anthropic
  #   api_key: sk-ant-your-key
  #   model: claude-sonnet-4-5
  #   base_url: https://api.anthropic.com
  #   thinking: true
  #   context_window: 200000

enable_subagent_background: true

wechat:
  enabled: true
  provider: deepseek
  allowed_contacts:
    - 专用测试好友
  allowed_groups:
    - 专用测试群
  self_names:
    - 机器人在群里的完整名称
  task_timeout_seconds: 180
  max_reply_chars: 1500
  log_level: INFO
  info_tools:
    enabled: true
    tavily_api_key: ${TAVILY_API_KEY}
    nominatim_user_agent: MewCode-WeChat/0.1
    nominatim_proxy: ${HTTPS_PROXY}
```

说明：`providers[].api_key` 当前要求填写字符串；微信公共信息配置中的 Tavily Key 和 Nominatim 代理支持使用完整形式的 `${环境变量名}` 引用。

### Provider 配置

| 字段 | 必填 | 说明 |
|---|---:|---|
| `name` | 是 | Provider 的唯一标识；微信通过 `wechat.provider` 引用它。 |
| `protocol` | 是 | `anthropic` 或 `openai`。 |
| `api_key` | 是 | 对应服务的 API Key。请保存在用户目录配置，不要提交到仓库。 |
| `model` | 是 | 使用的模型名称。图片消息需要模型支持视觉输入。 |
| `base_url` | 否 | 自定义 API 地址或 OpenAI 兼容端点。 |
| `thinking` | 否 | 仅 Anthropic Provider 生效，默认 `false`。 |
| `context_window` | 否 | 模型上下文 Token 上限，默认 `1000000`。 |

终端模式配置多个 Provider 时，启动后可以选择 Provider；微信模式始终使用 `wechat.provider` 指定的 Provider。

### 微信配置

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `false` | 是否启用微信机器人。 |
| `provider` | 无 | 必须与 `providers` 中某个 `name` 完全一致。 |
| `allowed_contacts` | `[]` | 允许处理的好友名称，精确匹配。启用机器人时，好友和群聊白名单至少配置一项。 |
| `allowed_groups` | `[]` | 允许处理的群名称，精确匹配。启用群聊时必须配置 `self_names`。 |
| `self_names` | `[]` | 机器人在群聊消息中可能显示的完整名称，用于识别 `@` 和 OCR 发送者。 |
| `task_timeout_seconds` | `180` | 单个微信任务的最大处理时间，必须为正数。 |
| `max_reply_chars` | `1500` | 单条回复的最大字符数，必须为正整数。 |
| `log_level` | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR` 或 `CRITICAL`。 |

白名单注意事项：

- `allowed_contacts` 和 `allowed_groups` 使用微信中显示的会话名称，不是备注 ID 或微信号。
- 私聊和群聊白名单不能出现同名会话。
- 群聊必须填写机器人在微信中实际显示的完整 `@名称`；名称不匹配时不会触发回复。
- 搜索结果不唯一、群成员 OCR 不唯一或无法恢复目标会话时，程序会安全拒绝回复。

### 公共信息工具配置

`wechat.info_tools.enabled` 默认为 `false`。启用后：

- `get_current_time` 可以查询本机时间和地点时间。
- `web_search` 和天气查询需要 `tavily_api_key`；建议通过 `${环境变量名}` 注入，而不是把 Key 写进配置示例。
- `web_fetch` 可以读取用户提供的公开静态页面，即使没有 Tavily Key 也可以工作。
- `nominatim_user_agent` 用于地点解析请求，并会标注 OpenStreetMap 数据来源。
- 只有显式配置 `nominatim_proxy` 时，地点解析才使用该代理；Tavily 和公开网页读取不继承这个代理。
- 公共网页搜索使用 Tavily Basic；搜索失败、额度耗尽或来源不足时不会自动切换到未配置的搜索源或付费接口。

在 PowerShell 中设置 Tavily Key 并启动：

```powershell
$env:TAVILY_API_KEY = "tvly-your-key"
mewcode-wechat
```

### MCP、权限、Hook 与项目指令

这些配置属于 MewCode 终端 Agent，不会被微信侧继承：

| 文件 | 作用 |
|---|---|
| `~/.mewcode/mcp.yaml` | 终端 Agent 的 MCP Server 配置；可参考 [`.mewcode/mcp-servers.example.yaml`](.mewcode/mcp-servers.example.yaml)。 |
| `<项目根>/.mewcode/settings.yaml` | 项目级权限规则和默认权限模式。 |
| `<项目根>/.mewcode/settings.local.yaml` | 本机未提交的权限规则，优先级高于项目级规则。 |
| `<项目根>/.mewcode/hooks.yaml` | 终端 Agent 生命周期 Hook。 |
| `<项目根>/MEWCODE.md` | 项目级指令。也支持 `<项目根>/.mewcode/MEWCODE.md`。 |

MCP Server 必须显式声明 `type: stdio` 或 `type: http`；`env` 和 `headers` 支持 `${环境变量名}` 展开。微信机器人不会加载 MCP、Hook 或项目级本地工具。

### 项目运行数据

启动命令时的当前目录会被视为项目根目录。MewCode 和微信机器人会在这个目录下保存运行数据：

```text
<项目根>/
├── .mewcode/
│   ├── sessions/          # 终端会话和好友私聊 Session 的 JSONL 档案
│   ├── cache/             # 工具结果缓存
│   ├── memory/            # 项目级记忆
│   └── wechat.sqlite3     # 微信事件去重、会话绑定和公共信息缓存
└── ...
```

这些运行数据已被 `.gitignore` 排除。微信机器人应从希望保存运行数据的项目根目录启动，而不是从任意临时目录启动。

## 使用

### 启动终端 MewCode

在已安装依赖并准备好 `config.yaml` 后：

```powershell
mewcode
```

也可以直接运行模块：

```powershell
python -m mewcode
```

常用命令：

| 命令 | 作用 |
|---|---|
| `/help` | 查看可用命令和单条命令帮助。 |
| `/plan` | 进入只读计划模式，只开放查找和读取工具。 |
| `/do` | 退出计划模式并恢复执行工具。 |
| `/resume` | 恢复历史会话。 |
| `/compact` | 手动压缩当前模型上下文。 |
| `/status` | 查看权限、Token、工具、模型和工作目录。 |
| `/clear` | 结束当前会话并开启新会话。 |
| `/exit` | 退出程序。 |

### 启动微信聊天机器人

#### 1. 准备微信客户端

1. 安装并激活包含 `[wechat]` 依赖的 Python 环境。
2. 打开微信 Windows 客户端并登录一个账号。
3. 保持 Windows 桌面解锁、微信主窗口可见，并确保只运行一个已登录账号。
4. 首次验证使用已明确授权的专用好友或群聊。

微信 `4.1.9.30` 如果只暴露 Qt 外壳，需要先启动 Windows 讲述人，再彻底退出微信（包括托盘进程）并重新启动微信。程序不会自动操作讲述人或重启微信。

#### 2. 只读探测控件

从项目根目录执行：

```powershell
mewcode-wechat --probe
```

探测结果应显示支持的版本 `4.0.5.15` 或 `4.1.9.30`，并包含以下必要控件：

- `session_list`
- `chat_message_list`
- `chat_input_field`

探测失败时不要直接启动机器人，先根据错误信息检查微信版本、登录状态、桌面锁定状态和讲述人设置。

#### 3. 启动机器人

```powershell
mewcode-wechat
```

机器人只处理配置白名单中的会话，并只处理启动后到达的消息。第一次收发建议使用普通好友验证；微信的“文件传输助手”是特殊页面，不作为 V1 测试会话。

## 消息处理规则

### 私聊

- 连续普通文字消息在停止发送 7 秒后合并为一个意图。
- 不同好友的任务按全局 FIFO 顺序串行执行，不交错发送。
- 好友在当前任务排队、调用工具或发送气泡期间继续发来普通消息时，当前任务会被取消，新消息重新进入合并窗口。
- 支持一批 1～4 张 JPEG、PNG、GIF 或 WebP 图片；单边不超过 8192 像素，原始数据总量不超过 32 MiB。
- 图片和文字同时到达时只进行一次图文问答；只有图片没有文字时才生成简短图片描述。
- 私聊引用必须包含一层文字或图片引用，以及非空的当前问题；引用会作为独立 FIFO 意图处理。

### 群聊

- 群名必须在 `allowed_groups` 中。
- 普通问题和引用问题的当前文字区域必须包含 `self_names` 中的完整 `@名称`。
- 本机 OCR 必须唯一识别出发送者昵称；识别失败时不会猜测发送者，也不会回复。
- 群聊普通图片不能单独触发机器人；符合门禁的引用图片可以用于当前引用问答。
- 每个群只在内存中保留本次启动后的最近 20 条带发送者名称的消息。
- 回复第一条气泡会尝试真正 `@` 提问者；成员菜单无法唯一匹配时降级为可见文本 `@昵称`。

### 引用、回复与来源

- 只解析当前一层引用。
- 支持引用文字和引用图片；不支持引用文件、语音、视频、分享卡片或其他附件。
- 原文定位失败时可能使用引用预览或缩略图，回答会说明内容可能不完整。
- 闲聊输出使用 `<|bubble|>` 分隔气泡，通常 1～4 个，最多 7 个；专业回答、代码和工具结果不使用气泡协议。
- 使用网页或地点工具时，最终回复会追加本回合实际使用的网页来源或 OpenStreetMap 数据署名。

## 数据与隐私

请在启用前确认自己已经获得相关好友和群聊成员的授权。程序具有以下数据行为：

- 微信消息通过配置的模型 Provider 发送；图片问答需要把图片上传给支持视觉输入的 Provider。
- 白名单私聊图片会以 Base64 形式写入对应好友的 Session JSONL；临时截图会在成功、失败、取消或超时后清理。
- 群聊引用图片只在当前请求中临时使用，不写入群聊上下文，也不保存 Base64。
- 私聊好友使用独立 Session；群聊只使用本次启动后的内存上下文，不恢复启动前的群消息。
- 网页搜索只提交必要的搜索词；不会把好友身份、完整聊天历史、凭据、手机号、身份证号或精确住址发送给外部信息服务。
- 网页正文和搜索结果缓存在当前项目的 `.mewcode/wechat.sqlite3`，不会写入好友 JSONL、长期记忆或 `.mewcode/cache`；公共信息缓存最长保留 7 天。
- `web_fetch` 只读取公网 HTTP(S) 的 HTML 或纯文本，不执行 JavaScript、不读取登录态，并在重定向时重新检查 SSRF 边界。
- API Key、代理地址和其他敏感配置不要提交到仓库；配置模板只放占位符。

## 项目结构

```text
Mewcode/
├── pyproject.toml                 # 依赖、可选依赖和两个命令入口
├── README.md
├── .mewcode/
│   ├── config.yaml.example        # 用户级 config.yaml 模板
│   ├── mcp-servers.example.yaml   # MCP 配置模板
│   └── ...                        # 本地运行数据和项目配置
├── src/mewcode/
│   ├── agent/                     # ReAct Agent Loop
│   ├── tool/                      # MewCode 六个核心 Tool
│   ├── llm/                       # Anthropic / OpenAI Provider
│   ├── mcp/                       # MCP 配置和工具管理
│   ├── skill/                     # Skill 发现、加载和安装
│   ├── subagent/                  # 子 Agent 与后台任务
│   ├── permission/                # 权限、沙箱和规则
│   ├── session/                   # Session 档案和恢复
│   ├── tui/                       # 终端界面
│   └── wechat/
│       ├── cli.py                 # mewcode-wechat 入口
│       ├── bot.py                 # 微信事件监听、队列和回复发送
│       ├── runtime.py             # 微信侧 Agent Runtime
│       ├── config.py              # 微信配置解析
│       ├── uia_client.py           # 微信 UIA 控件访问
│       ├── uia_driver.py           # 会话、消息和目标校验
│       ├── group_sender_ocr.py     # 群发送者 OCR
│       ├── image.py               # 图片校验、编码和临时文件
│       ├── info/                  # 时间、网页和地点工具
│       ├── prompts/               # 微信角色与回复协议
│       └── store.py               # 微信 SQLite 状态与缓存
└── tests/                         # 单元测试和集成逻辑测试
```

## 开发与测试

自动化测试不会连接或操作真实微信客户端。建议在项目根目录执行：

```powershell
python -m pytest -q
python -m compileall src\\mewcode tests
python -m ruff check .
python -m ruff format --check .
python -m mypy src\\mewcode
```

微信相关测试主要覆盖配置解析、消息去重、队列、Session、图片限制、引用解析、公共信息工具和 UIA 驱动逻辑。真实微信验证应使用专用账号、最小化白名单和明确授权的测试会话。

## 当前限制

- 仅支持 Windows 桌面微信 `4.0.5.15` 和 `4.1.9.30`。
- 不支持 macOS、Linux、网页版微信、服务器部署、多账号和主动发送。
- 不支持群聊普通图片触发、语音理解、文件内容理解和其他附件理解。
- 微信 `4.1.9.30` 的 UIA 控件可见性可能依赖 Windows 讲述人；程序不会自动修复客户端环境。
- 网页搜索依赖 Tavily Basic 和本地每月额度；搜索失败时不会编造结果，也不会自动切换到未批准的数据源。
- 引用图片和好友私聊图片会受到模型视觉能力、网络、图片大小及本地 Session 空间限制。
- 运行数据和配置依赖当前工作目录与用户级 `.mewcode` 目录；更换启动目录前请先确认数据存放位置。

## 许可证

当前仓库未提供独立的 `LICENSE` 文件。用于公开发布或再分发前，请由维护者补充明确的许可证和第三方依赖声明。

## 致谢

- MewCode 终端 Agent 基础架构。
- 微信 Windows 客户端的 Windows UI Automation 接口。
- Tavily Basic 公共网页搜索。
- OpenStreetMap Nominatim 地点解析。
- 国家首都数据生成所使用的 [mledoze/countries](https://github.com/mledoze/countries) 与 [GeoNames](https://www.geonames.org/) 数据。
