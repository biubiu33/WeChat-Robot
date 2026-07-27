# Hook 生命周期挂钩系统 Tasks

## File List

| Action | File | Responsibility |
|---|---|---|
| Create | `src/mewcode/hook/__init__.py` | 导出 Hook 公共 API。 |
| Create | `src/mewcode/hook/model.py` | Hook、事件、条件、动作、会话状态和快照模型。 |
| Create | `src/mewcode/hook/config.py` | 两层 YAML 加载、解析、校验与诊断。 |
| Create | `src/mewcode/hook/actions.py` | shell、prompt、HTTP、subagent 动作执行。 |
| Create | `src/mewcode/hook/engine.py` | 条件筛选、分派、拦截、once、后台任务与提醒。 |
| Modify | `src/mewcode/permission/rule.py` | 四种共享匹配模式与兼容规则解析。 |
| Modify | `src/mewcode/permission/settings.py` | 无效权限规则 stderr 诊断。 |
| Modify | `src/mewcode/permission/__init__.py` | 导出新的匹配类型。 |
| Modify | `src/mewcode/session/runtime.py` | 保存每个会话的 HookSessionState。 |
| Modify | `src/mewcode/agent/__init__.py` | 请求、工具、停止、通知 Hook 接入。 |
| Modify | `src/mewcode/context/controller.py` | 自动/紧急/手动压缩观察回调。 |
| Modify | `src/mewcode/tui/app.py` | 会话、提交和压缩 Hook 生命周期接入。 |
| Modify | `src/mewcode/tui/stream.py` | 向 Agent 注入 Hook dispatcher 与 reminder。 |
| Modify | `src/mewcode/tui/command.py` | 提供 Hook 命令快照。 |
| Modify | `src/mewcode/command/model.py` | 扩展命令控制协议。 |
| Modify | `src/mewcode/command/builtin.py` | 注册 `/hooks`。 |
| Modify | `src/mewcode/cli.py` | 启动期加载并注入 HookEngine。 |
| Modify | `README.md` | Hook 配置、语义和命令文档。 |
| Create | `tests/test_hook_config.py` | 配置、来源、校验、冲突和条件测试。 |
| Create | `tests/test_hook_actions.py` | 四类动作、超时、失败和 HTTP 测试。 |
| Create | `tests/test_hook_engine.py` | 分派、拦截、提醒、once 和 async 测试。 |
| Modify | `tests/test_permission.py` | 匹配语法和旧配置兼容回归。 |
| Modify | `tests/test_agent.py` | 请求、工具、通知、停止 Hook 集成。 |
| Modify | `tests/test_tui.py` | 提交拦截与会话生命周期集成。 |
| Modify | `tests/test_tui_command.py` | `/hooks` TUI 路由。 |
| Modify | `tests/test_command.py` | `/hooks` 本地命令输出。 |
| Modify | `tests/test_context_artifact.py` | 三种压缩来源 Hook 回调。 |

## T1: 扩展权限匹配器

**Files:** `src/mewcode/permission/rule.py`, `src/mewcode/permission/__init__.py`, `tests/test_permission.py`

**Dependencies:** None

**Steps:**
1. 定义可缓存正则的结构化 Pattern，支持 exact、glob、regex 与递归 not。
2. 让 Rule 与 RuleSet 使用 Pattern，同时保留无 pattern 的全匹配和既有工具名匹配。
3. 扩展规则串解析以识别 `=`、`~`、`!` 前缀，并让旧 glob 写法保持原行为。
4. 覆盖精确、glob、正则、嵌套反向、空 path、非法语法和既有规则集优先级。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_permission.py`

## T2: 增加权限规则诊断

**Files:** `src/mewcode/permission/settings.py`, `tests/test_permission.py`

**Dependencies:** T1

**Steps:**
1. 保持 `settings.yaml` / `settings.local.yaml` 的现有加载路径和默认模式语义。
2. 让非法权限规则包含原始规则与原因写入 stderr，并跳过该条规则。
3. 验证合法相邻规则仍会进入 RuleSet，坏 YAML 与缺失文件仍按现有安全降级处理。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_permission.py -k "rule or settings"`

