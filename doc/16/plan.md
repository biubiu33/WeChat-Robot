# MewCode 微信自然对话节奏与分段回复 Plan

状态：已批准（2026-08-20）

## Architecture Overview

本次改造保留微信 UIA 驱动和单消费者全局 FIFO，不引入独立分类模型或新的队列依赖。协调器在 FIFO 前增加按好友隔离的 7 秒静默收集器；模型继续完成一次正式回答，并通过是否输出 `<|bubble|>` 决定使用闲聊气泡还是专业正文。

```text
微信入站事件
  -> 白名单与 SQLite 去重
  -> 按好友收集并重置 7 秒静默计时
  -> 静默期结束，带修订号进入全局 FIFO
  -> 消费时校验修订号，跳过已经失效的旧队列项
  -> 微信 Agent + 好友 Session
       -> 工具阶段事件 -> 一次自然状态消息
       -> 最终文本 -> 纯文本化与回复整形
  -> 闲聊气泡 / 专业传输分段 / 独立来源消息
  -> 可取消的顺序发送
  -> 只把实际发送成功的可见消息写入好友会话档案
```

模型不返回额外的 `chat` 或 `answer` 标签：包含 `<|bubble|>` 的普通最终回答按闲聊协议处理；不含该标记的回答按专业纯文本处理。网页工具阶段强制使用专业回答路径，防止资料答案被模型误拆成闲聊气泡。

提示词按职责分成三层：`wechat.system_prompt` 只定义可由用户调整的人物角色；`WECHAT_REPLY_POLICY` 固定定义气泡协议、专业回答格式和 few-shot；`WECHAT_INFO_POLICY` 继续定义只读信息工具安全边界。人物角色不能覆盖后两层协议和安全规则。

## Core Data Structures

### `PendingBatch`

协调器内部的每好友可变收集状态：

```python
@dataclass
class PendingBatch:
    events: list[WechatDesktopEvent]
    revision: int
    timer: asyncio.Task[None] | None = None
    queued: bool = False
```

- `events` 按实际到达顺序保存本轮尚未领取的全部事件。
- `revision` 在好友补充消息时递增，用于让已经进入 FIFO 的旧快照自然失效。
- `timer` 是可取消的 7 秒静默任务；新消息到达时取消旧任务并创建新任务。
- `queued` 表示当前修订是否已经生成一个可领取队列项。

### `QueuedBatch`

全局 FIFO 中的不可变快照：

```python
@dataclass(frozen=True)
class QueuedBatch:
    conversation_name: str
    events: tuple[WechatDesktopEvent, ...]
    revision: int
    enqueued_at: float

    @property
    def text(self) -> str: ...
```

`text` 使用换行连接原始消息，而不是空格拼接，以保留好友分条表达的边界。消费者只有在该快照与当前 `PendingBatch.revision` 一致时才领取；失效快照只从 FIFO 移除，不标记事件已处理。

### `ActiveTurn`

```python
@dataclass
class ActiveTurn:
    conversation_name: str
    cancel: asyncio.Event
    delivered: list[str]
```

- `cancel` 同时控制模型流、工具执行、工具状态通知、气泡间隔和剩余发送。
- `delivered` 只记录已经由 UIA 确认发送成功的好友可见文本，供本轮结束后提交会话档案。

### `WechatReply`

```python
@dataclass(frozen=True)
class WechatReply:
    messages: tuple[str, ...]
    chat: bool
    source_message: str = ""
```

- `messages` 是已经完成 Markdown 包装清理和长度整形的正文消息。
- `chat=True` 时，消息来自 `<|bubble|>` 语义气泡，需要长度感知间隔；否则是专业正文或专业传输分段。
- `source_message` 为空或一条独立纯文本来源消息，始终在正文之后发送。

### `FinalizedInfoReply`

```python
@dataclass(frozen=True)
class FinalizedInfoReply:
    answer: str
    source_message: str = ""
```

信息工具来源账本不再直接把来源拼进最终字符串，而是分别返回已净化正文和独立来源文本。

### Nullable archive transform

```python
MessageTransform = Callable[[Message], Message | None]
```

会话运行时允许归档转换器返回 `None`，表示该条模型消息暂不落盘。普通调用方继续返回原消息，行为不变；微信运行时只暂缓模型生成的最终 assistant 文本，用户消息和已净化工具记录仍即时写入。

## Public Interfaces

### `WechatAgentRuntime.reply`

