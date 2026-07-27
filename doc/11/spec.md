# Hook 生命周期挂钩系统 Spec

## 背景

MewCode 现有的 Skill 和 Slash 命令均需要用户显式触发。对于文件格式化、工具调用
拦截、上下文提醒和外部通知等“触发条件明确、动作固定”的重复工作，用户需要自行
执行或维护额外脚本。

本功能在 Agent 生命周期的固定时刻运行由 YAML 声明的 Hook。它补充既有权限系统：
权限系统决定工具调用是否允许，Hook 还可以执行自动化、注入一次性提示和发送通知。

## 目标

- 以固定生命周期事件驱动声明式 Hook，减少用户手动重复操作。
- 让 Hook 条件和权限规则共享精确、反向、正则和 glob 四种匹配语义。
- 支持 shell、提示词、HTTP 和子 Agent 占位四种动作。
- 在工具调用和用户提交前提供可解释的拦截，使模型或用户可以调整后续行为。
- 保持 Hook 配置错误和运行失败不会中断 MewCode 主流程。

## Functional Requirements

- F1: 权限规则的匹配模式扩展为 `exact`、`not`、`regex` 和 `glob`。既有未显式
  标记的权限规则继续按 glob 语义工作；规则解析或正则编译失败须输出 stderr 诊断并
  跳过该规则，不影响其他规则或启动。
- F2: Hook 从 `<projectRoot>/.mewcode/hooks.yaml` 和 `~/.mewcode/hooks.yaml` 在
  启动期加载。两层规则按加载顺序和各自 YAML 声明顺序共同分派；同名 Hook 输出冲突
  诊断并跳过后加载的定义。文件缺失不报错，YAML 或顶层结构非法时输出 stderr 后继续。
- F3: 每个 Hook 必须有唯一 `name`、有效 `event` 和有效 `action`；可选 `if` 省略时
  无条件触发，可选 `only_once`、`async` 和 `timeout` 使用规定默认值。未知字段、
  缺失必填字段、非法动作或非法事件均使该 Hook 被诊断并跳过。
- F4: 支持以下 11 个事件：`SessionStart`、`SessionEnd`、`SessionResume`、
  `UserPromptSubmit`、`Stop`、`PreUserMessage`、`PreToolUse`、`PostToolUse`、
  `PreCompact`、`PostCompact` 和 `Notification`。它们分别在会话开始、结束或恢复，
  用户消息提交、自然结束、模型请求前、工具前后、上下文压缩前后和审批或流错误通知时
  触发。
- F5: 每个事件提供稳定 payload，均包含事件名、会话 ID、工作目录和当前权限模式。
  工具事件额外提供工具名、输入、结果摘要和错误状态；消息事件提供 prompt；通知事件
  提供类型与详情；压缩事件提供触发来源和压缩前后 Token；自然停止事件提供迭代数。
  估算请求长度达到或超过模型 `context_window` 时，压缩事件的触发来源为 `emergency`；
  仅进入既有安全余量时为 `auto`；由 `/compact` 发起时为 `manual`。
- F6: 条件仅支持一个 `all_of` 或 `any_of` 原子条件数组，二者不可同时出现或嵌套混用。
  原子条件通过点分字段路径读取 payload，缺失路径按空字符串处理。匹配对象只支持
  `exact`、`glob`、`regex` 和递归 `not`；匹配器在加载期构造并在运行期复用。
- F7: `shell` 动作接收命令和可选超时。执行时将稳定字段顺序的事件 payload JSON 写入
  标准输入。非拦截事件的命令失败、超时或启动失败只写 stderr 日志。
- F8: `prompt` 动作将原样文本加入下一次模型请求的 reminder 区，按 Hook 声明顺序位于
  既有计划 reminder 之后。提醒仅本轮有效，不进入可见对话、JSONL、长期记忆或压缩
  历史。`prompt` 动作不得设置 `async: true`。
- F9: `http` 动作支持 URL、方法、头和请求体。缺省请求体为事件 payload JSON；显式
  body 仅支持基于 payload 的 `{field}` 基础插值。网络、超时或模板错误只写 stderr 日志。
- F10: `subagent` 动作必须声明目标名称和提示词，但首期仅输出固定的未实现日志，不运行
  子 Agent，也不阻断主流程。
- F11: `PreToolUse` 和 `UserPromptSubmit` 是拦截事件，禁止 `async: true`。同步 shell
  动作以退出码 2 表示拦截，并使用 stderr 或 stdout 文本作为原因；退出码 0 放行，其余
  非零退出视为 Hook 失败且放行。同步 HTTP 动作仅在 2xx 响应体为
  `{"decision":"block","reason":"..."}` 时拦截；其他响应或 HTTP 失败均放行。
