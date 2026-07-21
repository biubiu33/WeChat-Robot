# Skill 系统技术设计

## 架构概览

新增 `mewcode.skill` 子系统，负责 Skill 的发现、校验、运行时激活、目录热更新、
安装和隔离执行。它以既有 `Registry`、`Agent`、`CommandRegistry`、`Conversation`
和 Provider 为基础，不引入新的进程或第三方运行时。

```text
项目 / 用户 / 内置 Skill 位置
              |
              v
       SkillCatalog（发现、优先级、元数据）
              |
              +-- 启动：校验普通工具、注册 /<name>、提供名称和说明
              |
              +-- LoadSkill：读取正文、替换参数、inline 激活或 fork 执行
              |
              v
       SkillRuntime（活动状态、工具策略、动态环境上下文）
              |
      +-------+--------+
      |                |
      v                v
 Agent 每轮请求      TUI /skill 与动态 Slash 命令
```

Skill 的三层位置如下，前者覆盖后者的同名定义：

```text
<项目根目录>/.mewcode/skills/       # 项目级
~/.mewcode/skills/                   # 用户级
mewcode 包内置 Skill 资源目录          # 内置级
```

单文件 Skill 为位置根目录下的 `*.md`；目录型 Skill 为位置根目录下的一个直接子目录，
入口固定为 `SKILL.md`。目录中的其他文件均为该能力包的辅助资源，不作为独立 Skill
发现。Skill 正文中的相对文件引用由 SOP 使用既有工具按工作目录处理，不自动读取或执行。

## 数据结构

### `SkillMode`

```python
class SkillMode(Enum):
    INLINE = "inline"
    FORK = "fork"
```

### `SkillSource`

```python
class SkillSource(Enum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"
```

### `SkillMetadata`

```python
@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    allowed_tools: frozenset[str]
    mode: SkillMode
    fork_history: Literal["none"]
    model: str | None
```

### `Skill`

```python
@dataclass(frozen=True)
class Skill:
    metadata: SkillMetadata
    source: SkillSource
    entry_path: Path | Traversable
    package_root: Path | Traversable

    def load_instruction(self, argument: str) -> str: ...
```

发现阶段只读取和校验 frontmatter；`load_instruction` 才读取正文，并且只做确定性的
`{{args}}` 字面替换。该替换不执行模板表达式，不解析外部文件。名称使用既有命令名称规则，
并额外要求只含小写 ASCII 字母、数字和连字符，以确保可直接注册为 `/<name>`。

### `ActiveSkill` 与 `SkillRuntime`

```python
@dataclass(frozen=True)
class ActiveSkill:
    name: str
    argument: str
    instruction: str
    allowed_tools: frozenset[str]
    model: str | None

class SkillRuntime:
    def activate_inline(self, name: str, argument: str) -> ActiveSkill: ...
    def prepare_fork(self, name: str, argument: str) -> ActiveSkill: ...
    def clear(self) -> None: ...
    def active_environment(self) -> str: ...
    def ordinary_allowed_tools(self) -> frozenset[str] | None: ...
    def requested_model(self) -> str | None: ...
    def refresh(self) -> SkillRefresh: ...
```

`active_environment()` 按激活顺序渲染完整 SOP，并在动态环境上下文开头输出。没有活动
Skill 时返回空字符串。多个 `inline` Skill 的普通工具允许集取并集；无活动 Skill 时返回
`None`，表示全部普通工具可见。多个活动 Skill 指定不同 `model` 时，后一次激活失败并保留
原活动状态；没有冲突时，指定模型覆盖当前 Provider 的模型名。

`fork` 的 `ActiveSkill` 只传递给隔离执行器，不加入主 `SkillRuntime`，因而其 SOP、
模型选择和工具限制不会在完成后继续影响主对话。

### Frontmatter 格式

```markdown
---
name: review
description: 审查当前改动并按严重程度报告问题
allowed_tools: [read_file, glob, grep, bash]
mode: inline
fork_history: none
model: null
---

请审查当前工作区。关注参数：{{args}}
```

`name`、`description`、`allowed_tools`、`mode`、`fork_history` 为必填项，`model` 可省略。
`mode` 只能是 `inline` 或 `fork`，本阶段 `fork_history` 只能是 `none`。frontmatter 必须是
文档开头由 `---` 包围的 YAML 对象，正文必须为非空 Markdown。解析失败会产生包含路径和原因
的诊断条目。

## 模块设计

### `mewcode.skill.model`

定义 `Skill`、`SkillMetadata`、`ActiveSkill`、来源和模式枚举，以及面向用户的
`SkillError`、`SkillParseError`、`SkillValidationError`。该模块不访问文件系统。

### `mewcode.skill.catalog`

