# Agent Loop Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为；括号内为验证方式与对应需求。

## 实现完整性
- [ ] 多轮自动连环：需要连续两步工具的任务，Agent 无需中途催促即自动多轮执行工具直到给出最终答复（验证：`python -m mewcode` 跑「读 A 文件 → 据内容新建 B 文件」，观察 `read_file` 与 `write_file` 跨多轮依次出现、最终答复）。(AC1/F1)
- [ ] 自然完成停止：模型给出无工具调用的纯文本即停（验证：`tests/test_agent.py` 场景 A 断言收到最终 `text` + `done=True`，循环不再发起请求）。(AC2/F2)
- [ ] 迭代上限兜底：模型反复调工具时达到 `MAX_ITERATIONS` 即停并提示，不无限循环（验证：`tests/test_agent.py` 场景 B 断言恰好上限轮后停 + `notice == NOTICE_MAX_ITER`）。(AC3/F2)
- [ ] 连续未知工具停止：连续 `MAX_UNKNOWN_RUN` 轮只产生未知工具调用即停；混入已注册工具则计数重置（验证：`tests/test_agent.py` 场景 C 两路断言）。(AC4/F2)
- [ ] 流出错恢复：provider 流出错时停止本轮、发 `err`、程序不退出（验证：端到端临时改坏 `base_url` 发一条，观察错误块 + 仍可继续；`tests/test_agent.py` 注入 err 脚本断言收到 err 后停）。(AC5/F2)
- [ ] 事件流完备：Agent 对外事件含文本 / 工具开始 / 工具结束 / `usage` / `iter` / `notice` / `done` / `err`（验证：`tests/test_agent.py` 断言一次多轮运行收集到的事件类型集合覆盖上述各类；端到端跑多轮任务，界面实时显示文本增量、工具进度、轮次、用量、最终答复，证明界面所需信息均来自事件流）。(AC6/F3)
- [ ] 流式收集双路：文本实时显示的同时，完整工具调用（拼齐 JSON 参数）被收集用于下一轮（验证：`tests/test_agent.py` 断言 `ToolCall.input`/`args` 完整可解析；端到端工具行参数与请求一致）。(AC7/F4)
- [ ] 保序分批并发：一次回复含多个工具时，连续只读并发执行、有副作用串行，结果按原序回灌（验证：`tests/test_agent.py` 场景 D 用插桩工具断言两只读的执行时间窗重叠（并发峰值 ≥2）、有副作用工具在其后开始、最终写入历史的工具结果顺序与模型调用序一致——按结果内容/ID 比对，与函数名无关）。(AC8/F5/N6)
- [ ] 取消历史一致：执行中取消后历史配对合法（有 tool_results、末尾 assistant 文本、无悬空 tool_use）（验证：`tests/test_agent.py` 场景 E 断言 `conv` 序列；端到端取消后再发一条不报 400）。(AC9/F6)
- [ ] 用户取消：流式态 Esc 或 Ctrl+C 中断本轮回空闲态、不退出；空闲态 Ctrl+C 退出（验证：端到端各按一次观察行为）。(AC10/F7)
- [ ] 用量展示：状态栏显示会话累计 token（输入/输出），随轮次增长更新（验证：端到端跑多轮观察状态栏数值递增）。(AC11/F8)
- [ ] 进度展示：流式态动态区显示当前迭代轮次（验证：端到端跑多轮任务观察「第 N 轮」递增）。(AC12/F9)
- [ ] Plan Mode：`/plan` 后只出现只读工具与计划文本、无写/执行；`/do` 切回全工具并立即按计划执行（验证：端到端 Plan Mode 场景；`tests/test_agent.py` 场景 F 断言 `Mode.PLAN` 下 fake 收到的 `tools` 仅只读）。(AC13/F10)

