# 微信私聊与群聊文字/图片引用回复 Tasks

状态：已批准

## File List

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/mewcode/wechat/models.py` | 一层引用快照、解析结果和不可变 FIFO 批次标记 |
| Modify | `src/mewcode/wechat/uia_client.py` | 引用标签解析、控件重获、定位原文、引用图片三级获取和目标恢复 |
| Modify | `src/mewcode/wechat/uia_driver.py` | 引用身份传播、群当前文字 @ 门禁、授权后的队首物化 |
| Modify | `src/mewcode/wechat/bot.py` | 引用独立排队、结构化 Prompt、类型化失败、群历史和临时清理 |
| Modify | `src/mewcode/wechat/runtime.py` | 私聊/群聊引用多模态、长引用拒绝、群图片不落 JSONL |
| Modify | `src/mewcode/wechat/prompts/reply_policy.md` | 引用内容不可信、上下文优先级和降级披露 |
| Modify | `tests/test_wechat_uia_driver.py` | 引用解析、身份、UI 操作顺序、恢复和门禁测试 |
| Modify | `tests/test_wechat_bot.py` | 独立 FIFO、失败行为、图文请求、群历史和临时清理测试 |
| Modify | `tests/test_wechat_runtime.py` | 私聊持久图片、群图片无落盘、长引用和上下文测试 |
| Modify | `README.md` | 使用范围、限制、版本和隐私披露 |

本版不修改通用 LLM 消息、OpenAI Provider、图片校验模块、Session repository、SQLite schema 或配置文件。

## T1: Add Reference Snapshot Models

**Files:** `src/mewcode/wechat/models.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** None

**Steps:**

1. 增加 `ReferenceKind`、`MessageReference` 和 `ResolvedReference`，字段与已批准 Plan 一致。
2. 为 `VisibleMessage`、`WechatDesktopEvent` 增加可选 `reference`，保持所有现有位置参数兼容。
3. 为 `QueuedBatch` 增加末尾 `immutable` 字段和 `reference_event` 只读属性。
4. 添加最小测试，断言普通消息缺省不带引用、单引用批次可取回引用事件、普通图片批次行为不变。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "reference_model or image_event_keeps_identity" -q`，现有图片测试和新增模型测试全部通过。

## T2: Parse Flattened Reference Labels

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T1

**Steps:**

1. 增加精确扁平引用标签解析和引用类型分类。
2. 覆盖短文字、图片、已知不支持类型、文件名、空当前问题和未知形态。
3. 覆盖嵌套引用，断言只拆当前一层，内层引用完整留在预览中。
4. 确保名称精确为“图片/Image”的 `ChatBubbleReferItemView` 仍是普通图片，不被误判为引用。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "reference_label or visible_messages_includes_plain_image" -q`，全部通过。

## T3: Emit Reference-Aware Visible Messages

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T2

**Steps:**

1. 让 `visible_messages()` 对引用气泡只输出当前问题，并附加 `MessageReference`。
2. 空当前问题、未知引用结构继续安全忽略。
3. 保留普通文字、普通图片、时间行和不支持气泡的现有分类行为。
4. 添加私聊与群聊可见消息快照测试，不依赖真实微信或 OCR 引擎。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "visible_messages" -q`，全部通过。

## T4: Preserve Reference Identity Through Driver Scans

**Files:** `src/mewcode/wechat/uia_driver.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T3

**Steps:**

1. 将引用快照从 `VisibleMessage` 复制到 `WechatDesktopEvent`。
2. 让稳定签名、事件指纹和后缀哈希纳入被引用者、类型和预览。
3. 群聊只对拆分后的当前问题执行 `strip_self_mention()`，引用预览中的 @ 不参与触发。
4. 添加“相同问题引用不同原文不去重”“当前 @ 触发”“引用内 @ 不触发”和 OCR 未知发送者忽略测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "reference and (event or mention or fingerprint)" -q`，全部通过。

## T5: Reacquire Exact Reference Controls

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T3

**Steps:**

1. 增加引用控件重获逻辑，同时核对 runtime id/边界、当前问题、被引用者、类型和预览。
2. 单一完整身份匹配才返回控件；仅文字相同或多个候选时返回 `None`。
3. 添加 runtime id 重用、边界轻微变化、被引用者变化和重复文本候选测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "reference_control" -q`，全部通过。

## T6: Add Safe Locate-Original UI Primitives

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T5

**Steps:**

