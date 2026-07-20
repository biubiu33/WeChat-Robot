# Slash 命令注册与分发系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/command/__init__.py` | 命令域公共导出。 |
| 新建 | `src/mewcode/command/model.py` | 命令元数据、输入类型、查询快照与控制协议。 |
| 新建 | `src/mewcode/command/registry.py` | 注册、冲突校验、名称解析和补全候选。 |
| 新建 | `src/mewcode/command/dispatcher.py` | 输入解析与命令分发。 |
| 新建 | `src/mewcode/command/builtin.py` | 十二个内置命令及默认注册表。 |
| 新建 | `src/mewcode/tui/command.py` | Textual 命令控制适配器。 |
| 新建 | `src/mewcode/tui/completion.py` | 输入框下方的内联命令菜单。 |
| 新建 | `tests/test_command.py` | 命令域单元测试。 |
| 新建 | `tests/test_tui_command.py` | TUI 命令、补全和会话统计集成测试。 |
| 修改 | `src/mewcode/memory/store.py` | 提取项目层与用户层索引引用文件名。 |
| 修改 | `src/mewcode/memory/update.py` | 向 TUI 暴露记忆索引文件快照。 |
| 修改 | `src/mewcode/session/archive.py` | 定义会话统计和 usage JSONL 事件。 |
| 修改 | `src/mewcode/session/repository.py` | 恢复时汇总 Token 与用户回合。 |
| 修改 | `src/mewcode/session/__init__.py` | 导出会话统计类型。 |
| 修改 | `src/mewcode/tui/app.py` | 输入分流、统一回合入口、统计恢复、清理和补全组装。 |
| 修改 | `src/mewcode/tui/stream.py` | usage 累计、持久化与状态刷新。 |
| 修改 | `src/mewcode/tui/timeline.py` | 清空可见时间线。 |
| 修改 | `src/mewcode/tui/view.py` | 命令输出项与方括号模式标记。 |
| 修改 | `src/mewcode/cli.py` | 启动期构造并注入命令注册表。 |
| 修改 | `tests/test_memory_store.py` | 记忆索引引用快照测试。 |
| 修改 | `tests/test_session_archive.py` | usage 事件序列化测试。 |
| 修改 | `tests/test_session_repository.py` | Token 与回合恢复测试。 |
| 修改 | `tests/test_tui.py` | 既有命令、状态栏和普通对话回归。 |
| 修改 | `tests/test_tui_resume.py` | 恢复统计与 Chapter 08 行为回归。 |
| 修改 | `README.md` | 十二个命令、别名、补全与统计说明。 |

`README.md` 与 `HANDOVER.md` 是进入本章前已有的用户工作区改动。实现时保留这些内容；仅在 `README.md` 相关章节增量补充命令系统说明，不重写 `HANDOVER.md`。

## T1: 建立命令模型和控制协议

**文件：** `src/mewcode/command/model.py`、`src/mewcode/command/__init__.py`、`tests/test_command.py`

**依赖：** 无

**步骤：**

1. 定义 `CommandKind`、`InputKind`、`Command`、`ParsedInput` 和异步 handler 类型。
2. 定义 `StatusSnapshot`、`MemorySnapshot`、`SessionSnapshot`，其中记忆快照提供合计条目数。
3. 定义 `CommandControl` 与 `CommandContext`，只依赖标准库和现有 `Mode`，不导入 Textual。
4. 在包入口导出公共类型，并用最小 fake handler 验证元数据不可变、快照计数和协议可实现。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py -k model`

## T2: 实现命令注册、冲突校验和补全匹配

**文件：** `src/mewcode/command/registry.py`、`src/mewcode/command/__init__.py`、`tests/test_command.py`

**依赖：** T1

**步骤：**

1. 用规范名称和别名共用的大小写不敏感占用索引实现 `register()` 与 `resolve()`。
2. 拒绝空名称、空别名、同命令重复别名、规范名称冲突、别名冲突和名称/别名交叉冲突；错误包含冲突键和命令来源。
3. 实现按规范名称排序的公开命令列表，隐藏命令不返回。
4. 实现规范名称与别名前缀匹配，按规范名称去重、排序返回补全候选。
5. 覆盖大小写解析、冲突矩阵、隐藏过滤、别名匹配和 `/c` 同时命中 `clear`/`compact` 的边界。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py -k registry`

