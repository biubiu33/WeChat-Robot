# 子 Agent 与后台任务 Tasks

## File List

| Action | File | Responsibility |
|---|---|---|
| Create | `src/mewcode/subagent/__init__.py` | 导出子 Agent 公共接口。 |
| Create | `src/mewcode/subagent/model.py` | 角色、请求、状态、用量与任务数据模型。 |
| Create | `src/mewcode/subagent/catalog.py` | 角色 frontmatter 解析、发现、优先级与诊断。 |
| Create | `src/mewcode/subagent/policy.py` | 工具能力过滤与嵌套阻断。 |
| Create | `src/mewcode/subagent/cache.py` | 独立文件读缓存。 |
| Create | `src/mewcode/subagent/runtime.py` | 子运行时工厂、Fork 历史与宿主。 |
| Create | `src/mewcode/subagent/task.py` | 后台任务与通知管理。 |
| Create | `src/mewcode/subagent/tool.py` | `Agent` 与四个任务管理工具。 |
| Create | `src/mewcode/subagent/builtin/*.md` | 三个内置角色定义。 |
| Modify | `src/mewcode/agent/__init__.py` | 共享 ReAct 驱动与 RunToCompletion。 |
| Modify | `src/mewcode/permission/__init__.py` | 子 Agent 权限模式导出。 |
| Modify | `src/mewcode/permission/engine.py` | 子 Engine 授权快照与永久授权桥接。 |
| Modify | `src/mewcode/tool/__init__.py` | 允许 Registry 的受限作用域包装。 |
| Modify | `src/mewcode/config.py` | 后台功能开关。 |
| Modify | `src/mewcode/cli.py` | 角色目录、后台服务与依赖装配。 |
| Modify | `src/mewcode/tui/app.py` | 子任务宿主、审批、ESC 与关闭清理。 |
| Modify | `src/mewcode/tui/stream.py` | 角色目录、通知 reminder 与用量接入。 |
| Modify | `src/mewcode/tui/view.py` | 子 Agent 批准来源显示。 |
| Modify | `src/mewcode/skill/fork.py` | 基于公共子 Agent 底座的 Skill fork 适配。 |
| Modify | `src/mewcode/skill/tool.py` | 子 Agent 中只允许 inline Skill。 |
| Modify | `pyproject.toml` | 打包内置角色资源。 |
| Modify | `README.md` | 用户配置、角色、任务和边界说明。 |
| Create/Modify | `tests/test_subagent_*.py` | 子系统单元和集成测试。 |
| Modify | `tests/test_agent.py`、`test_permission.py`、`test_skill_fork.py`、`test_tui.py`、`test_config.py` | 现有模块回归与端到端覆盖。 |

## T1: 建立子 Agent 数据模型与角色目录

**Files:** `src/mewcode/subagent/model.py`, `src/mewcode/subagent/catalog.py`, `src/mewcode/subagent/__init__.py`, `tests/test_subagent_catalog.py`

**Dependencies:** None

**Steps:**

1. 定义角色来源、权限模式、角色定义、调用请求、用量和任务状态模型。
2. 解析 Markdown frontmatter，校验所需/可选字段、类型、范围、未知字段和小写 kebab-case 名称。
3. 加载内置、用户、项目和空插件来源；按优先级覆盖并收集可恢复诊断。
4. 提供大小写不敏感解析与仅含名称/说明的动态提示目录。
5. 覆盖有效定义、来源覆盖、同层重复、无效用户/项目文件、无效内置文件和模型/权限/轮次边界。

**Validation:** `python -m pytest -q tests/test_subagent_catalog.py`

## T2: 添加内置角色、后台配置与资源打包

**Files:** `src/mewcode/subagent/builtin/general-purpose.md`, `src/mewcode/subagent/builtin/explore.md`, `src/mewcode/subagent/builtin/plan.md`, `src/mewcode/config.py`, `pyproject.toml`, `tests/test_subagent_catalog.py`, `tests/test_config.py`

**Dependencies:** T1

**Steps:**

1. 添加三个内置角色及其模型、权限、工具范围和最大轮次。
2. 让配置接受默认开启的 `enable_subagent_background` 布尔开关，并拒绝非布尔值。
3. 配置构建系统包含内置 Markdown 资源。
4. 断言内置定义可通过资源加载，后台开关缺省/显式/非法值符合约定。

