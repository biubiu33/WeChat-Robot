# 上下文管理与记忆系统 Checklist

> 每项必须以自动化测试、命令输出或可观察的 TUI 行为验证。测试中使用临时项目目录、临时用户目录和可控 Provider stub，不访问真实模型或用户的真实会话数据。

## 上下文与工具产物

- [ ] 每次 Provider 请求前均先检查工具结果、再估算上下文、最后决定是否自动压缩（验证：`conda run -n mewcode pytest tests/test_context_artifact.py tests/test_context_compact.py -q`）。
- [ ] 单个工具结果超过 16,000 字符时，原结果写入当前会话 cache，Prompt Context 只保留预览、相对路径和重新读取提示（验证：归档阈值测试检查文件内容、JSONL 引用和替换后的请求消息）。
- [ ] 同一工具消息累计超过 32,000 字符时，按结果大小由大到小归档，直到低于阈值（验证：多结果边界测试检查归档顺序和未归档结果）。
- [ ] 归档失败不丢弃原 Prompt Context 工具结果，也不阻塞请求（验证：模拟缓存目录写入失败，断言请求继续且有状态通知）。
- [ ] 工具归档不会修改 JSONL 中的完整工具结果或恢复后的 TUI 内容（验证：归档后读取档案、重放结果与归档前原文一致）。
- [ ] Token 预算使用最近 Provider input usage 锚定，并只按请求字符增量近似调整；无 usage 时可降级估算（验证：`conda run -n mewcode pytest tests/test_context_budget.py -q`）。
- [ ] Provider 未配置 `context_window` 时使用 1,000,000；非法或非正配置被拒绝（验证：`conda run -n mewcode pytest tests/test_config.py -q`）。
- [ ] 自动压缩在窗口余量 13,000 Token 时触发，`/compact` 使用 3,000 Token 余量（验证：自动和手动阈值测试分别断言摘要调用条件）。
- [ ] 压缩后保留约 10,000 Token 的最近原文或至少五条消息，取能保留更多历史的边界（验证：不同长度/条数的保留边界测试）。

## 摘要安全与双视图

- [ ] 摘要请求复用当前会话 Provider/模型且不携带工具定义；模型返回工具调用时摘要视为失败（验证：Provider stub 检查请求 tools 为空并模拟工具调用）。
- [ ] 正式摘要包含九个固定段落，且“所有用户消息”保持原文、“当前工作”位于要求的详细段落（验证：摘要提示和输出校验测试）。
- [ ] 分析草稿、临时摘要提示和 Provider 原始错误不会写入 JSONL、cache 或 TUI（验证：成功/失败后的档案事件断言）。
- [ ] 成功压缩写入正式摘要、覆盖边界和保留边界检查点；完整历史消息仍保留在 JSONL（验证：检查点后扫描档案包含压缩前的消息事件）。
- [ ] 恢复会话时 TUI 从所有可见事件重放，不会仅显示最新压缩检查点后的消息（验证：含检查点的档案重放测试）。
- [ ] 恢复 Prompt Context 使用最新完整检查点和之后的消息；没有检查点时从完整档案构建（验证：两种恢复路径的 Provider 请求内容测试）。
- [ ] 压缩后模型可见上下文包含“按需重读文件、不要根据摘要臆测代码”的边界提醒，且它不作为用户或助手消息显示（验证：System.context 与 Timeline 断言）。
- [ ] 自动摘要连续失败三次后在该会话熔断；熔断状态可从档案恢复；手动成功压缩会清零并恢复自动压缩（验证：`conda run -n mewcode pytest tests/test_context_compact.py -q`）。

## 会话档案与生命周期

