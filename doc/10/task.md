# Skill 系统任务拆分

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/skill/__init__.py` | Skill 子系统公共导出 |
| 新建 | `src/mewcode/skill/model.py` | 不可变模型、来源、模式和异常 |
| 新建 | `src/mewcode/skill/catalog.py` | frontmatter 解析、三级发现、优先级与热更新 |
| 新建 | `src/mewcode/skill/runtime.py` | 激活状态、动态提示词、工具策略、模型选择 |
| 新建 | `src/mewcode/skill/tool.py` | `load_skill`、`install_skill` 系统工具 |
| 新建 | `src/mewcode/skill/install.py` | HTTPS/ZIP 安全安装 |
| 新建 | `src/mewcode/skill/fork.py` | 隔离 Agent、取消和摘要回流 |
| 新建 | `src/mewcode/skill/builtin/*/SKILL.md` | `commit`、`review`、`test` 内置目录型样板 |
| 修改 | `src/mewcode/tool/__init__.py` | 系统工具标记与白名单过滤 |
| 修改 | `src/mewcode/agent/__init__.py` | 动态 Provider、工具和环境供应器 |
| 修改 | `src/mewcode/context/controller.py` | 动态环境计入上下文预算 |
| 修改 | `src/mewcode/prompt/modules.py` | 有效 Skill 名称和说明模块 |
| 修改 | `src/mewcode/prompt/__init__.py` | 扩展稳定提示词构造接口 |
| 修改 | `src/mewcode/command/model.py` | Skill 命令控制接口与快照 |
| 修改 | `src/mewcode/command/registry.py` | 动态命令安全卸载与替换 |
| 修改 | `src/mewcode/command/builtin.py` | `/skill` 与动态 `/<name>` 命令 |
| 修改 | `src/mewcode/command/__init__.py` | 新增命令 API 导出 |
| 修改 | `src/mewcode/tui/app.py` | Skill 生命周期、热更新和 fork 会话状态 |
| 修改 | `src/mewcode/tui/command.py` | Skill 控制实现、主历史写入 |
| 修改 | `src/mewcode/tui/stream.py` | Agent 动态供应器接线 |
| 修改 | `src/mewcode/cli.py` | 启动发现、校验、系统工具和动态命令注册 |
| 修改 | `pyproject.toml` | 内置 Markdown 资源打包 |
| 修改 | `README.md` | Skill 位置、格式、命令与安装说明 |
| 新建 | `tests/test_skill_catalog.py` | 格式、发现、优先级、诊断和热更新 |
| 新建 | `tests/test_skill_runtime.py` | 激活、参数、环境、白名单、模型冲突 |
| 新建 | `tests/test_skill_tool.py` | 系统工具、白名单与模式边界 |
| 新建 | `tests/test_skill_install.py` | ZIP/URL 来源和安装安全 |
| 新建 | `tests/test_skill_fork.py` | 隔离、取消、摘要回流 |
| 修改 | `tests/test_tool.py` | 系统工具和过滤注册表回归 |
| 修改 | `tests/test_agent.py` | 两阶段加载后的动态请求回归 |
| 修改 | `tests/test_prompt.py` | 仅注入名称说明的启动提示词回归 |
| 修改 | `tests/test_command.py` | `/skill` 与动态命令注册回归 |
| 修改 | `tests/test_tui.py` | clear、热更新和两种运行模式回归 |
| 修改 | `tests/test_tui_command.py` | TUI Skill 控制与主历史边界 |

## T1：建立 Skill 模型和 frontmatter 解析

**文件：** `src/mewcode/skill/__init__.py`、`src/mewcode/skill/model.py`、`src/mewcode/skill/catalog.py`、`tests/test_skill_catalog.py`

**依赖：** 无

**步骤：**

1. 定义 Skill 来源、执行模式、元数据、入口对象和可诊断异常。
2. 实现单个入口的 YAML frontmatter 读取、必填字段校验、名称规范校验与非空正文校验。
3. 实现 `{{args}}` 的字面替换，不解析表达式或外部文件。
4. 覆盖单文件、目录入口、缺少字段、错误 YAML、非法名称、错误模式、非 `none` 历史设置、空正文和参数替换。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_skill_catalog.py -k "parse or frontmatter or parameter"`

## T2：实现三级发现、优先级和可恢复诊断

**文件：** `src/mewcode/skill/catalog.py`、`tests/test_skill_catalog.py`

**依赖：** T1

**步骤：**

1. 扫描项目、用户和内置三层位置的一层 Markdown 文件及一层目录型 `SKILL.md` 入口。
2. 按内置、用户、项目顺序合并，保证高优先级同名覆盖低优先级定义。
3. 将单个入口解析失败记录为含路径与原因的诊断，不中断有效 Skill 目录构建。
4. 记录位置快照并实现变化检测；覆盖目录删除、正文修改、新增和同层重复名称。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_skill_catalog.py -k "discover or precedence or diagnostic or refresh"`

## T3：实现运行时激活、提示词和策略

**文件：** `src/mewcode/skill/runtime.py`、`src/mewcode/skill/__init__.py`、`tests/test_skill_runtime.py`

**依赖：** T1、T2

**步骤：**

1. 实现 inline 激活、fork 临时准备和活动状态清空。
2. 渲染“仅名称和说明”的可用 Skill 摘要，以及按激活顺序排列的完整动态环境 SOP。
3. 实现多个 inline Skill 的普通工具白名单并集与无活动 Skill 的全量工具策略。
4. 实现指定模型选择及冲突检测，并覆盖刷新后重渲染活动 Skill、删除活动 Skill 的行为。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_skill_runtime.py`

## T4：扩展工具注册表以支持系统工具和白名单

**文件：** `src/mewcode/tool/__init__.py`、`tests/test_tool.py`、`tests/test_skill_tool.py`

**依赖：** T3

**步骤：**

1. 为工具协议提供向后兼容的系统工具标识，并实现普通工具与系统工具的查询。
2. 扩展全量和只读工具定义接口，使白名单始终保留系统工具。
3. 在执行入口重复校验白名单，拒绝未暴露的普通工具调用。
4. 覆盖无白名单、单一白名单、多个系统工具、计划模式、MCP 普通工具和伪造工具调用。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tool.py tests/test_skill_tool.py -k "system or allowed or whitelist or plan"`

## T5：改造 Agent 的动态请求供应器

**文件：** `src/mewcode/agent/__init__.py`、`src/mewcode/context/controller.py`、`tests/test_agent.py`

**依赖：** T3、T4

**步骤：**

1. 将稳定提示词、动态环境、工具策略和 Provider 改为每个 ReAct 迭代可重新获取的供应器，保持无 Skill 时的既有构造方式兼容。
2. 使 `load_skill` 在当前迭代执行完成后，下一次模型请求立即收到活动 SOP 和收窄后的工具定义。
3. 将动态环境字符数纳入上下文控制器预算与压缩请求判断。
4. 覆盖两阶段加载、模型覆盖、计划模式、白名单执行防线和现有工具循环回归。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_agent.py tests/test_context_budget.py`

## T6：接入 Skill 提示词模块

**文件：** `src/mewcode/prompt/modules.py`、`src/mewcode/prompt/__init__.py`、`tests/test_prompt.py`

**依赖：** T3

**步骤：**

1. 添加稳定的“可用 Skill”模块，只渲染生效名称和一句话说明。
2. 保持“已激活 Skill”稳定模块为空，确保完整 SOP 不进入稳定系统提示词。
3. 扩展提示词构造函数，保持既有项目指令和长期记忆调用兼容。
4. 覆盖不含 Skill 时的确定性、仅元信息注入和 SOP 不泄漏到启动提示词。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_prompt.py`

## T7：实现 LoadSkill 系统工具

**文件：** `src/mewcode/skill/tool.py`、`src/mewcode/skill/__init__.py`、`tests/test_skill_tool.py`

**依赖：** T3、T4、T5

**步骤：**

1. 实现 `load_skill` 的名称和参数 JSON schema、参数校验、未知 Skill 错误与 SOP 返回格式。
2. 对 inline Skill 调用运行时激活，保留可由下一 ReAct 迭代读取的状态。
3. 定义 fork 调用所需的执行器协议，先以测试替身验证工具将参数路由给隔离执行器并返回摘要。
4. 确保该工具作为系统只读工具不受 Skill 白名单影响，且不绕过其他权限规则。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_skill_tool.py -k load`

## T8：实现第三方 ZIP 安装器与 InstallSkill 工具

**文件：** `src/mewcode/skill/install.py`、`src/mewcode/skill/tool.py`、`tests/test_skill_install.py`、`tests/test_skill_tool.py`

**依赖：** T1、T2、T4、T7

**步骤：**

1. 实现本地 ZIP 和 HTTPS 下载来源识别，拒绝 HTTP、其他 URL 方案和非 ZIP 本地文件。
2. 使用临时位置下载/解压，拒绝绝对路径、路径穿越、符号链接和不符合目录型 Skill 入口结构的包。
3. 在原子安装前解析包并按当前普通工具注册表校验元数据；目标目录已存在时拒绝覆盖。
4. 让 `install_skill` 在成功后通知目录刷新；覆盖成功、本地非法包、HTTP、重定向降级、路径穿越、已有目标和脚本未执行。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_skill_install.py tests/test_skill_tool.py -k install`

## T9：实现隔离 fork 执行与摘要回流

**文件：** `src/mewcode/skill/fork.py`、`tests/test_skill_fork.py`

**依赖：** T3、T4、T5、T7

**步骤：**

1. 创建仅包含调用参数的隔离 `Conversation`，不创建归档写入器或上下文控制器。
2. 在隔离 Agent 中应用该 fork Skill 的 SOP、模型选择、工具白名单、既有权限模式和取消事件。
3. 通过无工具摘要请求生成短摘要，并实现 Provider 错误或空摘要时的脱敏截断后备结果。
4. 覆盖主历史完全未传递、隔离工具结果未回流、摘要回流、取消、指定模型和权限限制。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_skill_fork.py`

## T10：扩展命令模型和注册表以支持动态 Skill 命令

**文件：** `src/mewcode/command/model.py`、`src/mewcode/command/registry.py`、`src/mewcode/command/__init__.py`、`tests/test_command.py`

**依赖：** T2、T3

**步骤：**

1. 扩展命令控制协议，加入 Skill 列表、Skill 运行和目录刷新能力。
2. 增加规范名称卸载与原子动态命令替换，确保内置命令冲突不会静默覆盖。
3. 为每个生效 Skill 生成 `/<name>` UI 命令，参数为该 Skill 的唯一输入。
4. 覆盖命令注册、内置冲突、刷新替换、完成菜单可见性、大小写解析与未知命令回归。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py -k "skill or registry or completion"`

## T11：实现 `/skill` 和动态 Skill 命令行为

**文件：** `src/mewcode/command/builtin.py`、`src/mewcode/command/__init__.py`、`tests/test_command.py`

**依赖：** T3、T9

**步骤：**

1. 注册本地 `/skill`，输出有效 Skill 的名称、说明、来源、活动状态和有限诊断摘要，不输出 SOP。
2. 将动态 `/<name>` 命令统一委托给控制协议，inline 与 fork 均不把原始 Slash 文本写入主历史。
3. 验证 `/help` 和补全菜单同时包含 `/skill` 与动态命令，并保持现有命令的参数拒绝规则。
4. 覆盖无 Skill、多个来源、多个活动 Skill、诊断显示和动态命令调用。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py -k skill`

## T12：接入 CLI 启动、内置样板和资源打包

**文件：** `src/mewcode/cli.py`、`src/mewcode/skill/builtin/commit/SKILL.md`、`src/mewcode/skill/builtin/review/SKILL.md`、`src/mewcode/skill/builtin/test/SKILL.md`、`pyproject.toml`、`tests/test_skill_catalog.py`

**依赖：** T2、T4、T7、T8、T10、T11

**步骤：**

1. 在 MCP 工具注册完成后发现 Skill、校验所有生效白名单、注册系统工具和动态命令，再构造 TUI。
2. 对启动白名单校验失败输出包含 Skill 名称和不存在工具名的错误，并在进入 TUI 前退出。
3. 创建三个符合本章格式的内置目录型 Skill，分别覆盖提交、审查和测试工作流。
4. 配置 wheel 包含内置 Markdown 资源，并验证资源目录可由 `importlib.resources` 发现。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_skill_catalog.py tests/test_skill_tool.py tests/test_config.py`

## T13：在 TUI 中接入 Skill 生命周期与两种执行模式

**文件：** `src/mewcode/tui/app.py`、`src/mewcode/tui/command.py`、`src/mewcode/tui/stream.py`、`tests/test_tui.py`、`tests/test_tui_command.py`

**依赖：** T5、T6、T9、T10、T11、T12

**步骤：**

1. 将 SkillRuntime、动态命令注册器和 Provider 配置映射注入 App，连通 Agent 的四类动态供应器。
2. 在菜单刷新、新用户回合和安装成功后检查 Skill 热更新；刷新失败时保留上一份有效目录/命令集合并显示 notice。
3. inline 命令激活后以参数启动主对话回合；fork 命令进入可取消隔离状态，随后把调用事件和摘要写入主可见/持久化历史。
4. 在 `/clear`、Provider 切换、会话恢复和退出时清空活动 inline Skill；保持既有会话、取消、审批和状态栏行为。
5. 覆盖 inline 主历史、fork 无内部污染、clear 清空、热更新补全、取消、恢复会话不恢复活动 Skill 和既有 Slash 命令回归。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tui.py tests/test_tui_command.py tests/test_tui_resume.py`

## T14：更新用户文档

**文件：** `README.md`

**依赖：** T12、T13

**步骤：**

1. 说明三层 Skill 位置、单文件和目录型入口规则及同名优先级。
2. 提供包含完整 frontmatter 与 `{{args}}` 的格式示例，说明 `inline` 与不带主历史的 `fork`。
3. 说明 Agent 自动发现/`load_skill` 两阶段加载、`/skill`、`/<name>`、工具白名单和热更新。
4. 说明 HTTPS/本地 ZIP 安装边界、安全限制和三个内置样板；明确市场与版本管理不在本期范围。

**验证：** `rg -n "Skill|SKILL.md|load_skill|/skill|fork|HTTPS|commit" README.md`

## T15：完成跨模块验收场景与兼容回归

**文件：** `tests/test_skill_catalog.py`、`tests/test_skill_runtime.py`、`tests/test_skill_tool.py`、`tests/test_skill_install.py`、`tests/test_skill_fork.py`、`tests/test_agent.py`、`tests/test_prompt.py`、`tests/test_command.py`、`tests/test_tui.py`、`tests/test_tui_command.py`

**依赖：** T1-T14

**步骤：**

1. 覆盖端到端 inline 场景：启动只见 Skill 名称说明 -> Agent 调用 `load_skill` -> 下一 ReAct 请求含 SOP 且工具收窄 -> `/clear` 后消失。
2. 覆盖端到端 fork 场景：`/<name> 参数` -> 隔离 Agent 仅收到参数 -> 主对话仅记录调用与摘要 -> 后续主对话仍可正常运行。
3. 覆盖安装场景：本地 ZIP 安全安装 -> 动态命令刷新 -> `/skill` 可见新 Skill；同时验证 HTTP/路径穿越失败。
4. 运行全部受影响既有测试，修复本章引入的兼容性问题，不处理无关历史技术债。

**验证：**

```powershell
conda run -n mewcode python -m pytest -q tests/test_skill_catalog.py tests/test_skill_runtime.py tests/test_skill_tool.py tests/test_skill_install.py tests/test_skill_fork.py
conda run -n mewcode python -m pytest -q tests/test_agent.py tests/test_tool.py tests/test_prompt.py tests/test_command.py tests/test_tui.py tests/test_tui_command.py tests/test_tui_resume.py
```

## T16：执行完整质量验证

**文件：** 本章涉及的全部文件

**依赖：** T15

**步骤：**

1. 运行全量测试，记录通过、跳过和失败结果，并仅修复本章造成的问题。
2. 运行编译检查，确认新增模块、Markdown 资源引用和测试导入没有语法或导入错误。
3. 运行 Ruff 检查和格式检查，按项目现有规则修正代码与测试。
4. 逐项执行批准的 `checklist.md` 并记录验收证据。

**验证：**

```powershell
conda run -n mewcode python -m pytest -q
conda run -n mewcode python -m compileall -q src tests
conda run -n mewcode ruff check .
conda run -n mewcode ruff format --check .
```

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T7 -> T8 -> T12
T3 -> T6
T3 + T4 + T5 + T7 -> T9
T2 + T3 -> T10 -> T11
T5 + T6 + T9 + T10 + T11 + T12 -> T13 -> T14
T1-T14 -> T15 -> T16
```