**Validation:** `python -m pytest -q tests/test_subagent_catalog.py tests/test_config.py`

## T3: 实现工具能力作用域与文件读缓存

**Files:** `src/mewcode/subagent/policy.py`, `src/mewcode/subagent/cache.py`, `src/mewcode/tool/__init__.py`, `tests/test_subagent_policy.py`, `tests/test_subagent_cache.py`, `tests/test_tool.py`

**Dependencies:** T1

**Steps:**

1. 定义全局子 Agent 禁止工具、后台白名单和角色白黑名单的合并算法。
2. 实现包装共享 Registry 的 `ScopedRegistry`，确保系统工具不能绕过最终作用域。
3. 在作用域执行层实现基于规范路径、修改时间和大小的读缓存；成功写入/编辑后失效当前缓存。
4. 覆盖角色收窄、后台收窄、控制面工具不可见、重复读取命中、外部修改失效、写入/编辑失效、错误不缓存和父子缓存不共享。

**Validation:** `python -m pytest -q tests/test_subagent_policy.py tests/test_subagent_cache.py tests/test_tool.py`

## T4: 扩展权限引擎的子会话语义

**Files:** `src/mewcode/permission/__init__.py`, `src/mewcode/permission/engine.py`, `src/mewcode/permission/persist.py`, `tests/test_permission.py`

**Dependencies:** T1

**Steps:**

1. 增加子 Agent 专用 `dontAsk` 兜底，并保留黑名单、沙箱和显式 deny 的优先级。
2. 添加从父 Engine 创建子 Engine 的能力：快照 session 允许规则、新建子 session 状态、共享永久本地规则。
3. 让子 Agent 的 Allow Forever 同时更新共享永久规则和本地配置；Allow Session 只改变子 Engine。
4. 覆盖父授权创建时可见、之后不同步、子会话允许隔离、永久允许跨边界、dontAsk 自动放行未匹配规则及硬拒绝不可绕过。

**Validation:** `python -m pytest -q tests/test_permission.py`

## T5: 提取共享 ReAct 驱动并新增 RunToCompletion

**Files:** `src/mewcode/agent/__init__.py`, `tests/test_agent.py`

**Dependencies:** T3, T4

**Steps:**

1. 将现有循环重构为可由普通 `run` 与子任务复用的内部驱动，保持原事件协议和 25 轮默认行为。
2. 增加最大轮次、稳定系统提示、一次性 reminder、审批转发和用量观察扩展点。
3. 实现 `run_to_completion`：追加任务、复用同一工具/Hook/权限路径、在无工具时返回最后文本、达到上限时返回最后文本及错误状态。
4. 覆盖普通循环不回归、定义轮次上限、最后文本、取消、工具执行、Hook 分派和用量回调。

**Validation:** `python -m pytest -q tests/test_agent.py`

## T6: 构造隔离运行时与安全 Fork 历史

**Files:** `src/mewcode/subagent/runtime.py`, `tests/test_subagent_runtime.py`, `tests/test_conversation.py`

**Dependencies:** T1, T3, T4, T5

**Steps:**

1. 实现定义式、Fork 式和 Skill 兼容路径的统一运行时工厂。
2. 为定义式应用角色正文与空对话；为 Fork 深拷贝父历史、补齐未完成工具调用并追加 Fork Boilerplate 和任务。
3. 创建独立对话、Engine、Hook 状态、缓存与用量观察器；连接共享 Provider、HookEngine 和基础 Registry。
4. 接入审批桥：子 Agent Ask 事件推送到宿主队列，原 Future 在主 TUI 响应后继续。
5. 覆盖无父历史污染、Fork 合法消息、boilerplate 位置、权限快照、独立 Hook/缓存/用量、模型档案选择和不可用档案错误。

**Validation:** `python -m pytest -q tests/test_subagent_runtime.py tests/test_conversation.py`

## T7: 实现后台任务管理与通知队列

**Files:** `src/mewcode/subagent/task.py`, `tests/test_subagent_task.py`

**Dependencies:** T6

**Steps:**

1. 实现任务创建、运行、状态转移、异常捕获、取消、ID/名称索引和进程内保留。
2. 实现可转交的前台运行句柄，使超时和 ESC 继续同一协程而非重启任务。
3. 实现终态一次性通知、任务详情、列表、停止和仅对 completed 任务可用的续派。
4. 覆盖显式后台、Fork 强制后台、120 秒接管、手动接管、成功/失败/取消通知、同名覆盖、旧 ID 可查、续派与后台关闭分支。