- [ ] 新会话 ID 符合 `YYYYMMDD-HHMMSS-xxxx`，并创建 `.mewcode/sessions/<id>.jsonl` 和 `.mewcode/cache/<id>/`（验证：路径/格式测试）。
- [ ] JSONL 中每行可独立解析，消息事件保存角色、正文、工具调用/结果和写入时间；首条用户消息保存模型（验证：`conda run -n mewcode pytest tests/test_session_archive.py -q`）。
- [ ] 异步生成的标题和失败回退标题均作为 JSONL 标题事件保存，会话列表使用最新标题；缺少标题事件的旧档案回退到首条用户消息（验证：标题扫描测试）。
- [ ] 归档引用、压缩检查点和自动压缩失败状态均作为独立 JSONL 事件保存（验证：事件序列化/恢复测试）。
- [ ] 多个追加路径不会使 JSONL 行互相交错；每次追加都会 flush 和 fsync；重复关闭 Writer 安全（验证：并发追加和 Writer mock 测试）。
- [ ] 末尾损坏 JSON 行被跳过，先前完整事件仍可恢复（验证：人为追加半行后的恢复测试）。
- [ ] 末尾存在未配对工具调用时，恢复上下文截断到最后完整位置（验证：孤立工具调用测试）。
- [ ] 恢复后新消息继续追加到原 JSONL，不创建 meta 文件或 Prompt Context 快照文件（验证：恢复前后文件路径、行数和目录内容检查）。
- [ ] 距上次活动超过七天时只向模型加入时效提醒，要求复查可能变化的工作区；该提醒不伪装为档案聊天消息（验证：七天边界的系统上下文和 TUI 测试）。
- [ ] 启动后和打开恢复列表前都会清理超过 30 天的会话 JSONL 及同 ID cache；单项清理失败不会影响其它会话（验证：清理测试）。
- [ ] 旧格式或不可解析 ID 的会话既不列入 `/resume`，也不被自动清理（验证：兼容性测试）。
- [ ] 项目 `.gitignore` 默认且幂等地包含 sessions、cache、memory 规则，不覆盖已有内容（验证：首次与重复初始化后的文件比较）。

## `/resume` 与 TUI 重放

- [ ] IDLE 时输入 `/resume` 不发送给 LLM，进入会话列表；Esc 取消后恢复 IDLE（验证：`conda run -n mewcode pytest tests/test_tui_resume.py -q`）。
- [ ] 列表按最后活动时间倒序，显示标题、ID、相对时间、消息数，并显示模型和档案大小补充信息（验证：构造多份 JSONL 的列表渲染测试）。
- [ ] 列表支持上下键选择、输入标题过滤和 Enter 恢复（验证：Textual 交互测试）。
- [ ] 选中会话提供可点击删除按钮；点击后对应 JSONL 档案与同 ID cache 目录被删除，当前筛选列表立即移除该项（验证：Textual 交互测试与临时目录断言）。
- [ ] 删除会话不会删除项目级或用户级 `memory/`、`MEMORY.md` 或笔记文件；删除失败时列表项保留并显示可观察状态（验证：保留 memory 夹具并模拟文件删除失败）。
- [ ] Agent 流式执行、权限审批和恢复状态期间不能启动新的恢复/Agent 请求；用户获得明确状态反馈（验证：状态机测试）。
- [ ] 选择会话后关闭旧 Writer，重建会话 Prompt Context，并重放用户、助手、工具、notice 和 error 等完整可见事件（验证：恢复切换集成测试）。
- [ ] 长档案初次只创建最近一批 Timeline 组件，加载更早记录后顺序正确且不影响底部实时跟随（验证：分批重放测试）。
- [ ] `/compact` 是本地命令，不写入用户消息、不发给 Agent Loop；压缩期间禁用普通输入，结束后恢复焦点（验证：TUI 命令路由测试）。
- [ ] `/compact` 成功、无需压缩和失败均显示状态通知；失败不破坏现有 Prompt Context（验证：手动压缩状态测试）。

## 项目指令与系统提示

