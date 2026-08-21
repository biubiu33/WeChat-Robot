# MewCode 微信自然对话节奏与分段回复 Tasks

状态：已批准（2026-08-20）

## File List

| Action | File | Responsibility |
|---|---|---|
| Modify | `src/mewcode/wechat/models.py` | 定义待收集批次、FIFO 快照和结构化回复 |
| Modify | `src/mewcode/session/runtime.py` | 允许归档转换器暂缓单条消息 |
| Modify | `src/mewcode/wechat/info/registry.py` | 将信息正文与来源消息分离 |
| Modify | `src/mewcode/wechat/runtime.py` | 回复提示、工具阶段、纯文本整形和投递后归档 |
| Modify | `src/mewcode/wechat/bot.py` | 7 秒聚合、队列失效、自然打断和顺序发送 |
| Modify | `src/mewcode/wechat/config.py` | 提供默认朋友型人物角色 |
| Create | `tests/test_session_runtime.py` | 验证 nullable archive transform |
| Modify | `tests/test_wechat_info_registry.py` | 验证独立来源和 URL 净化 |
| Modify | `tests/test_wechat_runtime.py` | 验证回复协议、工具阶段和实际投递历史 |
| Modify | `tests/test_wechat_bot.py` | 验证聚合、FIFO、打断、间隔和发送顺序 |
| Modify | `tests/test_wechat_config.py` | 验证默认人物角色和自定义覆盖 |
| Modify | `README.md` | 更新微信自然聊天行为和使用说明 |
| Modify | `C:\Users\nhdt_\.mewcode\config.yaml` | 更新当前安装实际使用的人物角色，不改其他配置 |
| Modify | `TODO.md` | 验收完成后更新 P0 第 1、2 项进度 |
| Modify | `doc/16/spec.md` | 保留批准状态，验收后不改行为范围 |
| Modify | `doc/16/plan.md` | 保留批准状态，记录获批技术设计 |
| Create | `doc/16/checklist.md` | 下一阶段生成的可执行验收清单 |

## T1: Replace WeChat queue and reply models

**File:** `src/mewcode/wechat/models.py`
**Dependencies:** None

**Steps:**
1. 删除仅承载单事件的 `QueuedMessage`。
2. 增加 `PendingBatch`，保存事件、修订号、计时任务和 queued 状态。
3. 增加不可变 `QueuedBatch`，保存好友名、事件快照、修订号和入队时间，并按换行生成合并文本。
4. 将 `WechatReply` 改为 `messages`、`chat` 和 `source_message`。
5. 更新模块导出。

**Validation:** 导入新数据结构，构造两条事件并断言 `QueuedBatch.text` 按原顺序以换行连接。

## T2: Allow deferred archive messages

**File:** `src/mewcode/session/runtime.py`
**Dependencies:** None

**Steps:**
1. 将 `MessageTransform` 返回类型扩展为 `Message | None`。
2. `_append` 在转换结果为 `None` 时跳过 archive append。
3. 保持标题生成仍由原始 user 消息触发，普通调用路径不变。

**Validation:** 运行新增的 session runtime 定向测试，确认返回 `None` 的消息不在档案中，其他消息正常写入。

## T3: Add deferred archive regression test

**File:** `tests/test_session_runtime.py`
**Dependencies:** T2

**Steps:**
1. 使用最小 Fake Provider 创建 `SessionRuntime`。
2. 配置只跳过普通 assistant 消息的转换器。
3. 追加 user、assistant 和其他保留消息后关闭并恢复档案。
4. 断言被跳过消息不存在，保留消息顺序正确。

**Validation:** `python -m pytest tests/test_session_runtime.py -q` 通过。

## T4: Separate information answer and sources

**File:** `src/mewcode/wechat/info/registry.py`
**Dependencies:** None

**Steps:**
1. 增加不可变 `FinalizedInfoReply`。
2. 将来源账本 finalization 改为分别生成净化 answer 和独立 `source_message`。
3. 保持允许 URL、未核实 URL、前三个来源和 OpenStreetMap 署名规则不变。
4. 更新 `WechatInfoTurn` 返回类型和模块导出。

