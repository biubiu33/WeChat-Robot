# 系统提示工程化 Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为；括号内为验证方式与对应需求。

## 实现完整性
- [ ] 模块化装配：系统提示由按优先级排列的固定模块拼成、模块间空行分隔（验证：`tests/test_prompt.py` 断言身份段在工具使用段之前、以空行分隔）。(AC1/F1)
- [ ] 挂载即扩展：新增一个模块只需出现在模块列表，装配自动按优先级插入，不改 `assemble_system` 逻辑（验证：`tests/test_prompt.py` 传入额外模块断言其落在预期位置）。(AC1/F1)
- [ ] 可选空槽：自定义指令/已激活 Skill/长期记忆内容为空时装配跳过、不留多余空行（验证：`tests/test_prompt.py` 断言空模块不出现、无连续空行）。(AC2/F1)
- [ ] 缓存确定性：连续两次构造稳定系统提示逐字节相等；改变环境信息不改变稳定块（验证：`tests/test_prompt.py` 断言两次 `build_system_prompt()` 相等、稳定块不含 date/git/cwd）。(AC5/F3/N1)
- [ ] 环境信息呈现：系统提示第二段含工作目录、平台、当前日期、git 状态、版本、模型；与稳定块分属不同内容块（验证：`tests/test_prompt.py` 断言 `Environment.render()` 含各项；Anthropic 请求 `system` 为两个文本块）。(AC3/F2)
- [ ] 双重强化：关键约定（优先用专用工具、编辑前必先读）在工具描述与系统提示模块文本中均出现（验证：`tests/test_prompt.py` 断言系统提示含相关语句；检索 `edit_file`/`bash` `DESCRIPTION` 含强化语句）。(AC7/F5)
- [ ] 补充消息注入机制：`plan_reminder` 输出以 `<system-reminder>` 标签包裹（验证：`tests/test_prompt.py` 断言标签存在）。(AC8/F6)
- [ ] 缓存字段解析：provider 用量对外暴露缓存写/读；Anthropic 取 `cache_creation_input_tokens`/`cache_read_input_tokens`，OpenAI 取 `cached_tokens`，缺字段为 0 不抛异常（验证：`tests/test_agent.py` fake 发缓存用量断言 `Event.usage` 透传；smoke 打印真实字段）。(AC6/F4/N6)
- [ ] Anthropic 缓存断点真实发出：稳定块序列化后带 `cache_control: {"type": "ephemeral"}`、环境块不带（验证：`tests/test_anthropic_system.py` 断言——守护回归）。(AC4/F3)

## 集成
- [ ] 规划模式按轮次注入：`/plan` 后 iter1 注入完整提醒、间隔轮（每 4）重复完整、其余轮精简；reminder 不写入持久历史（验证：`tests/test_agent.py` 多轮脚本断言各轮 `req.reminder` 详略 + `conv.messages()` 不含 reminder 文本）。(AC9/F6/F7)
- [ ] 规划模式工具集：规划模式 `req.tools` 仅只读、普通模式全量（验证：`tests/test_agent.py` 断言两模式 tools 差异）。(AC9/F7)
- [ ] 稳定系统提示跨模式一致：普通与规划模式 `req.system.stable` 相同（规划提醒已移出系统通道）（验证：`tests/test_agent.py` 断言两模式 stable 相等）。(F7/N1)
- [ ] 历史合法：注入 reminder 后请求消息序列角色合法（Anthropic 并入末条 user、不产生连续 user）（验证：`tests/test_agent.py` 断言织入后末条仍为单一 user 回合；端到端 plan 多轮不报 400）。(AC12/N3)
- [ ] 跨协议一致：anthropic 与 openai（含兼容 base_url）都装配同一系统提示 + 环境段、注入同一 reminder（验证：两配置各跑多轮；anthropic 看缓存命中、openai 看 `cached_tokens`）。(AC10/F8)
- [ ] 不破坏 ch04：多轮连环、用户取消、流出错恢复、历史一致仍成立（验证：跑 ch04 端到端关键场景；`pytest` 通过）。(AC11/N2)
- [ ] 环境采集降级：非 git 目录/git 不可用时环境段对应项省略、不卡界面、请求正常发起（验证：在非 git 临时目录跑 smoke/TUI 观察）。(AC13/N4)
- [ ] 界面不阻塞：环境采集（含 git 外调）不冻结界面、不显著拖慢首字（验证：正常目录跑，观察发起延迟无异常；git 调用以 `subprocess.run(..., timeout=2)` 或 `asyncio.to_thread` 收口）。(N4)

## 编译与测试
- [ ] `python -m mewcode` 在合法配置下能正常启动。
- [ ] `ruff check .` 无告警。
- [ ] `ruff format --check .` 通过。
- [ ] `pytest` 通过（`tests/test_config.py`、`tests/test_conversation.py`、`tests/test_tool.py`、`tests/test_agent.py`、`tests/test_prompt.py`、`tests/test_anthropic_system.py`）。
- [ ] （可选）`mypy src/mewcode` 通过子集检查。(N2/N6)
- [ ] 密钥不回显：对话区、环境段与任何输出均不出现 `api_key`（验证：通读输出、检索无明文 key；确认环境段不含环境变量）。(AC14/N5)

## 端到端场景（tmux 实跑）
- [ ] 场景 1（缓存命中，Anthropic）：同一会话连发两条消息 → smoke/调试打印首轮 `cache_write > 0`、次轮 `cache_read > 0`，证明稳定前缀被缓存复用。(AC4/F3)
- [ ] 场景 2（规划模式按轮次）：`/plan` 发一个需多步只读调研的任务 → 模型仅用只读工具产出计划、首轮注入完整提醒、后续轮精简；`/do` 切回全工具并按计划执行（产生写/执行类调用）。(AC9/F7)
- [ ] 场景 3（reminder 不被当用户输入）：规划模式下模型不复述/回应 `<system-reminder>` 内容，而是据其约束行事。(AC8/F6)
- [ ] 场景 4（环境感知）：问「我现在在哪个目录、什么平台、今天几号」→ 模型据环境段正确回答。(AC3/F2)
- [ ] 场景 5（取消后可继续）：规划模式多轮中途按 Esc 取消 → 回空闲态、再发一条继续对话不报 400。(AC12/N3)
- [ ] 场景 6（非 git 目录降级）：在非 git 目录启动 → 环境段省略 git 状态、正常对话。(AC13/N4)
