# 微信私聊图片识别与多模态会话 Plan

状态：已批准

## Architecture Overview

复用现有“UIA 观察线程 → 7 秒静默批次 → 全局 FIFO → 好友持久 Session → Agent → 微信顺序发送”主链路，只在四个边界补入图片能力：

```text
微信私聊可见消息
  -> UIA 识别文字 / 图片气泡（只保存身份和边界）
  -> 7 秒好友批次（文字 + 最多 4 个图片事件）
  -> FIFO 队首时打开大图查看器并临时截图
  -> 格式 / 尺寸 / 总量校验并编码 Base64
  -> 原子执行好友图片档案配额清理
  -> Session 追加一条多模态 user 消息
  -> 只保留最近图片批次及最多 3 个后续文字回合为活动图片上下文
  -> OpenAI Chat Completions 内容块
  -> deepseek-v4-flash-vision-exp 流式回答 / Tool Calls
  -> 删除本批临时目录
```

图片气泡扫描阶段不打开查看器、不截图、不编码。真实图片物化推迟到批次位于全局 FIFO 队首时执行，避免后台扫描长时间占用微信窗口，也避免为已被新消息取消或被批次上限拒绝的图片付出 UI 和内存成本。

核心消息仍以文字为主，只增加 `images` 字段；不引入通用附件接口、媒体工厂、远端文件服务或新的持久化系统。

## Core Data Structures

### `ImageContent`

位置：`mewcode.llm`

```python
@dataclass(frozen=True)
class ImageContent:
    media_type: Literal[
        "image/jpeg", "image/png", "image/gif", "image/webp"
    ]
    data: str
    detail: Literal["original"] = "original"
    sha256: str = ""
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    created_at: int = 0
    degraded: bool = False
    cleared: bool = False
```

- `data` 是不含 `data:` 前缀的 Base64；只有 OpenAI 序列化边界拼成 Data URL。
- `degraded=True` 表示来自气泡截图而非已验证的大图查看器。
- 配额清理后保留全部元数据，令 `data=""`、`cleared=True`。
- 不保存临时路径、文件名或好友提供的 MIME 声明。

### Extended `Message`

```python
@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    images: list[ImageContent] = field(default_factory=list)
```

`images` 放在现有字段之后，保留当前位置参数调用兼容性。只有 `role="user"` 可以携带非空、未清理图片。所有复制或替换 `Message` 的现有代码必须显式保留该字段，避免上下文处理时静默丢图。

### Extended `VisibleMessage`

```python
@dataclass(frozen=True)
class VisibleMessage:
    key: str
    conversation_key: str
    text: str
    incoming: bool
    kind: str = "text"       # text | image
    sender_name: str = ""
    bounds: tuple[int, int, int, int] | None = None
```

沿用现有结构；`kind="image"` 时 `text` 只使用固定占位 `[图片]`，图片身份来自 runtime id 和边界，不把 UIA 名称当作图片内容。

### Extended `WechatDesktopEvent`

新增：

```python
message_key: str = ""
message_kind: str = "text"  # text | image
bounds: tuple[int, int, int, int] | None = None
```

事件只携带重新定位图片气泡所需的安全快照，不携带控件对象、图片字节或临时路径。

### `ImageCapture`

位置：`mewcode.wechat.models`

```python
@dataclass(frozen=True)
class ImageCapture:
    path: Path
    degraded: bool
```

只存在于一个 FIFO 批次的临时目录生命周期内，不进入 JSONL、SQLite、日志或模型消息。

## Module Design

### `mewcode.llm`

**Responsibility:** 表达最小的 Provider 无关图片内容，并保持现有纯文字消息兼容。

**Changes:**

- 新增 `ImageContent`。
- `Message` 末尾新增 `images`。
- 新增小型纯函数 `message_request_chars(message)`：文字按字符数计算，每张活动图片按 DeepSeek 官方最多 384 image tokens 折算为 1536 个等价字符；不把 Base64 长度误当文本 Token。

不增加 URL 图片、Files API、音频、视频或通用附件联合类型。

### `mewcode.llm.openai_provider`

**Responsibility:** 把活动图片转换为 DeepSeek 接受的 OpenAI Chat Completions 内容块。

**Serialization:**

```python
def to_openai_messages(req: Request) -> list[dict[str, Any]]
```

