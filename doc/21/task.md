# 微信私聊图片识别与多模态会话 Tasks

状态：已批准

## File List

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/mewcode/llm/__init__.py` | 定义图片内容并扩展消息模型与请求预算估算 |
| Modify | `src/mewcode/llm/openai_provider.py` | 序列化 DeepSeek Base64 多模态内容块 |
| Modify | `src/mewcode/llm/anthropic_provider.py` | 明确拒绝误路由的图片消息 |
| Modify | `src/mewcode/conversation.py` | 接受并追加带图片的用户消息 |
| Modify | `src/mewcode/session/archive.py` | JSONL 图片往返与可检查写入结果 |
| Modify | `src/mewcode/session/repository.py` | 执行每好友 256 MiB 图片档案预留和原子清理 |
| Modify | `src/mewcode/context/budget.py` | 按图片 token 上限计算请求预算 |
| Modify | `src/mewcode/context/controller.py` | 在上下文变换中保留图片字段 |
| Modify | `src/mewcode/context/compact.py` | 摘要只读取文字或安全图片占位 |
| Modify | `src/mewcode/wechat/models.py` | 扩展可见消息、事件、批次与临时捕获模型 |
| Create | `src/mewcode/wechat/image.py` | 校验图片信任边界并编码 Base64 |
| Modify | `src/mewcode/wechat/uia_client.py` | 发现私聊图片并执行查看器优先的截图 |
| Modify | `src/mewcode/wechat/uia_driver.py` | 生成图片事件并在队首物化图片 |
| Modify | `src/mewcode/wechat/runtime.py` | 持久化多模态消息并筛选活动图片批次 |
| Modify | `src/mewcode/wechat/bot.py` | 合并七秒图文批次、整批拒绝与临时文件清理 |
| Modify | `src/mewcode/wechat/prompts/reply_policy.md` | 加入图片回答、不确定性和不可信内容规则 |
| Modify | `.mewcode/config.yaml` | 将本地 `openai` Provider 切换到视觉模型且保留密钥 |
| Modify | `.mewcode/config.yaml.example` | 更新无密钥视觉模型示例 |
| Modify | `README.md` | 说明能力边界、DeepSeek 上传和明文 Base64 归档 |
| Create | `scripts/probe_deepseek_vision.py` | 可重复验证流式视觉文本与自动 Tool Calls |
| Modify | `tests/test_llm_helpers.py` | 覆盖核心消息和 Provider 多模态序列化 |
| Modify | `tests/test_conversation.py` | 覆盖图片用户消息追加 |
| Modify | `tests/test_session_archive.py` | 覆盖图片 JSONL 往返、清理占位和写入状态 |
| Modify | `tests/test_session_repository.py` | 覆盖图片配额和原子清理 |
| Modify | `tests/test_context_budget.py` | 覆盖图片预算和摘要隔离 |
| Create | `tests/test_wechat_image.py` | 覆盖格式、尺寸、批次限制、哈希和 Base64 |
| Modify | `tests/test_wechat_uia_driver.py` | 覆盖图片发现、私聊边界、物化和降级 |
| Modify | `tests/test_wechat_runtime.py` | 覆盖档案预留、三轮活动上下文和重启恢复 |
| Modify | `tests/test_wechat_bot.py` | 覆盖七秒图文合并、拒绝、取消和临时目录清理 |

## T1: 为核心图片消息模型建立测试

**Files:** `tests/test_llm_helpers.py`, `tests/test_conversation.py`
**Dependencies:** None
**Steps:**
1. 增加 `ImageContent` 默认值、不可变性和 `Message.images` 兼容测试。
2. 验证纯文字消息保持原有结构，图片请求预算不使用 Base64 字符长度。
3. 验证 `Conversation.add_user()` 能同时保存文字和有序图片副本。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_llm_helpers.py tests/test_conversation.py -q`；新增测试应因功能尚未实现而失败，现有纯文字测试不得出现无关失败。

## T2: 实现核心图片消息模型

**Files:** `src/mewcode/llm/__init__.py`, `src/mewcode/conversation.py`
**Dependencies:** T1
**Steps:**
1. 新增最小 `ImageContent` 数据类，并在 `Message` 尾部增加 `images` 字段。
2. 实现每张活动图片按 384 token 折算的统一请求字符估算函数。
3. 扩展 `Conversation.add_user()`，不改变现有纯文字调用方式。

