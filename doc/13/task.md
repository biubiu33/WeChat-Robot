# MewCode 微信桌面聊天机器人 V1 Tasks

状态：已批准

## File List

| Action | File | Responsibility |
|---|---|---|
| Modify | `pyproject.toml` | 注册 `mewcode-wechat` 命令和 Windows 微信可选依赖 |
| Modify | `README.md` | 补充安装、配置、运行、安全边界和人工验证说明 |
| Modify | `src/mewcode/config.py` | 保留顶层 `wechat` 原始配置，同时维持现有配置兼容性 |
| Create | `src/mewcode/wechat/__init__.py` | 微信包边界 |
| Create | `src/mewcode/wechat/models.py` | UIA、队列和回复使用的纯数据模型 |
| Create | `src/mewcode/wechat/config.py` | 独立解析和校验 MewCode 微信配置 |
| Create | `src/mewcode/wechat/store.py` | SQLite 消息去重、处理状态和好友 Session 绑定 |
| Create | `src/mewcode/wechat/uia_client.py` | 微信 4.1.12.55 的只读探测、控件读取和安全发送 |
| Create | `src/mewcode/wechat/shell_hook.py` | Windows Shell 通知唤醒 |
| Create | `src/mewcode/wechat/uia_driver.py` | 启动基线、消息快照差异、事件构造和目标复核 |
| Create | `src/mewcode/wechat/runtime.py` | 使用现有 Agent 的零工具微信会话运行时 |
| Create | `src/mewcode/wechat/bot.py` | 白名单、FIFO、取消、错误降级和生命周期协调 |
| Create | `src/mewcode/wechat/cli.py` | 独立微信机器人命令入口 |
| Create | `tests/test_wechat_config.py` | 微信配置和现有配置兼容性测试 |
| Create | `tests/test_wechat_store.py` | 去重、处理状态和 Session 绑定测试 |
| Create | `tests/test_wechat_uia_driver.py` | 合成 UIA 快照、过滤、基线和目标复核测试 |
| Create | `tests/test_wechat_runtime.py` | 会话隔离、恢复、零工具和超时测试 |
| Create | `tests/test_wechat_bot.py` | 白名单、FIFO、取消、分段和错误恢复测试 |

## T1：建立微信包和数据模型

**Files:** `src/mewcode/wechat/__init__.py`, `src/mewcode/wechat/models.py`

**Dependencies:** None

**Steps:**

1. 创建 `mewcode.wechat` 包。
2. 按 `plan.md` 定义不可变的事件、会话绑定、排队消息和回复模型。
3. UIA Control 对象不得进入数据模型。

**Validation:** 运行 `python -m compileall src/mewcode/wechat`，预期编译成功。

## T2：接入顶层原始微信配置

**Files:** `src/mewcode/config.py`, `tests/test_wechat_config.py`

**Dependencies:** T1

**Steps:**

1. 让现有配置加载器保留可选的顶层 `wechat` 对象。
2. 对非对象的 `wechat` 值返回明确配置错误。
3. 保持未配置 `wechat` 时的 TUI 和 Provider 行为不变。

**Validation:** 运行 `pytest tests/test_wechat_config.py -q`，预期新增兼容性用例通过。

## T3：实现 MewCode 自有微信配置校验

**Files:** `src/mewcode/wechat/config.py`, `tests/test_wechat_config.py`

**Dependencies:** T2

**Steps:**

1. 解析 `enabled`、`provider`、`allowed_contacts`、系统提示、超时、回复分段长度和日志级别。
2. 校验 Provider 引用、精确白名单、数值范围和必填字段。
3. 配置默认值全部定义在 MewCode 内，不读取 fake-wx-account。

**Validation:** 运行 `pytest tests/test_wechat_config.py -q`，预期合法、缺失和非法配置用例全部通过。

## T4：建立 SQLite 状态库和事件去重

**Files:** `src/mewcode/wechat/store.py`, `tests/test_wechat_store.py`

**Dependencies:** T1

**Steps:**

1. 使用标准库 `sqlite3` 创建事件表和唯一指纹约束。
2. 实现同一事件的原子首次登记和处理状态更新。
3. 支持安全关闭和重复初始化。

**Validation:** 运行 `pytest tests/test_wechat_store.py -q`，预期重复指纹只有第一次登记成功。

## T5：实现好友到 Session 的持久绑定

**Files:** `src/mewcode/wechat/store.py`, `tests/test_wechat_store.py`

**Dependencies:** T4

**Steps:**

