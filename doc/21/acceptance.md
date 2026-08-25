# 微信私聊图片识别与多模态会话 Acceptance Report

状态：自动化验收通过；真实好友发图场景待专用测试账号人工确认

验收日期：2026-08-25

## Passed

- [x] 全局用户配置中的 `openai` Provider 已切换为 `deepseek-v4-flash-vision-exp`，Key、base URL 和其他 Provider 未改动。
- [x] 最小真实 API 探测通过：视觉文本流、usage 和 `tool_choice=auto` Tool Calls 均可用；观察到 1 个文本增量和 12 个 Tool Call 增量。
- [x] 微信 UIA 只读探测通过：微信 `4.1.9.30` 的主窗口、会话列表、消息列表和输入框均可识别；探测没有打开聊天、读取图片或发送消息。
- [x] 自动化测试通过：`449 passed, 1 skipped`。
- [x] Ruff 通过：`All checks passed!`。
- [x] 本次修改的 15 个 Python 源文件隔离 Mypy 检查通过：`Success: no issues found`。
- [x] `git diff --check` 无补丁格式错误。
- [x] 敏感数据审计通过：真实 Provider Key 未出现在补丁中，补丁中没有长 Base64 图片数据。

## Covered End-To-End With Fixtures

- [x] 私聊单图在静默窗口后形成一次多模态问答，批次临时目录随后删除。
- [x] 两图加文字合并为一次有序问答，不提前发送默认图片描述。
- [x] 第五张图片整批拒绝，不采集图片且不调用模型。
- [x] 图片采集失败只提示一次，不重试、不调用模型。
- [x] 大图查看器截图成功后关闭查看器并恢复主窗口；关闭失败时删除截图并安全拒绝。
- [x] JPEG、PNG、GIF、WebP 实际格式、8192 单边、32 MiB 批次和原始字节哈希边界。
- [x] Base64 只在 JSONL 原始用户消息归档一次；三个后续文字回合继续携图，第四回合停止携图。
- [x] 新图片替换旧活动批次、重启恢复、256 MiB 清理占位和 Session 删除边界。
- [x] 非白名单和群聊图片不进入图片物化或模型调用链路，原有文字、群聊、FIFO、取消与工具测试无回归。

## Not Performed Automatically

- [ ] 没有使用真实好友图片执行“发送图片 → 打开大图查看器 → DeepSeek 回答 → 微信发送”的写操作场景。该操作会真实读取并上传图片、切换微信窗口并发送消息，应只由通道所有者使用明确授权的专用测试好友完成。

## Known Baseline

- 全仓 Mypy 仍报告 60 个既有问题，主要是缺失 PyYAML/pywin32 stubs 以及旧模块类型错误。本次修改文件使用隔离检查均通过，没有把该历史类型债务扩展成本版重构。

## Bug Fix Verification: 2026-08-25

- 真实好友图片未识别的根因是微信 `4.1.9.30` 将普通图片气泡暴露为 `mmui::ChatBubbleReferItemView` 且名称为“图片”，而首版只接受 `mmui::ChatImageItemView`。
- 修复后只额外接受名称精确等于“图片”或 `Image` 的该类控件；包含当前正文和引用预览的引用气泡仍被排除，引用解析范围没有提前进入本版。
- 真实微信只读分类验证观察到当前私聊 `2` 条图片和 `2` 条文字；验证没有输出正文、点击图片、截图或发送消息。
- 修复后全量回归结果为 `449 passed, 1 skipped`，相关三个源文件隔离 Mypy 检查通过。