**Validation:** 构造包含已记录和未记录 URL 的账本，断言正文不包含未核实 URL，来源只出现在独立字段。

## T5: Update source ledger tests

**File:** `tests/test_wechat_info_registry.py`
**Dependencies:** T4

**Steps:**
1. 更新旧的整串来源断言为 answer/source_message 双字段断言。
2. 增加多个网页来源只形成一条末尾来源消息的测试。
3. 增加 OpenStreetMap 署名与无来源空字段测试。

**Validation:** `python -m pytest tests/test_wechat_info_registry.py -q` 通过。

## T6: Add stable natural-reply policy

**File:** `src/mewcode/wechat/runtime.py`
**Dependencies:** None

**Steps:**
1. 增加稳定 `WECHAT_REPLY_POLICY`。
2. 写入闲聊短答、避免套话、`<|bubble|>`、专业纯文本、无 Markdown 包装和工具状态不重复等规则。
3. 加入闲聊多气泡、闲聊单气泡、专业说明和代码回答示例。
4. 将策略拼接到微信稳定系统提示，并保留用户自定义 Prompt 和信息工具安全策略。

**Validation:** Fake Provider 捕获请求，断言稳定 system 同时包含用户 Prompt、气泡协议、纯文本约束和既有信息工具策略。

## T7: Implement conservative WeChat plain-text conversion

**File:** `src/mewcode/wechat/runtime.py`
**Dependencies:** T6

**Steps:**
1. 实现逐行识别三反引号代码围栏，删除围栏但原样保留内部代码。
2. 仅在非代码段移除 Markdown 标题、引用、成对强调和行内代码包装。
3. 将 Markdown 链接转换为标题和原 URL 的纯文本。
4. 清理首尾空白和过量空行，不删除任意单个 `#`、`*`、反斜线或下划线。

**Validation:** 对混合普通文本和 Python/正则/Windows 路径的示例运行纯函数断言，包装消失且代码逐字保留。

## T8: Implement chat bubbles and professional splitting

**File:** `src/mewcode/wechat/runtime.py`
**Dependencies:** T1, T7

**Steps:**
1. 实现专业正文按自然段、句子、硬切三级分段。
2. 实现 `<|bubble|>` 解析、空白气泡过滤和最多 7 条归并。
3. 实现 `build_wechat_reply`，无标记走专业路径，有标记走闲聊路径。
4. `force_professional=True` 时不解释气泡标记为出站气泡，并按专业正文处理。
5. 对正文和来源消息应用纯文本包装清理。

**Validation:** 定向运行回复整形测试，覆盖 1 条、7 条、超过 7 条、长专业正文、路径反斜线和强制专业模式。

## T9: Add reply-formatting tests

**File:** `tests/test_wechat_runtime.py`
**Dependencies:** T7, T8

**Steps:**
1. 增加闲聊气泡解析及超限归并测试。
2. 增加专业反斜线不拆分和长文自然分段测试。
3. 增加 Markdown 包装清理及围栏内代码字符保留测试。
4. 增加网页强制专业路径和独立来源字段测试。

**Validation:** `python -m pytest tests/test_wechat_runtime.py -q` 的回复格式用例通过。

## T10: Observe and deduplicate tool stages

**File:** `src/mewcode/wechat/runtime.py`
**Dependencies:** T4, T6, T8

**Steps:**
1. 将微信回复路径改为消费现有 Agent 事件流，同时保留超时、取消和受控错误语义。
2. 将时间工具映射为 `time` 阶段，将网页搜索和网页读取映射为 `web` 阶段。
3. 每轮按阶段去重，并在阶段首次开始时调用异步通知回调。
4. 记录是否使用网页阶段，最终回复据此强制专业路径。
5. 未知工具不生成用户可见状态。

**Validation:** Fake Provider 依次触发 search/fetch 和 time，断言 web 只通知一次、time 单独通知、取消可停止后续工具。

## T11: Defer final model reply and record actual delivery

**File:** `src/mewcode/wechat/runtime.py`
**Dependencies:** T2, T10