1. 增加唯一好友显示名到 MewCode Session ID 的查询与绑定。
2. 保证重复绑定幂等，冲突绑定安全失败。
3. 不为已判断为重名的会话建立绑定。

**Validation:** 运行 `pytest tests/test_wechat_store.py -q`，预期关闭并重开数据库后绑定仍可恢复。

## T6：只读探测微信 4.1.12.55 UIA 树

**File:** `src/mewcode/wechat/uia_client.py`

**Dependencies:** T1

**Steps:**

1. 实现只读 `probe()`，输出主窗口及必要控件的名称、类型、AutomationId 和层级信息。
2. 在用户本机已登录微信 4.1.12.55 上执行探测。
3. 根据实际结果记录主窗口、会话列表、消息列表和输入框的最小稳定定位条件。
4. 探测期间不得点击发送按钮、写入输入框或发送真实消息。

**Validation:** 人工观察探测输出，确认能识别唯一微信窗口和四类必要控件，且微信中没有产生新消息。

## T7：实现窗口、会话和文字消息读取

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`

**Dependencies:** T6

**Steps:**

1. 仅使用 T6 在 4.1.12.55 上确认的定位条件实现控件查找。
2. 读取可见私聊会话和可见文字气泡，并转换为纯数据快照。
3. 对找不到窗口、控件歧义和重名会话返回明确错误。

**Validation:** 使用合成控件快照运行 `pytest tests/test_wechat_uia_driver.py -q`，并在真实微信上执行一次只读读取检查。

## T8：实现目标复核和文字发送原语

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`

**Dependencies:** T7

**Steps:**

1. 使用 `Ctrl+F`、精确好友名和 Enter 按原会话重新定位；输入前确认搜索框焦点，打开前确认搜索值和唯一结果，打开后复核聊天标题。
2. 仅在目标唯一且复核成功后，通过输入框 `ValuePattern.SetValue`、`SetFocus` 和 Enter 发送文字，并确认输入框清空。
3. 会话切换和发送不得调用鼠标 `Click()`；焦点、唯一性、目标或发送结果无法确认时安全失败。
4. 避免因当前可见会话变化而向其他联系人降级发送。

**Validation:** 合成测试覆盖键盘序列、目标匹配、目标变化、重名和焦点拒绝；真实微信验证切换与发送前后鼠标坐标不变。

## T9：实现 Shell Hook 唤醒和低频校准

**File:** `src/mewcode/wechat/shell_hook.py`

**Dependencies:** T6

**Steps:**

1. 使用 `pywin32` 监听目标微信窗口的 Shell 通知。
2. 回调只设置唤醒信号，不在回调中访问 UIA。
3. Hook 不可用时允许驱动依靠低频校准扫描继续运行。

**Validation:** 在 Windows 上启动和停止 Hook 两次，预期无残留线程；禁用 Hook 时仍能触发校准信号。

## T10：实现启动基线和快照差异

**Files:** `src/mewcode/wechat/uia_driver.py`, `tests/test_wechat_uia_driver.py`

**Dependencies:** T7, T9

**Steps:**

1. 建立启动基线，只记录当前可见消息而不产生事件。
2. 在 Hook 或校准唤醒后读取新快照并计算新增气泡。
3. 用单把锁串行化全部 UIA 访问。

**Validation:** 运行 `pytest tests/test_wechat_uia_driver.py -q`，预期历史消息不产生事件，新增气泡只产生一次候选事件。

## T11：构造并过滤稳定的微信事件

**Files:** `src/mewcode/wechat/uia_driver.py`, `tests/test_wechat_uia_driver.py`

**Dependencies:** T10

**Steps:**

1. 从快照生成稳定的事件 ID、指纹、会话和时间信息。
2. 识别并排除出站气泡、群聊、非文字内容和系统通知。
3. 暴露发送前目标复核和受锁保护的文字发送方法。

**Validation:** 运行 `pytest tests/test_wechat_uia_driver.py -q`，预期各类非目标消息均不产生入站事件。

## T12：实现好友会话创建、恢复与隔离

**Files:** `src/mewcode/wechat/runtime.py`, `tests/test_wechat_runtime.py`

**Dependencies:** T3, T5

**Steps:**

1. 复用现有 Provider、`SessionRuntime` 和 `SessionRepository`。
2. 首次消息创建并绑定 Session，后续消息恢复同一 Session。
3. 每轮结束关闭 Writer，不同好友使用不同 Session。

**Validation:** 运行 `pytest tests/test_wechat_runtime.py -q`，预期两名好友上下文隔离，重建 runtime 后各自恢复原 Session。

