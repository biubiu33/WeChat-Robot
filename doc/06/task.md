# 权限系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/permission/__init__.py` | 导出权限模块的公共类型和工厂函数。 |
| 新建 | `src/mewcode/permission/blacklist.py` | 内置 Unix 与 Windows 高危命令黑名单。 |
| 新建 | `src/mewcode/permission/sandbox.py` | 项目目录路径沙箱与符号链接防逃逸。 |
| 新建 | `src/mewcode/permission/rule.py` | 规则解析、规则集和精确/glob 匹配。 |
| 新建 | `src/mewcode/permission/settings.py` | 三层 YAML 配置读取、工具分类和目标参数解析。 |
| 新建 | `src/mewcode/permission/persist.py` | 会话级规则写入与永久本地规则持久化。 |
| 新建 | `src/mewcode/permission/engine.py` | 前四层权限流水线、模式矩阵与引擎构造。 |
| 修改 | `src/mewcode/agent/__init__.py` | 接入权限判定、批准事件与四种人工决策。 |
| 修改 | `src/mewcode/tui/app.py` | 权限模式状态、批准态按键和取消分派。 |
| 修改 | `src/mewcode/tui/stream.py` | 消费批准事件并协调 Agent 恢复。 |
| 修改 | `src/mewcode/tui/view.py` | 状态栏权限模式与四项批准块渲染。 |
| 修改 | `src/mewcode/cli.py` | 以启动目录构造并注入权限引擎。 |
| 修改 | `examples/smoke.py` | 使用启动目录引擎并以 bypass 模式非交互运行。 |
| 修改 | `.gitignore` | 忽略本地永久规则文件。 |
| 新建 | `.mewcode/settings.yaml.example` | 权限配置格式示例。 |
| 新建 | `tests/test_permission.py` | 权限模块单元测试。 |
| 修改 | `tests/test_agent.py` | Agent 的 Allow/Deny/Ask、会话/永久放行和回归测试。 |
| 修改 | `tests/test_tui.py` | TUI 模式切换、批准菜单、取消和状态栏测试。 |

## T1: 建立权限公共模型

**文件：** `src/mewcode/permission/__init__.py`、`src/mewcode/permission/rule.py`

**依赖：** 无

**步骤：**
1. 定义四档 `Mode`、三态 `Decision`、三类 `Category` 与四项 `Outcome`，提供模式文本转换和安全回退解析。
2. 定义 `Rule`、`RuleSet`，实现友好工具名规则的解析、同层 deny 优先以及命令/路径的精确和 glob 匹配。
3. 在包入口导出后续模块将共享的公共类型与接口。

**验证：** 添加规则与模式单测；运行 `python -m pytest tests/test_permission.py -q`，规则优先级与匹配断言通过。

## T2: 实现配置读取与调用参数归类

**文件：** `src/mewcode/permission/settings.py`

**依赖：** T1

**步骤：**
1. 定义 `Settings` 与权限规则配置结构，按 UTF-8 读取 YAML 的 `default_mode`、`permissions.allow`、`permissions.deny`。
2. 实现用户级、项目级、本地级配置路径的无异常读取与非法内容降级为安全空规则集。
3. 为六个内置工具实现友好名映射、只读/写文件/命令执行分类，并安全提取 JSON 调用中的命令或文件目标。

**验证：** 单测覆盖缺失文件、非法 YAML、错误字段类型、`default_mode` 优先级输入和参数解析失败。

## T3: 实现命令黑名单与路径沙箱

**文件：** `src/mewcode/permission/blacklist.py`、`src/mewcode/permission/sandbox.py`

**依赖：** T1

**步骤：**
1. 定义不可配置的大小写不敏感高危命令正则，覆盖 Unix shell 和 Windows PowerShell/CMD 的已确认危险模式。
2. 实现项目根解析、目标存在时的符号链接解析，以及目标不存在时最近已存在祖先的解析。
3. 使用规范化后的路径进行根目录包含关系判断，支持项目内新文件和多级未创建父目录。

**验证：** 单测覆盖 Unix/Windows 黑名单、项目外绝对/相对路径、符号链接逃逸、项目内新路径与根目录自身。

## T4: 组装权限引擎与规则持久化

**文件：** `src/mewcode/permission/engine.py`、`src/mewcode/permission/persist.py`、`src/mewcode/permission/__init__.py`

**依赖：** T1、T2、T3

**步骤：**
1. 构造 `Engine`，加载 `~/.mewcode/settings.yaml`、`<root>/.mewcode/settings.yaml`、`<root>/.mewcode/settings.local.yaml`，确定 `default_mode`。
2. 按黑名单、沙箱、会话/本地/项目/用户规则、模式兜底的顺序实现短路裁决与统一原因文本。
3. 实现精确会话 allow 规则的内存写入，以及精确永久 allow 规则的本地 YAML 写入与内存同步。
4. 确保配置读写失败不会使权限检查崩溃或放宽安全默认。