## T3: 实现输入解析和统一分发

**文件：** `src/mewcode/command/dispatcher.py`、`src/mewcode/command/__init__.py`、`tests/test_command.py`

**依赖：** T1、T2

**步骤：**

1. 实现空输入、普通消息和 Slash 命令三路解析；命令名使用第一个空格分隔并转小写，参数清理首尾空白。
2. 实现 `CommandDispatcher`，未知命令通过 `show_message()` 输出错误与 `/help` 引导，绝不回退为普通消息。
3. 对没有 `argument_hint` 的命令统一拒绝非空参数并显示用法；合法调用创建含同一注册表的 `CommandContext`。
4. 覆盖空白、大小写、`/`、未知命令、多余参数、普通消息和 handler 调用参数。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py -k "parser or dispatcher"`

## T4: 实现帮助和纯本地内置命令

**文件：** `src/mewcode/command/builtin.py`、`tests/test_command.py`

**依赖：** T1-T3

**步骤：**

1. 定义 `/help`、`/status`、`/memory`、`/permission`、`/session` 的元数据、用法和纯本地处理函数。
2. `/help` 从 `CommandContext.registry` 渲染字典序两列总表；单条详情支持规范名称或别名，并验证只能有一个查询参数。
3. `/status` 严格输出六项快照信息；`/permission` 复用相同模式字符串；`/session` 处理无会话状态。
4. `/memory` 分项目层与用户层列出文件名，空层显示“无”，不输出正文。
5. 使用纯内存 fake control 覆盖输出、空状态、帮助别名、两列顺序、敏感正文不泄漏和不调用 Agent 能力。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py -k local`

## T5: 实现界面类、提示词类命令和默认注册表

**文件：** `src/mewcode/command/builtin.py`、`src/mewcode/command/__init__.py`、`tests/test_command.py`

**依赖：** T4

**步骤：**

1. 定义 `/exit`、`/plan`、`/do`、`/compact`、`/resume`、`/clear`、`/review` 的元数据和处理函数。
2. `/plan` 设置 `Mode.PLAN` 后刷新状态并显示 notice；`/do` 严格按“默认模式 -> 刷新 -> 既有执行指令”顺序调用控制协议。
3. `/review` 只发送批准的固定提示词；其余界面命令只委托对应控制能力。
4. 构造默认注册表，注册十二个公开命令；仅 `help` 配置 `h`、仅 `clear` 配置 `c`。
5. 覆盖十二命令名称、类型、别名、调用顺序、固定提示词以及无多余参数命令的拒绝行为。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py`

## T6: 暴露记忆索引引用文件快照

**文件：** `src/mewcode/memory/store.py`、`src/mewcode/memory/update.py`、`tests/test_memory_store.py`

**依赖：** 无

**步骤：**

1. 从项目层和用户层 `MEMORY.md` 的现有索引注释中提取安全笔记文件名。
2. 每层去重并按文件名字典序返回；排除 `MEMORY.md`，忽略非法文件名和不带索引标记的文本。
3. 通过 `MemoryManager` 原样暴露两层结果，不读取笔记正文，不要求目标笔记文件存在。
4. 覆盖两层索引、重复引用、非法标记、空/缺失索引和正文不读取。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_memory_store.py tests/test_memory_update.py`

## T7: 持久化 Token usage 并恢复会话统计

**文件：** `src/mewcode/session/archive.py`、`src/mewcode/session/repository.py`、`src/mewcode/session/__init__.py`、`tests/test_session_archive.py`、`tests/test_session_repository.py`

**依赖：** 无

**步骤：**