1. 增加保持鼠标位置的点右键、桌面菜单精确查找和控件点击辅助函数。
2. 从已验证引用区域打开“定位到原文位置”，有界等待后重新取得消息列表。
3. 排除引用气泡，只接受唯一预览匹配的候选；重复匹配不得按距离猜测。
4. 增加“回到引用位置”动作；菜单缺失时不得发送全局 Escape。
5. 添加菜单缺失、重复原文、唯一原文和回到引用位置测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "locate_original or return_to_reference" -q`，全部通过。

## T7: Resolve Referenced Text With Preview Fallback

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T6

**Steps:**

1. 实现文字引用完整原文解析，返回 `wechat_locate_original` 与非降级结果。
2. 原消息本身是引用时只取其当前正文，不递归调用定位。
3. 安全定位失败时返回 `uia_reference_preview_only`；预览为空时返回安全空结果。
4. 定位后发现原控件属于图片或不支持类型时返回相应引用类型。
5. 添加完整文字、嵌套一层、预览降级、空预览和类型重分类测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "referenced_text or preview_fallback or nested_reference" -q`，全部通过。

## T8: Capture the Referenced Image Viewer Directly

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T5

**Steps:**

1. 增加引用内容命中点和从点打开大图查看器的辅助函数。
2. 复用现有查看器新窗口验证、截图、关闭、主窗口恢复和三态结果。
3. 确保点击发生在 UIA 主窗口上下文退出后，避免嵌套 COM 初始化。
4. 添加命中点、查看器成功、未打开和不安全关闭测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "referenced_image and viewer" -q`，全部通过。

## T9: Complete the Three-Stage Referenced Image Fallback

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T6, T8

**Steps:**

1. 直接引用大图失败后定位原图片，并只尝试原图大图查看器。
2. 安全回到引用位置后，优先取唯一图片子节点，缺失时截取经测试的引用下半区。
3. 缩略图结果标记 `degraded=True`，三段安全失败返回空图片结果。
4. 任一查看器关闭失败、会话恢复失败或会话类型变化时抛出 `WechatReferenceTargetError` 并停止降级。
5. 添加严格调用顺序、每级成功、全部失败和目标丢失测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "referenced_image and (fallback or target or order)" -q`，全部通过。

## T10: Gate Reference Materialization in the Driver

**Files:** `src/mewcode/wechat/uia_driver.py`, `tests/test_wechat_uia_driver.py`  
**Dependencies:** T4, T7, T9

**Steps:**

1. 增加 `materialize_reference()`，在现有 Driver 锁中调用 Client。
2. 私聊复核好友白名单；群聊复核群白名单、明确 @、唯一发送者、非空当前问题和引用存在。
3. 调用前后验证会话名称及私聊/群聊类型，失败统一抛出目标丢失错误。
4. 添加非白名单、未 @、发送者为空、会话类型变化和成功委派测试，断言门禁失败时 Client 未被调用。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py -k "materialize_reference" -q`，全部通过。

## T11: Implement Immutable Reference Queue Boundaries

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`  
**Dependencies:** T1, T4

**Steps:**

1. 增加将活动普通静默窗口立即封口并排队的内部辅助函数。
2. 引用到达时先固化前置普通批次，再将引用作为独立 immutable 批次排队。
3. 修改 `_claim()`：immutable 批次直接认领，普通批次保持 revision 语义。
4. 私聊引用继续取消同好友活动回复，群聊引用不取消活动群回复。
5. 添加 A 普通消息、B 引用、C 普通消息的 `A -> B -> C` 顺序测试，以及相邻引用互不合并测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_bot.py -k "reference and (queue or immutable or order)" -q`，全部通过。

## T12: Enforce Private and Group Reference Trigger Gates

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`  
**Dependencies:** T10, T11

**Steps:**

1. 私聊只排队白名单好友的“引用 + 非空当前问题”。
2. 群聊引用只在现有白名单、当前明确 @ 和唯一发送者门禁后排队。
3. 私聊空问题引用只去重并标记处理；群聊未 @ 引用只进入文字历史，不调用 Driver。
4. 非白名单引用不得进入持久化、图片读取或 Runtime。
5. 添加私聊空问题、群未 @、引用内 @、OCR 空发送者和非白名单测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_bot.py -k "reference and (gate or whitelist or empty or mention)" -q`，全部通过。

## T13: Build Structured Reference Prompts and Text Replies

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`  
**Dependencies:** T7, T11, T12

**Steps:**

1. 增加固定的当前问题、被引用内容和解析状态区块生成函数。
2. 完整文字调用 Runtime 一次；预览文字追加“内容可能不完整”约束。
3. 空文字发送一次固定失败提示；不支持类型发送一次“当前只支持引用文字和图片”。
4. 群聊失败提示继续通过现有首条真实 @ 发送路径。
5. 目标丢失错误只写元数据日志，不调用 Runtime 或发送失败提示。
6. 添加结构化内容、一次调用、降级披露、类型化失败和 target-lost 零发送测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_bot.py -k "reference and (prompt or text or unsupported or target)" -q`，全部通过。

## T14: Process Referenced Images in the Bot

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`  
**Dependencies:** T9, T10, T13