**Validation:** `python -m pytest -q tests/test_subagent_task.py`

## T8: 实现 Agent 与任务管理工具

**Files:** `src/mewcode/subagent/tool.py`, `tests/test_subagent_tool.py`

**Dependencies:** T6, T7

**Steps:**

1. 实现固定 JSON Schema 的 `Agent` 工具及 `TaskList`、`TaskGet`、`TaskStop`、`SendMessage`。
2. 校验必填参数、可选参数类型、角色解析、模型档案、Fork 强制后台、角色默认后台和全局后台开关。
3. 前台调用等待最终文本或接管摘要；后台调用立即返回任务 ID 与状态。
4. 以结构化错误覆盖未知角色、缺失模型、禁用 Fork、无任务、无可续派名称和嵌套拒绝。
5. 断言工具均为主 Agent 系统工具且不进入子 Agent 作用域。

**Validation:** `python -m pytest -q tests/test_subagent_tool.py`

## T9: 组装 CLI、TUI 宿主和 Provider 档案解析

**Files:** `src/mewcode/cli.py`, `src/mewcode/tui/app.py`, `src/mewcode/tui/stream.py`, `src/mewcode/tui/view.py`, `tests/test_tui.py`, `tests/test_config.py`

**Dependencies:** T2, T7, T8

**Steps:**

1. 在启动装配角色目录、任务管理器、子 Agent 宿主和五个工具，并在退出时取消后台子任务及关闭子 Hook 状态。
2. 将角色名称/说明加入主 Agent 动态环境；将一次性任务通知加入下一次请求的 reminder。
3. 按 Provider 配置名称解析 `haiku`、`sonnet`、`opus` 等档案，复用/缓存客户端；`inherit` 保持父 Provider。
4. 将子 Agent 审批转发到带来源标识的 UI；执行阶段 ESC 接管后台，审批阶段 ESC 拒绝本次。
5. 覆盖稳定工具列表、通知不写入可见历史、模型档案解析、审批桥和两类 ESC 行为。

**Validation:** `python -m pytest -q tests/test_tui.py tests/test_config.py`

## T10: 迁移 Skill fork 并限制子 Agent Skill 行为

**Files:** `src/mewcode/skill/fork.py`, `src/mewcode/skill/tool.py`, `src/mewcode/skill/__init__.py`, `tests/test_skill_fork.py`, `tests/test_skill_tool.py`

**Dependencies:** T6, T8, T9

**Steps:**

1. 让 Skill fork 通过 SubAgentHost 的公共构造和 RunToCompletion 路径运行，再保留既有摘要/Slash 回流行为。
2. 向子 Agent 注入受限的 Skill 执行器：inline 仍可激活，fork 返回 `nested_agent_denied`。
3. 覆盖旧 fork 的隔离与取消、摘要回流、共享底座调用、inline 可用和 fork 嵌套拒绝。

**Validation:** `python -m pytest -q tests/test_skill_fork.py tests/test_skill_tool.py`

## T11: 更新文档与端到端回归

**Files:** `README.md`, `tests/test_subagent_runtime.py`, `tests/test_subagent_task.py`, `tests/test_agent.py`, `tests/test_permission.py`, `tests/test_skill_fork.py`, `tests/test_tui.py`

**Dependencies:** T9, T10

**Steps:**

1. 记录 Agent 工具参数、角色文件来源和格式、模型档案、后台开关、任务工具、通知可见性、权限升级和范围外事项。
2. 添加端到端测试：主 Agent 选择角色并得到前台结果；Fork 进入后台，完成后下一请求接收通知并可通过 TaskGet 查询；权限 Ask 被主 TUI 批准后子任务继续。
3. 运行子系统定向测试、全量测试和静态检查，修复仅由本功能引入的失败。

**Validation:**

```text
python -m pytest -q tests/test_subagent_catalog.py tests/test_subagent_policy.py tests/test_subagent_cache.py tests/test_subagent_runtime.py tests/test_subagent_task.py tests/test_subagent_tool.py
python -m pytest -q
python -m ruff check src tests
```

## Execution Order

```text
T1 -> T2
T1 -> T3 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11
T1 -> T4 -> T5
```