1. 定义 `SessionStats`，并允许 JSONL 读写 `usage` 事件的 input/output 非负整数增量。
2. 为 Writer 增加 usage 追加方法；保持 flush、fsync、关闭和写失败降级语义。
3. 恢复时汇总全部合法 usage 事件；非法类型、负值和坏行跳过，不污染其它事件。
4. 以恢复后的合法用户消息数作为 `turns`，兼容 Chapter 08 旧档案；将统计附加到 `RestoredArchive`。
5. 覆盖多次 usage 求和、零值、非法事件、旧档案回合数、工具续轮不计回合及无事件默认值。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_session_archive.py tests/test_session_repository.py`

## T8: 增加命令输出视图、状态标记和时间线清空

**文件：** `src/mewcode/tui/view.py`、`src/mewcode/tui/timeline.py`、`tests/test_tui.py`

**依赖：** 无

**步骤：**

1. 新增保留多行和空格对齐的命令输出时间线项，不复用会写档案的消息路径。
2. 将状态栏权限模式改为 `[DEFAULT]`、`[PLAN]` 及其他既有模式对应的方括号大写标记。
3. 为 Timeline 增加异步清空全部可见条目的能力，并保持清空后的滚动状态可继续追加。
4. 覆盖两列文本空格、四种模式标记、Token 紧凑显示和清空后只剩新追加条目。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tui.py -k "status_bar or timeline or command_output"`

## T9: 抽取统一 Agent 回合启动入口

**文件：** `src/mewcode/tui/app.py`、`tests/test_tui.py`

**依赖：** T7

**步骤：**

1. 将现有普通文本提交中创建 runtime、添加用户消息、锁定输入和启动 stream task 的逻辑抽成单一异步入口。
2. 在用户消息成功加入 Conversation/JSONL 后，将当前内存 `SessionStats.turns` 加一；同一流式 Agent Loop 内不再修改该值。
3. 新会话、Provider 重新激活和无 runtime 状态使用零值统计；保留现有输入锁、取消、标题与流式行为。
4. 让当前普通消息提交先复用该入口，暂时保留既有 Slash 分支，验证无行为变化。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tui.py -k "stream or submit or plan_and_do"`

## T10: 实现 Textual 命令控制适配器

**文件：** `src/mewcode/tui/command.py`、`tests/test_tui_command.py`

**依赖：** T5-T9

**步骤：**

1. 实现 `TuiCommandControl` 的消息显示、用户消息发送、模式设置、状态刷新、压缩、恢复和退出委托。
2. 从应用构造状态快照：计划模式统计只读工具，其他模式统计全部工具；组合会话 Token、记忆总数、模型和绝对工作目录。
3. 将 MemoryManager 的通用索引结果转换为命令域 `MemorySnapshot`；无 runtime 时返回空 session 快照且不创建文件。
4. 实现 session 快照返回当前 session ID 与绝对 JSONL 路径。
5. 用运行中的测试 App 验证纯本地查询不触发 Provider、不创建会话、不写 JSONL，且模式变化刷新状态。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tui_command.py -k control`

## T11: 用命令分发器替换硬编码 Slash 路由

**文件：** `src/mewcode/tui/app.py`、`tests/test_tui.py`、`tests/test_tui_command.py`

**依赖：** T3、T5、T9、T10

**步骤：**

1. 为 App 注入 `CommandRegistry`，创建单一 `CommandDispatcher` 和 `TuiCommandControl`；未注入时使用默认注册表。
2. 将回车入口改成 `parse_input()` 三路分流，删除 `/exit`、`/resume`、`/compact`、`/plan`、`/do` 的硬编码条件。
3. 命令提交前清空输入；分发完成且仍为 IDLE 时恢复焦点。提示词命令经控制适配器进入 T9 的统一回合入口。
4. 覆盖空输入、普通消息、大小写命令、未知命令、`/h`、多余参数及既有五条命令兼容行为；`/c` 的 TUI 行为留给 T13。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py tests/test_tui_command.py tests/test_tui.py -k "command or plan_and_do"`

## T12: 接入实时 usage 持久化和恢复统计

**文件：** `src/mewcode/tui/stream.py`、`src/mewcode/tui/app.py`、`tests/test_tui_command.py`、`tests/test_tui_resume.py`

**依赖：** T7、T9、T11

**步骤：**

1. 流式消费收到每个 usage 时更新当前 `SessionStats`、追加 JSONL usage 事件并刷新状态栏。
2. 保持同一 Agent Loop 多次模型请求的 usage 分别记录并累计；没有 runtime 的防御路径不得抛错。
3. 创建新会话时统计归零；恢复会话时用 `RestoredArchive.stats` 替换当前统计并立即刷新状态栏。
4. 覆盖普通单轮、工具续轮两次 usage、退出恢复、旧档案只有用户消息和状态栏/`/status` 一致性。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tui_command.py tests/test_tui_resume.py -k "usage or stats or resume"`