## 集成
- [ ] 跨协议一致：anthropic 与 openai（含兼容 `base_url`）跑同一多轮任务，触发/执行/回灌/用量/取消行为一致（验证：两种配置各跑多轮场景）。(AC14/F11/N3)
- [ ] 多轮历史正确携带：每轮 `assistant(tool_use)` 回合 + `tool_result` 回合按序入历史并被下一轮请求携带（验证：`tests/test_agent.py` 断言 `conv` 末尾序列；或抓请求体见历史增长）。(F6)
- [ ] 界面不阻塞：多轮循环与工具执行（含并发批）期间 spinner / 轮次 / 计时持续刷新（验证：跑含稍慢 `bash` 的任务，观察界面不冻结）。(N2)
- [ ] scrollback 顺序正确：跨多轮 preamble → 工具行 → 结果摘要 → 最终答复按序出现不交错，并发批的工具行按模型调用序排列（验证：跑一个含并发只读批 + 后续写的多轮任务，回滚 `RichLog` 肉眼核对各块严格按发生顺序连续、无交错、并发工具行顺序==调用序）。(N3)
- [ ] 结果体量受控：大文件 / 长输出 / 海量命中被工具级上限截断标注 `[truncated]`，多轮累积不撑爆（验证：多轮中读大文件 / 跑长输出命令观察截断）。(N4)
- [ ] 取消无泄漏：取消后无挂起 asyncio task / 无未关闭 queue（验证：`pytest tests/test_agent.py` 含取消用例（场景 E）通过；端到端反复触发取消后继续对话多次，进程内存/句柄稳定不增长）。(N5/N6)
- [ ] 系统提示体现 Agent 循环：问「你能做什么」答复体现可多步使用工具完成任务（验证：发一条询问观察答复）。(F3)

## 编译与测试
- [ ] `python -m mewcode` 能正常启动（在合法配置下进入 TUI）。
- [ ] `ruff check .` 无告警。
- [ ] `ruff format --check .` 通过（或本地 `ruff format .` 已统一格式）。
- [ ] `pytest` 通过（`test_config`、`test_conversation`、`test_tool`、`test_agent` 等单测）。
- [ ] （可选）`mypy src/mewcode` 通过。
- [ ] 密钥不回显：对话区与任何输出均不出现 `api_key`（验证：通读运行输出、检索无明文 key）。(N7)

## 端到端场景
- [ ] 场景 1（多轮连环）：openai 兼容端点 → 「读 `docs/ch03/spec.md`，再据内容新建 `docs/ch03/summary.txt` 写一句话摘要」→ `read_file` → `write_file` 跨多轮自动出现 → 状态栏用量增长、动态区轮次递增 → 最终答复 → `/exit` 无残留。
- [ ] 场景 2（用户取消）：发一个多步任务，中途按 Esc（再试 Ctrl+C）→ 回空闲态不退出 → 再正常发一条继续对话（历史未坏，无 400）。
- [ ] 场景 3（流出错恢复）：临时改坏 `base_url` 发一条 → 错误块 + 程序不退出 → 改回后继续正常对话。
- [ ] 场景 4（Plan Mode）：`/plan` → 问一个改动类需求 → 只出现 read/glob/grep + 计划文本、无写/执行 → `/do` → 切回全工具并按计划执行（出现 write/edit/bash）。
- [ ] 场景 5（跨协议，若有 anthropic 配置）：切到 anthropic 配置重跑场景 1 → 多轮行为与 openai 一致。
- [ ] 场景 6（迭代上限）：主要由 `tests/test_agent.py` 场景 B 确定性验证；可选手动复现——临时把 `MAX_ITERATIONS` 改小（如 3）跑一个会多步调工具的任务，观察第 3 轮后停并显示 `NOTICE_MAX_ITER`、之后仍可继续对话。
- [ ] 场景 7（连续未知工具）：主要由 `tests/test_agent.py` 场景 C 确定性验证；可选手动复现——在 system prompt 临时引导模型调用一个不存在的工具名，观察连续 `MAX_UNKNOWN_RUN` 轮后停并显示 `NOTICE_UNKNOWN_TOOLS`、之后仍可继续对话。