**验证：** 单测覆盖完整模式矩阵、四层规则优先级、短路顺序、配置降级、会话规则重建引擎后失效、永久规则重建引擎后仍生效。

## T5: 在 Agent 工具编排中接入权限判定

**文件：** `src/mewcode/agent/__init__.py`

**依赖：** T4

**步骤：**
1. 将 `Mode` 迁移为 permission 模块类型，并让 `Agent` 接收 `Engine`。
2. 在每个工具实际执行前调用引擎；Deny 生成带调用 ID 的结构化工具错误并回灌，Allow 保持原执行路径。
3. 保留只读批并发：批内逐项检查后只并发可执行项，且按原调用顺序发送开始、结束事件和结果。
4. 为 Ask 增加包含 `asyncio.Future` 的批准事件；串行副作用工具等待四项人工决策，分别执行一次、写入会话规则后执行、写入本地规则后执行或回灌拒绝。
5. 保留计划模式硬限制、取消语义、未知工具停止条件和历史角色交替合法性。

**验证：** 扩展 `tests/test_agent.py`，覆盖 Allow/Deny/Ask、会话/永久决策、被拒与执行混合保序、只读并发、批准等待取消与原有 Agent 回归用例。

## T6: 实现批准态和权限模式交互

**文件：** `src/mewcode/tui/app.py`、`src/mewcode/tui/stream.py`

**依赖：** T5

**步骤：**
1. 向 `SessionState` 增加 `APPROVING`，将引擎和当前权限模式保存到 `MewCodeApp`，初始值为 `engine.default_mode`。
2. 消费 Agent 批准事件时保存待批准请求、切换批准态并暂停后续流消费；用户选择后完成 Future 并恢复流式状态。
3. 实现四项菜单的上/下、Enter、数字键 1-4，以及允许本次、拒绝本次快捷键。
4. 扩展 Esc/Ctrl+C：批准态时先完成待批准 Future 再设置现有取消事件，确保本轮退出但程序不退出。
5. 增加仅空闲态生效的 Shift+Tab 循环：default、acceptEdits、plan、bypassPermissions；保留 `/plan` 和 `/do` 的既有语义，且 `/do` 固定回 default。

**验证：** 扩展 `tests/test_tui.py`，模拟键盘事件验证四种选择、批准态取消、Shift+Tab 循环与跨轮模式保持。

## T7: 更新权限相关 TUI 视图

**文件：** `src/mewcode/tui/view.py`

**依赖：** T6

**步骤：**
1. 让状态栏左侧常驻显示当前权限模式，保留右侧模型名和 token 用量。
2. 实现工具名、参数安全预览、请求原因和四项菜单的多行批准块，当前选择项明确高亮。
3. 使用现有时间线通知组件展示模式变更，不引入新的日志组件。

**验证：** 视图单测断言模式文本、批准菜单四项、当前项标记和参数不泄漏写入内容。

## T8: 装配 CLI、非交互示例与配置样例

**文件：** `src/mewcode/cli.py`、`examples/smoke.py`、`.gitignore`、`.mewcode/settings.yaml.example`

**依赖：** T4、T5、T6

**步骤：**
1. 在 CLI 以 `Path.cwd()` 作为唯一项目根构造引擎，报告可恢复的引擎降级信息并继续启动 TUI。
2. 给 `MewCodeApp` 注入引擎；给 smoke 示例创建同一根目录的引擎并使用 `Mode.BYPASS`，避免非交互等待批准。
3. 忽略 `.mewcode/settings.local.yaml`，提供只含 `default_mode`、allow、deny 的 UTF-8 YAML 示例。

**验证：** 运行 `python examples/smoke.py --help`；检查配置样例可被 YAML 解析，且 `.gitignore` 覆盖本地规则文件。

## T9: 完成权限模块覆盖测试

**文件：** `tests/test_permission.py`

**依赖：** T1、T2、T3、T4

**步骤：**
1. 为黑名单、沙箱、规则解析和 glob、友好名路由、参数失败安全默认建立独立单测。
2. 为配置路径、层级优先级、同层 deny 优先、模式矩阵、会话规则和永久规则建立临时目录集成测试。
3. 覆盖 Unix 与 Windows 命令模式，但不执行任何高危命令。

**验证：** 运行 `python -m pytest tests/test_permission.py -q`，全部通过。

## T10: 执行回归、格式和验收验证

**文件：** 全部本章修改文件

**依赖：** T5、T6、T7、T8、T9

**步骤：**
1. 运行并修复全部单元测试和现有回归测试。
2. 运行 Python 编译检查、Ruff 格式检查与静态检查（若环境提供）。
3. 根据 `checklist.md` 逐项执行黑名单、沙箱、规则、批准、取消、模式切换和跨协议边界的验收。

**验证：** `python -m compileall src examples`、`python -m pytest -q`、`ruff format --check .`、`ruff check .` 均通过；若 `mypy` 已安装，再运行 `mypy src`。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10
```