## T3: 建立 Hook 领域模型与会话状态

**Files:** `src/mewcode/hook/model.py`, `src/mewcode/hook/__init__.py`, `tests/test_hook_engine.py`

**Dependencies:** T1

**Steps:**
1. 定义 11 个 HookEvent、Action、Condition、ConditionGroup、Hook、HookContext、HookDispatch 和 HookSnapshot。
2. 定义 HookSessionState 的预留、已执行、reminder 和后台任务集合。
3. 实现稳定 payload JSON 序列化与点分字段读取，缺失路径返回空字符串。
4. 覆盖事件枚举、payload 字段访问、稳定排序和模型默认值。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_hook_engine.py -k model`

## T4: 实现 Hook YAML 读取与集中校验

**Files:** `src/mewcode/hook/config.py`, `src/mewcode/hook/__init__.py`, `tests/test_hook_config.py`

**Dependencies:** T1, T3

**Steps:**
1. 按项目级后用户级顺序读取两个 `hooks.yaml`，记录成功加载的来源。
2. 解析顶层 `hooks` 数组和 Hook 的必填、默认与动作专属字段。
3. 校验未知字段、重复 name、未知事件、条件组混用、非法 Pattern、超时、阻塞 async 与 prompt async。
4. 将每个错误写 stderr 并只跳过相应 Hook；缺失文件不输出错误，整体文件错误不阻断其他来源。
5. 覆盖来源合并、后加载重名跳过、所有主要配置错误和条件求值准备。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_hook_config.py`

## T5: 实现 shell、prompt 与 subagent 动作

**Files:** `src/mewcode/hook/actions.py`, `tests/test_hook_actions.py`

**Dependencies:** T3

**Steps:**
1. 用异步子进程运行 shell 命令，把稳定排序的 payload JSON 传至 stdin，并收集 stdout、stderr、返回码与超时。
2. 区分同步拦截事件的退出码 0、2 和其它失败结果，生成可供引擎消费的动作结果。
3. 实现 prompt 的原样 reminder 入队，不允许它表达拦截。
4. 实现 subagent 的固定占位日志与成功结果。
5. 使用跨平台 Python 子进程夹具覆盖放行、拒绝、失败、超时、stdin JSON 与固定日志。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_hook_actions.py -k "shell or prompt or subagent"`

## T6: 实现 HTTP 动作

**Files:** `src/mewcode/hook/actions.py`, `tests/test_hook_actions.py`

**Dependencies:** T3

**Steps:**
1. 用标准库在工作线程发起带 timeout 的 HTTP 请求，支持默认 JSON body、方法与 headers。
2. 对显式 body 执行限制性的 `str.format_map` 渲染，并将模板错误作为动作失败。
3. 对拦截事件仅解析 2xx JSON block 响应；其余响应、网络异常、超时和坏 JSON 均放行并返回失败诊断。
4. 以临时本地 HTTP server 覆盖请求体、block、放行、模板错误和网络失败。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_hook_actions.py -k http`

## T7: 实现 HookEngine 分派与执行控制

**Files:** `src/mewcode/hook/engine.py`, `tests/test_hook_engine.py`

**Dependencies:** T3, T4, T5, T6

**Steps:**
1. 按目录顺序筛选 event 与条件，串行运行同步 Hook，并在首个有效拦截后结束阻塞分派。
2. 实现 once 的“预留 -> 成功确认 -> 失败释放”流程，并支持异步任务完成时确认或释放。
3. 管理 async 后台任务、失败 stderr 格式、取消传播、会话关闭时的取消和收集。
4. 实现 reminder 的入队与一次性取走，并构造 `/hooks` 所需的按事件快照。
5. 覆盖 all/any、缺失字段、多个 prompt 顺序、同步拦截、失败放行、once 重试、异步不阻塞和取消。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_hook_engine.py`

## T8: 将 Hook 状态绑定到会话运行时

**Files:** `src/mewcode/session/runtime.py`, `tests/test_hook_engine.py`, `tests/test_session_repository.py`

**Dependencies:** T3, T7

**Steps:**
1. 为新建和恢复的 SessionRuntime 创建新的 HookSessionState，不写入 JSONL。
2. 在 Runtime 关闭路径保留供上层取消 Hook 后台任务的状态访问点。
3. 覆盖新会话、恢复会话和替换 Runtime 时 once/reminder 状态不会泄漏。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_hook_engine.py tests/test_session_repository.py`