**Validation:** 重跑 T1 命令并确认全部通过。

## T3: 为 Provider 多模态边界建立测试

**File:** `tests/test_llm_helpers.py`
**Dependencies:** T2
**Steps:**
1. 覆盖纯文字 OpenAI payload 保持字符串 `content`。
2. 覆盖文字块加有序 Base64 `image_url` 块、固定 `detail=original`。
3. 覆盖已清理图片占位，以及无效角色、MIME、空数据和 detail 的显式失败。
4. 覆盖 Anthropic 收到图片时显式失败，并断言 OpenAI 流式、usage 和 `tool_choice=auto` 参数不变。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_llm_helpers.py -q`，确认新增边界测试按预期失败且既有测试保持稳定。

## T4: 实现 Provider 多模态序列化

**Files:** `src/mewcode/llm/openai_provider.py`, `src/mewcode/llm/anthropic_provider.py`
**Dependencies:** T3
**Steps:**
1. 仅为带图片的用户消息生成 DeepSeek 接受的内容块和 Data URL。
2. 在序列化前拒绝非法或误路由图片，不在错误和日志中输出 Base64。
3. 保持流式文本、usage 汇总、自动 Tool Calls 和纯文字 payload 行为。

**Validation:** 重跑 T3 命令并确认全部通过。

## T5: 为 JSONL 图片档案建立测试

**File:** `tests/test_session_archive.py`
**Dependencies:** T2
**Steps:**
1. 覆盖图片元数据与 Base64 的写入、读取和顺序往返。
2. 覆盖旧版无图片事件兼容、已清理占位和畸形图片字段的安全处理。
3. 覆盖 `ArchiveWriter` 写入结果可检查，且异常内容不包含 Base64。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_session_archive.py -q`，确认新增测试先失败且旧档案测试继续通过。

## T6: 实现 JSONL 图片档案往返

**File:** `src/mewcode/session/archive.py`
**Dependencies:** T5
**Steps:**
1. 只在有图片时写入 `images` 数组，保持纯文字 JSONL 格式兼容。
2. 严格恢复图片字段和清理占位，不保存临时路径。
3. 让追加接口返回写入结果并暴露最后一次写入状态。

**Validation:** 重跑 T5 命令并确认全部通过。

## T7: 为图片档案配额建立测试

**File:** `tests/test_session_repository.py`
**Dependencies:** T6
**Steps:**
1. 覆盖未超 256 MiB 时不改写档案。
2. 覆盖超限后按顺序清理最早非活动 Base64并保留时间、格式、尺寸、大小、哈希与占位。
3. 覆盖新批次自身不可容纳、临时写入失败和替换失败时原档案保持不变。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_session_repository.py -q`，确认新增配额测试先失败且原有恢复测试继续通过。

## T8: 实现图片档案原子配额预留

**File:** `src/mewcode/session/repository.py`
**Dependencies:** T7
**Steps:**
1. 按 `size_bytes` 计算每好友尚未清理的原始图片总量。
2. 在 Writer 打开前用同目录临时文件、flush、fsync 和 `os.replace` 清理最旧 Base64。
3. 失败时清理临时文件、保留原档案并返回失败结果。

**Validation:** 重跑 T7 命令并确认全部通过。

## T9: 为图片上下文预算与摘要隔离建立测试

**File:** `tests/test_context_budget.py`
**Dependencies:** T2, T6
**Steps:**
1. 覆盖每张活动图片的固定等价预算和已清理图片不计图片预算。
2. 覆盖上下文裁剪、消息复制与压缩不会丢失活动图片字段。
3. 覆盖摘要只出现原文字或固定占位，绝不包含 Base64 片段。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_context_budget.py tests/test_context_artifact.py -q`，确认新增测试先失败且原有上下文测试继续通过。

## T10: 实现图片上下文预算与摘要隔离

**Files:** `src/mewcode/context/budget.py`, `src/mewcode/context/controller.py`, `src/mewcode/context/compact.py`
**Dependencies:** T9
**Steps:**
1. 将统一消息估算接入请求预算和保留边界。
2. 在上下文替换与恢复中显式保留图片字段。
3. 为图片消息生成安全摘要文字，不读取或复制 Base64。