```python
async def reply(
    self,
    conversation_name: str,
    text: str,
    cancel: asyncio.Event,
    on_tool_stage: Callable[[str], Awaitable[None]] | None = None,
) -> WechatReply
```

- 复用现有 Agent 事件流完成模型请求和工具循环。
- 第一次遇到某个工具阶段时调用 `on_tool_stage`；同一阶段后续工具调用不重复通知。
- 最终文本经过来源分离、微信纯文本化、气泡解析和专业长度整形后返回。
- 取消或错误仍使用现有受控异常，不泄露 Provider 详情。

### `WechatAgentRuntime.record_delivery`

```python
def record_delivery(
    self,
    conversation_name: str,
    messages: Sequence[str],
) -> None
```

在当前 Session writer 已关闭后，把本轮实际发送成功的工具状态、正文气泡、专业分段、来源或受控错误合并为一条 assistant 历史消息追加到对应好友档案。空列表不追加 assistant 消息。

### Reply formatting helpers

```python
def to_wechat_plain_text(text: str) -> str
def build_wechat_reply(
    text: str,
    *,
    max_chars: int,
    source_message: str = "",
    force_professional: bool = False,
) -> WechatReply
def split_professional_text(text: str, max_chars: int) -> tuple[str, ...]
```

这些函数保持为微信运行时模块中的私有纯函数，不新增通用格式化框架。

## Module Design

### `mewcode.wechat.bot`

**Responsibility:** 负责好友消息静默聚合、失效队列项、全局 FIFO、自然打断、工具状态发送、正文批次发送和实际投递记录。

**Changes:**

- 将单事件队列改为 `QueuedBatch` 队列。
- 增加 `conversation_name -> PendingBatch` 状态表。
- 每次有效入站事件都重置对应好友的 7 秒异步计时器。
- 删除 `/cancel` 的本地分支和取消确认文本；`/cancel` 与其他普通文字一样进入消息收集。
- 新消息到达时，如果同一好友正处于活动轮次，立即设置其 `cancel`；其他好友不受影响。
- 消费队列项前比较修订号。有效项从待收集状态表领取并开始处理；失效项直接跳过。
- 工具阶段回调在当前活动任务内直接顺序发送状态消息，沿用 UIA 目标复核，不创建旁路发送任务。
- 每次 UIA 发送成功后才把文本加入 `ActiveTurn.delivered`。
- 闲聊正文在第二条及以后发送前进行可取消等待。每个回复批次只采样一次每字速度，使同一批次内消息越长等待时间不会越短：

```text
seconds_per_char = 本批次一次性随机取 0.035～0.055
delay = clamp(0.25 + 下一条字符数 × seconds_per_char, 0.4, 2.0)
```

- 专业传输分段和独立来源消息不套用闲聊模拟间隔。
- 发送失败后停止本批剩余发送，记录受控日志；已成功发送部分仍提交会话档案。
- 本轮无论成功、取消或错误，都在结束时标记已领取批次中的全部事件已处理，并提交实际投递历史。
- 关闭时取消所有静默计时器和活动任务，停止接收新事件，再结束消费者。

为避免测试真实等待 7 秒，构造函数提供仅供内部和测试使用的 `quiet_seconds` 默认参数，生产默认固定为 `7.0`，不增加用户配置项。

### `mewcode.wechat.models`

**Responsibility:** 保存协调层使用的纯数据结构。

**Changes:**

- 用 `PendingBatch`、`QueuedBatch` 替代当前只包含单事件的 `QueuedMessage`。
- 将未使用的 `WechatReply(conversation_name, text)` 改为正文消息、聊天模式和独立来源字段。

### `mewcode.wechat.config`

**Responsibility:** 提供微信人物角色的默认值，并保留现有 `wechat.system_prompt` 自定义入口。

**Changes:**

- 将 `DEFAULT_SYSTEM_PROMPT` 改为统一的年轻朋友型角色：温暖、活泼、自然关心好友，可以适度开玩笑。
- 明确角色不虚构恋爱、亲属关系或现实生活经历，被问身份时如实说明是 AI 助手。
- 不新增 `persona`、`bubble_mode` 等配置字段；现有 `system_prompt` 已能表达用户可编辑角色。
- 当前实际使用的 `C:\Users\nhdt_\.mewcode\config.yaml` 已显式保存旧通用角色，因此开发时同步替换该字段，否则新的默认值不会影响现有安装。

### `mewcode.wechat.runtime`