## T9: 接入请求、提醒、停止与通知事件

**Files:** `src/mewcode/agent/__init__.py`, `tests/test_agent.py`

**Dependencies:** T3, T7, T8

**Steps:**
1. 为 Agent 增加可选 Hook dispatcher、会话状态与 reminder 供应接口，未注入时保持既有行为。
2. 在每次 Provider 请求前触发 PreUserMessage，并在 plan reminder 后拼接并清空 Hook reminders。
3. 在权限 Ask 前、流错误上报前触发 Notification，在自然 `done=True` 前触发 Stop。
4. 覆盖 reminder 顺序与一次性边界、Notification payload、自然完成 Stop、错误/取消不触发 Stop 和无 Hook 回归。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_agent.py -k "hook or reminder or stream_error or permission"`

## T10: 接入工具前后 Hook 与拒绝回灌

**Files:** `src/mewcode/agent/__init__.py`, `tests/test_agent.py`

**Dependencies:** T7, T9

**Steps:**
1. 在可执行工具的权限 check 前分派 PreToolUse，命中 block 时构造 `[hook <name>]` 错误 ToolResult 并跳过权限和真实执行。
2. 保留现有 ToolStart/ToolEnd 行为，并在所有结果（包括权限拒绝）结束事件前分派 PostToolUse。
3. 让只读并行批次先逐条完成 Hook/权限准入，再保留真实工具的并行执行。
4. 覆盖 shell/HTTP 拒绝、放行、权限拒绝后的 PostToolUse、并行只读工具与模型接收拒绝原因。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_agent.py -k "hook and tool"`

## T11: 接入自动、紧急与手动压缩 Hook

**Files:** `src/mewcode/context/controller.py`, `tests/test_context_artifact.py`, `tests/test_context_budget.py`

**Dependencies:** T3, T7

**Steps:**
1. 增加可选压缩观察回调，保持未配置 Hook 时 ContextController 的现有接口和行为。
2. 在每次实际压缩尝试前后发送 trigger、压缩前后估算 Token；手动路径标记 manual。
3. 先判断硬阈值并标记 emergency，再判断安全余量并标记 auto，保持同一摘要与熔断语义。
4. 覆盖 auto、emergency、manual 的 payload、失败/无需压缩边界及无观察者回归。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_context_artifact.py tests/test_context_budget.py`

## T12: 装配 HookEngine 并接入 TUI 会话与提交事件

**Files:** `src/mewcode/cli.py`, `src/mewcode/tui/app.py`, `src/mewcode/tui/stream.py`, `tests/test_tui.py`

**Dependencies:** T7, T8, T9, T10, T11

**Steps:**
1. 在 CLI 启动期一次性加载 HookEngine 并注入 App；配置诊断不阻断启动。
2. 在首次 Runtime 创建后触发 SessionStart；在普通非 Slash 提交写入 Conversation 前触发 UserPromptSubmit。
3. 对用户提交 block 保留输入、显示 `[hook <name>] <reason>`，且不写 timeline、档案或回合统计。
4. 为 Agent 和 ContextController 提供包含 session_id、cwd、mode 与事件特化字段的上下文工厂。
5. 覆盖 SessionStart 提醒进入首轮请求、用户提交拒绝、普通输入回归和 Hook 未配置路径。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_tui.py tests/test_agent.py -k "hook or session or submit"`

## T13: 接入会话结束与恢复生命周期

**Files:** `src/mewcode/tui/app.py`, `src/mewcode/tui/command.py`, `tests/test_tui.py`, `tests/test_tui_resume.py`

**Dependencies:** T7, T8, T12

