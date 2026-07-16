# 权限系统 Checklist

> 每项均须通过运行代码、测试或可观察的交互结果验证。除非另有说明，测试使用临时项目根，不执行真实高危命令。

## 实现完整性

- [ ] 黑名单在执行前拦截 Unix 与 Windows 的高危命令，且 `bypassPermissions` 不能绕过（验证：权限单测对 `rm -rf /`、`Remove-Item -Recurse -Force`、`del /s /q`、`format`、`diskpart`、`Clear-Disk` 返回 Deny，工具执行记录为空）。
- [ ] 文件类工具只能访问启动项目根及其子目录（验证：权限单测对项目外绝对路径与 `../outside` 返回 Deny，对项目内路径返回非 Deny）。
- [ ] 符号链接不会逃出路径沙箱，尚未存在的项目内多级新路径可以通过（验证：权限单测建立指向项目外的链接并断言 Deny，同时断言 `nested/new/file.txt` 通过）。
- [ ] 规则支持精确和 glob 匹配，友好工具名能路由六个内置工具（验证：`Bash(git status)`、`Bash(git *)`、`Write(src/**)` 及 Bash/Read/Write/Edit/Glob/Grep 的测试断言通过）。
- [ ] 未注册工具、无效 JSON、缺少必需文件路径和类别不明调用均不静默放行（验证：权限单测断言结果为 Ask 或 Deny）。

## 配置与裁决

- [ ] 三个 YAML 配置位置被正确加载：`~/.mewcode/settings.yaml`、`<root>/.mewcode/settings.yaml`、`<root>/.mewcode/settings.local.yaml`（验证：临时 home 与项目根测试分别注入规则并观察裁决）。
- [ ] 规则优先级为会话 > 本地 > 项目 > 用户，且同层 deny 优先 allow（验证：构造互相冲突的规则，断言最终裁决）。
- [ ] 配置文件缺失或 YAML/字段格式非法时降级为空规则集，不中断引擎构造（验证：权限单测传入缺失和非法文件，`new_engine` 仍返回可用引擎）。
- [ ] `default_mode` 按本地 > 项目 > 用户选择，均未配置时为 default（验证：临时三层配置测试各设置不同模式并断言 `engine.default_mode`）。
- [ ] 四档模式矩阵准确生效：default、acceptEdits、plan、bypassPermissions 均只产生 Allow 或 Ask（验证：对读、文件写、命令执行逐档断言；黑名单和沙箱仍优先 Deny）。
- [ ] 「允许本会话」只写入内存精确规则，并在当前引擎后续匹配调用中生效（验证：调用 `allow_session` 后断言 Allow，重建引擎后不再命中）。
- [ ] 「永久允许」写入本地 YAML 的精确 allow 规则，并在重建引擎后生效（验证：调用持久化后检查 YAML 内容并重建引擎断言 Allow）。

## Agent 集成

- [ ] 权限 Deny 被转换为带原工具调用 ID 的错误结果并回灌，Agent Loop 继续运行（验证：`tests/test_agent.py` 断言拒绝结果、调用 ID、后续模型轮次和最终回复）。
- [ ] 同一批多个工具调用中的允许和拒绝互不串位，结果按原调用顺序回灌（验证：混合允许/拒绝批次测试通过）。
- [ ] 连续只读工具仍并发执行，检查权限后不会触发人工确认（验证：并发计时测试通过且没有 `approval` 事件）。
- [ ] 计划模式仍只暴露只读工具；即使模型请求副作用工具，也不执行并返回原有计划模式限制结果（验证：现有计划模式回归测试通过）。
- [ ] Ask 事件支持允许本次、允许本会话、永久允许和拒绝本次四种结果（验证：Agent 测试逐项完成 Future，分别断言执行、内存规则、本地规则或拒绝回灌）。
- [ ] 人工确认等待中取消能结束当前轮且不遗留挂起任务，后续对话仍可进行（验证：Agent 取消测试后再运行一轮正常请求）。

## TUI 集成

- [ ] 状态栏左侧显示当前权限模式而不显示 provider 名，右侧仍包含模型名与 token 用量（验证：渲染 `status_bar`，断言 mode、model 和 token 文本）。
- [ ] Shift+Tab 仅在空闲态循环 default → acceptEdits → plan → bypassPermissions → default，跨轮保持（验证：TUI 测试模拟按键与后续对话，断言模式序列）。
- [ ] `/plan` 和 `/do` 仍能进入/退出计划流程，`/do` 固定切回 default 并注入执行指令（验证：现有 TUI 计划模式测试更新后通过）。
- [ ] Ask 时显示工具名、参数安全预览、原因与四项批准菜单；上/下、Enter、数字键 1-4 和快捷键均可回传决策（验证：TUI 测试驱动按键并断言 Future 结果和视图文本）。
- [ ] 在批准态按 Esc 或 Ctrl+C 只取消当前回合，不退出程序；输入框恢复可编辑并可提交下一条消息（验证：TUI run_test 中取消后完成后续一轮）。

## 边界与回归

- [ ] Anthropic 与 OpenAI provider 均通过同一 agent 权限路径；本章没有修改 provider 适配层（验证：权限测试使用 fake provider，且 `git diff -- src/mewcode/llm` 为空）。
- [ ] 现有多轮 ReAct、流错误恢复、用户取消、对话历史、缓存与系统提示注入没有退化（验证：`python -m pytest -q` 全部通过）。
- [ ] 本地永久规则文件不会被 Git 跟踪，配置样例为 UTF-8 且可被 YAML 解析（验证：检查 `.gitignore`、执行 YAML 解析测试与 UTF-8 测试）。

## 构建与静态检查

- [ ] Python 源码和示例可编译（验证：`python -m compileall src examples` 退出码为 0）。
- [ ] 全部测试通过（验证：`python -m pytest -q` 退出码为 0）。
- [ ] Ruff 格式和静态检查通过（验证：安装后运行 `ruff format --check .`、`ruff check .`；若安装 `mypy`，再运行 `mypy src`）。

## 端到端场景

- [ ] 默认模式文件写：模型请求项目内 `write_file` → TUI 显示批准块 → 选择「允许本次」→ 工具执行 → 模型收到成功结果并继续回复（验证：fake provider + TUI 集成测试）。
- [ ] 会话放行：模型首次请求同一命令 → 选择「允许本会话」→ 后续匹配命令无需再次批准；重启引擎后恢复默认裁决（验证：Agent/权限集成测试）。
- [ ] 永久放行：模型请求项目内操作 → 选择「永久允许」→ 本地配置出现精确规则 → 新引擎匹配调用自动放行（验证：临时项目根测试）。
- [ ] 危险命令：模型请求 Windows 或 Unix 高危删除/格式化命令 → 无论权限模式或用户配置为何均直接拒绝 → 模型收到原因后可继续选择安全替代方案（验证：Agent 集成测试）。
- [ ] 路径逃逸：模型请求通过 `../` 或符号链接读写项目外文件 → 直接拒绝且不执行 → 模型改用项目内路径后可继续完成任务（验证：Agent 集成测试）。
