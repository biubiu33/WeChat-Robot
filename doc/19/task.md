# 微信提示词文件化与原始回复日志 Tasks

状态：已批准

## File List

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/mewcode/wechat/prompts/role.md` | 唯一微信角色设定 |
| Create | `src/mewcode/wechat/prompts/reply_policy.md` | 唯一气泡与专业回复协议 |
| Modify | `src/mewcode/wechat/config.py` | 删除可配置角色字段并忽略旧键 |
| Modify | `src/mewcode/wechat/runtime.py` | 缓存加载提示词、组合系统提示、打印原始最终回复 |
| Modify | `tests/test_wechat_config.py` | 配置结构和旧键忽略测试 |
| Modify | `tests/test_wechat_runtime.py` | 提示词资源、日志顺序、错误与切分测试 |
| Modify | `tests/test_wechat_bot.py` | 适配删除后的配置数据结构 |
| Modify | `tests/test_wechat_info_registry.py` | 适配配置结构并验证提示词拼接顺序 |
| Modify | `README.md` | 删除角色配置示例并说明提示词文件与控制台隐私 |
| Modify | `doc/19/spec.md` | 保留批准需求 |
| Modify | `doc/19/plan.md` | 保留批准设计 |
| Create | `doc/19/task.md` | 实施任务拆分 |
| Create | `doc/19/checklist.md` | 验收设计与结果 |

## T1: Create the two prompt resources

**Files:** `src/mewcode/wechat/prompts/role.md`, `src/mewcode/wechat/prompts/reply_policy.md`
**Dependencies:** None

**Steps:**

1. 将当前年轻朋友型角色完整迁移到 `role.md`。
2. 将当前回复协议迁移到 `reply_policy.md`，直接写入 `<|bubble|>` 字面量。
3. 强化闲聊约束：多句、多问题、多语义点必须使用唯一分隔标记，换行和标点不算气泡边界。
4. 保留单一短回应、专业正文、Markdown 清理、工具状态和身份安全规则。
5. 检查两个文件均为 UTF-8、非空，且没有实现说明或配置占位符。

**Validation:**

```powershell
rg -n "<\|bubble\|>|换行|专业|AI" src/mewcode/wechat/prompts
```

预期角色文件包含身份与边界，协议文件包含严格分隔规则和示例。

## T2: Load prompts and remove configurable persona

**Files:** `src/mewcode/wechat/config.py`, `src/mewcode/wechat/runtime.py`, `tests/test_wechat_config.py`, `tests/test_wechat_runtime.py`
**Dependencies:** T1

**Steps:**

1. 从 `WechatConfig` 和配置解析结果移除 `system_prompt`，保持旧键静默忽略。
2. 使用标准库包资源接口读取两个 Markdown 文件，并以进程缓存包装。
3. 对读取失败和空内容抛出包含文件名的 `ConfigError`。
4. 在运行时构造阶段加载并保存角色与协议。
5. 让稳定系统提示按角色、回复协议、可选信息工具策略顺序拼接。
6. 更新配置与运行时测试，验证旧配置不能覆盖角色、加载顺序和文件错误。

**Validation:**

```powershell
python -m pytest tests/test_wechat_config.py tests/test_wechat_runtime.py -q -k "prompt or system or config"
```

预期所有相关测试通过，运行时系统提示只来自两个资源文件和可选信息策略。

## T3: Print every raw final model reply

**Files:** `src/mewcode/wechat/runtime.py`, `tests/test_wechat_runtime.py`
**Dependencies:** T2

**Steps:**

1. 在成功检查之后、任何 `strip`、来源净化和回复整形之前输出固定开始标签。
2. 原样输出 `completion.text`，随后输出固定结束标签并刷新控制台。
3. 用包含 `<|bubble|>` 和多行文本的测试验证原始字符可见。
4. 验证最终 `WechatReply` 仍只按显式标记切分。
5. 验证取消、超时和错误路径不打印成功原始回复标签。

**Validation:**

```powershell
python -m pytest tests/test_wechat_runtime.py -q -k "raw or bubble or cancel or timeout"
```

预期成功回复完整打印，错误路径无伪造日志，现有切分行为不变。

## T4: Update docs and verify packaging/regressions

**Files:** `README.md`, package build output, all modified files
**Dependencies:** T1, T2, T3

**Steps:**

1. 从 README 微信配置示例和说明中删除 `system_prompt`。
2. 说明 `role.md`、`reply_policy.md` 的职责以及原始回复会打印本地聊天内容。
3. 编译修改模块并对修改范围运行 Ruff 与格式检查。
4. 构建 wheel，检查归档中包含两个提示词文件。
5. 运行微信专项测试和全量自动化测试。
6. 检查依赖文件、UIA 逻辑和用户其他未提交改动未被覆盖。

**Validation:**

```powershell
python -m compileall src/mewcode/wechat/config.py src/mewcode/wechat/runtime.py
python -m ruff check src/mewcode/wechat/config.py src/mewcode/wechat/runtime.py tests/test_wechat_config.py tests/test_wechat_runtime.py
python -m ruff format --check src/mewcode/wechat/config.py src/mewcode/wechat/runtime.py tests/test_wechat_config.py tests/test_wechat_runtime.py
python -m pytest tests/test_wechat_config.py tests/test_wechat_runtime.py tests/test_wechat_bot.py tests/test_wechat_uia_driver.py -q
python -m pytest -q
```

预期修改范围静态检查通过、全量测试无新增失败，wheel 同时包含 `role.md` 和 `reply_policy.md`。

## Execution Order

```text
T1 -> T2 -> T3 -> T4
```