负责三层发现和优先级覆盖。

```python
class SkillCatalog:
    @classmethod
    def load(cls, project_root: Path, user_home: Path | None = None) -> SkillCatalog: ...
    def effective(self) -> tuple[Skill, ...]: ...
    def get(self, name: str) -> Skill | None: ...
    def diagnostics(self) -> tuple[SkillDiagnostic, ...]: ...
    def refresh_if_changed(self) -> bool: ...
```

目录扫描只检查一层单文件和一层目录型入口，避免把辅助文档误判为新 Skill。按内置、用户、
项目顺序合并，后写入的同名名称覆盖先写入的定义。相同优先级中的重复名称被诊断并跳过，
避免依赖目录遍历顺序。记录入口文件和目录的修改时间、大小与存在性快照；下一次命令菜单
刷新或新回合启动时检测变化并重建目录。

`cli._run_app` 在注册 MCP 工具后加载目录，并在进入 TUI 前以完整普通工具注册表校验每个
生效 Skill 的 `allowed_tools`。任何不存在的工具都会产生 `SkillValidationError` 并让启动
失败；单文件 YAML/正文错误只进入诊断列表。

### `mewcode.skill.runtime`

封装 `SkillCatalog` 与活动状态。它提供：

- 可注入稳定系统提示词的“可用 Skill 名称 + 说明”清单；
- 位于动态环境上下文开头的活动 SOP；
- 当前普通工具允许集和可选模型覆盖；
- 激活、清空和目录变化后的活动状态重绑定；
- `/skill` 所需的生效来源、激活状态和诊断摘要。

热更新时，同名且仍有效的活动 Skill 使用原始参数从新定义重新渲染正文；被删除或变为无效
的活动 Skill 被自动移除并产生 notice。刷新后重新校验普通工具名称。目录更新不会静默覆盖
内置命令；若新 Skill 名称与内置命令冲突，刷新失败并保留上一份有效命令集和目录。

### `mewcode.skill.tool`

实现两个系统级 `Tool`：

```python
class LoadSkillTool:
    name() -> "load_skill"
    parameters() -> {"name": string, "argument": string}

class InstallSkillTool:
    name() -> "install_skill"
    parameters() -> {"source": string}
```

`load_skill` 对 `inline` 调用 `SkillRuntime.activate_inline`，返回渲染后的 SOP；Agent 的
下一次 ReAct 请求会从动态环境供应器取得同一 SOP。对 `fork`，它委托隔离执行器运行并返回
摘要，不向主运行时保留激活状态。

`install_skill` 委托安装器，成功后触发目录刷新。两个工具标记为系统工具；`load_skill`
标记只读，因此计划模式也可用于按需取得指令；`install_skill` 不是只读，仍受计划模式与
既有权限引擎限制。

### `mewcode.skill.install`

安装器只接受 `https://` URL 或指向本地 `.zip` 文件的路径。HTTPS 下载使用标准库并在
重定向后再次校验最终方案；下载到临时文件，限制归档大小。解压前逐项拒绝绝对路径、`..`
穿越路径和符号链接，并要求压缩包根目录或唯一顶层目录是一个含 `SKILL.md` 的目录型 Skill。

安装器先在临时目录解析并使用当前普通工具注册表校验包，再原子移动到
`~/.mewcode/skills/<skill-name>/`。若目标名称已存在则拒绝覆盖，不执行包内脚本，也不读取
除入口 frontmatter 和正文外的包内容。所有临时文件在成功与失败后均清理。

### `mewcode.skill.fork`

```python
class ForkSkillRunner:
    async def run(
        self,
        skill: ActiveSkill,
        provider: Provider,
        registry: Registry,
        engine: Engine,
        cancel: asyncio.Event,
    ) -> ForkSummary: ...
```

执行器新建没有归档写入器、没有 `ContextController` 的 `Conversation`，仅添加当前 Skill
参数作为 user 消息。它创建独立 `Agent`，传入仅包含该 Skill SOP 的动态环境供应器和该
Skill 的工具允许集；主对话消息、主会话归档与工具结果均不复制进去。

隔离 Agent 自然结束后使用一个禁止工具调用的文本生成请求将最终答复概括为短摘要；该请求
失败时退化为经过长度限制和脱敏的最终答复。TUI 将“Skill 调用（参数）”作为专用用户事件
和摘要作为助理事件写入主会话，而不写入 `/name` 原始命令文本或隔离内部记录。取消主回合
会将同一取消事件传递给隔离执行器。

### `mewcode.tool.Registry`

为工具协议增加可选 `system` 属性，并向 `Registry` 增加：

