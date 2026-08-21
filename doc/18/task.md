# 微信 4.1.9.30 UIA 兼容 Tasks

状态：已批准

## File List

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/mewcode/wechat/uia_client.py` | 双版本门禁、进程路径读取和未激活 UIA 外壳诊断 |
| Modify | `src/mewcode/wechat/cli.py` | `--probe` 双版本帮助文本 |
| Modify | `tests/test_wechat_uia_driver.py` | 双版本和讲述人提示回归测试 |
| Modify | `README.md` | 双版本兼容及讲述人前置说明 |
| Modify | `doc/18/spec.md` | 保留批准状态并用于验收追踪 |
| Modify | `doc/18/plan.md` | 保留批准技术设计 |
| Create | `doc/18/task.md` | 本任务拆分 |
| Create | `doc/18/checklist.md` | 后续验收设计 |

## T1: Extend the exact version gate

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`
**Dependencies:** None

**Steps:**
1. 将单版本常量替换为按 `4.0.5.15`、`4.1.9.30` 排序的版本元组。
2. 将客户端测试注入参数改为版本元组，并保持默认值为正式支持集合。
3. 将版本相等判断改为集合成员判断。
4. 让不支持版本错误稳定列出两个支持版本及实际版本。
5. 参数化现有窗口测试，验证两个版本均通过且同一 HWND 只读取一次版本。
6. 更新不支持版本测试的期望错误。

**Validation:**

```powershell
python -m pytest tests/test_wechat_uia_driver.py -q -k "main_window"
```

预期两个支持版本通过，其他版本被拒绝，句柄缓存断言保持通过。

## T2: Diagnose an inactive Weixin UIA shell

**Files:** `src/mewcode/wechat/uia_client.py`, `tests/test_wechat_uia_driver.py`
**Dependencies:** T1

**Steps:**
1. 从现有版本读取逻辑中提取只读的进程可执行文件路径查询。
2. 增加 Qt 顶层窗口外壳判断：类名匹配 `Qt*QWindowIcon` 且进程文件名为 `Weixin.exe`。
3. 在没有 `mmui::MainWindow`、但存在微信 Qt 外壳时立即抛出讲述人和微信重启提示。
4. 保留无微信窗口和多个可用主窗口的现有数量错误。
5. 使用假 UIA 控件验证微信外壳触发讲述人提示。
6. 验证其他 Qt 应用不会触发微信讲述人提示。

**Validation:**

```powershell
python -m pytest tests/test_wechat_uia_driver.py -q -k "main_window or narrator or shell"
```

预期未激活微信外壳快速失败，普通 Qt 窗口仍走原有数量错误。

## T3: Update CLI and user guidance

**Files:** `src/mewcode/wechat/cli.py`, `README.md`
**Dependencies:** T1, T2

**Steps:**
1. CLI 改用双版本常量生成 `--probe` 帮助文本。
2. README 把唯一兼容版本说明改为精确支持两个版本。
3. 说明 `4.1.9.30` 需要先启动 Windows 讲述人，再完全退出并重启微信。
4. 说明程序只检查 UIA 状态，不会自动操作讲述人、重启微信或修改微信进程。
5. 更新只读探测成功条件为实际版本属于支持集合且三个必要控件均存在。
6. 保留 README 中当前未提交的其他用户修改，不重排无关段落。

**Validation:**

```powershell
python -m mewcode.wechat.cli --help
```

预期帮助文本同时包含 `4.0.5.15` 和 `4.1.9.30`；README 包含讲述人操作顺序和非自动操作边界。

## T4: Run focused and full automated validation

**Files:** `src/mewcode/wechat/uia_client.py`, `src/mewcode/wechat/cli.py`, `tests/test_wechat_uia_driver.py`, `README.md`
**Dependencies:** T1, T2, T3

**Steps:**
1. 运行 UIA 驱动定向测试。
2. 编译本次修改的 Python 模块。
3. 对本次修改的 Python 文件运行 Ruff 检查和格式检查。
4. 运行全量测试，确认微信机器人及现有 TUI 行为无回归。
5. 检查 diff，确认没有新增依赖或自动控制讲述人、重启微信、写微信进程的代码。

**Validation:**

```powershell
python -m pytest tests/test_wechat_uia_driver.py -q
python -m compileall src/mewcode/wechat/uia_client.py src/mewcode/wechat/cli.py
python -m ruff check src/mewcode/wechat/uia_client.py src/mewcode/wechat/cli.py tests/test_wechat_uia_driver.py
python -m ruff format --check src/mewcode/wechat/uia_client.py src/mewcode/wechat/cli.py tests/test_wechat_uia_driver.py
python -m pytest -q
git diff --check
```

预期所有命令通过；若全仓存在与本次无关的既有失败，记录具体基线并确认定向验证通过。

## T5: Verify the real 4.1.9.30 client read-only

**Files:** None
**Dependencies:** T4

**Steps:**
1. 保持讲述人已激活且微信 `4.1.9.30` 主界面已登录。
2. 执行正式 `mewcode-wechat --probe`。
3. 确认输出实际版本 `4.1.9.30`。
4. 确认唯一输出会话列表、消息列表和聊天输入区域的必要控件信息。
5. 确认探测过程中没有发送消息或改变当前会话。

**Validation:** 记录只读 probe 的退出码和脱敏结构输出；成功退出且三个必要控件各出现一次。

## Execution Order

```text
T1 -> T2 -> T3 -> T4 -> T5
```
