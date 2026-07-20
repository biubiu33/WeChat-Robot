# Slash 命令注册与分发系统 Checklist

> 每项必须通过自动化测试、命令输出或可观察的 TUI 行为验证。测试使用临时项目目录、临时用户目录、可控 Provider stub 和内存 fake control，不调用真实模型，不读取或修改用户真实会话与记忆数据。

## 命令注册与架构边界

- [ ] 默认命令目录恰好包含十二个公开规范名称：`exit`、`plan`、`do`、`compact`、`resume`、`clear`、`help`、`status`、`memory`、`permission`、`session`、`review`；仅 `help` 有别名 `h`、仅 `clear` 有别名 `c`（验证：`conda run -n mewcode python -m pytest -q tests/test_command.py -k registry`）。【AC1】
- [ ] 每条默认命令都有非空描述、用法、正确类型、参数提示、可见性和可调用处理行为（验证：遍历默认命令元数据断言）。【AC1/AC4】
- [ ] 规范名称重复、别名重复、同命令内部重复别名、名称与别名交叉冲突均在注册阶段抛出可诊断错误，不发生后注册覆盖（验证：冲突矩阵单测）。【AC1】
- [ ] 名称和别名冲突按大小写不敏感处理，例如 `Help` 与 `help` 不能同时占用（验证：大小写冲突单测）。【AC1】
- [ ] 默认命令注册表在进入 TUI 前完成构造；人为注入冲突时应用以非零状态退出且 TUI 未运行（验证：启动装配测试捕获退出状态与错误文本）。【AC1】
- [ ] 命令模型、注册、解析、分发和内置 handler 可在不启动 Textual 的情况下由 fake control 完整测试（验证：`tests/test_command.py` 不创建 `MewCodeApp`）。【N3】
- [ ] 内置 handler 只通过界面控制协议执行；命令域模块不导入 Textual Widget 或具体 TUI App（验证：源码导入检查和命令域单测）。【N3】
- [ ] `/help`、分发和实时命令菜单读取同一个注册表实例，不维护独立命令清单（验证：向测试注册表加入临时公开命令后，三条路径都能立即看到它）。【AC1/AC4/AC5】

## 输入解析、分流与参数

- [ ] 空字符串和纯空白输入直接返回，不显示错误、不创建会话、不调用 Provider（验证：解析单测与 TUI 提交测试）。【AC2】
- [ ] 非 `/` 开头输入保持普通用户消息流程，只启动一次 Agent Loop 并写入一条用户消息（验证：Provider stub 请求数与 JSONL 消息事件）。【AC2】
- [ ] Slash 命令以第一个空格分隔名称和参数，名称统一小写匹配，参数只清理首尾空白（验证：`/HeLp   clear` 等解析样例）。【AC2】
- [ ] 解析器收到单独 `/` 或未知 `/unknown` 时不进入 Agent，并返回未知命令与 `/help` 引导；TUI 提交未知命令后输入框保持可用（验证：解析单测、Provider 请求数为零、Timeline 文本和焦点状态）。【AC2/N5】
- [ ] `/h` 和 `/c` 不经 Tab 也能直接解析到 `/help`、`/clear`；命令原文不进入 Conversation（验证：别名 TUI 路由测试）。【AC2/AC5】
- [ ] 除 `/help` 外的十一条命令带非空参数时均拒绝执行并显示对应用法，原业务行为未发生（验证：参数化遍历十二命令，排除 help）。【AC3】
- [ ] `/help clear` 与 `/help c` 返回同一详情；`/help` 参数超过一个名称或目标不存在时显示用法/未知命令引导（验证：帮助参数单测）。【AC3】
- [ ] IDLE 以外的流式、审批、压缩和恢复状态不能通过命令分流并发启动第二个 Agent 回合（验证：状态机集成测试）。【F11/N5】

## 帮助与补全

