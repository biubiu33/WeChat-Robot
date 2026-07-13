# MewCode 项目进度与待办清单

> 基于 `doc/` 下四章设计文档与实际源码对比，更新于 2025-07。

## 总体进度

| 章节 | 主题 | 代码实现 | 测试 | 验证 |
|------|------|----------|------|------|
| doc/01 | 多协议 LLM 终端对话客户端 | ✅ 完成 | ✅ | ⬜ 待手工验证 |
| doc/02 | 任意路径启动配置发现 | ✅ 完成 | ⚠️ 测试因环境问题 ERROR | ⬜ 待手工验证 |
| doc/03 | 工具系统（6 工具 + 单轮闭环） | ✅ 完成 | ⚠️ 部分 ERROR | ⬜ 待手工验证 |
| doc/04 | Agent Loop（ReAct 多轮 + Plan Mode） | ✅ 完成 | ✅ | ⬜ 待手工验证 |

---

## 待修复

### 🔴 代码 Bug

- [x] **`src/mewcode/tui/stream.py` 缺少 `import asyncio`** ✅ 已修复（已添加 `import asyncio`）

### 🟡 环境问题

- [ ] **pytest `tmp_path` fixture 权限错误（Windows）**
  - `test_config.py`（8 个）、`test_tool.py`（7 个）因 `PermissionError` 在 `C:\Users\nhdt_\AppData\Local\Temp\pytest-of-nhdt_` 上失败
  - 这是 Windows 环境下 pytest 临时目录权限问题，非代码逻辑问题
  - 不影响功能，但阻塞了这些测试的运行
  - 建议：清理 `%TEMP%\pytest-of-nhdt_` 目录或以管理员身份重跑

- [ ] **ruff 未安装**
  - 当前环境无 ruff，无法运行 `ruff check` / `ruff format --check`
  - 安装：`pip install ruff`

---

## 待办（来自各章 checklist 的未验证项）

### doc/01 — 基础对话（14 项 checklist 全部待手工验证）

- [ ] 配置加载与校验（合法/缺密钥/非法protocol/文件缺失）
- [ ] 单/多 provider 选择流程
- [ ] 内置 system prompt 与多轮上下文携带
- [ ] Anthropic thinking 开启且思考文本不出现
- [ ] 流式逐字 + Markdown 定型渲染
- [ ] 多行输入（Alt+Enter 换行）
- [ ] 响应计时 Imagining…(Ns)
- [ ] 错误反馈（错误 key/不存在模型时红色显示、不退出）
- [ ] /exit 与 Ctrl+C 安全退出
- [ ] 界面布局（猫 banner + 版本 + cwd + ❯ 输入框 + 状态栏）
- [ ] 跨协议一致体验
- [ ] 窗口自适应

### doc/02 — 配置发现（4 项 checklist 全部待手工验证）

- [ ] 任意非项目目录启动（用户目录配置生效）
- [ ] 项目目录配置覆盖用户目录配置
- [ ] `MEWCODE_CONFIG` 环境变量指定配置
- [ ] 所有候选配置缺失时输出中文错误和候选路径

### doc/03 — 工具系统（约 20 项 checklist 全部待手工验证）

- [ ] 6 个核心工具执行正确（读/写/改文件、bash、glob、grep）
- [ ] 工具定义随请求注入
- [ ] 流式工具调用解析（OpenAI 分片拼接、Anthropic tool_use 提取）
- [ ] 工具结果回灌与续答
- [ ] 单轮闭环上限（续答再次请求工具不再执行）
- [ ] TUI 工具行渲染（Claude Code 风格 `● name(args)`）
- [ ] 结果截断与错误样式
- [ ] 跨协议一致（Anthropic + OpenAI 各跑一遍）

### doc/04 — Agent Loop（约 20 项 checklist 全部待手工验证）

- [ ] 多轮自动连环（如「读 A 文件 → 据内容写 B 文件」）
- [ ] 自然完成停止
- [ ] 迭代上限兜底（25 轮）
- [ ] 连续未知工具停止（3 轮）
- [ ] 流出错恢复
- [ ] 保序分批并发（连续只读并发、有副作用串行）
- [ ] 用户取消（Esc/Ctrl+C 中断当前回合、不退出）
- [ ] Token 用量展示（状态栏 `↑N ↓N tok`）
- [ ] 迭代进度展示（动态区「第 N 轮」）
- [ ] Plan Mode（`/plan` 仅只读工具 + `/do` 切回全工具执行）
- [ ] 取消后历史一致性（配对合法、可继续对话）

---

## 文档更新

- [ ] **README.md 已过时**
  - 当前 README 末尾写"本阶段不支持工具调用、MCP、权限系统、文件读写、代码编辑…"
  - 实际项目已支持全部 6 个工具、ReAct 多轮 Agent Loop、Plan Mode
  - 需要更新"当前范围"一节，补充 `/plan`、`/do`、工具使用说明

---

## 非紧急优化

- [ ] doc/04 plan 中提到 `tool/registry.py` 单独文件，实际代码中 Registry 类在 `tool/__init__.py` 中（功能完整，只是文件组织略有偏差）
- [ ] 可考虑添加 `mypy` 静态类型检查