**Steps:**
1. 调整微信 archive transform：继续保存 user、已净化工具调用和工具结果，跳过普通最终 assistant 文本。
2. 实现 `record_delivery`，按好友 Session 绑定打开档案并追加实际可见 assistant 文本。
3. 多条实际消息使用空行连接成一次 assistant 历史；空投递不追加。
4. 保持信息工具原始参数和正文不进入档案。

**Validation:** 运行恢复测试，确认模型完整草稿不在历史中，只有显式报告的部分投递内容可被下一轮看到。

## T12: Add runtime tool-stage and delivery tests

**File:** `tests/test_wechat_runtime.py`
**Dependencies:** T10, T11

**Steps:**
1. 增加 time/web 阶段文案和去重测试。
2. 增加工具阶段回调取消测试。
3. 增加完整投递、部分投递和零投递的 Session 恢复测试。
4. 断言归档中仍只有净化后的工具结构，没有网页正文或工具参数。

**Validation:** `python -m pytest tests/test_wechat_runtime.py -q` 全部通过。

## T13: Implement per-friend quiet-window collection

**File:** `src/mewcode/wechat/bot.py`
**Dependencies:** T1

**Steps:**
1. 将队列类型改为 `QueuedBatch | None`，增加每好友 `PendingBatch` 状态表。
2. 有效事件记录去重后加入好友批次，递增修订号并取消旧静默任务。
3. 启动可取消静默任务，默认等待固定 7 秒后把当前修订快照放入 FIFO。
4. 删除 `/cancel` 本地特殊处理。
5. 关闭时取消并回收所有未完成静默任务。

**Validation:** 使用极短测试静默时间提交同好友连续消息，断言只入队一个按换行合并的最新修订快照。

## T14: Implement stale-batch validation and FIFO claiming

**File:** `src/mewcode/wechat/bot.py`
**Dependencies:** T13

**Steps:**
1. 消费者领取前比较当前好友修订号、queued 状态和事件快照。
2. 失效快照只完成 queue bookkeeping，不调用 Runtime、不标记事件 processed。
3. 有效快照从 pending 状态领取后进入现有单消费者处理路径。
4. 批次结束时逐个标记所有已领取事件 processed。

**Validation:** 构造 A 旧快照、A 补充消息和 B 就绪任务，断言 A 旧快照跳过，B 与 A 新快照按实际入队顺序各处理一次。

## T15: Implement natural interruption and visible delivery

**File:** `src/mewcode/wechat/bot.py`
**Dependencies:** T10, T11, T14

**Steps:**
1. `ActiveTurn` 保存好友名、cancel event 和 delivered 文本。
2. 同好友新事件到达时立即设置活动 cancel，并正常进入新的 7 秒收集；其他好友不设置 cancel。
3. 工具阶段回调发送自然状态消息，发送成功后加入 delivered。
4. 发送结构化正文和独立来源，每条成功后加入 delivered。
5. 成功、错误或取消结束时调用 `record_delivery`，只提交实际发送文本。

**Validation:** Fake Runtime 阻塞期间发送同好友新消息，断言取消生效、无取消确认、其他好友消息不取消活动任务。

## T16: Implement capped cancellable chat timing

**File:** `src/mewcode/wechat/bot.py`
**Dependencies:** T15

**Steps:**
1. 每个闲聊回复批次采样一次每字速度。
2. 按下一条长度计算并夹取到 0.4～2 秒。
3. 使用 cancel event 与超时竞速实现可中断等待，不使用阻塞 sleep。
4. 专业分段和来源不使用闲聊延迟。
5. 任一 UIA 发送失败后停止本批剩余发送。

**Validation:** 注入确定速度并记录时间，断言延迟上下限、长度单调性、取消时不发送剩余气泡、专业消息无模拟等待。

## T17: Add aggregation and stale-queue tests

**File:** `tests/test_wechat_bot.py`
**Dependencies:** T13, T14

**Steps:**
1. 更新 Fake Runtime 返回结构化 `WechatReply` 并记录批次文本。
2. 覆盖同好友 7 秒聚合、计时重置和消息顺序。
3. 覆盖已排队批次失效、跨好友 FIFO 和事件 processed 状态。