**Validation:** 重跑 T9 命令并确认全部通过。

## T11: 为微信图片校验器建立测试

**File:** `tests/test_wechat_image.py`
**Dependencies:** T2
**Steps:**
1. 用内存/临时样本覆盖 JPEG、PNG、GIF、WebP 的签名识别、尺寸、哈希和 Base64。
2. 覆盖伪扩展名、损坏图片、空图片、未知格式和单边超过 8192 的拒绝。
3. 覆盖最多四张、原始总量 32 MiB 和整批失败的稳定错误码。
4. 覆盖 `degraded` 元数据透传且不进行压缩或转码。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_image.py -q`，确认测试因模块尚不存在而失败。

## T12: 实现微信图片校验与 Base64 编码

**File:** `src/mewcode/wechat/image.py`
**Dependencies:** T11
**Steps:**
1. 使用 Pillow 依实际文件签名验证四种格式并重新读取尺寸。
2. 读取未转码原始字节，计算 SHA-256、大小和 Base64。
3. 实现数量、单边和批次总量常量与整批校验。

**Validation:** 重跑 T11 命令并确认全部通过。

## T13: 为微信图片事件模型建立测试

**Files:** `tests/test_wechat_uia_driver.py`, `tests/test_wechat_bot.py`
**Dependencies:** T2
**Steps:**
1. 覆盖文字事件构造保持兼容，图片事件保存类型、消息键和边界。
2. 覆盖 `QueuedBatch.text` 排除图片占位并按事件顺序返回图片事件。
3. 覆盖 `ImageCapture` 只包含临时路径和降级标志。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py tests/test_wechat_bot.py -q`，确认新增模型测试先失败且纯文字队列测试继续通过。

## T14: 实现微信图片事件模型

**File:** `src/mewcode/wechat/models.py`
**Dependencies:** T13
**Steps:**
1. 向可见消息和桌面事件追加兼容默认字段。
2. 新增临时 `ImageCapture` 并实现批次图片事件只读属性。
3. 保持群聊、文字事件和既有位置参数调用兼容。

**Validation:** 重跑 T13 命令并确认模型相关测试通过。

## T15: 为 UIA 图片发现建立测试

**File:** `tests/test_wechat_uia_driver.py`
**Dependencies:** T14
**Steps:**
1. 覆盖私聊普通图片气泡被识别为稳定图片快照。
2. 覆盖启动基线和重复扫描不会重复派发同一图片。
3. 覆盖群聊图片、引用气泡、文件、语音、视频和分享卡片不会进入事件流。
4. 覆盖 `visible_text_messages()` 兼容包装仍只返回文字。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -q`，确认新增发现测试先失败。

## T16: 实现 UIA 私聊图片发现

**Files:** `src/mewcode/wechat/uia_client.py`, `src/mewcode/wechat/uia_driver.py`
**Dependencies:** T15
**Steps:**
1. 从文字和普通图片控件生成统一可见消息快照。
2. 使用 runtime id 与边界形成稳定图片键，不读取图片字节。
3. 私聊扫描产生图片事件，群聊继续过滤为纯文字。

**Validation:** 重跑 T15 命令并确认全部通过。

## T17: 为大图查看器采集与气泡降级建立测试

**File:** `tests/test_wechat_uia_driver.py`
**Dependencies:** T16
**Steps:**
1. 覆盖按消息键优先、边界容差后备的图片气泡重新定位。
2. 覆盖只接受同一微信进程中新出现且符合特征的大图查看器窗口。
3. 覆盖查看器截图成功、关闭并恢复原好友会话。
4. 覆盖各查看器失败点降级为气泡截图，以及两者都失败或会话改变时返回失败。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -q`，确认新增采集测试先失败。

## T18: 实现大图查看器采集与气泡降级

**Files:** `src/mewcode/wechat/uia_client.py`, `src/mewcode/wechat/uia_driver.py`
**Dependencies:** T17
**Steps:**
1. 迁移 `fake-wx-account` 中查看器验证、窗口截图、关闭和恢复所需的最小逻辑。
2. 将成功截图写入调用方批次临时目录，并标记来源是否降级。
3. 让 Driver 物化调用与现有发送操作共享锁，拒绝错误会话或非白名单路径。