**Responsibility:** 运行微信专属 Agent、观察工具阶段、执行回复协议并维护真实可见会话历史。

**Changes:**

- 增加稳定的 `WECHAT_REPLY_POLICY`，拼接在用户配置的微信系统提示之后，并与现有信息工具策略共同进入稳定 system 块。
- 不再直接调用只返回最终结果的便捷入口；改为消费现有 Agent 事件流，以便在工具开始前通知协调器。
- 工具名映射为少量用户可理解的阶段：
  - `get_current_time` -> 阶段 `time` -> “我看一下时间。”
  - `web_search`、`web_fetch` -> 阶段 `web` -> “我查一下相关资料。”
- 每轮维护已经通知的阶段集合；同一阶段只回调一次。未知工具不向好友暴露名称。
- 记录本轮是否进入网页阶段；进入后强制按专业回答整形，即使模型错误输出 `<|bubble|>` 也不拆成闲聊气泡。
- 暂缓归档模型最终 assistant 文本，待协调器报告实际投递后再追加可见历史。
- 提供纯函数完成 Markdown 包装清理、气泡上限归并和专业长文拆分。
- 强化稳定回复策略：多句或多语义点闲聊必须输出 `<|bubble|>`，只有单一短回应允许不带分隔符。
- 加入多句拆分和简短单气泡 few-shot；不在发送层新增句号切割或第二次意图分类，避免破坏专业回答、代码和缩写。

### `WECHAT_REPLY_POLICY`

该稳定提示参考 `_WXAUTO_SE/prompt.md` 中有效的聊天经验，但保持 MewCode 的助手身份和安全边界：

- 日常闲聊默认简短、口语化、直接回应当前语境，避免“当然可以”“希望对你有所帮助”“随时找我”等固定套话。
- 不机械复述好友原话，不无缘无故扩展成长说明，不强行开启新话题或发出邀请。
- 闲聊包含多个完整句子、问题或独立语义点时必须使用 `<|bubble|>`，不能只用逗号、句号或换行把它们留在同一个气泡；通常 1～4 条，最多 7 条。
- 只有“嗯”“好”“哈哈哈哈哈哈”等简短确认、情绪、笑声或单一语义点允许一个气泡，不为拆分而机械扩写。
- 专业知识、步骤说明、代码、资料整理和工具结果不得使用 `<|bubble|>`，应使用完整纯文本段落。
- 所有回答禁止 Markdown 加粗、标题、引用、Markdown 链接和三反引号围栏；代码直接原样输出并保留缩进。
- 工具进度由宿主发送，模型不得自行重复“我正在调用工具”。
- 不复制参考 Prompt 中的固定恋爱角色、30 字硬限制、隐藏 AI 身份、解除伦理约束、禁用最新信息或主动消息要求。
- few-shot 使用明确的“好友输入 / 你的输出”对：两条日常输入对应四个 `<|bubble|>` 气泡；“嗯”和笑声对应单气泡；专业说明和代码示例继续保持无分隔符。

### Markdown wrapper removal

`to_wechat_plain_text` 使用标准库正则和逐行状态，不删除任意单个符号：

- 三反引号围栏行被删除；围栏之间的代码行逐字保留。
- 非代码段的 Markdown 标题前缀和引用前缀被移除，正文保留。
- 非代码段的成对加粗、斜体和行内代码包装被去掉，内部文本保留。
- Markdown 链接转换成可见标题和原始 URL 的纯文本形式。
- 代码段内的 `#`、`*`、`**`、反斜线、下划线和缩进不参与包装清理。
- 结果只清理多余首尾空白和过量连续空行，不压缩正常段落。

### Professional text splitting

专业正文不解析反斜线，只在超过 `max_reply_chars` 时拆分：

1. 优先按空行形成的自然段落装箱。
2. 单个段落过长时按换行和中文、英文句末标点拆分。
3. 单句仍过长时按字符上限硬切，作为无法再安全细分的最后降级。
4. 不改变片段内部代码字符和 URL；所有片段按原顺序返回。

### `mewcode.wechat.info.registry`

**Responsibility:** 净化网页正文中的 URL 并形成独立来源消息。

**Changes:**

- 来源账本返回 `FinalizedInfoReply(answer, source_message)`，不再把两者拼成一个字符串。
- `source_message` 使用纯文本：首行为“来源：”，后续为编号、标题和净化 URL；OpenStreetMap 署名单独成行。
- 正文中允许且已记录的 URL 改写为“链接见来源”，未核实 URL 继续省略。
- 来源标题经过相同的微信纯文本包装清理，避免网页标题携带 Markdown 标记。

