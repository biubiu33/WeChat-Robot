# 微信群聊 @ 触发与按成员批处理 Tasks

状态：已完成

> 2026-08-21 缺陷修复：补充群会话行/群搜索结果点击切换、已选中目标仍先激活窗口及对应回归测试。

## File List

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `pyproject.toml` | 微信可选依赖增加本机群昵称 OCR 运行时 |
| Modify | `.mewcode/config.yaml.example` | 增加测试群与机器人名称示例 |
| Modify | `README.md` | 群聊配置、限制、OCR 隐私和 @ 降级说明 |
| Modify | `src/mewcode/wechat/config.py` | 解析 `allowed_groups`、`self_names` 与交叉校验 |
| Modify | `src/mewcode/wechat/models.py` | 群标志、消息坐标、按成员批次和上下文快照 |
| Create | `src/mewcode/wechat/group_sender_ocr.py` | 群昵称 OCR 与保守几何匹配 |
| Modify | `src/mewcode/wechat/uia_client.py` | 群类型、消息读取、列表边界、真正 @ 和文本降级 |
| Modify | `src/mewcode/wechat/uia_driver.py` | 群启动基线、稳定消息、OCR 与 @ 事件 |
| Modify | `src/mewcode/wechat/bot.py` | 群上下文、按成员 7 秒窗口、不取消与首气泡 @ |
| Modify | `src/mewcode/wechat/runtime.py` | 群输入格式、临时 Session 和环境文案 |
| Modify | `src/mewcode/wechat/prompts/reply_policy.md` | 群参考记录的信任边界与回复要求 |
| Modify | `src/mewcode/wechat/cli.py` | 注入群配置并在监听前预热 OCR |
| Modify | `tests/test_wechat_config.py` | 群配置验证 |
| Modify | `tests/test_wechat_uia_driver.py` | 群控件读取、目标校验、发送降级、基线、群事件、@ 与去重测试 |
| Modify | `tests/test_wechat_bot.py` | 交叉成员窗口、上下文和取消语义测试 |
| Modify | `tests/test_wechat_runtime.py` | 群模型输入、临时 Session 和日志回归 |
| Create | `tests/test_wechat_group_sender_ocr.py` | OCR 几何匹配与 fail-closed 测试 |
| Create | `doc/20/spec.md` | 已确认需求 |
| Create | `doc/20/plan.md` | 技术设计 |
| Create | `doc/20/task.md` | 实施任务拆分 |
| Create | `doc/20/checklist.md` | 验收设计与执行记录 |

## T1: Extend configuration and data models

**Files:** `src/mewcode/wechat/config.py`, `src/mewcode/wechat/models.py`, `tests/test_wechat_config.py`, related test fixtures
**Dependencies:** None

**Steps:**

1. 增加 `allowed_groups` 与 `self_names`，复用统一的非空、去重字符串列表解析。
2. 将启用校验改为私聊或群聊至少一个白名单非空；群聊要求机器人名称。
3. 拒绝私聊/群聊白名单交集，保留未知旧配置键的现有兼容行为。
4. 扩展会话、消息、事件、待处理批次和队列快照的数据字段。
5. 更新所有测试构造器，先保证现有私聊测试语义不变。

**Validation:**

```powershell
python -m pytest tests/test_wechat_config.py tests/test_wechat_bot.py tests/test_wechat_uia_driver.py -q
```

## T2: Add conservative group sender OCR

**Files:** `pyproject.toml`, `src/mewcode/wechat/group_sender_ocr.py`, `tests/test_wechat_group_sender_ocr.py`
**Dependencies:** T1

**Steps:**

1. 在 `wechat` 可选依赖中加入 RapidOCR、兼容 Python 3.12+ 的 ONNX Runtime、Pillow 与 NumPy。
2. 定义标准化 OCR 行和纯几何匹配函数。
3. 实现 UIA 正文到 OCR 正文的唯一匹配、方向判断和气泡上方昵称选择。
4. 实现内存截图、相同图像摘要缓存和线程锁，不写截图文件。
5. 实现引擎可用性检查与预热；缺失依赖给出明确异常。
6. 用固定 OCR 行测试高置信成功、正文不匹配、多个昵称、低置信、出站消息和未知发送者。

**Validation:**

```powershell
python -m pytest tests/test_wechat_group_sender_ocr.py -q
python -m ruff check src/mewcode/wechat/group_sender_ocr.py tests/test_wechat_group_sender_ocr.py
```

## T3: Generalize UIA reading and establish group baseline

**Files:** `src/mewcode/wechat/uia_client.py`, `src/mewcode/wechat/uia_driver.py`, `tests/test_wechat_uia_driver.py`
**Dependencies:** T1, T2

**Steps:**

