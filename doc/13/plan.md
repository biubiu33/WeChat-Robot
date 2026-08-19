# MewCode 微信桌面聊天机器人 V1 Plan

状态：已批准

## Architecture Overview

V1 在 MewCode 包内新增一个仅 Windows 可用的微信桌面入口，继续复用现有 `Agent`、Provider、`SessionRuntime` 和 `SessionRepository`。微信入口不启动 Textual TUI，也不加载普通工具、MCP、Skills、Sub-agent、Hook 或长期记忆。

微信适配器使用 MewCode 自己的配置、默认值和控件定位结果，不读取或继承 fake-wx-account 的配置、控件选择器、操作节拍及版本假设。fake-wx-account 仅可用于参考与版本无关的通用算法，例如 Shell Hook 唤醒、消息快照、方向判断、去重和发送前目标复核。

```text
WeChat 4.1.12.55
  -> Windows Shell Hook
  -> UIA snapshot reader
  -> WechatDesktopEvent
  -> allowlist/filter/dedup
  -> global asyncio FIFO
  -> WechatAgentRuntime
  -> existing MewCode Agent + SessionRuntime
  -> final text
  -> target revalidation
  -> UIA text sender
```

V1 不新增通用 Channel 接口。只有微信一个非 TUI 入口时，直接实现 `mewcode.wechat`，等出现第二个真实渠道后再抽象。

## Core Data Structures

### `WechatConfig`

```python
@dataclass(frozen=True)
class WechatConfig:
    enabled: bool
    provider: str
    allowed_contacts: tuple[str, ...]
    system_prompt: str
    task_timeout_seconds: float
    max_reply_chars: int
    log_level: str
```

- 配置位于现有 `~/.mewcode/config.yaml` 的 `wechat` 段。
- `provider` 必须引用现有 `providers[].name`。
- `allowed_contacts` 使用微信会话显示名做精确匹配。
- 如果 UIA 同时发现重名私聊，V1 拒绝自动回复这些重名会话并记录诊断，避免错误合并。
- 未配置或 `enabled: false` 时，微信入口给出明确提示后退出。

### `WechatDesktopEvent`

```python
@dataclass(frozen=True)
class WechatDesktopEvent:
    event_id: str
    fingerprint: str
    conversation_key: str
    conversation_name: str
    sender_name: str
    text: str
    observed_at: float
    incoming: bool
    private: bool
```

- 只表达 V1 需要的私聊文字信息。
- 不把 UIA Control 对象带出驱动层。
- `conversation_key` 优先来自会话行 RuntimeId；重名时不使用显示名降级。
- `fingerprint` 由会话、方向、正文和可见消息身份组成，用于重复观察去重。

### `ConversationBinding`

```python
@dataclass(frozen=True)
class ConversationBinding:
    conversation_name: str
    session_id: str
```

- V1 只为显示名唯一的白名单私聊创建持久绑定。
- 重名会话被安全拒绝，因此不会错误共享会话。

### `QueuedMessage`

```python
@dataclass(frozen=True)
class QueuedMessage:
    event: WechatDesktopEvent
    enqueued_at: float
```

### `ActiveTurn`

```python
@dataclass
class ActiveTurn:
    conversation_name: str
    cancel: asyncio.Event
```

用于限定 `/cancel` 只能取消同一好友当前正在运行的任务。

### `WechatReply`

```python
@dataclass(frozen=True)
class WechatReply:
    conversation_name: str
    text: str
```

V1 只支持最终文本，不表达流式片段或媒体。

## Public Interfaces

### 配置

```python
def parse_wechat_config(raw: object, provider_names: set[str]) -> WechatConfig
```

负责微信配置的类型、取值范围、Provider 引用和白名单校验。

### 状态存储

```python
class WechatStateStore:
    def record_event_once(self, event: WechatDesktopEvent) -> bool
    def get_session_id(self, conversation_name: str) -> str | None
    def bind_session(self, conversation_name: str, session_id: str) -> None
    def mark_processed(self, event_id: str) -> None
```

使用 Python 标准库 `sqlite3`，数据库位于项目 `.mewcode` 状态目录。事件指纹唯一约束是最终去重门禁，会话绑定使用显示名唯一约束。

### UIA 客户端

```python
class WechatUiaClient:
    def probe(self) -> None
    def visible_private_conversations(self) -> list[ConversationRow]
    def visible_text_messages(self, row: ConversationRow) -> list[VisibleMessage]
    def focus_conversation(self, row: ConversationRow) -> None
    def send_text(self, row: ConversationRow, text: str) -> None
```

