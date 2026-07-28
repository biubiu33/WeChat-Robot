# 子 Agent 与后台任务 Checklist

> 每项必须通过运行测试或观察到的行为验证；未记录证据不得标记完成。

## Implementation Completeness

- [ ] 主 Agent 无论角色目录如何变化，都只暴露一份固定参数结构的 `Agent` 工具，并在动态环境中看到当前角色的名称和说明（验证：目录增删覆盖测试与主请求断言）。
- [ ] 角色文件支持有效 frontmatter、大小写不敏感调用、项目/用户/内置优先级覆盖及可恢复诊断；无效内置定义使启动失败（验证：角色目录测试）。
- [ ] `general-purpose`、`explore`、`plan` 三个内置角色可发现且分别体现完整能力、只读探索和只读规划策略（验证：资源加载与角色元数据测试）。
- [ ] 定义式任务从空白对话和角色指令运行；Fork 任务克隆父历史、补齐未配对工具结果、附加 Fork 约束并强制后台（验证：运行时和消息序列测试）。
- [ ] 子 Agent 在没有新工具调用时返回最后 assistant 文本，在轮次上限时返回最后文本和明确上限错误（验证：RunToCompletion 定向测试）。
- [ ] 子 Agent 的消息、会话级授权、文件读缓存、用量和 Hook 状态相互隔离；仅创建时快照的父精确授权可复用（验证：隔离与权限快照测试）。
- [ ] 子工具调用保留前置 Hook、权限、执行和后置 Hook 顺序，但不发出用户会话生命周期 Hook（验证：事件记录测试）。
- [ ] 权限判定按父授权快照、永久规则、角色模式和主 TUI 批准升级；本次/会话授权不跨 Agent，只有 Allow Forever 写入永久规则（验证：权限与审批桥测试）。
- [ ] 黑名单、路径沙箱、参数校验和显式 deny 在任何子 Agent 权限模式下仍生效（验证：危险命令、越界路径和非法参数测试）。
- [ ] 子 Agent 永远看不到 `Agent` 与任务控制工具；子 Agent 加载 fork Skill 得到 `nested_agent_denied`，inline Skill 仍能使用（验证：工具作用域与 Skill 测试）。
- [ ] 同一 Agent 重复读取未变化文件可命中缓存；外部改动、成功写入或编辑后不返回过期内容；缓存不在父子或并行任务间共享（验证：缓存定向测试）。
- [ ] 调用指定后台、角色默认后台、运行超过 120 秒和执行阶段 ESC 均能将同一运行转为后台；Fork 始终后台；后台禁用时定义式强制前台且 Fork 返回错误（验证：任务管理测试）。
- [ ] 后台任务保存运行、完成、失败和取消状态及详情到进程退出；同名查询返回最新任务，旧任务 ID 仍有效，完成任务能接收续派消息（验证：任务管理测试）。
- [ ] 每个终态后台任务只在下一次主模型请求中注入一次不可见 `<task-notification>`；通知不写入可见对话、档案、记忆或压缩历史（验证：TUI/请求载荷测试）。
- [ ] 模型档案使用配置中的 Provider 名称解析；`inherit` 使用父 Provider，不存在档案返回结构化错误且不硬编码模型 ID（验证：Provider 选择测试）。
- [ ] 现有 Skill fork 复用公共子 Agent 路径，同时保留原有取消、隔离和摘要回流行为（验证：Skill fork 回归测试）。

## Integration

- [ ] 子 Agent 批准请求在主 TUI 显示来源，批准后原子任务继续；批准框内 ESC 等价于拒绝本次而不是转后台（验证：TUI 集成测试）。
- [ ] 主 Agent 能通过任务列表、详情、停止和续派工具管理任务，子 Agent 不可访问这些控制面工具（验证：工具集成测试）。
- [ ] 角色目录、后台服务和五个主 Agent 工具在启动时正确装配，并在关闭时取消运行任务和清理子 Hook 状态（验证：应用生命周期测试）。
- [ ] 已有 Provider、MCP、Skill、Hook、权限审批、会话恢复、上下文压缩和 Slash 命令行为没有回归（验证：相关既有测试全部通过）。

## Build And Tests

- [ ] 子 Agent 定向测试通过（验证：`python -m pytest -q tests/test_subagent_catalog.py tests/test_subagent_policy.py tests/test_subagent_cache.py tests/test_subagent_runtime.py tests/test_subagent_task.py tests/test_subagent_tool.py`）。
- [ ] 受影响的既有模块测试通过（验证：`python -m pytest -q tests/test_agent.py tests/test_permission.py tests/test_skill_fork.py tests/test_skill_tool.py tests/test_tui.py tests/test_config.py`）。
- [ ] 全量测试通过（验证：`python -m pytest -q`）。
- [ ] 静态检查通过（验证：`python -m ruff check src tests`）。

## End-To-End Scenarios

- [ ] 场景 1：主 Agent 读取角色目录并调用 `Agent(subagent_type="explore")` 执行短探索任务；子 Agent 只看到允许工具，前台返回最终文本，父对话只保留工具结果（验证：使用 FakeProvider 的端到端测试）。
- [ ] 场景 2：主 Agent 不传 `subagent_type` 发起 Fork；工具立即返回后台任务 ID，任务完成后下一次主请求收到一次通知，随后 `TaskGet` 返回完整结果（验证：使用受控异步 FakeProvider 的端到端测试）。
- [ ] 场景 3：定义式全工具子 Agent 请求需批准的写入；主 TUI 显示带来源的批准框，Allow Once 后写入执行，Allow Forever 后未来子任务可匹配永久规则（验证：TUI 与权限联合测试）。
- [ ] 场景 4：后台子 Agent 尝试调用 Agent、任务控制工具和 fork Skill；所有尝试被结构化拒绝，同时 inline Skill 继续可用（验证：工具作用域与 Skill 联合测试）。
- [ ] 场景 5：前台子 Agent 正在运行时按 ESC；同一任务转入后台且不中断，最终可查询；在权限批准框按 ESC 则仅拒绝该调用并让子任务继续（验证：TUI 状态机测试）。