- F12: 工具被 Hook 拦截时，跳过权限检查和真实执行，并把 `[hook <name>] <reason>` 作为
  错误工具结果返回模型；工具开始/结束事件仍正常发出。用户提交被拦截时，消息不进入
  对话或档案，界面显示同格式原因并让用户继续编辑。
- F13: `only_once: true` 仅在当前会话生效。首次匹配时先预留，以避免并发重复；动作成功
  后确认标记，失败则释放预留以允许重试。异步动作在后台任务完成后确认或释放。`/clear`
  和 `/resume` 切换会话时清空标记，进程退出不持久化。
- F14: `async: true` 的 shell、HTTP 和子 Agent 动作在后台运行，不阻塞 Agent。拦截事件
  与 `async` 的组合、以及 `prompt` 与 `async` 的组合均为加载错误。所有失败统一以
  `[hook <name>] <event> failed: <reason>` 写 stderr，不重试、不创建专属日志或 UI 通知。
- F15: 新增无参数本地命令 `/hooks`，按事件分组列出已加载 Hook 的名称、事件、动作类型和
  `[once]` / `[async]` 标志，并显示来源文件；没有 Hook 时输出 `No hooks loaded.`。

## Non-Functional Requirements

- N1: Hook 加载和校验只在启动期进行；单条或整个配置文件失败不得阻断 MewCode 启动。
- N2: 事件分派和后台任务必须正确传播取消，避免阻塞 Agent Loop。
- N3: 拦截事件中的同步 Hook 串行执行，单条动作各自应用 timeout。
- N4: Hook 提醒与现有 plan reminder 具有相同的历史、压缩和 Token 估算边界。
- N5: Hook 条件和权限规则必须复用同一匹配实现，并覆盖空串、转义、嵌套反向和空路径。
- N6: 现有 Provider、MCP、权限模式、审批、会话、上下文压缩、Agent 事件流和 Slash 命令
  行为不得退化。

## Out of Scope

- 子 Agent 动作的真实执行。
- `only_once` 标记跨进程持久化。
- Hook 显式优先级、热更新、依赖、互斥、重试或独立日志文件。
- Hook 配置的 `@include`、继承和专属环境变量入口。
- 新增或迁移 `permissions.yaml`；权限规则继续使用项目现有的 `settings.yaml` 与
  `settings.local.yaml` 配置结构。
- `$EVENT`、`$TOOL_ARGS.xxx` 等变量替换；shell 仅从 stdin JSON 读取 payload，prompt
  原样注入，HTTP 仅在 body 中支持 `{field}`。

## Acceptance Criteria

- AC1: 既有 glob 权限规则与新增精确、反向和正则规则按预期匹配；非法规则输出诊断但其他
  规则仍可用。
- AC2: 项目级和用户级 hooks 文件合并加载；同名后加载 Hook 被跳过；无 Hook 时 `/hooks`
  输出 `No hooks loaded.`。
- AC3: 缺失字段、未知事件、非法条件、正则错误、重复名称和非法 async 组合均被诊断并只
  跳过相应 Hook。
- AC4: `PreToolUse` shell 以退出码 2 拦截工具，模型收到带 Hook 名和原因的错误结果，真实
  工具未执行；退出码 0 放行，其他非零退出只记录失败并放行。
- AC5: `PreToolUse` HTTP 在 block 决策时拦截工具；网络、超时和非 block 响应只记录失败或
  放行。
- AC6: `UserPromptSubmit` 拦截能阻止消息入档并在输入区域显示原因。
- AC7: `SessionStart` 的 prompt 在首个模型请求中以隐藏 reminder 出现，下一轮自动移除，且
  不进入档案、记忆或压缩历史。
- AC8: PostToolUse 的异步 shell 格式化不暂停主对话；失败仅输出规定格式的 stderr 日志。
- AC9: `only_once` Hook 在同一会话只在成功后运行一次；失败可重试，`/clear` 或 `/resume`
  后在新会话可再次运行。
- AC10: 所有 11 个事件在规定生命周期时刻提供正确 payload。工具拒绝、权限审批和流错误
  均覆盖；估算值仅进入安全余量时触发 `auto` 压缩、达到或超过 `context_window` 时触发
  `emergency` 压缩、`/compact` 时触发 `manual` 压缩。
- AC11: subagent Hook 通过固定格式日志表明已跳过，主流程保持可用。
- AC12: 全量测试、编译、静态检查和格式检查通过，现有核心功能无回归。