只处理窗口、控件、剪贴板、键盘和微信 UI 结构。V1 不包含文件、图片、OCR 和分享卡片能力。

### UIA 驱动

```python
class WechatUiaDriver:
    def start(self) -> None
    def close(self) -> None
    def establish_baseline(self) -> None
    def wait_for_events(self, stop: threading.Event) -> list[WechatDesktopEvent]
    def validate_target(self, event: WechatDesktopEvent) -> bool
    def send_text(self, event: WechatDesktopEvent, text: str) -> None
```

- 使用 Windows Shell Hook 唤醒扫描。
- Shell Hook 不可用时使用低频校准扫描。
- 所有 UIA 操作通过同一把锁串行执行。
- `establish_baseline()` 记录启动时现状但不产生入站事件。
- 发送前重新定位原会话并校验目标，失败时拒绝发送。

### 微信 Agent Runtime

```python
class WechatAgentRuntime:
    async def reply(
        self,
        conversation_name: str,
        text: str,
        cancel: asyncio.Event,
    ) -> str

    async def close(self) -> None
```

- 根据持久绑定创建或恢复 `SessionRuntime`。
- 使用现有 MewCode Provider 和 `Agent`。
- Agent 注册表为空，因此模型请求没有工具定义，执行层也没有任何工具可调用。
- 不加载 MCP、Skills、Sub-agent、Hook、项目指令或长期记忆。
- 使用微信专属稳定系统提示。
- 只返回最终文本；推理、Usage 和内部事件只进入受控日志。
- 每轮结束关闭当前 `SessionRuntime` Writer，下一轮按绑定恢复，避免同时打开大量好友档案。
- 使用 `asyncio.wait_for` 强制执行任务超时，并通过现有取消事件停止 Agent。

### 微信机器人协调器

```python
class WechatBot:
    async def run(self) -> None
    async def stop(self) -> None
```

- UIA 观察器运行在后台线程。
- 观察线程通过线程安全回调把事件送入唯一的 `asyncio.Queue`。
- 单个异步消费者严格 FIFO 调用 Agent。
- 构造函数接受可替换的 driver/runtime/store，测试使用轻量假对象，不引入抽象基类。

## Module Design

### `mewcode.config`

**Responsibility:** 在现有 YAML 顶层配置中保留可选 `wechat` 原始对象，同时不改变已有 Provider 和 Sub-agent 配置行为。

**Changes:**

- `Config` 增加可选微信配置原始值。
- 顶层 `wechat` 非对象时报配置错误。
- 原有调用方无需使用该字段，TUI 行为保持不变。

### `mewcode.wechat.config`

**Responsibility:** 将原始微信配置解析为不可变、已验证的 `WechatConfig`。

**Dependencies:** `mewcode.config.ProviderConfig`。

### `mewcode.wechat.models`

**Responsibility:** 保存 UIA 层和协调层之间的纯数据对象。

### `mewcode.wechat.store`

**Responsibility:** 事件去重、已处理状态和联系人到 MewCode Session 的持久绑定。

**Dependencies:** 标准库 `sqlite3`、`pathlib`、`threading`。

### `mewcode.wechat.shell_hook`

**Responsibility:** 监听目标微信进程的 Windows Shell Flash 通知，只负责唤醒，不在 Windows 消息回调中读取 UIA。

### `mewcode.wechat.uia_client`

**Responsibility:** 封装微信 4.1.12.55 的窗口、会话列表、文字气泡、输入框和文本发送操作。控件选择器必须来自用户本机该版本的 UIA 树探测结果，由 MewCode 独立维护。

**Dependencies:** 可选依赖 `uiautomation`、`pywin32`。

实现实际选择器前，先以只读方式探测微信 UIA 树，确认主窗口、会话列表、消息列表和输入框等必要控件。探测过程不得自动发送真实消息。操作等待时间从保守的 MewCode 默认值起步，只暴露实际调试证明必需的少量校准项。

会话切换使用微信自身的键盘搜索流程：激活主窗口后按 `Ctrl+F`，确认焦点位于 `mmui::XValidatorTextEdit`，输入精确好友名，确认唯一 `mmui::SearchContentCellView` 搜索结果后按 Enter，并再次核对当前聊天标题。发送使用输入框 `ValuePattern.SetValue`、`SetFocus` 和 Enter，随后确认输入框清空及目标仍匹配。两条路径都不调用鼠标 `Click()`；任何焦点、搜索值、结果唯一性或目标复核失败都安全停止。

