# MewCode 微信自然对话节奏与分段回复 Checklist

状态：已批准（2026-08-20）

> 每一项必须通过运行代码、检查档案或观察真实微信行为验证；仅阅读实现不能标记通过。

## Implementation Completeness

- [x] 微信消息模型能够表达待收集批次、带修订号的 FIFO 快照和结构化回复（verification：导入模块并运行模型构造测试）。
- [x] 会话归档转换器可以暂缓指定消息且不改变普通 Session 行为（verification：`tests/test_session_runtime.py` 通过）。
- [x] 信息工具能够分别返回净化正文和独立来源消息（verification：信息来源定向测试通过）。
- [x] 微信稳定提示包含自然闲聊、`<|bubble|>`、专业纯文本、无 Markdown 包装和避免重复工具状态的约束（verification：Fake Provider 捕获 system 内容并断言）。
- [x] 回复整形支持闲聊气泡、专业长文、独立来源和网页强制专业模式（verification：回复纯函数测试通过）。
- [x] 微信运行时能够观察真实工具开始事件并按阶段通知（verification：Fake Provider 工具循环测试通过）。
- [x] 微信协调器实现每好友 7 秒收集、失效队列项、自然打断和实际投递记录（verification：Bot 定向测试通过）。
- [x] README 和 TODO 与最终实现一致，不再宣称 `/cancel` 可用（verification：文档搜索和人工复核）。

## Message Aggregation And Queueing

- [x] AC1：同一好友连续发送多条消息时，最后一条后的前 7 秒不调用模型；静默满 7 秒只调用一次，模型输入保留原顺序和全部内容（verification：Fake Runtime 计数与合并文本断言）。
- [x] AC1：单条消息也必须等待完整 7 秒静默窗口，不能沿用旧的立即入队行为（verification：可控时钟测试在窗口前后分别断言调用次数）。
- [x] AC2：好友在收集窗口内补充消息会重置计时，不会产生两个模型任务（verification：连续重置计时测试）。
- [x] AC2：好友任务已经进入 FIFO 但尚未处理时，新消息使旧任务失效；新旧消息重新等待并最终只回答一次（verification：阻塞消费者并检查 Runtime 调用）。
- [x] AC3：两个好友按各自静默完成时间进入全局 FIFO，并按该顺序处理（verification：双好友调度测试）。
- [x] AC3：同一回复批次中的工具状态、正文、气泡和来源不会与另一好友回复交错（verification：Fake Driver 全局发送序列断言）。
- [x] AC15：重复 UI 事件仍被 SQLite 唯一约束拒绝，不会进入聚合或重复回答（verification：既有去重测试和新增批次断言）。

## Casual Chat Bubbles

- [x] AC4：`你好<|bubble|>今天怎么样` 被发送为两个有序气泡，分隔标记不出现在任何可见消息中（verification：Fake Driver 发送记录）。
- [x] AC4：空白分段被忽略，单气泡和少于 7 个气泡正常发送（verification：参数化回复格式测试）。
- [x] AC4：模型输出超过 7 个气泡时最多发送 7 条，超出的内容归入最后一条且没有内容丢失（verification：重组发送内容与原内容比较）。
- [x] AC5：闲聊气泡间隔都位于 0.4～2 秒，且同一批次中更长的下一条不会获得更短等待（verification：注入确定速度并记录异步时间）。
- [x] AC5：气泡等待使用可取消异步机制，自动化测试和程序关闭不会被阻塞 sleep 卡住（verification：取消任务并断言在短超时内结束）。

## Professional Answers And Plain Text

- [x] AC6：包含 `C:\Users\name`、`\d+`、LaTeX 转义和普通反斜线的专业回答不会按反斜线拆分（verification：回复格式参数化测试）。
- [x] AC7：不超过微信单条限制的专业回答保持单条，不模拟闲聊气泡节奏（verification：Fake Driver 发送次数和无等待断言）。
- [x] AC7：超过单条限制的专业回答优先按段落和句子拆分，必要时才硬切；所有片段均不超限且按序重组后内容一致（verification：多种长文输入测试）。
- [x] AC7：专业传输分段数量不受闲聊 7 条上限约束（verification：构造需要超过 7 个传输片段的长文本）。
- [x] AC12：普通文本中的 `**加粗**`、`## 标题`、引用前缀、Markdown 链接和三反引号围栏不会出现在发送结果中（verification：混合 Markdown 输入测试）。
- [x] AC12：围栏内代码移除围栏后仍完整保留缩进、`#`、`*`、`**`、反斜线、下划线和其他代码字符（verification：逐字代码内容断言）。
- [x] AC12：专业正文保留普通段落、空行和自然编号，不被清理成一整行（verification：段落结构断言）。