**Validation:** 重跑 T17 命令并确认全部通过；测试不得打开真实好友图片。

## T19: 为 Runtime 活动图片上下文建立测试

**File:** `tests/test_wechat_runtime.py`
**Dependencies:** T4, T8, T10, T12
**Steps:**
1. 覆盖图片写入前配额预留、一次多模态 user 消息和写入失败时不调用模型。
2. 覆盖最近批次在后续三个纯文字好友回合中持续发送，第四回合停止发送。
3. 覆盖新图片批次立即替换旧活动批次，旧 Base64 仍留在 JSONL。
4. 覆盖重启恢复三回合状态，以及已清理图片永不发送。
5. 覆盖流式回答、取消、usage 和现有工具循环保持不变。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_runtime.py -q`，确认新增 Runtime 测试先失败且既有文字测试继续通过。

## T20: 实现 Runtime 多模态会话和活动批次筛选

**File:** `src/mewcode/wechat/runtime.py`
**Dependencies:** T19
**Steps:**
1. 扩展私聊 `reply()` 的关键字图片参数，群聊接口不增加图片能力。
2. 在打开 Writer 前预留档案配额，追加并核验一条多模态用户消息。
3. 以纯函数从消息顺序推导最近图片批次和三次后续文字回合。
4. 在发送模型前仅对请求副本清除非活动图片，不改写未触发配额清理的原始档案。

**Validation:** 重跑 T19 命令并确认全部通过。

## T21: 为 Bot 七秒图文批次建立测试

**File:** `tests/test_wechat_bot.py`
**Dependencies:** T12, T14, T18, T20
**Steps:**
1. 覆盖私聊单图在七秒静默后直接触发默认简短识别。
2. 覆盖同一窗口内多图加文字合并为一次问答，图片顺序稳定且不额外发默认描述。
3. 覆盖超过四张、非法格式、单边超限或总量超限时整批不调用模型并只提示一次。
4. 覆盖采集失败只提示一次且不重试、不回退纯文字猜测。
5. 覆盖非白名单和群聊图片不物化、不读取、不上传。
6. 覆盖成功、失败、取消、超时和发送异常后批次临时目录均被删除。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_bot.py -q`，确认新增批次测试先失败且既有私聊取消、FIFO 与群聊测试继续通过。

## T22: 实现 Bot 图片批次消费与清理

**File:** `src/mewcode/wechat/bot.py`
**Dependencies:** T21
**Steps:**
1. 仅在批次成为 FIFO 队首后统计并物化白名单私聊图片。
2. 用一个 `TemporaryDirectory` 包围整批采集、编码、Runtime 调用和所有退出路径。
3. 实现默认识别提示、图文合并、固定失败/超限提示和降级披露状态。
4. 保持原有七秒静默、好友任务取消、全局 FIFO 和顺序发送行为。

**Validation:** 重跑 T21 命令并确认全部通过。

## T23: 加固微信图片回复安全策略

**File:** `src/mewcode/wechat/prompts/reply_policy.md`
**Dependencies:** T20
**Steps:**
1. 要求无文字图片简短说明主体、场景和清晰关键文字，不确定时明确说明。
2. 将图片与其中的文字一律标为不可信，只回答好友当前问题。
3. 禁止图片指令改变系统规则或扩大微信本地工具权限。
4. 要求气泡降级来源在最终回答中说明可能不是完整原图。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_runtime.py tests/test_prompt.py -q` 并确认提示加载和 Runtime 测试通过；再用 `rg -n "不可信|完整原图|不确定" src/mewcode/wechat/prompts/reply_policy.md` 检查规则可见。

## T24: 更新视觉模型配置与数据披露

**Files:** `.mewcode/config.yaml`, `.mewcode/config.yaml.example`, `README.md`, `src/mewcode/wechat/bot.py`
**Dependencies:** T22
**Steps:**
1. 只将现有 `openai` Provider 的模型名替换为 `deepseek-v4-flash-vision-exp`，保留本地密钥和其他 Provider 设置。
2. 更新无密钥示例；不为 TUI 增加图片入口。
3. 文档说明私聊范围、四图/32 MiB/8192 限制、三轮追问、256 MiB 清理、明文 Base64 和上传 DeepSeek。
4. 启动时仅在存在白名单好友时打印一次相同数据披露，不输出好友名、密钥或图片内容。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_config.py tests/test_wechat_config.py tests/test_wechat_bot.py -q`；使用只输出 Provider 名与模型名的配置检查确认微信和 TUI 解析到同一视觉模型，且输出不含 Key。