1. 泛化会话列表读取并解析 @ 自己标记，不改变双版本主窗口发现和讲述人错误提示。
2. 增加当前会话类型读取、期望类型目标验证和唯一搜索结果检查。
3. 读取群文字气泡的 UIA 正文、runtime id、边界及消息列表边界。
4. 在群路径调用 OCR 补齐方向和发送者；未知结果 fail closed。
5. 为配置中的会话主动建立启动基线，旧消息不产生事件或上下文。
6. 维护每会话已见消息和快照，只对启动后新文字产生一次事件。
7. 实现 Unicode 规范化的精确 @ 检测与机器人 @ 清理。
8. 验证非白名单、类型不符、同名搜索、正文无 @ 和附件均不触发；同时验证活动群无会话行标记但新气泡精确 @ 时仍触发。

**Validation:**

```powershell
python -m pytest tests/test_wechat_uia_driver.py -q
```

## T4: Implement per-sender batching and rolling context

**Files:** `src/mewcode/wechat/bot.py`, `src/mewcode/wechat/models.py`, `tests/test_wechat_bot.py`
**Dependencies:** T3

**Steps:**

1. 私聊继续按会话键提交并维持现有取消行为。
2. 为每个群创建 `deque(maxlen=20)`，追加所有启动后可信文字事件。
3. 群普通消息只更新上下文；合格 @ 事件按 `(精确群名, 发送者)` 创建 7 秒窗口。
4. 同一成员新 @ 只重置自己的 timer，不影响其他成员。
5. 窗口到期冻结群上下文并按到期顺序进入现有 FIFO。
6. 群新事件不取消活动回答；私聊取消回归保持通过。
7. 覆盖张三/李四交叉消息、不 @ 消息排除、第 21 条淘汰、重复事件和关闭时 timer 清理。

**Validation:**

```powershell
python -m pytest tests/test_wechat_bot.py -q
```

## T5: Compose group model input without old sessions

**Files:** `src/mewcode/wechat/runtime.py`, `src/mewcode/wechat/prompts/reply_policy.md`, `tests/test_wechat_runtime.py`
**Dependencies:** T4

**Steps:**

1. 让运行时接收私聊或群批次元数据，私聊接口与行为保持兼容。
2. 按固定标签组装带发送者的 20 条参考记录和当前成员批次。
3. 群调用使用临时 SessionRuntime，不绑定或恢复启动前群 Session；私聊继续持久化。
4. 环境文案正确区分微信私聊/群聊，保持现有只读工具权限。
5. 在回复协议中声明群历史为不可信参考数据，发送层负责 @。
6. 验证机器人 @ 被移除、其他 @ 保留、不同成员不混合、原始最终回复仍恰好打印一次。

**Validation:**

```powershell
python -m pytest tests/test_wechat_runtime.py -q
```

## T6: Send the first bubble with a real mention and safe fallback

**Files:** `src/mewcode/wechat/uia_client.py`, `src/mewcode/wechat/uia_driver.py`, `src/mewcode/wechat/bot.py`, `tests/test_wechat_uia_driver.py`, `tests/test_wechat_bot.py`
**Dependencies:** T3, T4, T5

**Steps:**

1. 增加只用于群第一气泡的发送接口。
2. 通过键盘 `@` 触发成员菜单，按窗口归属、可见名称和唯一精确匹配选择成员。
3. 选择成功后追加正文并复用目标与发送结果验证。
4. 菜单未出现、超时、无匹配或多匹配时清理本次草稿并文本降级。
5. 降级日志只包含群名、发送者和原因，不包含消息正文。
6. 确保后续气泡和来源消息调用普通发送路径，不重复 @。
7. 测试真实 @ 成功、四类降级、草稿清理失败时安全拒绝、第一气泡唯一发送和目标变化。

**Validation:**

```powershell
python -m pytest tests/test_wechat_uia_driver.py tests/test_wechat_bot.py -q
```

## T7: Wire CLI, docs and full regression validation

**Files:** `src/mewcode/wechat/cli.py`, `.mewcode/config.yaml.example`, `README.md`, all modified files
**Dependencies:** T1-T6

**Steps:**

1. CLI 把两个白名单与 self names 注入驱动，并只在群聊启用时构造、预热 OCR。
2. 示例写入 `测试群聊` 和 `biubiubiu仿生人`，README 说明配置与严格触发条件。
3. 文档说明 OCR 只识别发送者、截图不持久化、同名成员与可视区域限制、真实 @ 文本降级。
4. 运行编译、Ruff、格式、微信专项和全量测试。
5. 构建 wheel，确认 OCR 模块、提示词和可选依赖元数据正确。
6. 运行 `git diff --check` 并确认没有覆盖用户已有提示词与日志改动。

**Validation:**

```powershell
python -m compileall src/mewcode/wechat
python -m ruff check src/mewcode/wechat tests/test_wechat_*.py
python -m ruff format --check src/mewcode/wechat tests/test_wechat_*.py
python -m pytest tests/test_wechat_config.py tests/test_wechat_group_sender_ocr.py tests/test_wechat_uia_driver.py tests/test_wechat_bot.py tests/test_wechat_runtime.py -q
python -m pytest -q
python -m build
git diff --check
```

## Execution Order

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7
```

实施必须在四份 `doc/20` 文档全部批准后开始。若真实微信探测显示两个支持版本的群成员菜单无法用当前安全条件唯一识别，应停止 T6、更新设计并重新请求批准，不得改用坐标盲点。