## Tool Stages And Sources

- [x] AC10：第一次调用时间工具时发送一次“查看时间”类自然状态，不暴露 `get_current_time` 名称或参数（verification：Fake Tool 事件和可见消息断言）。
- [x] AC10：一次网页任务中的 `web_search` 和多个 `web_fetch` 只发送一次网页阶段状态（verification：多工具调用序列测试）。
- [x] AC10：同一轮从时间阶段切换到网页阶段时可以各发送一次不同状态（verification：跨阶段工具序列测试）。
- [x] AC10：模型没有实际调用工具时不发送虚假的工作状态（verification：纯文本 Provider 回答测试）。
- [x] AC11：网页查询的可见顺序严格为工具状态、专业正文、最后的独立来源消息（verification：Fake Driver 发送序列断言）。
- [x] AC11：正文中的已记录 URL 被替换为来源指引，未核实 URL 被省略，最多三个净化来源及 OpenStreetMap 署名规则保持正确（verification：来源账本测试）。
- [x] AC11：网页工具失败或无可靠来源时发送纯文本失败说明，不生成虚假来源消息（verification：失败工具测试）。
- [x] AC15：微信侧仍只暴露既有三个只读公共信息工具，不获得 Bash、文件、MCP、Skill、子 Agent 或任意 HTTP 权限（verification：捕获 Provider Request 的工具定义和环境）。

## Natural Interruption And Session Truth

- [x] AC8：同一好友在模型生成期间发来新消息会取消当前模型任务，旧最终回答不发送；新消息重新等待 7 秒（verification：Blocking Provider 测试）。
- [x] AC8：同一好友在工具执行期间发来新消息会取消当前工具和后续旧回复，已发送状态不撤回，也不发送取消确认（verification：Blocking Tool 测试）。
- [x] AC8：同一好友在气泡间隔期间发来新消息会停止所有剩余旧气泡（verification：在可控等待中注入新事件）。
- [x] AC9：其他好友的新消息不会设置当前活动任务的取消状态，只进入自己的收集窗口（verification：双好友活动任务测试）。
- [x] AC13：部分气泡发送后被打断，恢复 Session 时只包含已经成功发送的状态或气泡，不包含未发送的完整模型草稿（verification：读取 JSONL 并发起下一轮 Fake Provider 请求）。
- [x] AC13：第一条可见消息发送失败时，不把该消息或后续消息写成好友已经看到的 assistant 历史（verification：Failing Driver + Session 恢复测试）。
- [x] AC14：文本 `/cancel` 不触发本地取消确认或专用分支，而是和普通文字一样进入 7 秒收集（verification：提交 `/cancel` 并检查队列及可见发送记录）。

## Isolation, Safety And Failure Handling

- [x] N1：不同好友的 Pending 状态、修订号、取消事件、Session 和投递历史互不共享（verification：双好友并发入站和恢复测试）。
- [x] N2：每条工具状态、气泡、专业分段和来源发送前仍会重新定位并验证原好友（verification：UIA Driver 委托及目标变化失败测试）。
- [x] N3：实现没有新增意图分类 API 请求、第三方队列或运行依赖（verification：Fake Provider 请求计数、依赖清单 diff 和代码检查）。
- [x] N4：7 秒计时器、工具任务和气泡间隔在程序关闭时均被取消并回收（verification：启动含 pending/active 状态的 Bot 后执行 stop，断言无悬挂任务）。
- [x] N5：失效快照不会提前标记事件 processed，有效合并批次结束后其全部事件只标记一次（verification：Store 状态断言）。
- [x] AC15：非白名单、群聊、出站消息和重复好友名继续被拒绝（verification：现有 Bot/UIA Driver 回归测试）。
- [x] AC15：信息工具参数、网页正文、代理凭据和异常详情不进入好友 JSONL（verification：读取测试档案并搜索敏感样例）。
- [x] AC21：模型、工具和发送失败只产生受控纯文本，不向好友显示堆栈、密钥、本地路径或内部异常类型（verification：注入带敏感字符串的异常并检查可见消息）。