- 无图片消息保持当前字符串 `content`，保证现有请求快照不变。
- 带图片的用户消息输出：一个 `text` 块加按顺序排列的 `image_url` 块。
- 每个 URL 为 `data:<media_type>;base64,<data>`，`detail="original"`。
- 清理后的图片不发送；若一条消息只有已清理图片且没有可用文字，则只保留安全占位文本。
- 非用户角色携带图片、空 Base64、未知 MIME 或非 `original` detail 时在请求前明确失败，不静默丢弃。
- 保持现有 `stream=True`、`stream_options.include_usage=True` 和 `tool_choice="auto"`。

`AnthropicProvider` 本版不增加图片序列化；若意外收到带图片消息则明确报错，防止静默忽略。TUI 纯文字和现有 Claude 会话不受影响。

### `mewcode.conversation`

**Responsibility:** 让现有用户消息追加入口接受可选图片。

```python
def add_user(
    self,
    text: str,
    images: Sequence[ImageContent] = (),
) -> None
```

其余调用者继续只传字符串。图片列表在创建 `Message` 时复制，避免调用者后续修改。

### `mewcode.session.archive`

**Responsibility:** JSONL 图片往返和写入结果可观测。

**Changes:**

- `message_to_data()` 在有图片时增加 `images` 数组；纯文字旧档案格式不变。
- `message_from_data()` 严格解析图片元数据并兼容没有 `images` 的旧事件。
- Base64 不出现在异常文本；解析失败只使对应消息无效或图片变为不可用，不回显原数据。
- `ArchiveWriter.append()` / `append_message()` 返回布尔写入结果并记录 `last_append_ok`；现有非关键调用可继续忽略返回值，微信图片用户消息必须检查。

归档示例：

```json
{
  "type": "message",
  "ts": 1787620000,
  "role": "user",
  "content": "比较这两张图",
  "images": [
    {
      "media_type": "image/png",
      "data": "<BASE64>",
      "detail": "original",
      "sha256": "...",
      "width": 1200,
      "height": 800,
      "size_bytes": 123456,
      "created_at": 1787620000,
      "degraded": false,
      "cleared": false
    }
  ]
}
```

### `mewcode.session.repository`

**Responsibility:** 在打开好友 Session Writer 之前执行图片配额预留和原子清理。

```python
def reserve_image_bytes(
    self,
    session_id: str,
    incoming_bytes: int,
    limit_bytes: int = 256 * 1024 * 1024,
) -> bool
```

处理顺序：

1. 读取现有 JSONL 并计算所有 `cleared=False` 图片的 `size_bytes`。
2. 若总量加新批次不超限，不改文件并返回 `True`。
3. 超限时按档案顺序清理最早图片的 `data`，设置 `cleared=True`，保留原事件和元数据。
4. 当前新批次尚未写入，因此现有最近批次在新批次到来后已不再活动，可以按最老优先参与清理。
5. 使用同目录临时文件、flush、fsync 和 `os.replace` 原子替换；事件数与顺序不变，不破坏消息索引和压缩检查点。
6. 任一步失败或预留后仍超限，保持原档案不变并返回 `False`。

该方法只在新图片批次到达时调用；普通文字恢复不重复改写大档案。

### `mewcode.context`

**Responsibility:** 图片不泄露到摘要，图片 Token 估算不使用 Base64 字符长度。

**Changes:**

- 请求预算和 retained 边界复用 `message_request_chars()`。
- 摘要输入仍只使用 `Message.content`；带图消息以已有文字或固定 `[好友发送了图片]` 占位进入摘要，绝不拼接 `ImageContent.data`。
- `Message` 替换、工具产物归档和恢复时保留 `images`。
- 微信运行时在交给通用 ContextController 前已移除非活动图片，因此通用压缩器最多看到最近一个活动批次。

### `mewcode.wechat.uia_client`

**Responsibility:** 识别私聊图片气泡并安全物化一张临时 PNG。

```python
def visible_messages(self, row: ConversationRow) -> list[VisibleMessage]

def capture_private_image(
    self,
    row: ConversationRow,
    message_key: str,
    bounds: tuple[int, int, int, int] | None,
    target_dir: Path,
) -> ImageCapture | None
```

`visible_messages()`：