## T13：落实零工具 Agent 和任务超时

**Files:** `src/mewcode/wechat/runtime.py`, `tests/test_wechat_runtime.py`

**Dependencies:** T12

**Steps:**

1. 使用现有 `Agent` 和空 `Registry`，不注册任何系统或普通工具。
2. 不加载 MCP、Skills、Sub-agent、Hook、项目指令和长期记忆。
3. 只返回最终文字，并支持超时与取消事件。

**Validation:** 运行 `pytest tests/test_wechat_runtime.py -q`，断言发送给模型的工具定义为空，命令请求不会触发本地执行，超时和取消可结束当前任务。

## T14：实现白名单、去重和全局 FIFO

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`

**Dependencies:** T3, T4, T11, T13

**Steps:**

1. 在模型调用前执行私聊文字、精确白名单、重名和事件去重检查。
2. 把通过检查的事件放入唯一 `asyncio.Queue`。
3. 使用单消费者按入队顺序调用 runtime。

**Validation:** 运行 `pytest tests/test_wechat_bot.py -q`，预期非白名单和重复消息不调用模型，并发入站按 FIFO 顺序处理。

## T15：实现限定好友的 `/cancel`

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`

**Dependencies:** T14

**Steps:**

1. 在进入 Agent 前识别精确 `/cancel` 命令。
2. 只取消同一好友当前活动任务，不影响其他好友和机器人进程。
3. 无活动任务时返回简短状态，取消消息不写入 Agent 会话。

**Validation:** 运行 `pytest tests/test_wechat_bot.py -q`，预期跨好友取消无效，同好友取消后队列继续运行。

## T16：实现回复分段、安全发送和错误恢复

**Files:** `src/mewcode/wechat/bot.py`, `tests/test_wechat_bot.py`

**Dependencies:** T14, T15

**Steps:**

1. 忽略空回复，并按配置长度有序分段最终文本。
2. 每轮发送前复核原会话；复核失败时停止发送并记录错误。
3. 将模型失败、超时和单消息异常转换为一次简短提示，不终止消费者。
4. 日志默认不记录完整聊天正文、API Key 或完整系统提示。

**Validation:** 运行 `pytest tests/test_wechat_bot.py -q`，预期分段顺序正确、目标变化不发送、单条失败后下一条仍被处理。

## T17：实现启动、停止和独立 CLI

**Files:** `src/mewcode/wechat/bot.py`, `src/mewcode/wechat/cli.py`, `pyproject.toml`

**Dependencies:** T8, T9, T16

**Steps:**

1. 组装配置、状态库、UIA 驱动、runtime 和 bot。
2. 启动时检查 Windows、单个微信实例、4.1.12.55 必要控件和配置。
3. 建立基线后再开始监听；Ctrl+C 时按顺序停止观察、取消活动任务并关闭资源。
4. 注册 `mewcode-wechat` 命令和独立 `wechat` 可选依赖组。

**Validation:** 运行 `mewcode-wechat`，预期兼容环境进入监听；微信未启动或依赖缺失时输出一次明确错误并非零退出。

## T18：补充使用文档和完整验证

**Files:** `README.md`, `tests/test_wechat_*.py`

**Dependencies:** T17

**Steps:**

1. 记录可选依赖安装、MewCode 自有 `wechat` 配置、运行命令和 V1 安全边界。
2. 记录只读探测、专用普通好友收发和两个授权测试联系人的人工验收步骤。
3. 运行微信专项测试、现有全量测试、编译和项目已有的 lint/format 检查。
4. 在专用普通好友完成文字闭环后，再用明确授权联系人验证隔离、FIFO 和取消。

**Validation:** 所有自动化检查通过；人工检查确认不回复启动前历史消息、不会发送给错误会话，且原有 TUI 可完成一次对话。

## Execution Order

```text
T1
├─ T2 -> T3
├─ T4 -> T5
└─ T6 -> T7 -> T8
          └─ T9 -> T10 -> T11

T3 + T5 -> T12 -> T13
T3 + T4 + T11 + T13 -> T14 -> T15 -> T16
T8 + T9 + T16 -> T17 -> T18
```

## Scope Guard

- 不创建通用 Channel 接口或第二套 Agent 循环。
- 不实现群聊、媒体、主动发送、管理 UI、部署或多账号。
- 不读取 fake-wx-account 配置，不复制其 4.1.9.30 选择器和节拍。
- 不自动向真实好友发送测试消息；所有真实联系人测试必须明确授权。
- `task.md` 批准后只生成 `checklist.md`，四份文档全部批准前不写实现代码。