### `mewcode.wechat.uia_driver`

**Responsibility:** 建立快照、识别新增私聊文字、构造稳定事件、过滤出站气泡、恢复微信窗口、协调扫描和发送。

**Dependencies:** UIA client、Shell Hook、models。

### `mewcode.wechat.runtime`

**Responsibility:** 选择 Provider、创建或恢复好友会话、以零工具方式运行现有 Agent，并返回最终文字。

**Dependencies:** `Agent`、`Registry`、`SessionRuntime`、`SessionRepository`、Provider factory。

### `mewcode.wechat.bot`

**Responsibility:** 白名单、消息类型过滤、去重、FIFO、取消、错误降级、回复分段和生命周期管理。

**Dependencies:** config、driver、runtime、store。

### `mewcode.wechat.cli`

**Responsibility:** 加载现有 MewCode 配置、初始化日志、启动机器人、处理 Ctrl+C 并有序关闭。

### Packaging

**Responsibility:** 注册独立 `mewcode-wechat` 命令，将 Windows UIA 依赖放入 `wechat` 可选依赖组。

## Module Interactions

### Startup

```text
mewcode-wechat
  -> load ~/.mewcode/config.yaml
  -> validate wechat config and selected provider
  -> create state store
  -> create UIA client/driver
  -> probe exactly one supported WeChat window
  -> establish baseline without emitting messages
  -> create zero-tool Agent runtime
  -> start observer thread and FIFO consumer
```

任何启动检查失败都输出一次明确错误并以非零状态退出。

### Inbound Message

```text
Shell flash / reconcile deadline
  -> inspect changed visible private conversations
  -> compare visible text bubbles with baseline
  -> create event
  -> reject outgoing/non-text/group/duplicate-name conversation
  -> exact allowlist check
  -> record_event_once
  -> enqueue
```

白名单和去重都在调用模型前完成。

### Agent Turn

```text
dequeue event
  -> handle /cancel locally or mark active turn
  -> restore/create MewCode session
  -> append friend text
  -> run existing Agent with empty Registry
  -> collect final text only
  -> close session writer
  -> clear active turn
```

自然完成后不触发长期记忆更新。

### Reply

```text
final text
  -> trim empty response
  -> split by max_reply_chars
  -> validate original conversation before each send cycle
  -> send chunks in order under UIA lock
  -> mark event processed
```

目标校验失败时记录失败并停止发送，绝不向当前可见的其他会话降级发送。

### Cancellation

```text
/cancel event
  -> verify sender matches active turn
  -> set active cancel Event
  -> send concise acknowledgement
```

没有匹配的活动任务时只返回“当前没有可取消的任务”。取消消息不进入 Agent 会话。

### Shutdown

```text
Ctrl+C
  -> set stop flags
  -> cancel active Agent turn
  -> stop UIA observer and Shell Hook
  -> drain no new work
  -> close runtime/store
```

V1 进程停止时未处理的内存队列直接丢弃；入站事件仍保留未处理状态，但下次启动先建立新基线，不自动补发历史消息。

## File Organization

```text
Mewcode/
├─ pyproject.toml                         # 可选微信依赖与独立命令
├─ README.md                              # 安装、配置、运行与安全限制
├─ src/mewcode/config.py                  # 保留可选 wechat 配置对象
├─ src/mewcode/wechat/
│  ├─ __init__.py
│  ├─ cli.py                              # 独立进程入口
│  ├─ config.py                           # 微信配置验证
│  ├─ models.py                           # 纯数据模型
│  ├─ store.py                            # SQLite 去重与 Session 绑定
│  ├─ shell_hook.py                       # Windows Shell 通知
│  ├─ uia_client.py                       # 微信 UIA 基础操作
│  ├─ uia_driver.py                       # 消息观察和安全发送
│  ├─ runtime.py                          # 零工具 MewCode Agent 会话
│  └─ bot.py                              # 白名单、FIFO、取消和错误处理
├─ tests/
│  ├─ test_wechat_config.py
│  ├─ test_wechat_store.py
│  ├─ test_wechat_runtime.py
│  ├─ test_wechat_bot.py
│  └─ test_wechat_uia_driver.py
└─ doc/13/
   ├─ spec.md
   ├─ plan.md
   ├─ task.md
   └─ checklist.md
```