- [ ] 仅在进程启动时读取项目根、项目 `.mewcode`、用户 `.mewcode` 三层 `MEWCODE.md`，且高优先级内容在模型提示中靠前（验证：`conda run -n mewcode pytest tests/test_memory_instructions.py tests/test_prompt.py -q`）。
- [ ] 进程运行后修改任意 `MEWCODE.md`，后续请求和 `/resume` 仍使用启动缓存；重建进程后才读取新内容（验证：缓存语义测试）。
- [ ] 只有独占行 `@include <relative_path>` 被展开，合法嵌套至第五层生效（验证：include 语法和五层测试）。
- [ ] 第六层、环路、跳出项目/用户信任根、缺失或二进制 include 都被安全跳过且不阻塞启动（验证：深度、环路、路径逃逸、NUL 文件测试）。
- [ ] 自定义指令和长期记忆以已有 priority 80、100 模块注入；无内容时保持原有系统提示渲染（验证：模块排序和空值回归测试）。
- [ ] 摘要、时效提醒和压缩边界提醒作为独立动态系统上下文序列化到 Anthropic 与 OpenAI 请求，不影响稳定提示缓存分层（验证：`conda run -n mewcode pytest tests/test_llm_helpers.py -q`）。

## 自动记忆

- [ ] 最终回复自然完成且没有工具调用时，异步发起一次记忆更新；取消、流错误、最大迭代和保护性停止不触发（验证：`conda run -n mewcode pytest tests/test_memory_update.py tests/test_tui.py -q`）。
- [ ] 记忆更新复用当前 Provider/模型、无工具定义，并只使用从最后用户消息到最终助手消息的快照和现有索引（验证：Provider stub 请求检查）。
- [ ] `user`、`feedback` 笔记写入 `~/.mewcode/memory/`；`project`、`reference` 写入 `<root>/.mewcode/memory/`（验证：四类映射测试）。
- [ ] 新建或更新笔记为带 frontmatter 的 Markdown；对应 `MEMORY.md` 使用规定索引行格式并可在下一次请求前注入（验证：文件内容和系统提示测试）。
- [ ] 用户级与项目级索引按项目在前、用户在后合并；合并注入超过 25KB 时截断并加标记（验证：大小边界测试）。
- [ ] 任一索引达到 200 行或 25KB 时，同次异步更新合并重复条目、保留高价值近期条目，并缩短索引；原始笔记不删除（验证：超限重写与原文件存在性测试）。
- [ ] 记忆文件名和操作受路径/类型/层级校验保护，拒绝 `delete`、无效 JSON 和路径逃逸（验证：恶意操作测试）。
- [ ] 记忆写入使用锁；连续自然回合产生的后台更新不会发生索引覆盖或笔记损坏（验证：并发更新测试）。
- [ ] 记忆 Provider/解析/写入失败只记录日志、不重试、不阻塞下一轮输入，也不显示为聊天消息（验证：失败注入与 TUI 响应性测试）。

## 兼容性与端到端

- [ ] 未配置 `MEWCODE.md`、memory 目录、历史会话或 MCP server 的项目仍能启动和对话（验证：空临时项目启动测试）。
- [ ] 既有 Provider、MCP 工具、权限模式、规划模式、流式输出和取消流程保持通过（验证：`conda run -n mewcode pytest tests/test_agent.py tests/test_mcp_config.py tests/test_mcp_manager.py tests/test_mcp_tool.py tests/test_permission.py tests/test_tui.py -q`）。
- [ ] 既有格式、类型和静态检查无新增问题（验证：`conda run -n mewcode ruff check src tests` 和 `conda run -n mewcode mypy src`）。
- [ ] 全量自动化测试通过（验证：`conda run -n mewcode pytest -q`）。
- [ ] 端到端场景：在临时项目启动新会话，发送首条用户消息，观察标题异步落盘；执行产生超过 16K 的工具结果，确认 cache/JSONL/Prompt Context 各自状态正确（验证：端到端集成测试或人工观察）。
- [ ] 端到端场景：通过 `/compact` 压缩上述会话，退出并重新启动，使用 `/resume` 选择该会话；确认 TUI 显示完整原历史、模型收到摘要与近期原文、后续消息继续追加同一 JSONL（验证：端到端集成测试或人工观察）。
- [ ] 端到端场景：配置三层指令和两级记忆索引，启动新会话并确认系统提示优先级/注入顺序；自然结束后确认记忆更新不阻塞下一输入（验证：端到端集成测试或人工观察）。
