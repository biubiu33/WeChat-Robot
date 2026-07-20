# MewCode Handover

更新日期：2026-07-20

## 1. 任务目标与最终验收标准

项目目标是完成可长期工作的终端 Coding Agent：多 Provider 流式 Agent、内置工具与权限控制、stdio/Streamable HTTP MCP，以及 Chapter 08 的上下文管理、会话持久化和长期记忆。

Chapter 08 的批准验收标准位于 `doc/08/spec.md`（AC1-AC10）：TUI 档案与 Prompt Context 分离；工具大结果归档；自动和手动压缩；JSONL 恢复；`/resume` 删除；三层 `MEWCODE.md`；四类自动记忆；全量回归不退化。

## 2. 当前完成状态

- 当前 HEAD：`b54145c feat: 上下文管理与记忆系统`。写入本交接文档前工作区无未提交改动。
- Provider 配置仅加载 `~/.mewcode/config.yaml`；MCP 配置仅加载 `~/.mewcode/mcp.yaml`。
- 已实现 stdio 与 Streamable HTTP MCP 发现、工具适配、注册、生命周期关闭与单 Server 降级。
- 已实现权限模式、规则匹配、路径沙箱、TUI 审批、计划模式与取消。
- 已实现 JSONL 会话档案、首条用户消息后创建会话、异步标题、`/resume` 搜索/键盘选择/行内 `X` 删除、30 天会话与缓存清理。
- 已实现工具结果落盘、近似 Token 估算、自动压缩、`/compact`、九段摘要、三次失败熔断、三层 `MEWCODE.md` 和四类自动记忆。
- `MEWCODE.md` 曾被报告为未加载。已在实际 Conda `mewcode` 环境中验证：项目文件读取结果为 571 字符、无 warning，且内容进入 `build_system_prompt`。未找到读取或 Provider 序列化断点；运行中编辑该文件必须重启 MewCode 才生效。

## 3. 关键文件与设计决策

| 文件 | 职责与取舍 |
|---|---|
| `src/mewcode/cli.py` | 启动时一次加载 `InstructionLoader`，把同一项目根传给权限、会话、记忆和 TUI；不维护额外 Context 快照。 |
| `src/mewcode/context/budget.py` | 用 API usage 锚定加字符增量估算，避免引入 tokenizer；默认窗口 1M，自动余量 13K。 |
| `src/mewcode/context/artifact.py` | 大工具结果写到 `.mewcode/cache/<session-id>/`，Prompt 仅保留路径与预览，减少工具输出占用。 |
| `src/mewcode/context/controller.py` | 请求前依次落盘和压缩；摘要、边界提醒、失败熔断属于隐藏 system context，不改变 TUI 历史。 |
| `src/mewcode/context/compact.py` | 单独禁止工具的 LLM 请求生成固定九段摘要，要求用户消息原文保留。 |
| `src/mewcode/session/archive.py`、`repository.py`、`runtime.py` | JSONL 是唯一会话事实来源；可见事件用于 TUI 重放，压缩检查点用于 Prompt Context 重建，避免 archive/context 双写。 |
| `src/mewcode/memory/instructions.py` | 按项目根、项目 `.mewcode`、用户 `.mewcode` 读取 `MEWCODE.md`，受限 `@include` 最大五层，防环和越界。 |
| `src/mewcode/memory/store.py`、`update.py` | 用户偏好/纠正反馈写用户目录；项目知识/参考资料写项目目录；索引限制 200 行或 25KB。 |
| `src/mewcode/tui/app.py`、`resume.py` | 会话不在选择 Provider 时创建，只在首条真实消息时创建；恢复页使用可键盘导航的列表，删除仅影响 JSONL 与同 ID cache。 |

## 4. 验证记录

2026-07-20，在 Conda 环境 `mewcode` 中执行：

```powershell
conda run -n mewcode python -m pytest -q
# 147 passed, 1 skipped in 15.14s

conda run -n mewcode python -m compileall -q src tests
# exit 0

conda run -n mewcode ruff check .
# All checks passed!

conda run -n mewcode ruff format --check .
# 77 files already formatted
```

历史已修复的关键错误：`/resume` 选择事件曾误进入 Provider 选择逻辑，导致 `src/mewcode/tui/select.py:14` 的 `IndexError: list index out of range`；随后重放取消又触发 `NoMatches('#statusbar')`。现有代码按 OptionList id 分流，并在状态刷新时处理组件已卸载情况；`tests/test_tui_resume.py` 覆盖恢复、键盘选择与删除路径。当前全量验证未出现失败日志。

## 5. 未解决风险与技术债

1. `MANUAL_RESERVE = 3_000` 已定义但未被 `/compact` 使用：手动压缩会在消息数大于 5 时直接压缩，而不是按“窗口减 3K”判定。
2. `compact.py` 只把 `Message.content` 交给摘要模型，忽略 `ToolResult.content`。工具读取到的关键代码、报错和命令输出可能无法进入摘要。
3. 多次压缩后恢复存在检查点索引风险：`ContextController` 将当前 Prompt Context 的相对 `retained_from` 写进 JSONL，`SessionRepository.restore()` 却把它应用到完整档案消息列表。第二次压缩后可能恢复过多已压缩消息；工具产物引用的相对索引也有同类风险。
4. `MEWCODE.md` 的静态加载已验证正确，但没有 TUI 可见的“已加载哪些指令文件”诊断。若模型未遵循内容，需要区分模型遵循度与加载问题。
5. 历史异常退出中出现过 `[mcp] warn: close failed: RuntimeError`；本次单元测试未复现，缺少真实 Server 退出场景的回归覆盖。
6. 当前验证以单元/集成测试为主，尚未用真实 Provider 和真实 MCP Server 做完整长会话、多次压缩、退出再恢复的端到端验收。

## 6. 避坑指南

- 不要用摘要替换 JSONL 或 TUI 历史；JSONL 是唯一事实来源，Prompt Context 必须由档案与检查点重建。
- 不要在现有相对检查点索引上修补恢复逻辑。先定义“archive 绝对消息序号”并让压缩检查点、工具产物引用、恢复路径全部使用同一坐标系。
- 不要把 `MEWCODE.md` 当成运行时热更新配置；设计要求启动时加载一次，编辑后必须重启。
- 不要把 Provider/MCP 配置改回项目级或环境变量发现；当前需求固定为用户级文件。
- 不要删除 `.mewcode/memory/` 来删除会话；删除会话只能删 `.mewcode/sessions/<id>.jsonl` 和 `.mewcode/cache/<id>/`。
- 不要在摘要、标题、自动记忆请求中开放工具调用；这些后台请求必须保持无工具。
- 不要将用户配置中的 API key 写入日志、README、测试夹具或交接文档。

## 7. Next Action

修复压缩检查点的坐标系：改为在 JSONL 中记录绝对 archive 消息边界，并添加“连续压缩两次后退出、`/resume` 恢复、下一次请求只包含最新摘要与应保留消息”的回归测试。