## Configuration Shape

```yaml
providers:
  - name: claude
    protocol: anthropic
    api_key: ${existing-value}
    model: ${existing-model}

wechat:
  enabled: true
  provider: claude
  allowed_contacts:
    - 专用测试好友
  system_prompt: |
    你是通过微信与好友聊天的个人助手。简洁、自然地回答，不声称执行不存在的工具。
  task_timeout_seconds: 180
  max_reply_chars: 1500
  log_level: INFO
```

示例只展示字段，不提交真实凭据。现有 Provider 凭据格式本阶段不调整。

## Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| 项目归属 | 直接加入 MewCode | MewCode 是主项目，避免运行两套 Agent、会话和配置 |
| Agent 循环 | 复用现有 `Agent` | 保持行为一致，禁止复制 ReAct Loop |
| 微信工具权限 | 空 `Registry`，不注册任何工具 | 从模型 schema 和执行入口双重移除工具，比提示词限制可靠 |
| 长期记忆 | V1 不加载、不更新 | 防止好友之间和主人记忆之间泄露或污染 |
| Hooks | V1 不加载 | Hook 可执行 shell/HTTP，不符合微信聊天权限边界 |
| Skills/MCP/Sub-agent | V1 不加载 | 已被批准为范围外，减少攻击面和启动复杂度 |
| 调度 | 单个全局 FIFO | UIA 只有一个前台微信窗口，串行最容易保证目标正确 |
| UIA 唤醒 | Shell Hook + 低频校准 | 避免高频忙轮询，同时允许 Hook 失效后恢复 |
| 状态存储 | SQLite 标准库 | 原子唯一约束适合去重，无需新增依赖 |
| 好友标识 | 唯一显示名持久绑定；重名安全拒绝 | UIA 不稳定地暴露微信内部账号 ID，V1 不能可靠支持重名好友 |
| UIA 适配 | 独立适配本机微信 4.1.12.55 | 不复用 fake-wx-account 的配置、选择器、节拍或 4.1.9.30 假设；仅参考与版本无关的通用算法 |
| 微信前台操作 | 键盘搜索切换会话，输入框聚焦后 Enter 发送 | 本机 4.1.12.55 实测可用且鼠标坐标不变；UIA Selection/Invoke/Legacy 对会话切换无效，发送按钮 Invoke 会假成功 |
| 通道抽象 | 不新增通用 Channel 接口 | 当前只有一个真实需求，避免为假想渠道设计框架 |
| 回复 | 缓冲最终文本后分段发送 | 防止流式气泡轰炸和发送顺序问题 |
| Windows 依赖 | Optional dependency | 非 Windows 和普通 TUI 用户不承担 UIA 依赖 |
| 队列持久化 | V1 不持久化待处理队列 | 重启后自动补发历史消息风险高；启动基线更安全 |

## Spec Coverage

| Requirements | Design Coverage |
|---|---|
| F1-F2 | 独立 CLI、可选依赖、启动探测、现有 Agent 复用 |
| F3-F5 | Shell Hook/UIA 快照、启动基线、方向过滤、SQLite 去重 |
| F6 | SessionRuntime/Repository + 持久绑定 + 重名拒绝 |
| F7-F8 | 微信专属系统提示、空 Registry、禁用 Memory/Hook/Skill/MCP/Sub-agent |
| F9-F10 | 单 asyncio FIFO、ActiveTurn 和会话限定取消 |
| F11-F12 | 目标二次校验、最终文本分段、有限恢复、受控错误消息 |
| F13-F14 | 同一 YAML 的微信段、标准日志脱敏和生命周期日志 |
| N1-N5 | Optional dependency、无 TUI 路径修改、假 driver 测试、人工只读冒烟 |

## Validation Strategy

- 配置、状态存储、队列、取消、会话隔离和安全权限使用自动化测试。
- UIA 驱动使用合成会话行和消息快照测试，不连接真实微信。
- 全量运行现有 pytest、compileall、Ruff 和格式检查，证明 TUI 无回退。
- 真实微信先执行人工只读探测，再使用明确授权的专用普通好友做文字收发冒烟；4.1.12.55 的“文件传输助手”不暴露标准消息列表和输入框，不作为 V1 测试会话。
- 端到端验收再使用两个明确授权的测试联系人验证隔离、FIFO 和取消。
