# 微信提示词文件化与原始回复日志 Plan

状态：已批准

## Architecture Overview

保持现有一次模型调用、微信回复整形和 UIA 发送链路不变，只把系统提示词来源从 Python 字符串与用户配置改为两个随包发布的 Markdown 资源。微信运行时初始化时通过标准库包资源接口读取并缓存两个文件；每轮成功取得模型最终文本后，先原样打印到控制台，再进入现有来源净化、纯文本清理和 `<|bubble|>` 切分流程。

```text
进程首次构造微信运行时
  -> 读取并缓存 prompts/role.md
  -> 读取并缓存 prompts/reply_policy.md
  -> 缺失、不可读或空文件：ConfigError 明确失败

每轮微信回复
  -> role.md + reply_policy.md + 可选信息工具策略
  -> Agent 生成最终文本
  -> 检查取消与模型错误
  -> 控制台打印原始最终文本
  -> 来源净化（如有）
  -> 微信纯文本清理
  -> 显式 <|bubble|> 切分或专业正文路径
  -> 现有 UIA 顺序发送
```

不增加换行兜底切分、提示词路径配置、热加载或第二个模型请求。

## Core Data Structures

不新增业务数据结构。`WechatConfig` 删除 `system_prompt` 字段，其余字段和默认值保持不变。

### Prompt tuple

加载函数返回固定二元组：

```python
tuple[str, str]  # (role_prompt, reply_policy)
```

两个文本均去除文件首尾空白，但保留内部换行、Markdown 结构和 `<|bubble|>` 字面量。

## Core Interfaces

### Prompt loader

```python
@cache
def _load_wechat_prompts() -> tuple[str, str]: ...

def _load_prompt(name: str) -> str: ...
```

- 使用 `importlib.resources.files("mewcode.wechat")` 定位包内 `prompts` 目录。
- `_load_prompt` 以 UTF-8 读取单个文件，读取失败或内容为空时抛出带文件名的 `ConfigError`。
- `_load_wechat_prompts` 在进程内缓存结果，多个好友和多个 Session 不重复读取磁盘。

### Stable system composition

```python
def _stable_system(self, turn: WechatInfoTurn | None) -> str: ...
```

固定顺序：

1. `role.md`
2. `reply_policy.md`
3. 启用信息工具时追加现有 `WECHAT_INFO_POLICY`

不再读取 `WechatConfig.system_prompt`。

### Raw final output

成功获得且通过取消、错误检查后的 `completion.text` 使用内置 `print` 输出：

```text
[wechat:model:raw-final]
<未经 strip、来源净化、Markdown 清理或气泡切分的原始最终文本>
[/wechat:model:raw-final]
```

结束标记负责让包含多行的回复仍能在控制台中明确识别边界；输出立即刷新。取消、超时和错误路径不执行这段输出。

## Module Design

### `mewcode.wechat.prompts.role.md`

**Responsibility:** 唯一微信角色设定。

内容沿用已批准的年轻朋友型 AI 角色：温暖、活泼、自然、有分寸；不虚构现实生活和未经确认的亲密关系；身份追问如实说明是 AI；不削弱权限边界。

### `mewcode.wechat.prompts.reply_policy.md`

**Responsibility:** 唯一微信回复格式协议。

从现有 `WECHAT_REPLY_POLICY` 迁移并加强可执行措辞，保留：

- `<|bubble|>` 是闲聊唯一分隔符；
- 换行、空行、标点不能替代；
- 多句、多问题、多语义点必须分开；
- 单一短回应可保持一个气泡；
- 专业回答、代码、步骤、资料和工具结果禁止使用分隔符；
- Markdown 清理边界和现有代表性示例。

文件直接包含 `<|bubble|>` 字面量，不再由 Python f-string 注入。

### `mewcode.wechat.runtime`

**Responsibility:** 提示词加载、系统提示组合、原始最终回复输出和现有回复整形。

Changes:

- 删除硬编码大段 `WECHAT_REPLY_POLICY`。
- 增加标准库包资源加载与进程缓存。
- 构造运行时时加载两个必需提示词，尽早暴露资源错误。
- 在成功完成模型请求后、任何文本转换前打印原始最终文本。
- 保持 `_build_wechat_reply` 和 UIA 发送行为不变。

### `mewcode.wechat.config`

**Responsibility:** 只解析仍然有效的微信运行参数。

Changes:

- 删除默认角色字符串和 `WechatConfig.system_prompt`。
- 不再解析 `wechat.system_prompt`；旧配置中的该键按现有宽松未知键行为被忽略，避免升级时因残留配置启动失败。
- 简化普通可选字符串校验，不保留角色专用分支。

### CLI and package build

CLI 保持现有入口。`ConfigError` 已由 CLI 输出具体消息并以状态码 1 退出，因此提示词文件错误复用现有错误边界。

提示词位于 `src/mewcode/wechat` 包目录内，由现有 Hatchling wheel 包规则随包发布；构建验证必须确认 wheel 中包含两个 Markdown 文件。

### Tests and documentation

- 配置测试改为确认残留 `system_prompt` 被忽略且不进入 `WechatConfig`。
- 运行时测试确认两个文件被加载、拼接顺序稳定、旧配置文本不进入系统提示词。
- 使用捕获控制台输出验证原始文本标签、分隔符、换行和切分前顺序。
- 验证取消或错误时没有原始成功回复日志。
- 验证缺失和空提示词资源明确失败。
- README 删除 `system_prompt` 配置示例，改为说明两个随包 Markdown 文件及控制台隐私边界。

## Module Interactions

```text
parse_wechat_config
  -> WechatConfig（无 system_prompt）

WechatAgentRuntime.__init__
  -> _load_wechat_prompts（进程缓存）
  -> role_prompt + reply_policy

WechatAgentRuntime.reply
  -> Agent.run
  -> Completion 成功检查
  -> print(raw completion.text)
  -> info source finalize（可选）
  -> _build_wechat_reply
  -> WechatReply
  -> WechatBot 现有发送流程
```

## File Organization

```text
src/mewcode/wechat/
├── prompts/
│   ├── role.md                  # 微信角色设定
│   └── reply_policy.md          # 气泡与专业回复协议
├── config.py                    # 删除可配置 system_prompt
└── runtime.py                   # 包资源加载、原始回复控制台输出

tests/
├── test_wechat_config.py        # 旧配置忽略与数据结构回归
└── test_wechat_runtime.py       # 提示词加载、日志和回复整形验证

README.md                        # 配置与隐私说明
doc/19/                          # 本次批准文档与验收记录
```

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| 提示词位置 | 随 Python 包发布的两个 Markdown 资源 | 符合“单独文件”，安装后路径稳定且无需新增用户配置 |
| 资源读取 | `importlib.resources` + `functools.cache` | 标准库即可处理源码和 wheel，且保证进程内只读一次 |
| 旧 `system_prompt` | 从数据结构和解析结果删除，残留键静默忽略 | 始终使用 `role.md`，同时避免已有配置升级即失败 |
| 原始回复输出 | 带开始/结束标签的直接控制台 `print(..., flush=True)` | 不受日志级别过滤，能原样观察分隔符和多行内容 |
| 输出时机 | 成功检查后、所有文本转换前 | 不把错误当回复打印，同时满足“原始最终回复”定义 |
| 气泡可靠性 | 继续依赖显式 `<|bubble|>`，只强化协议 | 遵守已选范围，避免误拆专业正文和额外模型调用 |
| 打包 | 复用现有 Hatchling 包目录规则 | 不新增依赖或构建插件 |