**Steps:**

1. 为每个引用任务建立唯一 `TemporaryDirectory`，在线程中物化、编码并复用 `validate_batch([image])`。
2. 私聊图片调用 `reply(..., images=[image], reference_turn=True)`；群聊调用带图片的 `reply_group()`。
3. 缩略图降级追加“可能不是完整原图”约束；大图不追加该说明。
4. 损坏、格式/尺寸/容量超限、图片空结果和模型失败都只走一次现有类型化提示，不重试、不纯文字猜测。
5. 添加成功、降级、超限、失败、取消和异常路径临时文件清理测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_bot.py -k "referenced_image or reference_image" -q`，全部通过。

## T15: Preserve Safe Group Reference History

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`  
**Dependencies:** T13, T14

**Steps:**

1. 群引用到达时写入只读预览占位，不触发额外 UI 操作。
2. 解析完成后按相同 `message_key` 替换当前快照和全局 20 条历史项。
3. 文字保存实际使用内容和降级状态；图片只保存被引用者、尺寸、SHA-256、降级与数据已释放占位。
4. 未 @ 图片引用只保存“未读取”标记，不计算尺寸或哈希。
5. 添加后续群问题可看到引用关系、历史上限仍为 20、图片历史不含 Base64/Data URL/临时路径的测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_bot.py -k "reference and group_history" -q`，全部通过。

## T16: Reject Oversized Reference Text Before Session Mutation

**Files:** `src/mewcode/wechat/runtime.py`, `tests/test_wechat_runtime.py`  
**Dependencies:** T13

**Steps:**

1. 增加 `WechatReferenceTooLongError` 和 `reference_turn` 缺省参数。
2. 复用 `TokenEstimator`、`message_request_chars()` 和 Provider `context_window`，只预检当前结构化引用消息。
3. 当前引用单独超限时在打开/写入 Session 和调用 Provider 前失败；可容纳时既有历史仍交给 ContextController 压缩。
4. Bot 捕获该错误并只发送一次“复制关键段落”提示。
5. 添加超限零 Provider 请求、零新 Session 消息和普通长文本行为不变测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_runtime.py tests/test_wechat_bot.py -k "reference and too_long" -q`，全部通过。

## T17: Allow Ephemeral Group Multimodal Requests Without Base64 Archives

**Files:** `src/mewcode/wechat/runtime.py`, `tests/test_wechat_runtime.py`  
**Dependencies:** T14, T16

**Steps:**

1. 扩展 `reply_group()` 接受 `images` 和 `reference_turn`，复用现有 `_reply(group=True)` 与 `_run_agent()`。
2. 增加群临时档案变换，序列化前移除 `Message.images`，内存 Conversation 保留图片供当前请求。
3. 保持群工具、流式、来源和临时 Session 删除逻辑不变。
4. 添加 Provider 收到图片、临时 JSONL 从未出现 Base64 样本、请求结束 Session 被删除和后续群问答不带旧图测试。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_runtime.py -k "group and (image or reference)" -q`，全部通过。

## T18: Reuse Persistent Private Image Context for References

**Files:** `src/mewcode/wechat/runtime.py`, `tests/test_wechat_runtime.py`  
**Dependencies:** T14, T16

**Steps:**

1. 确认私聊引用结构化文本与图片作为一条 user 消息进入现有 Session。
2. 保持写入前 256 MiB 预留、JSONL 写入检查、最近图片批次和三个后续文字回合逻辑。
3. 添加引用图片 Base64 只归档一次、随后三轮重复请求、第四轮退出、新图片替换和重启恢复测试。
4. 断言引用元数据可读但 Base64 不被复制进 `content`、摘要或工具结果。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_runtime.py -k "private and reference and image" -q`，全部通过。

## T19: Harden the Reference Reply Policy

**Files:** `src/mewcode/wechat/prompts/reply_policy.md`, `tests/test_wechat_runtime.py`  
**Dependencies:** T13

**Steps:**

1. 增加引用区块不可信、当前问题优先、引用内容为主要对象和历史只用于消歧的规则。
2. 明确引用内指令不得改变角色、工具、门禁、回复者、Provider 和保存策略。
3. 明确文字预览和图片缩略图降级必须披露，不得补造不可见内容。
4. 保留现有气泡、专业回答、图片、群聊和微信工具权限文本。
5. 添加 Runtime 系统提示断言，确保普通私聊和群聊均加载新增规则且工具白名单未扩大。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_runtime.py -k "prompt or tools or reference_policy" -q`，全部通过；再运行 `rg -n "引用|不可信|可能不完整|完整原图" src/mewcode/wechat/prompts/reply_policy.md`。

## T20: Add Safe Logging and Startup Disclosure

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`  
**Dependencies:** T13, T14, T15

