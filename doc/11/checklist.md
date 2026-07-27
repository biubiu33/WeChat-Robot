# Hook 生命周期挂钩系统 Checklist

> 每一项均须通过运行代码、测试或可观察行为验证；验收时记录实际命令输出或观察结果。

## Implementation Completeness

- [ ] 权限规则支持精确、glob、正则和递归反向匹配；旧 glob 规则保持可用，非法规则输出原因但不阻断其他规则（验证：`conda run -n mewcode python -m pytest -q tests/test_permission.py`）。
- [ ] 项目级与用户级 `hooks.yaml` 合并加载，同名后加载规则跳过；缺失文件静默，坏文件和坏单条规则输出 stderr 后继续（验证：`conda run -n mewcode python -m pytest -q tests/test_hook_config.py`）。
- [ ] Hook 仅接受批准的字段、11 个事件、四种动作、合法超时和单一 `all_of` / `any_of` 条件组；非法 event、条件、Pattern、async 组合和动作字段均被诊断跳过（验证：`conda run -n mewcode python -m pytest -q tests/test_hook_config.py`）。
- [ ] 所有事件 payload 均含 event、session_id、cwd、mode，并按事件提供工具、prompt、通知、压缩或迭代特化字段；嵌套字段缺失按空字符串匹配（验证：`conda run -n mewcode python -m pytest -q tests/test_hook_engine.py`）。
- [ ] shell 动作通过 stdin 接收稳定排序 JSON，超时/失败仅写规定格式 stderr；subagent 仅写固定的未实现日志（验证：`conda run -n mewcode python -m pytest -q tests/test_hook_actions.py -k "shell or subagent"`）。
- [ ] prompt 动作原样进入下一次请求的隐藏 reminder、位于 plan reminder 后、消费一次后清空，并且 `prompt + async` 在加载期被拒绝（验证：`conda run -n mewcode python -m pytest -q tests/test_hook_actions.py tests/test_hook_engine.py -k prompt`）。
- [ ] HTTP 动作使用默认 JSON 或受限 `{field}` body，正确处理 headers、timeout、模板失败和 block 响应（验证：`conda run -n mewcode python -m pytest -q tests/test_hook_actions.py -k http`）。
- [ ] `only_once` 在当前会话采用预留、成功确认、失败释放语义；异步任务完成后确认或释放，切换会话后状态重置且不持久化（验证：`conda run -n mewcode python -m pytest -q tests/test_hook_engine.py -k once`）。
- [ ] 非阻塞 async Hook 不暂停主流程，阻塞事件的 Hook 串行且不允许 async；取消会及时传播并清理后台任务（验证：`conda run -n mewcode python -m pytest -q tests/test_hook_engine.py -k "async or cancel"`）。

## Integration

- [ ] 首次会话、关闭、恢复、普通用户提交、每次模型请求、自然停止、工具前后、压缩前后及通知均在正确时刻触发对应事件（验证：`conda run -n mewcode python -m pytest -q tests/test_agent.py tests/test_tui.py tests/test_tui_resume.py tests/test_context_artifact.py -k hook`）。
- [ ] 用户提交 Hook 在消息入档前执行；拦截后输入保留、显示 `[hook <name>] <reason>`，不写对话、JSONL 或回合统计（验证：`conda run -n mewcode python -m pytest -q tests/test_tui.py -k "hook and submit"`）。
- [ ] 工具前 Hook 在权限检查和真实执行前运行；退出码 2 或 HTTP block 返回带 Hook 原因的错误工具结果，跳过权限和工具；退出码 0 与普通失败正确放行（验证：`conda run -n mewcode python -m pytest -q tests/test_agent.py -k "hook and tool"`）。
- [ ] 每个工具结果（包括权限拒绝）在结束事件前触发后置 Hook，且既有只读工具并行执行语义不退化（验证：`conda run -n mewcode python -m pytest -q tests/test_agent.py -k "hook or read_batch or permission"`）。
- [ ] 审批请求与流错误均触发 Notification；自然完成在 Done 前触发 Stop，取消、流错误和异常结束不触发 Stop（验证：`conda run -n mewcode python -m pytest -q tests/test_agent.py -k "hook and (notification or stop)"`）。
- [ ] 估算进入安全余量、达到硬窗口、以及 `/compact` 分别发出 auto、emergency、manual 压缩事件，并携带压缩前后 Token；未安装观察者时保持原压缩行为（验证：`conda run -n mewcode python -m pytest -q tests/test_context_artifact.py tests/test_context_budget.py`）。
- [ ] `/hooks` 按事件显示 Hook 名称、动作、once/async 标记和来源；无 Hook 时只显示 `No hooks loaded.`，且命令不创建会话或模型请求（验证：`conda run -n mewcode python -m pytest -q tests/test_command.py tests/test_tui_command.py -k hooks`）。
- [ ] README 说明配置位置、事件、条件、动作、拦截、控制项、`/hooks` 和范围外能力（验证：`rg -n "Hook|hooks.yaml|PreToolUse|only_once|/hooks|subagent" README.md`）。

## Build And Tests

- [ ] Hook 定向测试通过（验证：`conda run -n mewcode python -m pytest -q tests/test_permission.py tests/test_hook_config.py tests/test_hook_actions.py tests/test_hook_engine.py tests/test_agent.py tests/test_tui.py tests/test_tui_command.py tests/test_context_artifact.py`）。
- [ ] 全量测试通过且没有既有功能回归（验证：`conda run -n mewcode python -m pytest -q`）。
- [ ] 源码和测试可编译（验证：`conda run -n mewcode python -m compileall -q src tests`）。
- [ ] Ruff 静态检查通过（验证：`conda run -n mewcode ruff check .`）。
- [ ] Ruff 格式检查通过（验证：`conda run -n mewcode ruff format --check .`）。

## End-To-End Scenarios

- [ ] 场景 1：项目配置的 PreToolUse shell Hook 针对 `write_file` 返回退出码 2 -> 真实写入不发生 -> Agent 收到 `[hook <name>]` 原因并在下一请求调整（验证：FakeProvider + RecordingTool 集成测试通过）。
- [ ] 场景 2：SessionStart prompt Hook -> 首个 LLM 请求的 reminder 同时保留 plan reminder 和 Hook 文本 -> 第二个请求不再包含 Hook 文本 -> 对话档案中没有该文本（验证：两轮 FakeProvider 请求与 JSONL 断言通过）。
- [ ] 场景 3：PostToolUse async shell Hook 格式化成功或失败 -> 主 Agent 不等待 -> 失败仅有 stderr 日志 -> `/clear` 后同一 only_once Hook 在新会话可再次触发（验证：临时 Hook YAML、Python 子进程与 TUI 会话测试通过）。
- [ ] 场景 4：本地 HTTP PreToolUse 策略返回 block -> 对应工具被拒绝；网络失败和非 block 响应 -> 工具照常执行（验证：进程内 HTTP server 与 Agent 集成测试通过）。
- [ ] 场景 5：UserPromptSubmit shell Hook 拦截含敏感关键词的输入 -> 输入框显示原因且仍可编辑 -> 会话恢复、`/hooks`、权限审批、压缩和普通对话保持可用（验证：TUI 集成测试通过）。
