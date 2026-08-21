# 微信提示词文件化与原始回复日志 Checklist

状态：已完成

> 每一项必须通过运行代码、检查构建产物或观察控制台输出验证。

## Implementation Completeness

- [x] `role.md` 是非空 UTF-8 文件，包含朋友型 AI 角色、真实身份、关系边界、现实经历边界和权限边界。（verification：读取文件并检查关键规则）
- [x] `reply_policy.md` 是非空 UTF-8 文件，包含严格气泡协议、专业回答协议、Markdown 边界和代表性示例。（verification：读取文件并检查关键规则）
- [x] Python 代码中不再保留原来的大段硬编码 `WECHAT_REPLY_POLICY` 或默认角色字符串。（verification：搜索旧常量正文和最终 diff）
- [x] 微信配置数据结构不包含 `system_prompt`。（verification：配置单元测试和数据结构字段检查）
- [x] 旧配置中残留的 `system_prompt` 被忽略，不能覆盖 `role.md`。（verification：带冲突旧角色的配置与运行时测试）
- [x] 两个提示词使用标准库包资源接口加载并在进程内缓存。（verification：代码检查和重复构造运行时测试）
- [x] 任一提示词文件缺失、不可读或内容为空时给出包含文件名的明确配置错误。（verification：资源加载失败测试）
- [x] 系统提示词顺序固定为角色、回复协议、可选信息工具策略。（verification：运行时请求断言）

## Raw Reply Console Output

- [x] 每次成功的模型最终回复打印固定开始标签、未经转换的正文和固定结束标签。（verification：捕获标准输出测试）
- [x] 原始输出保留 `<|bubble|>`、空行、换行和 Markdown 字符。（verification：包含这些字符的捕获输出断言）
- [x] 输出发生在 `strip`、来源净化、Markdown 清理和气泡切分之前。（verification：原始输出与最终 `WechatReply` 对照测试）
- [x] 输出结束后立即刷新，不受 `wechat.log_level` 过滤。（verification：代码检查使用直接控制台输出且启用 flush）
- [x] 原始输出不附带系统提示词、API 密钥、工具参数、调用栈或会话档案。（verification：捕获输出负向断言）
- [x] 取消、超时和模型错误且没有成功最终回复时不打印原始成功标签。（verification：三条失败路径测试）

## Reply Protocol

- [x] 日常闲聊的唯一气泡边界是 `<|bubble|>`，协议明确禁止用换行、空行或标点替代。（verification：提示词内容断言）
- [x] 多个完整句子、问题或独立语义点被严格要求分成多个气泡。（verification：提示词内容和 few-shot 断言）
- [x] 单一短确认、情绪或笑声允许保持一个气泡。（verification：提示词内容断言）
- [x] 专业知识、步骤、代码、资料和工具结果明确禁止使用气泡标记。（verification：提示词内容断言）
- [x] 显式 `第一条<|bubble|>第二条` 仍生成两条聊天消息且不泄露标记。（verification：回复整形测试）
- [x] 只有换行而没有标记的文本仍走专业正文路径，不进行启发式气泡切分。（verification：回复整形测试）

## Integration And Safety

- [x] `WechatAgentRuntime` 初始化时加载提示词，所有好友 Session 共用相同角色和协议。（verification：多会话运行时测试）
- [x] 信息工具启用时，现有安全策略仍位于角色和回复协议之后。（verification：信息工具系统提示测试）
- [x] 不新增提示词路径配置、第三方依赖、模型调用或日志文件。（verification：配置、依赖和代码 diff 检查）
- [x] 微信双版本 UIA、白名单、去重、Session 隔离、全局 FIFO、取消和发送前目标复核逻辑没有被改写。（verification：相关文件 diff 与专项测试）
- [x] README 删除 `wechat.system_prompt` 示例和说明，并说明两个提示词文件与本地控制台隐私风险。（verification：README 搜索和人工检查）
- [x] 用户工作区中与本任务无关的未提交修改被保留。（verification：最终 diff 与初始状态对照）

## Build And Tests

- [x] 修改的 Python 模块可编译。（verification：`python -m compileall src/mewcode/wechat/config.py src/mewcode/wechat/runtime.py`）
- [x] 修改范围 Ruff 检查通过。（verification：对两个模块和两个测试文件运行 `ruff check`）
- [x] 修改范围 Ruff 格式检查通过。（verification：对两个模块和两个测试文件运行 `ruff format --check`）
- [x] 配置与运行时专项测试通过。（verification：`python -m pytest tests/test_wechat_config.py tests/test_wechat_runtime.py -q`）
- [x] 微信机器人和 UIA 回归测试通过。（verification：运行 bot 与 UIA driver 测试）
- [x] 全量自动化测试通过，或只存在已确认与本次无关的基线失败。（verification：`python -m pytest -q` 并记录结果）
- [x] 构建的 wheel 包含 `mewcode/wechat/prompts/role.md` 和 `mewcode/wechat/prompts/reply_policy.md`。（verification：构建并列出 wheel 归档）
- [x] Git diff 没有空白错误，依赖文件没有新增改动。（verification：`git diff --check` 和依赖文件 diff）

## End-To-End Scenarios

- [x] E2E-1：模型返回 `你好<|bubble|>最近怎么样？`，控制台先完整显示原始文本，发送层随后得到两个聊天气泡。（verification：运行时集成测试与捕获输出）
- [x] E2E-2：模型返回 `第一段\n\n第二段` 且无标记，控制台保留空行，发送层保持一条专业正文。（verification：运行时集成测试）
- [x] E2E-3：旧配置写有与 `role.md` 冲突的 `system_prompt`，实际模型请求只包含文件角色，不包含旧配置文本。（verification：配置到 Provider 请求集成测试）
- [x] E2E-4：启用只读网页工具时，原始最终回答被打印一次，现有来源净化和独立来源消息顺序不变。（verification：信息工具回归测试）
- [x] E2E-5：模拟模型取消、超时或失败，不输出原始成功回复标签，也不改变现有受控失败行为。（verification：失败路径测试）
- [x] E2E-6：从构建 wheel 安装或读取包资源时，两个提示词均能成功加载并组成系统提示。（verification：wheel 内容与资源读取验证）