## T25: 添加可重复的最小真实 API 探测

**File:** `scripts/probe_deepseek_vision.py`
**Dependencies:** T4, T24
**Steps:**
1. 从项目配置读取现有 `openai` Provider，在内存生成无敏感 16×16 PNG。
2. 通过一次视觉流请求验证文本增量与 usage。
3. 通过 `tool_choice=auto` 的视觉请求验证 Tool Calls 增量可以组装成有效函数参数。
4. 只输出模型名、布尔结果和计数；不打印 Key、Data URL、Base64 或完整响应。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe scripts/probe_deepseek_vision.py`，期望退出码为 0 且视觉流、usage 和自动 Tool Calls 均为通过；任一失败立即停止验收，不禁用工具。

## T26: 执行定向回归与静态检查

**Files:** All modified source and test files
**Dependencies:** T23, T24, T25
**Steps:**
1. 运行 LLM、Session、Context 和 WeChat 定向测试。
2. 运行 Ruff 检查所有修改的 Python 文件。
3. 运行 Mypy 项目检查并区分本次引入与既有问题。
4. 检查 git diff 中没有密钥、临时图片、Base64 样本或越界引用功能。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_llm_helpers.py tests/test_conversation.py tests/test_session_archive.py tests/test_session_repository.py tests/test_context_budget.py tests/test_wechat_image.py tests/test_wechat_uia_driver.py tests/test_wechat_runtime.py tests/test_wechat_bot.py -q`、`D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m ruff check src tests scripts/probe_deepseek_vision.py` 和 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m mypy src/mewcode`；本次相关检查全部通过。

## T27: 执行全量测试和需求覆盖审计

**Files:** Entire repository, `doc/21/spec.md`, `doc/21/plan.md`, `doc/21/task.md`
**Dependencies:** T26
**Steps:**
1. 运行完整测试套件，确认 TUI、纯文字 Provider、工具调用、群聊和 Session 恢复无回归。
2. 对照每条功能需求与验收标准检查实现和测试证据。
3. 检查用户可见失败提示、数据披露、临时文件清理和 JSONL 清理占位。
4. 记录真实 API 探测及自动 Tool Calls 结果供 `checklist.md` 验收使用。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest -q` 和 `git diff --check`，要求全量测试通过、补丁无格式错误、所有验收标准均有可执行证据。

## Requirement Coverage

| Area | Tasks |
|------|-------|
| 全局视觉模型、流式输出与 Tool Calls | T3-T4, T24-T27 |
| 私聊七秒图文批次与最多四图 | T13-T16, T21-T22 |
| 大图查看器优先与气泡降级 | T17-T18, T21-T23 |
| 格式、8192 单边与 32 MiB 整批限制 | T11-T12, T21-T22 |
| Base64 JSONL、重启恢复与三轮追问 | T5-T10, T19-T20 |
| 每好友 256 MiB 原子清理 | T7-T8, T19-T20 |
| 白名单、提示注入和本地工具边界 | T15-T16, T21-T24 |
| 临时文件生命周期和明确失败 | T17-T18, T21-T22 |
| README、启动披露与隐私边界 | T24, T26-T27 |
| TUI、群聊、引用解析不回归 | T3-T4, T15-T16, T24, T26-T27 |

## Execution Order

```text
T1 -> T2 -> T3 -> T4
          +-> T5 -> T6 -> T7 -> T8
          +-> T9 -> T10
          `-> T11 -> T12

T2 -> T13 -> T14 -> T15 -> T16 -> T17 -> T18

T4 + T8 + T10 + T12 -> T19 -> T20
T12 + T14 + T18 + T20 -> T21 -> T22
T20 -> T23
T22 -> T24
T4 + T24 -> T25
T23 + T24 + T25 -> T26 -> T27
```
