# 微信 4.0.5.15 单版本兼容 Tasks

状态：已批准（第二次修订）

## File List

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/mewcode/wechat/uia_client.py` | 切换唯一兼容版本并适配会话项与无 ID 搜索结果 |
| Modify | `src/mewcode/wechat/bot.py` | 输出可诊断的 UIA 观察错误原因 |
| Modify | `src/mewcode/wechat/cli.py` | 让探测帮助文本复用版本常量 |
| Modify | `tests/test_wechat_uia_driver.py` | 覆盖版本门禁、会话解析和安全搜索切换 |
| Modify | `tests/test_wechat_bot.py` | 覆盖观察错误日志 |
| Modify | `README.md` | 更新安装、探测和兼容性说明 |
| Modify | `.mewcode/config.yaml.example` | 更新示例配置版本说明 |
| Create | `doc/17/checklist.md` | 记录可执行验收项 |

## T1：切换运行时版本门禁

**Files:** `src/mewcode/wechat/uia_client.py`、`src/mewcode/wechat/cli.py`

**Dependencies:** None

**Steps:**

1. 将唯一支持版本改为 4.0.5.15。
2. 在 CLI 中复用该版本常量生成 `--probe` 帮助文本。
3. 不改变窗口发现、控件定位和发送逻辑。

**Validation:** 运行 CLI 帮助并确认只显示 4.0.5.15。

## T2：补充版本门禁回归测试

**File:** `tests/test_wechat_uia_driver.py`

**Dependencies:** T1

**Steps:**

1. 使用内存假 UIA 根节点和主窗口调用现有窗口发现路径。
2. 验证 4.0.5.15 被接受并缓存已验证窗口句柄。
3. 验证其他版本被拒绝，错误文本包含唯一支持版本和实际版本。

**Validation:** `python -m pytest -q tests/test_wechat_uia_driver.py`

## T3：适配 4.0.5.15 会话项

**Files:** `src/mewcode/wechat/uia_client.py`、`tests/test_wechat_uia_driver.py`

**Dependencies:** T1

**Steps:**

1. 从“`联系人 N条未读 预览 时间`”格式中提取联系人名和未读数。
2. 保持无未读会话不会产生事件。
3. 会话切换不再要求 `session_item_<联系人>`，直接进入已有的精确搜索、唯一结果和切换后标题复核流程。
4. 添加真实观测格式和通用 `session_item` 的内存回归测试。

**Validation:** `python -m pytest -q tests/test_wechat_uia_driver.py`

## T4：适配无 ID 搜索结果

**Files:** `src/mewcode/wechat/uia_client.py`、`tests/test_wechat_uia_driver.py`

**Dependencies:** T3

**Steps:**

1. 搜索结果不再要求联系人专属 AutomationId。
2. 只接受结果控件类型正确且显示名精确相等的项目。
3. 精确结果必须唯一；零结果和多结果继续安全失败。
4. 保留搜索焦点、搜索值和切换后聊天标题复核。
5. 添加无 ID 成功、零结果和多结果拒绝测试。

**Validation:** `python -m pytest -q tests/test_wechat_uia_driver.py`

## T5：记录具体观察错误

**Files:** `src/mewcode/wechat/bot.py`、`tests/test_wechat_bot.py`

**Dependencies:** T4

**Steps:**

1. UIA 观察失败日志同时记录异常类型和受控错误文本。
2. 保持单次异常隔离、两秒等待和后续重试行为不变。
3. 添加日志包含具体搜索失败原因的回归测试。

**Validation:** `python -m pytest -q tests/test_wechat_bot.py`

## T6：同步用户文档

**Files:** `README.md`、`.mewcode/config.yaml.example`

**Dependencies:** T1、T3、T4

**Steps:**

1. 将面向用户的兼容版本、探测说明和特殊会话说明更新为 4.0.5.15。
2. 更新示例配置注释。
3. 保留 `doc/13` 的历史设计记录不变。

**Validation:** 搜索面向用户的运行文件，确认不再声明支持 4.1.12.55。

## T7：执行回归和真实 UIA 验收

**Files:** None

**Dependencies:** T2、T3、T4、T5、T6

**Steps:**

1. 运行全部微信专项自动化测试。
2. 运行受影响文件的静态检查。
3. 在当前 4.0.5.15 客户端执行 `--probe`，不发送消息。
4. 验证精确搜索能切换到普通好友聊天页。
5. 验证输入框焦点、临时草稿写入、目标复核和清空，不按发送 Enter。
6. 按 `checklist.md` 记录实际证据。

**Validation:** 专项测试和静态检查通过；真实探测成功，或明确记录当前页面缺失的必要控件。

## Execution Order

```text
T1 -> T2
  \-> T3 -> T4 -> T5
T4 -> T6
T2 + T5 + T6 -> T7
```