- 接受现有 `mmui::ChatTextItemView` 和普通图片气泡 `mmui::ChatImageItemView`。
- 继续排除通用时间行、系统通知、引用气泡、文件、语音、视频和分享卡片。
- 图片即使 `Name` 为空也可依据 runtime id 与边界形成稳定快照。
- 保留 `visible_text_messages()` 作为只返回文字的兼容包装，避免外部调用者突然改变语义。

`capture_private_image()`：

1. 唯一确认好友私聊和当前目标。
2. 优先按 runtime id，缺失时按允许小误差的边界重新定位当前可见图片控件。
3. 点击已验证的图片区域，记录点击前顶层窗口集合，只接受同一微信进程新出现且满足图片查看器特征的窗口。
4. 截取查看器窗口到批次临时目录，关闭查看器并恢复微信主窗口与原好友会话。
5. 查看器打开、验证、截图、关闭或恢复任一步失败时，尝试截取原图片气泡边界并返回 `degraded=True`。
6. 两条路径都失败或目标会话改变时返回 `None`。

只迁移 `fake-wx-account` 已验证动作所需的最小 HWND、截图和恢复逻辑，不迁移文件、引用、分享卡片或通用附件代码。

### `mewcode.wechat.uia_driver`

**Responsibility:** 从可见文字/图片快照产生稳定事件，并在 FIFO 队首协调图片物化。

```python
def materialize_private_image(
    self,
    event: WechatDesktopEvent,
    target_dir: Path,
) -> ImageCapture | None
```

- 私聊扫描改用 `visible_messages()`；仍只取本次未读候选并建立启动基线。
- 图片事件保留 `message_key`、`message_kind` 和 `bounds`。
- 群聊继续只消费 `kind="text"`，图片不进入群上下文、不触发、不 OCR。
- 物化与现有发送操作共享同一个 Driver 锁。

### `mewcode.wechat.image`

**Responsibility:** 不依赖真实微信的图片信任边界校验和 Base64 编码。

```python
MAX_IMAGES_PER_BATCH = 4
MAX_BATCH_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_IMAGE_BYTES = 256 * 1024 * 1024
MAX_IMAGE_SIDE = 8192
FOLLOWUP_IMAGE_TURNS = 3

class WechatImageError(ValueError):
    code: str

def encode_capture(capture: ImageCapture, created_at: int) -> ImageContent

def validate_batch(images: Sequence[ImageContent]) -> None
```

- Pillow 按文件签名打开、`verify()` 后重新读取尺寸；允许 JPEG、PNG、GIF、WebP。
- 不改像素、不转码；读取原始字节计算 SHA-256、Base64 和 `size_bytes`。
- 批次校验一次性检查数量、单边尺寸、空数据和 32 MiB 总量。
- 任何成员失败都抛出无图片内容的稳定错误码，Bot 整批拒绝。

### `mewcode.wechat.models`

**Responsibility:** 扩展事件与批次快照，不保存 UIA 控件。

- 增加 `ImageCapture`。
- `WechatDesktopEvent` 增加消息类型、键和边界。
- `QueuedBatch` 增加只读属性：

```python
@property
def image_events(self) -> tuple[WechatDesktopEvent, ...]
```

`text` 继续只拼接文字事件，图片占位不进入好友原始问题。

### `mewcode.wechat.bot`

**Responsibility:** 在 FIFO 队首执行批次级图片物化、整批拒绝和临时目录清理。

消费流程：

1. 队列认领后先统计 `image_events`；超过四张直接发送一次上限提示。
2. 使用 `TemporaryDirectory` 为批次建立唯一临时目录。
3. 按事件顺序逐张调用 Driver 物化，再在线程中校验、编码。
4. 任一失败或总量超限时不调用 Runtime，只发送一次安全提示。
5. 图片成功时调用 `reply(..., images=...)`；纯图片批次传入固定默认识别提示。
6. `finally` 退出临时目录，覆盖成功、失败、取消、超时和发送异常。
7. 任一图片 `degraded=True` 时把固定降级状态传给 Runtime，要求最终可见回答说明清晰度边界。

启动日志在存在白名单好友时打印一次数据披露，不包含好友名、图片正文或密钥。

### `mewcode.wechat.runtime`

**Responsibility:** 图片档案预留、活动图片筛选、Session 追加与 Agent 调用。