**Validation:** 运行 `tests/test_wechat_bot.py` 中聚合和队列用例，测试不真实等待 7 秒。

## T18: Add interruption and delivery tests

**File:** `tests/test_wechat_bot.py`
**Dependencies:** T15, T16, T17

**Steps:**
1. 覆盖生成中、工具中和气泡间隔中的同好友自然打断。
2. 覆盖其他好友消息不取消当前活动任务。
3. 覆盖工具状态、闲聊气泡、专业分段和来源的原子发送顺序。
4. 覆盖部分发送失败后只记录成功投递。

**Validation:** `python -m pytest tests/test_wechat_bot.py -q` 全部通过。

## T19: Update user-facing documentation

**Files:** `README.md`, `TODO.md`
**Dependencies:** T12, T18

**Steps:**
1. README 描述固定 7 秒意图合并、闲聊语义气泡、专业纯文本、工具阶段状态和新消息自然打断。
2. 删除 README 中 `/cancel` 的能力和使用说明。
3. 说明微信回复不使用 Markdown 包装，但代码字符仍保留。
4. 在完整验收通过后勾选 TODO P0 第 1、2 项已经实现的条目；仍未覆盖的好友 Emoji 配置等条目保持未完成。

**Validation:** 搜索 README/TODO，确认不存在仍声称 `/cancel` 可用的内容，完成状态与实际实现一致。

## T20: Run focused quality checks

**Files:** All modified source and test files
**Dependencies:** T3, T5, T9, T12, T18, T19

**Steps:**
1. 运行 session、wechat bot、runtime、info registry 定向测试。
2. 运行修改模块 compileall。
3. 运行修改文件 Ruff check 和 format check。
4. 修复所有失败并重复执行。

**Validation:**

```powershell
python -m pytest tests/test_session_runtime.py tests/test_wechat_bot.py tests/test_wechat_runtime.py tests/test_wechat_info_registry.py -q
python -m compileall src/mewcode/session/runtime.py src/mewcode/wechat
python -m ruff check src/mewcode/session/runtime.py src/mewcode/wechat tests/test_session_runtime.py tests/test_wechat_bot.py tests/test_wechat_runtime.py tests/test_wechat_info_registry.py
python -m ruff format --check src/mewcode/session/runtime.py src/mewcode/wechat tests/test_session_runtime.py tests/test_wechat_bot.py tests/test_wechat_runtime.py tests/test_wechat_info_registry.py
```

## T21: Run full regression

**Files:** Entire repository
**Dependencies:** T20

**Steps:**
1. 运行全量 pytest。
2. 运行全量 compileall。
3. 运行全量 Ruff check 和 format check。
4. 记录实际通过、跳过和失败数量，失败时修复并重新验证。

**Validation:**

```powershell
python -m pytest -q
python -m compileall src/mewcode examples
python -m ruff check .
python -m ruff format --check .
```

## T22: Add the default friend persona

**Files:** `src/mewcode/wechat/config.py`, `tests/test_wechat_config.py`
**Dependencies:** T21

**Steps:**
1. 将 `DEFAULT_SYSTEM_PROMPT` 改成温暖、活泼、会适度开玩笑的年轻朋友型助手。
2. 明确不默认建立恋爱或亲属关系，不虚构现实生活经历。
3. 保留被问身份时如实说明 AI，以及不能访问本地环境的边界。
4. 保持现有 `wechat.system_prompt` 自定义值优先，不增加配置字段。
5. 更新配置测试，分别验证默认角色和显式自定义覆盖。

**Validation:** `python -m pytest tests/test_wechat_config.py -q` 通过；断言默认角色包含朋友语气、关系边界、现实经历边界和 AI 身份。

## T23: Strengthen multi-sentence bubble few-shots

**Files:** `src/mewcode/wechat/runtime.py`, `tests/test_wechat_runtime.py`
**Dependencies:** T21