### `mewcode.session.runtime`

**Responsibility:** 为微信的投递后归档提供最小通用扩展。

**Changes:**

- 允许 `archive_message_transform` 返回 `None`；`None` 时跳过该消息的 archive append。
- 现有未配置转换器或始终返回 `Message` 的调用路径完全不变。

### Documentation

**Changes:**

- README 更新微信消息聚合、自然分段、工具状态、取消方式和纯文本规则。
- README 的 `system_prompt` 示例更新为朋友型角色，并说明角色配置与稳定回复协议分属不同层。
- 同步更新当前用户配置中的 `wechat.system_prompt`，不改动 Provider、密钥、白名单或信息工具字段。
- TODO 在实现验收完成后勾选 P0 第 1、2 项已覆盖的条目；未实现的好友级 Emoji 和其他后续能力继续保留。

## Module Interactions

### Normal aggregation and queueing

```text
好友 A 发消息 a1
  -> 建立 PendingBatch(A, revision=1)
  -> 启动 7 秒任务

好友 A 在 7 秒内发 a2
  -> 取消旧计时器
  -> events=[a1,a2], revision=2
  -> 重启 7 秒任务

静默满 7 秒
  -> queued=True
  -> FIFO.put(QueuedBatch(A,[a1,a2],revision=2))

消费者领取
  -> 当前 A 的 revision 仍为 2，领取成功
  -> 输入模型的文本为 "a1\na2"
```

### Stale queued batch

```text
A revision=2 已进入 FIFO但未处理
  -> A 又发 a3
  -> revision=3，queued=False，重启 7 秒
  -> 消费者遇到 revision=2 时直接跳过
  -> revision=3 静默满 7 秒后重新进入 FIFO
```

### Tool stage and research reply

```text
Agent 发出 web_search 工具开始事件
  -> 阶段 web 尚未通知
  -> Bot 发送“我查一下相关资料。”并记录已投递
  -> 执行 web_search

Agent 随后发出 web_fetch
  -> 同属 web 阶段，不再通知

Agent 最终文本
  -> URL 净化
  -> Markdown 包装清理
  -> 专业正文按长度整形
  -> 发送正文
  -> 最后发送独立来源
  -> 归档实际已发送的状态、正文和来源
```

### Natural interruption

```text
A 的工具或第 2 个闲聊气泡正在进行
  -> A 发来新消息
  -> ActiveTurn(A).cancel.set()
  -> 当前工具或可取消间隔停止
  -> 不再发送剩余旧气泡
  -> 新消息进入新的 PendingBatch(A)
  -> 当前轮结束时只归档已经发送成功的可见消息
  -> 新消息静默 7 秒后重新排队
```

## File Organization

```text
Mewcode/
├─ README.md                              # 更新微信交互说明
├─ TODO.md                                # 验收后更新 P0 进度
├─ doc/16/
│  ├─ spec.md                             # 已批准行为规格
│  ├─ plan.md                             # 本技术设计
│  ├─ task.md                             # 后续任务拆分
│  └─ checklist.md                        # 后续验收清单
├─ src/mewcode/session/runtime.py         # 支持跳过暂缓归档消息
├─ src/mewcode/wechat/
│  ├─ models.py                           # 批次、活动轮次和结构化回复
│  ├─ bot.py                              # 7 秒聚合、FIFO、打断和发送
│  ├─ config.py                           # 默认朋友型角色与用户角色入口
│  ├─ runtime.py                          # 回复策略、工具阶段和纯文本整形
│  └─ info/registry.py                    # 正文与来源分离
└─ tests/
   ├─ test_session_runtime.py             # nullable archive transform
   ├─ test_wechat_bot.py                  # 聚合、失效、打断、顺序和间隔
   ├─ test_wechat_config.py               # 默认角色与自定义覆盖
   ├─ test_wechat_runtime.py              # Prompt、协议、归档和工具阶段
   └─ test_wechat_info_registry.py        # 独立来源与净化
```

## Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| 意图分类 | 不发起独立分类请求 | 是否输出气泡标记由同一个回答模型决定，网页工具则提供确定信号，避免额外成本和延迟 |
| 闲聊协议 | `<|bubble|>` | 与普通反斜线、路径、正则和代码不冲突，解析后不会显示给好友 |
| 人物角色 | 复用 `wechat.system_prompt` | 角色需要可编辑，但气泡协议和安全边界不能由角色配置承担；无需增加新字段 |
| 多句拆分 | 强指令 + 正反 few-shot | 真实失败发生在模型未输出分隔符；发送层无法在不知道回答类型时安全按句号拆分 |
| 消息聚合 | 每好友可取消 7 秒计时器 | 直接表达固定静默窗口，不需要轮询线程或第三方调度器 |
| 队列失效 | 修订号 + 惰性跳过 | `asyncio.Queue` 不支持安全删除任意项，修订号比重建队列更简单可靠 |
| 跨好友调度 | 保留单全局 FIFO | 微信只有一个前台窗口，串行最能保证目标和消息原子顺序 |
| 自然取消 | 同好友任意新消息设置现有 cancel event | 复用 Agent、工具已有取消能力，不保留额外 `/cancel` 控制面 |
| 工具提示 | 观察现有 Agent 工具开始事件并按阶段去重 | 状态只在真实工具调用时出现，不依赖模型猜测或重复文案 |
| 工具阶段 | 当前仅映射 time 与 web | 只实现现有三个微信工具；未来新增工具时再增加一条映射 |
| 专业分段 | 段落、句子、硬切三级降级 | 保持可读性，同时确保任何长度都能满足微信单条上限 |
| Markdown 清理 | 提示约束优先，标准库保守清理兜底 | 不新增解析依赖，也避免全局删除代码中的合法符号 |
| 发送间隔 | 每批一次随机速度 + 0.4～2 秒夹取 | 保留长度感知和轻微自然变化，同时保证同批次单调且可测试 |
| 会话真实性 | 模型最终文本暂缓归档，发送后追加实际可见文本 | 被取消或发送失败的气泡不能污染好友后续上下文 |
| 新配置 | 不新增配置键 | 现有 `system_prompt` 承载角色；7 秒、7 气泡和 0.4～2 秒继续作为固定产品规则 |

## Spec Coverage

| Spec | Design coverage |
|---|---|
| F1-F4 | `PendingBatch`、可取消静默任务、`QueuedBatch.revision` 和全局 FIFO |
| F5-F10 | `WECHAT_REPLY_POLICY`、`<|bubble|>`、`WechatReply`、气泡归并和专业分段 |
| F11-F13 | `ActiveTurn.cancel`、新消息自然打断和删除 `/cancel` 分支 |
| F14-F16 | Agent 工具开始事件、阶段映射、每轮去重集合和状态回调 |
| F17 | `FinalizedInfoReply`、正文与来源独立发送 |
| F18-F20 | Prompt 约束、保守 Markdown 包装清理和专业段落格式 |
| F21 | Bot/Runtime 现有受控错误路径扩展到结构化回复 |
| F22 | nullable archive transform、`ActiveTurn.delivered` 和 `record_delivery` |
| F23-F25 | 默认朋友型 `system_prompt`、稳定身份与安全规则 |
| F26 | 单气泡例外规则和简短回应 few-shot |
| N1-N2 | 每好友状态表、现有 UIA 锁、目标复核和单消费者 |
| N3-N4 | 复用当前 Agent、标准库 asyncio 可取消任务与等待 |
| N5-N6 | 事件唯一约束、修订校验和既有安全回归测试 |

## Validation Strategy

- 使用可调测试静默时间和 Fake Driver 验证 7 秒逻辑，不让自动化测试真实等待 7 秒。
- 使用纯函数单元测试覆盖气泡协议、7 条归并、Markdown 包装清理、代码字符保留和专业长文拆分。
- 使用 Fake Provider 产生工具调用事件，验证 time/web 阶段通知、同阶段去重、取消传播和来源顺序。
- 配置测试断言默认角色包含朋友式语气、真实身份和不虚构关系约束，同时验证用户自定义 `system_prompt` 仍可覆盖默认角色。
- Fake Provider 捕获稳定 system，断言包含多句强制拆分、四气泡 few-shot、短回应单气泡例外和专业回答反例。
- 恢复好友 Session，验证部分发送后只有实际可见消息进入下一轮模型上下文。
- 保留并运行现有微信配置、UIA、Store、公共信息工具和全量项目回归。
- 最终在专用测试好友上人工验证：指定的“今天忙吗 / 我好无聊”样例产生四个气泡，简短笑声保持一个气泡，身份与关系边界正确；并回归专业长答、网页查询三段式结果以及发送中自然打断。