## Documentation

- [x] README 准确说明固定 7 秒消息合并、闲聊气泡、专业长文、工具状态、自然打断和纯文本输出（verification：人工对照批准 spec）。
- [x] README 中所有 `/cancel` 能力、配置和操作说明已经删除（verification：`rg -n "/cancel" README.md` 无旧能力描述）。
- [x] TODO 只勾选已经通过验收的 P0 第 1、2 项，好友级 Emoji 等未实现条目仍保持未完成（verification：人工对照实际功能）。
- [x] `doc/16/spec.md`、`plan.md`、`task.md`、`checklist.md` 四份文档存在且批准状态正确（verification：读取文件头）。

## Build And Automated Tests

- [x] 定向测试通过（verification：2026-08-20 执行以下命令，`31 passed in 7.05s`）：

```powershell
python -m pytest tests/test_session_runtime.py tests/test_wechat_bot.py tests/test_wechat_runtime.py tests/test_wechat_info_registry.py -q
```

- [x] 修改模块编译通过（verification：2026-08-20 执行以下命令无错误）：

```powershell
python -m compileall src/mewcode/session/runtime.py src/mewcode/wechat
```

- [x] 修改范围 Ruff 检查与格式检查通过（verification：2026-08-20 执行以下命令，`All checks passed`，20 个文件格式正确）：

```powershell
python -m ruff check src/mewcode/session/runtime.py src/mewcode/wechat tests/test_session_runtime.py tests/test_wechat_bot.py tests/test_wechat_runtime.py tests/test_wechat_info_registry.py
python -m ruff format --check src/mewcode/session/runtime.py src/mewcode/wechat tests/test_session_runtime.py tests/test_wechat_bot.py tests/test_wechat_runtime.py tests/test_wechat_info_registry.py
```

- [x] 全量测试通过并记录 passed/skipped 数量（verification：2026-08-20 最终执行 `python -m pytest -q`，`378 passed, 1 skipped in 28.06s`）。
- [x] 全量源码和示例编译通过（verification：2026-08-20 执行 `python -m compileall src/mewcode examples` 无错误）。
- [ ] 全量 Ruff 检查和格式检查通过（verification：2026-08-20 检查发现本功能范围以外的既有基线仍有 149 个 lint 问题、26 个格式文件；本次修改范围已通过，未批量改写其他章节代码与文档）。

## End-To-End Scenarios

- [ ] E2E-1 连续意图：专用测试好友在 7 秒内连续发送三条补充消息；机器人静默等待，随后只生成一次结合全部条件的回答（verification：真实微信观察时间线与日志）。
- [ ] E2E-2 自然闲聊：测试好友发送日常短消息；机器人返回 1～7 个自然短气泡，间隔有长度感且不显示 `<|bubble|>` 或 Markdown 包装（verification：真实微信观察）。
- [ ] E2E-3 专业长答：测试好友询问专业知识并包含 Windows 路径或代码；机器人返回可读纯文本，路径和代码正确，长文只在必要时分段（verification：真实微信逐字核对关键样例）。
- [ ] E2E-4 网页查询：测试好友提出需要公开资料的问题；机器人先发一次工作状态，再发专业摘要，最后单独发实际来源，读取多个页面不重复报进度（verification：真实微信和受控日志）。
- [ ] E2E-5 发送中打断：机器人发送多个闲聊气泡时，测试好友补充新条件；剩余旧气泡停止，新条件静默 7 秒后得到新回答，无取消提示（verification：真实微信观察）。
- [ ] E2E-6 工具中打断：机器人发出网页查询状态后，测试好友立即补充或改问；旧工具和旧结果停止，新消息重新聚合处理（verification：真实微信和日志）。
- [ ] E2E-7 跨好友 FIFO：两个授权测试好友接近同时完成静默窗口；回复按入队顺序完成，每名好友只收到自己的完整批次（verification：两个真实会话和日志对照）。
- [ ] E2E-8 身份与安全：测试好友询问机器人身份并尝试要求读取本机文件；机器人如实说明 AI 身份且无法获得本地权限（verification：真实微信回复与工具日志）。