- [ ] `/help` 只显示十二个规范名称，按字典序排列为“名字 + 一句描述”两列且空格对齐；`h`、`c` 不重复成独立行（验证：渲染文本逐行断言）。【AC4】
- [ ] `/help <命令>` 显示规范名称、别名、类型、描述、用法和参数提示；没有别名或参数提示时显示确定的空状态（验证：`help`、`clear`、`review` 三类详情）。【AC4】
- [ ] 输入框内容刚变为 `/` 时，无需按键即在输入框下方展开全部十二个公开规范命令；候选按规范名称排序，合成的隐藏命令不出现，焦点始终留在输入框（验证：Textual 文本变更、候选内容、Widget 位置与焦点断言）。【AC5/N5】
- [ ] 继续输入时按规范名称和别名前缀实时过滤并按规范名称去重：`/h` 只显示 `/help`，`/c` 显示 `/clear` 与 `/compact`（验证：逐字符输入的候选快照，无需 Tab）。【AC5】
- [ ] 菜单可见时上/下键循环移动高亮；Tab、Enter 或鼠标点击都只把高亮项的规范名称写回输入框、将光标移到末尾并关闭菜单，不执行命令（验证：三种选择方式后的输入文本、Provider 请求数、Timeline 和会话状态）。【AC5/N5】
- [ ] 通过菜单写回规范名称后，程序化文本变更不会立即重开菜单；第二次 Enter 才按正常提交路径执行命令，用户继续编辑后恢复实时过滤（验证：两次 Enter 的分阶段状态与编辑后的候选快照）。【AC5】
- [ ] Esc 关闭菜单并保留原输入，且在用户再次编辑前不自动重开；输入参数、普通文本、无候选或非 IDLE 状态时菜单关闭且不向 Timeline 写“无匹配”提示（验证：各关闭条件、抑制状态、焦点和零副作用断言）。【AC5/F11/N5】
- [ ] 内联菜单挂载在 PromptInput 与状态栏之间，高度随候选数变化并受上限约束，溢出时可滚动；Shift+Tab 权限切换和 Alt+Enter 换行行为不退化（验证：Widget 顺序、尺寸/滚动与 PromptInput 键盘回归）。【F6/N4/N5】

## 既有命令兼容

- [ ] `/exit` 通过命令分发关闭 TUI，命令文本不进入对话或档案（验证：测试 App 退出状态与临时目录）。【AC6/AC12】
- [ ] `/plan` 不调用模型，将模式切换为 `plan`，状态栏立即显示 `[PLAN]`，并显示本地 notice（验证：TUI 路由测试）。【AC6】
- [ ] `/do` 严格先切换为 `default`、刷新 `[DEFAULT]`，再注入既有“请按上面的计划开始执行。”文本并立即启动一个 Agent 回合（验证：fake control 调用顺序和 Provider 请求内容）。【AC6/AC10】
- [ ] `/compact` 不作为用户消息发送，继续触发现有手动上下文压缩；无会话、成功、无需压缩和失败路径保持 Chapter 08 行为（验证：既有压缩 TUI 测试与命令路由测试）。【AC6/AC12】
- [ ] `/resume` 不作为用户消息发送，继续打开历史会话列表；选择后完整重放可见档案，并按 Chapter 08 最新有效检查点恢复模型上下文（验证：`conda run -n mewcode python -m pytest -q tests/test_tui_resume.py`）。【AC6/AC12】
- [ ] Shift+Tab 仍能循环四种权限模式，命令系统不会拦截或改变该快捷键（验证：既有权限模式 TUI 测试）。【N4】

## `/clear` 会话重置

- [ ] 有当前会话时 `/clear` 关闭旧 Writer 和标题任务，旧 JSONL/cache 保留且可重新读取（验证：执行前后旧文件存在、内容不变、旧 Writer 关闭）。【AC7】
- [ ] 没有当前会话时 `/clear` 也立即创建新 session ID、cache 目录和已打开的空 JSONL，不依赖后续用户消息（验证：首次提交即 `/clear` 的临时目录测试）。【AC7】
- [ ] 新会话使用当前 Provider 与 context window，Conversation 为空，累计 input/output Token 与回合数均为零（验证：运行时和状态快照断言）。【AC7】
- [ ] `/clear` 清空全部旧 Timeline 条目，随后界面只显示“已结束当前会话并开启新会话”的 notice（验证：清理前添加用户/工具/错误条目，清理后组件与文本断言）。【AC7】
- [ ] 指定 notice 写入新 JSONL，但 `/clear` 命令文本本身不写入；`/session` 随后显示新 ID 与新档案绝对路径（验证：读取新档案事件和 session 输出）。【AC7/AC12】
- [ ] `/c` 与 `/clear` 执行完全相同的新会话行为；`/clear extra` 被参数校验拒绝且不关闭旧会话（验证：别名与参数边界测试）。【AC3/AC5/AC7】

## 状态、记忆与会话查询