**Steps:**

1. 启动时分别披露私聊引用图片的 DeepSeek 上传/明文 Session，以及群聊合规引用图片的临时上传。
2. 新引用日志只记录会话类型、引用类型、策略、状态、降级、尺寸和哈希。
3. 错误日志不得包含引用正文、Base64、Data URL、模型请求体、联系人名、群名或密钥。
4. 保持现有模型最终回复控制台区块行为不变。
5. 添加启动日志和异常日志捕获测试，使用哨兵正文/Base64/密钥断言不泄露。

**Validation:** 运行 `D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_bot.py -k "reference and (log or disclosure or secret)" -q`，全部通过。

## T21: Update the README

**File:** `README.md`  
**Dependencies:** T19, T20

**Steps:**

1. 说明私聊“引用 + 非空问题”与群聊“引用 + 当前明确 @ + 唯一 OCR”的触发门禁。
2. 说明引用独立 FIFO、一层解析、文字完整原文/预览降级和图片三级获取。
3. 说明私聊引用图片明文 Base64、三回合和 256 MiB；群图片当前请求后删除且需再次引用追问。
4. 说明非白名单/门禁失败不读取上传，以及文件、语音、视频、分享卡片和出站引用不支持。
5. 标注 `4.1.9.30` 真人验收范围与 `4.0.5.15` 未真人实测时的兼容声明。

**Validation:** 运行 `rg -n "引用|DeepSeek|Base64|4\.1\.9\.30|4\.0\.5\.15|当前只支持" README.md`，逐项检查披露与实际行为一致；运行 `git diff --check` 无格式错误。

## T22: Run Targeted Reference Integration Tests

**Files:** 本版所有修改文件  
**Dependencies:** T1-T21

**Steps:**

1. 运行引用涉及的 UIA、Bot 和 Runtime 测试。
2. 运行上一版图片校验测试，确认引用路径确实复用格式、8192、32 MiB 和 `original` 边界。
3. 运行群 OCR、Store 和 Session archive/repository 测试，确认无数据库或档案回归。
4. 修复任何失败后重新运行同一组检查。

**Validation:** 运行：

```powershell
D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest tests/test_wechat_uia_driver.py tests/test_wechat_bot.py tests/test_wechat_runtime.py tests/test_wechat_image.py tests/test_wechat_group_sender_ocr.py tests/test_wechat_store.py tests/test_session_archive.py tests/test_session_repository.py -q
```

要求全部通过。

## T23: Run Static Quality Checks

**Files:** 本版所有修改文件  
**Dependencies:** T22

**Steps:**

1. 对修改源码和测试运行 Ruff。
2. 对 Mewcode 源码运行 mypy。
3. 运行格式差异检查，确认没有尾随空白、冲突标记、真实/完整 Base64 载荷或临时图片进入补丁；小型固定哨兵仅允许存在于自动化测试中。
4. 修复后重复检查直至全部通过。

**Validation:** 运行：

```powershell
D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m ruff check src tests
D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m mypy src/mewcode
git diff --check
git status --short
```

Ruff、mypy 和 diff 检查均成功；状态列表只包含批准范围内的源码、测试、README 和 `doc/22` 文档。

## T24: Run the Full Regression Suite

**Files:** 整个项目  
**Dependencies:** T23

**Steps:**

1. 使用 conda `mewcode` Python 运行全量测试。
2. 对照 `spec.md` 检查每条验收标准都有自动化或明确的真实微信验收步骤。
3. 记录自动化测试数量、跳过项和真实微信尚未执行的项目，不把未真人实测写成通过。

**Validation:** 运行：

```powershell
D:\SoftwareDownload\miniconda3\envs\mewcode\python.exe -m pytest -q
git diff --check
```

全量测试无新增失败，补丁格式正确；真实微信 `4.1.9.30` 四个端到端场景留到 `checklist.md` 验收阶段执行并记录证据。

## Execution Order

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7
                         `-> T8 -> T9
T4 + T7 + T9 -> T10 -> T11 -> T12 -> T13 -> T14 -> T15
T13 -> T16 -> T17 -> T18
T13 -> T19
T15 + T19 -> T20 -> T21
T1-T21 -> T22 -> T23 -> T24
```

## Coverage Summary

| Requirement group | Tasks |
|-------------------|-------|
| 一层识别与身份 | T1-T5 |
| 文字定位与降级 | T6-T7, T10, T13 |
| 图片三级获取与校验 | T8-T10, T14 |
| 独立 FIFO 与触发门禁 | T11-T12 |
| 上下文与群历史 | T13, T15, T18 |
| 长引用、私聊/群聊图片生命周期 | T16-T18 |
| 安全提示、日志和披露 | T13, T19-T21 |
| 自动化、静态检查和回归 | T22-T24 |