## T13: 完成 `/clear` 新会话语义

**文件：** `src/mewcode/tui/command.py`、`src/mewcode/tui/app.py`、`src/mewcode/tui/timeline.py`、`tests/test_tui_command.py`

**依赖：** T8、T10-T12

**步骤：**

1. 关闭当前 runtime 和标题任务，但保留旧 JSONL/cache 内容。
2. 使用当前 Provider 和 context window 立即创建并打开新 runtime/JSONL，替换 Conversation 和零值统计。
3. 清空时间线，追加且只显示“已结束当前会话并开启新会话”的 notice，并把该 notice 写入新 JSONL。
4. 更新状态栏、清空输入并恢复焦点；无旧 runtime 时执行相同行为。
5. 覆盖旧档案可继续读取、新 ID/路径、空 JSONL 已打开、消息/Token/回合归零、时间线唯一 notice 和 `/session` 新快照。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tui_command.py -k clear`

## T14: 实现输入框下方的内联命令菜单

**文件：** `src/mewcode/tui/completion.py`、`tests/test_tui_command.py`

**依赖：** T1、T2

**步骤：**

1. 实现默认隐藏的内联 OptionList，显示规范名称与一句描述，候选顺序保持注册表排序。
2. 提供候选整体替换、高亮上下移动和读取高亮规范名称的接口；空候选时隐藏并清空。
3. 将 Widget 放置在 PromptInput 与状态栏之间，高度按候选自适应并限制最大值，超出时内部滚动。
4. 菜单本身不修改 SessionState、不执行命令、不访问 Provider 或会话；鼠标选择只向 App 发出规范名称。
5. 覆盖十二项展示、隐藏、候选刷新、默认高亮、移动边界、鼠标选择和候选不重复。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tui_command.py -k inline_completion_menu`

## T15: 将实时内联补全接入 PromptInput

**文件：** `src/mewcode/tui/app.py`、`tests/test_tui_command.py`

**依赖：** T11、T13、T14

**步骤：**