- [ ] `/status` 恰好输出当前权限模式、累计 input/output Token、可用工具数、记忆条目数、模型名和当前工作目录六项信息（验证：构造确定快照并逐项断言）。【AC8】
- [ ] 计划模式的工具数只统计实际暴露的只读工具，`default`、`acceptEdits`、`bypassPermissions` 统计全部已注册内置与 MCP 工具（验证：混合只读/写入/MCP 注册表与四模式参数化测试）。【AC8】
- [ ] `/permission` 输出 `default`、`acceptEdits`、`plan` 或 `bypassPermissions`，与同状态下 `/status` 完全一致（验证：四模式参数化测试）。【AC8】
- [ ] 无活动 runtime 时 `/session` 显示“当前尚未创建会话”，不创建 `.mewcode/sessions` 下的新 JSONL（验证：纯本地首次命令测试）。【AC8/AC12】
- [ ] 有活动 runtime 时 `/session` 至少显示 session ID 和绝对档案路径，不显示 API Key 或 Provider 配置（验证：输出文本和敏感串排除）。【AC8/N6】
- [ ] 记忆索引引用解析分别返回项目层和用户层安全文件名，去重并按字典序排列；忽略非法标记、`MEMORY.md` 本身和普通正文（验证：`conda run -n mewcode python -m pytest -q tests/test_memory_store.py -k indexed`）。【AC9】
- [ ] `/memory` 只分层显示上述文件名，不展开笔记正文，也不要求引用文件真实存在（验证：索引引用不存在文件且正文含敏感串的输出测试）。【AC9/N6】
- [ ] 项目层或用户层索引缺失/为空时 `/memory` 显示“无”；`/status` 记忆条目数等于两层 `/memory` 文件数合计（验证：空态和混合态测试）。【AC9】
- [ ] `/status`、`/memory`、`/permission`、`/session` 均不触发 Provider、工具或记忆更新任务（验证：fake Provider/tool/memory 调用记录为空）。【AC8/AC9/AC12】

## 提示词命令

- [ ] `/review` 只注入固定文本“请审查当前工作区中的代码变更，重点关注正确性、安全性、回归风险和测试缺口，并按严重程度报告问题。”并立即启动一次 Agent Loop（验证：Provider 首条请求消息精确相等）。【AC10】
- [ ] `/review` 分发阶段不执行 Git diff、不读取工作区文件、不调用任何内置/MCP 工具；模型后续自主行为不计为分发预收集（验证：分发前 fake subprocess、工具和文件访问记录为空）。【AC10】
- [ ] `/do` 与 `/review` 的命令原文不入档，只有各自批准的注入文本作为用户消息写入 Conversation 和 JSONL（验证：对话与档案全文搜索）。【AC10/AC12】
- [ ] 普通消息、`/do`、`/review` 各增加一次会话回合；提示词命令与普通消息复用标题、档案、上下文、取消和流式入口（验证：统一回合入口集成测试）。【AC10/AC11】

## Token 与回合持久化

- [ ] Provider 每返回一次 usage，当前 JSONL 追加一个含非负 input/output 增量的 usage 事件，状态栏累计值立即更新（验证：单请求 Provider stub、档案行和状态栏文本）。【AC11】
- [ ] 同一 Agent Loop 因工具调用产生两次或更多模型请求时，每次 usage 分别写入并求和，但会话回合数只增加一次（验证：两轮工具 Provider stub）。【AC11】
- [ ] usage 为零可写入并保持累计不变；负值、非法类型和坏 JSON 行在恢复时被跳过，不影响其它消息或统计（验证：档案恢复边界测试）。【AC11/N7】
- [ ] Chapter 08 旧档案即使没有 usage 事件，也能按合法用户消息数恢复回合数，Token 默认为零（验证：旧格式夹具）。【AC11/N4】
- [ ] 退出并 `/resume` 后，累计 input/output Token 与用户回合数等于退出前值；后续请求在该值上继续累计（验证：恢复后再发送一轮的集成测试）。【AC11】
- [ ] 状态栏与 `/status` 对同一会话显示相同累计 Token；`/clear` 后两者同时归零（验证：三处状态一致性断言）。【AC7/AC8/AC11/N7】

## 档案与上下文隔离

- [ ] `/help`、`/status`、`/memory`、`/permission`、`/session` 在无会话时不会创建档案，在有会话时不会追加任何 JSONL 行（验证：执行前后目录与文件行数比较）。【AC12】
- [ ] 上述纯本地命令的输入和输出都不加入 Conversation，也不出现在下一次 Provider 请求消息中（验证：先执行所有本地命令，再发送普通消息检查请求）。【AC12/N6】
- [ ] `/plan` 的本地 notice 不写入 JSONL；`/compact` 只写既有压缩/notice 业务事件；`/clear` 只向新档案写指定 notice（验证：逐命令事件类型检查）。【AC12】
- [ ] 命令帮助、状态和记忆输出不包含 API Key、记忆正文、工具参数或完整 Provider 配置（验证：植入敏感哨兵字符串后全文排除）。【N6】

## 集成与兼容性