**Steps:**
1. 将多气泡规则从“需要时”改为：闲聊出现多个完整句子、问题或独立语义点时必须使用 `<|bubble|>`。
2. 明确不能用逗号、句号或换行代替气泡标记，把多句留在一个消息中。
3. 加入“今天忙吗 / 我好无聊”对应四气泡的完整 few-shot。
4. 加入“嗯”“好”“哈哈哈哈哈哈”等单一短回应的单气泡 few-shot。
5. 保留专业说明、代码和网页工具回答不得使用气泡标记的反例。
6. 更新 Fake Provider 捕获测试，断言上述稳定规则和样例完整进入 system。

**Validation:** `python -m pytest tests/test_wechat_runtime.py -q` 通过；捕获的 system 同时包含四气泡输出、单气泡例外和专业反例。

## T24: Update the active persona configuration and README

**Files:** `C:\Users\nhdt_\.mewcode\config.yaml`, `README.md`
**Dependencies:** T22, T23

**Steps:**
1. 对当前配置执行精确修改，只替换 `wechat.system_prompt` 块。
2. 不读取、输出或改写 Provider 密钥，不改 `provider`、`allowed_contacts`、超时、长度、日志或信息工具字段。
3. 将 README 配置示例改成朋友型角色。
4. 说明 `system_prompt` 负责可编辑人物角色，稳定回复策略负责强制气泡协议和安全边界。

**Validation:** 通过配置加载器只打印 `system_prompt` 的 Unicode 转义和微信字段名，确认新角色生效且其他字段集合未变化；README 与批准方案一致。

## T25: Run focused persona and prompt checks

**Files:** `src/mewcode/wechat/config.py`, `src/mewcode/wechat/runtime.py`, `tests/test_wechat_config.py`, `tests/test_wechat_runtime.py`, `README.md`
**Dependencies:** T22, T23, T24

**Steps:**
1. 运行微信配置和 Runtime 定向测试。
2. 运行修改模块 compileall。
3. 对修改范围运行 Ruff check 和 format check。
4. 运行全量 pytest，确认既有聚合、工具、安全和发送行为无回归。

**Validation:**

```powershell
python -m pytest tests/test_wechat_config.py tests/test_wechat_runtime.py -q
python -m compileall src/mewcode/wechat/config.py src/mewcode/wechat/runtime.py
python -m ruff check src/mewcode/wechat/config.py src/mewcode/wechat/runtime.py tests/test_wechat_config.py tests/test_wechat_runtime.py
python -m ruff format --check src/mewcode/wechat/config.py src/mewcode/wechat/runtime.py tests/test_wechat_config.py tests/test_wechat_runtime.py
python -m pytest -q
```

## T26: Verify the revised behavior in WeChat

**Files:** None
**Dependencies:** T25

**Steps:**
1. 执行 `mewcode-wechat --probe`，确认微信 `4.0.5.15` 和三个必要 UIA 控件。
2. 由明确授权的专用测试好友连续发送“今天忙吗”和“我好无聊”，观察是否形成多个自然气泡。
3. 发送适合“嗯”或笑声回应的短消息，确认不会强行拆分。
4. 询问身份和现实经历，确认朋友式语气、AI 身份及不虚构边界。
5. 回归一个专业问题，确认不会按句号机械拆成闲聊气泡。

**Validation:** 记录 probe 输出和真实微信可见消息顺序；只有实际观察到 AC16～AC18 才在 checklist 中勾选对应 E2E。

## Execution Order

```text
T1 ───────────────────────────────┐
T2 -> T3                          │
T4 -> T5                          │
T6 -> T7 -> T8 -> T9              │
T4 + T6 + T8 -> T10               │
T2 + T10 -> T11 -> T12            │
T1 -> T13 -> T14                  │
T10 + T11 + T14 -> T15 -> T16     │
T13 + T14 -> T17                   │
T15 + T16 + T17 -> T18             │
T12 + T18 -> T19                   │
T3 + T5 + T9 + T12 + T18 + T19    │
  -> T20 -> T21                    │
└─────────────────────────────────┘
```

本次批准修订的增量执行顺序：

```text
既有 T1-T21 已完成
  -> T22 + T23
  -> T24
  -> T25
  -> T26
```