1. 监听 PromptInput 文本变化；当内容为无参数 `/...` 前缀时实时查询注册表并刷新菜单，输入 `/` 时显示全部公开命令。
2. 输入参数、普通文本、无候选或非 IDLE 状态时隐藏菜单；不再向 Timeline 输出“无匹配”提示。
3. 菜单可见时在 PromptInput 捕获上/下键移动高亮，Tab 或 Enter 接受高亮项，Esc 隐藏；保留 Shift+Tab 权限切换与 Alt+Enter 换行。
4. 接受候选或 Esc 时记录当前补全文本抑制状态；程序化写回不重开菜单，用户继续编辑后清除抑制并恢复实时过滤。
5. 选择只写回规范名称并把光标移到末尾；第一次 Enter 只选择，第二次 Enter 才走现有命令提交。鼠标点击复用同一接受路径。
6. 覆盖 `/` 自动显示十二项、`/h` 单候选、`/c` 两候选、动态过滤、键盘/鼠标选择、二次 Enter、Esc、参数关闭、无匹配、隐藏命令排除和焦点不丢失。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_tui_command.py -k completion`

## T16: 在启动阶段装配命令注册表

**文件：** `src/mewcode/cli.py`、`tests/test_command.py`、`tests/test_tui_command.py`

**依赖：** T5、T11

**步骤：**

1. 在 MCP 连接和 TUI 启动前创建默认命令注册表，并注入 `MewCodeApp`。
2. 保持 Provider、MCP、权限、指令、记忆和会话服务的既有装配与关闭顺序。
3. 确认注册冲突异常进入现有顶层启动错误路径，以非零状态退出并输出可诊断信息。
4. 覆盖默认启动得到十二命令、冲突时 App 未运行，以及测试直接构造 App 的默认回退。

**验证：** `conda run -n mewcode python -m pytest -q tests/test_command.py tests/test_tui_command.py tests/test_mcp_manager.py`

## T17: 更新用户文档

**文件：** `README.md`

**依赖：** T5、T11-T16

**步骤：**

1. 将使用表扩展为十二个规范命令，并标明 `/h`、`/c` 别名及 `/help <命令名>`。
2. 说明 Tab 单匹配与多匹配行为、Slash 输入不进入 Agent、纯本地命令不消耗模型 Token。
3. 说明 Token usage 写入会话 JSONL、状态栏和 `/status` 的会话累计口径，以及恢复后继续累计。
4. 保留用户此前补充的回归记录和 Chapter 08 已知限制，不改写 `HANDOVER.md`。

**验证：** `rg -n "/help|/clear|/review|Tab|usage|Token" README.md`

## T18: 完成命令端到端和兼容回归

**文件：** `tests/test_tui_command.py`、`tests/test_tui.py`、`tests/test_tui_resume.py`

**依赖：** T1-T17

**步骤：**

1. 增加完整场景：输入 `/` 自动展开菜单并选择命令 -> 普通消息产生 usage -> `/status` -> `/plan` -> `/do` -> `/clear` -> `/session`，验证 Agent 请求数、模式、档案和界面。
2. 增加 `/review` 场景，验证只注入固定文本、增加一个回合、没有预读 Git diff 或额外本地工具调用。
3. 增加退出后 `/resume` 场景，验证完整 TUI 重放、最新 compact 约束、累计 Token 与回合恢复。
4. 运行既有 TUI、会话、权限、MCP 和 Agent 测试，修复本章引入的兼容问题，不处理 Chapter 08 范围外技术债。

**验证：**

```powershell
conda run -n mewcode python -m pytest -q tests/test_command.py tests/test_tui_command.py
conda run -n mewcode python -m pytest -q tests/test_tui.py tests/test_tui_resume.py
conda run -n mewcode python -m pytest -q tests/test_agent.py tests/test_permission.py tests/test_mcp_manager.py
```

## T19: 全量质量验证

**文件：** 全部本章改动

**依赖：** T18

**步骤：**

1. 运行全量测试并记录通过、跳过和耗时；只修复本章引入的失败。
2. 运行 Python 编译检查，确认新命令包和 TUI 模块无导入环或语法错误。
3. 运行 Ruff 检查与格式检查；按项目现有配置修正新代码和测试。
4. 对照批准的 `checklist.md` 执行最终验收并记录实际证据。

**验证：**

```powershell
conda run -n mewcode python -m pytest -q
conda run -n mewcode python -m compileall -q src tests
conda run -n mewcode ruff check .
conda run -n mewcode ruff format --check .
```

## 需求覆盖

| 需求 | 实现任务 | 验证任务 |
|---|---|---|
| F1 | T1、T2、T5、T16 | T2、T5、T16、T19 |
| F2 | T3、T11 | T3、T11、T18 |
| F3 | T1、T5、T10 | T4、T5、T10 |
| F4-F5 | T3、T4 | T3、T4、T18 |
| F6 | T2、T14、T15 | T2、T14、T15、T18 |
| F7 | T4、T5、T10-T13 | T5、T11-T13、T18 |
| F8 | T6、T8、T10 | T6、T8、T10、T18 |
| F9 | T7、T9、T12 | T7、T9、T12、T18 |
| F10 | T3-T5、T10-T13 | T4、T5、T10-T13、T18 |
| F11 | T9-T15 | T11-T15、T18 |
| N1-N7 | T1-T18 | T18、T19 |

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5
T6
T7
T8
T7 -> T9
T5 + T6 + T7 + T8 + T9 -> T10
T3 + T5 + T9 + T10 -> T11
T7 + T9 + T11 -> T12
T8 + T10 + T11 + T12 -> T13
T1 + T2 -> T14
T11 + T13 + T14 -> T15
T5 + T11 -> T16
T5 + T11..T16 -> T17
T1..T17 -> T18 -> T19
```