- [ ] TUI 控制适配器是命令域与 Textual 的唯一行为桥接；普通消息和提示词命令调用同一个 Agent 回合入口（验证：架构导入检查和统一入口 spy）。【N3/AC10】
- [ ] 命令注册表在 CLI 中与 Provider、MCP、权限、指令、记忆和会话服务共同装配，且不改变 MCP Manager 的关闭顺序（验证：CLI 装配测试）。【AC1/N4】
- [ ] 既有 Agent 多轮工具、权限审批、取消、计划模式和 Provider 流式测试保持通过（验证：`conda run -n mewcode python -m pytest -q tests/test_agent.py tests/test_permission.py tests/test_tui.py`）。【AC13】
- [ ] 既有 MCP 配置、连接、工具适配和生命周期测试保持通过（验证：`conda run -n mewcode python -m pytest -q tests/test_mcp_config.py tests/test_mcp_manager.py tests/test_mcp_tool.py`）。【AC13】
- [ ] 既有 Chapter 08 会话、上下文、指令和记忆测试保持通过；不借本章修改已记录压缩技术债（验证：运行全部 `test_session_*`、`test_context_*`、`test_memory_*`）。【AC6/AC13】
- [ ] README 说明十二个命令、`/h`/`/c`、`/help <命令名>`、输入 `/` 自动展开的实时内联菜单、Tab/Enter 只填入且第二次 Enter 执行、本地命令不进 Agent 和 usage 恢复口径，同时保留用户已有 Chapter 08 回归与限制文本（验证：文档关键词和 Git diff 人工检查）。【AC13】

## 构建与质量

- [ ] 命令域、TUI 命令、记忆索引和会话统计专项测试全部通过（验证：`conda run -n mewcode python -m pytest -q tests/test_command.py tests/test_tui_command.py tests/test_memory_store.py tests/test_session_archive.py tests/test_session_repository.py`）。【AC13】
- [ ] 全量测试通过且无新增失败或意外跳过（验证：`conda run -n mewcode python -m pytest -q`）。【AC13】
- [ ] 全部源码和测试可编译，无新导入环或语法错误（验证：`conda run -n mewcode python -m compileall -q src tests`）。【AC13】
- [ ] Ruff 静态检查无告警（验证：`conda run -n mewcode ruff check .`）。【AC13】
- [ ] Ruff 格式检查无 diff（验证：`conda run -n mewcode ruff format --check .`）。【AC13】
- [ ] 工作区原有 `README.md` 与 `HANDOVER.md` 内容得到保留，`HANDOVER.md` 未被本章实现重写（验证：Git diff 与文件哈希/内容人工检查）。【N4】

## 端到端场景

- [ ] 场景 1：在空临时项目启动 -> 执行 `/help`、`/status`、`/memory`、`/permission`、`/session` -> 确认零 Provider 请求、零 JSONL、帮助/空态正确 -> 发送普通消息后正常进入 Agent（验证：Textual 集成测试）。【AC2/AC4/AC8/AC9/AC12】
- [ ] 场景 2：发送产生 usage 的普通消息 -> `/plan` 显示 `[PLAN]` 和只读工具数 -> 输入 `/` 自动展开十二项并继续输入 `/h` 实时过滤为 `/help` -> Enter 只填入、第二次 Enter 执行帮助 -> `/do` 显示 `[DEFAULT]` 并触发一个回合 -> `/status` 显示两轮累计 Token（验证：可控 Provider 端到端测试）。【AC5/AC6/AC8/AC11】
- [ ] 场景 3：已有会话包含消息、工具结果、notice、compact 检查点和多次 usage -> 退出并 `/resume` -> TUI 完整重放、Prompt Context 沿用 Chapter 08 最新检查点、Token 与回合恢复 -> 后续消息继续追加同一 JSONL（验证：恢复端到端测试）。【AC6/AC11/AC13】
- [ ] 场景 4：在已有会话执行 `/clear` -> 旧档案保留、新档案立即打开、时间线只剩指定 notice、统计归零 -> `/session` 显示新 ID/路径 -> `/review` 只写固定提示词并启动新会话的第一个回合（验证：TUI 与临时目录端到端测试）。【AC7/AC8/AC10/AC12】
- [ ] 场景 5：输入 `/c` 后实时看到 `/clear` 与 `/compact` -> 选择 `/compact` 时只填入规范名称、第二次 Enter 才触发压缩 -> 再输入 `/c` 后按 Esc 关闭菜单并直接 Enter，以别名执行 clear（验证：别名解析、内联多候选和二次 Enter 端到端测试）。【AC5/AC6/AC7】