```python
async def reply(
    self,
    conversation_name: str,
    text: str,
    cancel: asyncio.Event,
    on_tool_stage: Callable[[str], Awaitable[None]] | None = None,
    *,
    images: Sequence[ImageContent] = (),
) -> WechatReply
```

图片路径：

1. 若 `images` 非空，在打开 Session Writer 前调用 `reserve_image_bytes()` 预留 256 MiB 配额。
2. 恢复好友 Session，追加一条文字加图片的 user 消息。
3. 检查图片消息已经成功写入 JSONL；失败则在模型调用前终止。
4. 对当前 Conversation 运行 `_wechat_active_image_messages()`：只保留最后一条含可用图片的 user 消息；统计其后的纯文字 user 消息，数量不超过三时保留图片，否则用相同元数据的 cleared/空图片副本替换活动上下文中的数据。
5. 新图片消息天然成为最后图片批次，旧图片立即退出活动上下文。
6. Agent 工具循环继续使用同一 Conversation；图片只位于原始 user 消息，不复制到 tool 或 assistant 消息。

```python
def _wechat_active_image_messages(messages: list[Message]) -> list[Message]
```

该函数是纯函数，通过已有消息顺序推导“剩余回合”，不新增 SQLite 状态或单独计数事件。重启恢复得到相同行为。

固定微信回复策略补充：图片无文字时的默认描述、图片文本不可信、降级截图披露、不确定性和禁止根据图片扩权。

### Configuration and documentation

**Files:** `.mewcode/config.yaml`、`.mewcode/config.yaml.example`、`README.md`

- 只把现有本地 `openai` Provider 的 `model` 改为 `deepseek-v4-flash-vision-exp`，保留现有 Key、name、protocol 和 base URL。
- 示例增加 DeepSeek 视觉 Provider 写法，但不写真实 Key。
- README 说明私聊范围、7 秒批次、四图/32 MiB/8192 边界、三次追问、256 MiB 清理、明文 Base64、DeepSeek 上传和群聊/引用不支持。

### Live probe script

位置：`scripts/probe_deepseek_vision.py`

- 从现有项目配置读取 `openai` Provider，不接受命令行 Key，不打印 Key 或 Data URL。
- 在内存生成无敏感 16×16 PNG。
- 请求一：验证图片流式文本和 usage。
- 请求二：使用 `tool_choice="auto"` 验证流式 Tool Calls 增量可组装为有效函数参数。
- 失败返回非零状态；输出只含模型名、布尔结果、增量数量和字符数量。

## Module Interactions

### Image-only private turn

```text
ChatImageItemView
  -> VisibleMessage(kind="image")
  -> WechatDesktopEvent(message_kind="image")
  -> 7 秒静默
  -> QueuedBatch(image_events=(...))
  -> TemporaryDirectory
  -> viewer capture | bubble fallback
  -> ImageContent(Base64)
  -> archive quota reserve
  -> Message(role="user", content=默认提示, images=[...])
  -> OpenAI content blocks
  -> streamed WechatReply
  -> temp cleanup
```

### Image followed by text

```text
图片 A -> 图片 B -> “比较一下”
            同一好友 7 秒窗口
  -> one QueuedBatch
  -> one multimodal user Message
  -> one model call
  -> one ordered reply batch
```

### Follow-up and replacement

```text
image batch A
  -> text follow-up #1: resend A
  -> text follow-up #2: resend A
  -> text follow-up #3: resend A
  -> text follow-up #4: strip A from request

image batch B at any point
  -> B becomes sole active image batch
  -> A remains archived but is stripped from requests
```

### Archive quota

```text
new batch raw bytes
  -> existing usable image bytes + new bytes
  -> <= 256 MiB: append normally
  -> > 256 MiB: atomically clear oldest inactive Base64
  -> still too large / rewrite failure: reject new batch
```

## File Organization