**Steps:**
1. 在 `/clear`、`/resume` 切换和退出关闭旧 Runtime 前同步分派 SessionEnd。
2. 关闭旧会话时取消并收集其 Hook 后台任务，再关闭 archive writer。
3. 在恢复、重放和新 HookSessionState 就绪后触发 SessionResume；隔离 fork Skill 不接入主会话 Hook。
4. 覆盖清空/恢复后的 once 状态重置、SessionEnd/Resume 顺序、退出取消和既有恢复 UI 回归。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_tui.py tests/test_tui_resume.py`

## T14: 实现 `/hooks` 本地命令

**Files:** `src/mewcode/command/model.py`, `src/mewcode/command/builtin.py`, `src/mewcode/tui/command.py`, `tests/test_command.py`, `tests/test_tui_command.py`

**Dependencies:** T4, T7, T12

**Steps:**
1. 在命令控制协议中定义 HookSnapshot，并由 TuiCommandControl 返回引擎加载的 Hook 与来源。
2. 注册无参数、本地类型的 `/hooks`，按 event 分组输出名称、动作、once/async 标志及来源。
3. 对空快照输出精确的 `No hooks loaded.`，并遵循既有参数拒绝、帮助和补全机制。
4. 覆盖命令目录、帮助、空列表、分组输出、flags、来源、参数拒绝和 TUI 提交路由。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_command.py tests/test_tui_command.py -k hooks`

## T15: 补齐 Hook 跨模块验收测试

**Files:** `tests/test_hook_config.py`, `tests/test_hook_actions.py`, `tests/test_hook_engine.py`, `tests/test_agent.py`, `tests/test_tui.py`, `tests/test_context_artifact.py`

**Dependencies:** T1-T14

**Steps:**
1. 将 AC1-AC11 映射到精确单元或集成测试，补齐未覆盖的事件 payload 和 stderr 文本。
2. 用临时 YAML、FakeProvider、RecordingTool 和本地 HTTP server 复现 shell 拦截、prompt 注入、异步格式化、HTTP block 与 subagent 占位。
3. 验证 Hook 失败不破坏 Agent、权限、会话、上下文和命令的原有路径。
4. 在 Windows 可运行环境中避免依赖外部 shell 或网络服务，使用 Python 子进程和进程内 server。

**Validation:** `conda run -n mewcode python -m pytest -q tests/test_hook_config.py tests/test_hook_actions.py tests/test_hook_engine.py tests/test_agent.py tests/test_tui.py tests/test_tui_command.py tests/test_context_artifact.py`

## T16: 更新用户文档

**Files:** `README.md`

**Dependencies:** T4, T5, T6, T7, T14

**Steps:**
1. 说明两个 Hook 配置位置、启动期加载和错误降级边界。
2. 给出覆盖条件、shell 拦截、prompt 与 HTTP 的 UTF-8 YAML 示例。
3. 列出 11 个事件、四种动作、only_once/async/timeout 约束、stdin JSON 与 `/hooks` 行为。
4. 明确 subagent 占位、无热更新、无持久 once 与无 `$...` 变量替换等范围外能力。

**Validation:** `rg -n "Hook|hooks.yaml|PreToolUse|only_once|/hooks|subagent" README.md`

## T17: 执行完整质量验证与验收清单

**Files:** 本章涉及的全部文件

**Dependencies:** T15, T16

**Steps:**
1. 运行 Hook 定向测试并修复本章引入的失败。
2. 运行全量测试、源码/测试编译、Ruff 静态检查和格式检查。
3. 按批准的 `checklist.md` 逐项记录实际命令输出与端到端结果。

**Validation:**

```powershell
conda run -n mewcode python -m pytest -q
conda run -n mewcode python -m compileall -q src tests
conda run -n mewcode ruff check .
conda run -n mewcode ruff format --check .
```

## Execution Order

```text
T1 -> T2
T1 -> T3 -> T4
T3 -> T5 -> T7
T3 -> T6 -> T7
T7 -> T8 -> T9 -> T10
T7 -> T11
T8 + T9 + T10 + T11 -> T12 -> T13
T4 + T7 + T12 -> T14
T1-T14 -> T15 -> T16 -> T17
```