```python
def definitions(self, allowed_tools: frozenset[str] | None = None) -> list[ToolDefinition]: ...
def read_only_definitions(
    self, allowed_tools: frozenset[str] | None = None
) -> list[ToolDefinition]: ...
def is_system(self, name: str) -> bool: ...
```

当存在允许集时，定义列表为“白名单中的普通工具 + 全部系统工具”；执行时采用同一策略再次
校验，防止模型伪造未暴露的普通工具调用。系统工具不因白名单隐藏，但仍受计划模式和权限
引擎约束。MCP 工具和六个内置工具仍都是普通工具。

### `mewcode.agent.Agent`

将固定 Provider、工具定义和环境文本改为每个 ReAct 迭代可重算的供应器：

```python
PromptSupplier = Callable[[], tuple[str, str, str]]
EnvironmentSupplier = Callable[[str], str]
ToolPolicySupplier = Callable[[], frozenset[str] | None]
ProviderSupplier = Callable[[], Provider]
```

稳定系统提示词继续包含既有项目指令、长期记忆和“可用 Skill：名称 + 说明”清单。动态环境
供应器在已有环境信息之前插入 `SkillRuntime.active_environment()`；因此 `load_skill` 作为
某一迭代的工具执行完毕后，下一迭代立即看到完整 SOP。`ContextController` 的预算计算接口
扩展为接收稳定提示词和动态环境文本，避免活动 SOP 未被计入压缩阈值。

Provider 供应器基于当前已选 Provider 配置构造同一协议、密钥和端点下的临时模型覆盖实例。
这样 inline Skill 在加载后的下一迭代开始使用其 `model`；没有指定模型时仍使用当前 Provider。
fork Skill 仅在自身隔离 Agent 中应用该覆盖。活动 inline Skill 出现不同指定模型时拒绝后一次
激活，避免不确定的请求模型选择。

### `mewcode.prompt`

扩展可选模块，新增“可用 Skill”稳定模块，仅渲染 `name` 和 `description`；保持“已激活
Skill”模块为空，避免 SOP 混入稳定缓存提示词。活动 SOP 改由动态环境上下文渲染，且位于
其最前方。

### `mewcode.command` 与 `mewcode.tui`

`CommandControl` 新增 `run_skill(name, argument)`、`list_skills()` 与 `refresh_skills()`。
内置命令中加入本地 `/skill`，其输出包含生效 Skill 的名称、说明、来源和活动状态，并单列
解析诊断摘要。

`CommandRegistry` 增加按规范名称卸载命令的能力。`SkillCommandRegistrar` 保存本次注册的
Skill 命令集合，在目录刷新时先构造并校验新集合，再原子替换旧动态命令，防止半刷新状态。
Skill 命令为 UI 类命令：inline 激活后将参数作为主对话用户消息启动普通 Agent 回合；fork
调用 `ForkSkillRunner` 并以新的 TUI 会话状态显示可取消的隔离执行。`/clear` 在创建新
会话前调用 `SkillRuntime.clear()`；Provider 切换、恢复会话和退出也清空活动状态，符合
“不跨应用/恢复持久化”的边界。

`MewCodeApp` 接收 `SkillRuntime`、动态命令注册器与 Provider 配置映射；在输入菜单刷新、
提交用户回合和安装成功后调用 `refresh_skills()`。执行器经由 TUI 回调运行，确保普通 slash
调用和模型调用 `load_skill` 使用相同的隔离策略。

### 内置样板与发行配置

新增三个包资源目录型 Skill：

```text
src/mewcode/skill/builtin/
├── commit/SKILL.md
├── review/SKILL.md
└── test/SKILL.md
```

它们使用本章 frontmatter 格式：`commit` 可使用版本控制命令与文件检查工具，`review` 使用
检查与检索工具，`test` 可使用测试命令和文件检查工具。Hatch 构建配置将这些 Markdown 资源
包含在 wheel 中；运行时通过 `importlib.resources` 定位，确保源码安装与 wheel 安装均可发现。

## 模块交互

### 启动与发现

1. CLI 注册默认与 MCP 普通工具。
2. CLI 构造 `SkillCatalog`，跳过并记录格式错误的单个文件。
3. CLI 用完整普通注册表校验每个有效 Skill 的工具白名单；失败则在创建 TUI 前退出。
4. CLI 将 `LoadSkillTool`、`InstallSkillTool` 注册为系统工具，创建 `SkillRuntime` 与动态
   Slash 命令集合。
5. TUI 的稳定提示词供应器输出既有指令、记忆和有效 Skill 摘要；完整 SOP 尚未进入提示词。

### 模型自动加载 inline Skill