```text
src/mewcode/
+-- llm/__init__.py                   # ImageContent、Message.images、请求估算
+-- llm/openai_provider.py            # OpenAI 多模态内容块
+-- llm/anthropic_provider.py         # 图片误路由时明确拒绝
+-- conversation.py                   # add_user(images=...)
+-- session/archive.py                # JSONL 图片往返与写入状态
+-- session/repository.py             # 256 MiB 原子配额清理
+-- context/controller.py             # 图片 token 等价估算与字段保留
+-- context/compact.py                # 图片占位摘要、不接触 Base64
`-- wechat/
    +-- models.py                     # 图片事件与临时捕获
    +-- image.py                      # 格式、尺寸、哈希、Base64、批次限制
    +-- uia_client.py                 # 图片气泡、大图查看器、气泡降级
    +-- uia_driver.py                 # 图片事件与 FIFO 队首物化
    +-- bot.py                        # 批次校验、拒绝、临时目录生命周期
    +-- runtime.py                    # 多模态 Session 与最近批次筛选
    `-- prompts/reply_policy.md       # 图片回复和不可信内容边界

tests/
+-- test_llm_helpers.py               # OpenAI 内容块与 Anthropic 拒绝
+-- test_session_archive.py           # 图片 JSONL 往返
+-- test_session_repository.py        # 原子配额清理
+-- test_context_budget.py            # 图片 token 等价估算
+-- test_wechat_image.py              # 纯图片校验和 Base64
+-- test_wechat_uia_driver.py         # 图片发现、物化和降级
+-- test_wechat_bot.py                # 7 秒图文批次、整批拒绝、清理
`-- test_wechat_runtime.py            # 活动三回合、替换、恢复与请求

scripts/probe_deepseek_vision.py       # 无敏感真实 API 验收
.mewcode/config.yaml                   # 本地 Provider 模型替换
.mewcode/config.yaml.example           # 无密钥示例
README.md                              # 能力、限制和数据披露
doc/21/                                # 本版四份规格文档
```

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Core media model | `Message.images` + `ImageContent` | 最小扩展，现有纯文字、工具调用和位置参数保持兼容 |
| Provider payload | OpenAI Chat Completions Base64 `image_url` | 与官方视觉接口和现有 Provider 完全一致 |
| Image detail | 固定 `original` | 截图小字与 OCR 是核心场景 |
| Acquisition timing | FIFO 队首延迟物化 | 不为取消/拒绝批次浪费 UI 操作，保持单窗口串行 |
| Image source | 大图查看器优先，气泡截图降级 | 质量优先，同时保留安全可见降级 |
| Temporary storage | `TemporaryDirectory` | 标准库自动覆盖所有退出路径，无长期临时缓存 |
| Active image state | 从消息顺序推导最近批次和三次文字回合 | 无新表、无新状态文件，重启行为自然一致 |
| Archive format | 图片 Base64 直接位于 message JSONL | 满足用户明确的重启恢复和明文归档要求 |
| Archive cap | 新批次写入前原子清理旧 Base64 | Writer 未打开，Windows 可安全替换；失败不破坏旧档案 |
| Context estimate | 每图固定 384 token 上限折算 | 不把 Base64 长度错误计入语言上下文，随后由真实 usage 校准 |
| Compaction | 只摘要文字/占位，不摘要图片数据 | 防止泄露、复制和无意义的 Base64 摘要 |
| Limits | 代码常量，不新增配置项 | 本版边界已固定，避免未要求的配置面 |
| Tool choice | 保持 `auto` | 真实探测通过；思考模式强制函数调用会返回 400 |
| Extra dependencies | 无 | stdlib + 现有 Pillow、pywin32 足够 |
| Future references | 不预留引用抽象 | 下一小版本按真实引用 UIA 结构单独设计，避免本版猜接口 |

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| 大 JSONL 恢复产生瞬时内存和 I/O 压力 | 固定 256 MiB 原始图片配额；恢复与编码在线程执行；活动请求只保留最近批次 |
| 微信查看器结构变化 | 严格验证新窗口所属进程和目标；失败降级气泡；恢复失败禁止发送 |
| Base64 写入中断损坏档案 | 现有单行追加 + fsync；配额清理使用同目录原子替换；损坏尾行沿用安全忽略 |
| 图片消息被上下文压缩误处理 | 图片数据独立字段；摘要和字符估算不读取 Base64 |
| 图片提示注入 | 固定系统规则将视觉内容标记为不可信；微信工具白名单不扩大 |
| 实验模型能力变化 | 可重复真实探测脚本；流式文本或 auto Tool Calls 缺失即验收失败 |
| 取消发生在阻塞 UI 操作期间 | UI 操作完成后立即检查取消；临时目录 finally 清理；不发送旧回答 |