1. 模型从稳定提示词中的名称与说明判断某 Skill 可复用，并调用 `load_skill`。
2. 工具渲染并激活 inline Skill，返回完整 SOP 作为工具结果。
3. Agent 下一迭代重新取得动态环境、工具白名单与 Provider；SOP 位于环境开头。
4. 模型按 SOP 执行，工具调用同时受 Skill 白名单、计划模式和权限引擎约束。

### `/name` 调用 fork Skill

1. 输入分发器匹配动态 Skill 命令并传递参数。
2. TUI 从目录刷新后的 SkillRuntime 创建临时 `ActiveSkill`，不向主运行时激活。
3. `ForkSkillRunner` 在无主历史、无主归档的 `Conversation` 中运行隔离 Agent。
4. 执行器生成或退化得到短摘要；TUI 将调用事件和摘要写入主可见/持久化历史。
5. 隔离临时对象被释放，主对话可继续正常 Agent 回合。

### 热更新与安装

1. 菜单刷新、新回合或安装成功时检查三层位置的快照。
2. 发生变化时重新发现、重新校验、重建有效目录与动态命令。
3. 安装器完成临时校验和原子移动后，调用同一刷新路径。
4. 失败的刷新保持上一个有效目录和命令集合，并向 TUI 输出诊断。

## 文件组织

```text
src/mewcode/
├── skill/
│   ├── __init__.py              # 对外导出
│   ├── model.py                 # Skill 不可变模型与错误
│   ├── catalog.py               # 三层发现、解析和热更新
│   ├── runtime.py               # 活动状态、提示词和工具策略
│   ├── tool.py                  # load_skill 与 install_skill 系统工具
│   ├── install.py               # HTTPS/ZIP 安全安装器
│   ├── fork.py                  # 隔离 Agent 与摘要回流
│   └── builtin/                 # 内置目录型 Skill 资源
├── agent/__init__.py            # 动态 Provider、工具和环境供应器
├── tool/__init__.py             # 系统工具标识和白名单过滤
├── prompt/modules.py            # 有效 Skill 摘要模块
├── prompt/__init__.py           # 扩展稳定提示词构造参数
├── command/model.py             # Skill 命令控制接口
├── command/builtin.py           # /skill 命令
├── command/registry.py          # 动态命令卸载
├── tui/app.py                   # Skill 生命周期、刷新、fork 状态
├── tui/command.py               # Skill 控制实现
├── tui/stream.py                # Agent 动态供应器接线
└── cli.py                       # 启动发现、校验、注册

tests/
├── test_skill_catalog.py        # frontmatter、目录、优先级、热更新、诊断
├── test_skill_runtime.py        # 激活、参数、环境、模型与白名单
├── test_skill_tool.py           # LoadSkill、InstallSkill、计划/白名单边界
├── test_skill_install.py        # HTTPS/ZIP 校验与路径穿越防护
├── test_skill_fork.py           # 无主历史、隔离、摘要和取消
├── test_agent.py                # 动态环境、模型、工具策略回归
├── test_command.py              # /skill 与动态 /<name> 回归
├── test_tui.py                  # clear、刷新与 Skill 调用回归
└── test_prompt.py               # 两阶段提示词边界回归

README.md                         # Skill 格式、位置、调用和安装说明
pyproject.toml                    # 内置 Markdown 资源打包
```

## 技术决策

| 决策 | 选择 | 原因 |
|---|---|---|
| Skill 存储 | 项目、用户、内置三层 | 支持局部覆盖且无需市场机制 |
| 目录入口 | 目录内固定 `SKILL.md` | 辅助 Markdown 不会被误识别为多个能力 |
| 初始提示词 | 仅名称和说明 | 让 Agent 自动发现，同时控制 Token 消耗 |
| 完整 SOP 位置 | 动态环境上下文开头 | 支持同一 ReAct 回合加载后的下一轮立即生效，且不污染稳定缓存块 |
| 多 Skill 工具策略 | 活动 inline Skill 白名单并集 | 同时启用多个互补工作流时仍可完成各自任务，且比全量工具集更窄 |
| fork 历史 | 固定 `none` | 已确认只传递当前调用参数，确保隔离 |
| fork 实现 | 内部独立 `Conversation` 和 `Agent` | 复用 Provider、权限、工具与取消语义，避免进程通信和会话污染 |
| 指定模型 | 同 Provider 配置的临时 model 覆盖 | 不新增 Provider 配置格式，也保持密钥和端点一致 |
| 动态命令 | 目录快照触发重建并原子替换 | 无需文件监听依赖，且不会出现半更新命令表 |
| 安装来源 | HTTPS 与本地 ZIP | 符合已确认安全边界，避免明文网络来源 |
| 安装覆盖 | 目标名称已存在即拒绝 | 避免第三方包静默改写用户 Skill；版本/升级不在本期范围 |
