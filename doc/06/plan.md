# 权限系统 Plan

> 技术栈：Python 3.12+；沿用 `anthropic` / `openai` 官方 SDK（本章**不改 provider 适配层**）。权限判定全部落在 agent 编排层与新增的 permission 模块，与协议无关。

## 架构概览

ch06 新增一个 **permission 模块**承载前四层防御与配置加载，并在 **agent 模块**把判定接入工具执行链、由 agent 编排承载第五层人在回路；**tui 模块**新增「待批准」交互态承载人在回路的 UI；**cli** 负责装配引擎并注入。**不改 llm / provider 适配层**（N6 跨协议一致天然成立）。

> 五层边界澄清：`permission.Engine.check` 实现**前四层**（黑名单/沙箱/规则/模式兜底），以返回 `Ask` 作为「请走第五层」的信号；**第五层人在回路由 agent 在 Ask 后编排驱动**（发 Approval 事件、await 决策）。二者合称五层。

- **permission 模块（新增）**：定义 `Mode`（四档 IntEnum）、`Decision`（Allow/Deny/Ask）、`Category`（Read/Write/Exec）；实现前四层判定 `Engine.check`；持有黑名单正则集、沙箱（项目根 + 符号链接解析）、四级规则集（内存 session + user/project/local 三个配置层）、模式兜底矩阵、友好名映射与路径提取。对外暴露 `check`、会话/本地规则写入、配置加载。仅依赖 `llm`（取 `ToolCall`）与标准库 + `pyyaml`。
- **agent 模块（改造）**：`Mode` 类型迁移到 permission 模块（`Mode.NORMAL` 改为 `Mode.DEFAULT`，新增 `Mode.ACCEPT_EDITS`/`Mode.BYPASS`）；`Agent` 持有 `Engine`；工具执行前调用 `engine.check`——Allow 执行、Deny 直接产被拒结果、Ask 通过现有异步事件生成器 yield 含 `asyncio.Future` 的 `ApprovalRequest` 并等待用户决策。plan 档的只读工具集与提醒沿用 ch04（键 `mode == Mode.PLAN`）。
- **tui 模块（改造）**：`MewCodeApp.mode` 改为 `permission.Mode`，持有 `Engine`；新增 `Approving` 态与待批准请求渲染/按键处理；**全局 ctrl+c/esc 分派从仅 `Streaming` 扩展到 `Streaming | Approving`**（见下，否则 approving 态 ctrl+c 会退出整个程序）；**新增全局 `shift+tab` 按键循环切换权限模式**（仅 idle 态生效）；状态栏左侧改为**常驻显示当前权限模式（取代 provider 名）**；把会话/永久放行的规则写入交给引擎（经 agent 在 Loop 内应用，TUI 只回传用户选择）。
- **cli（改造）**：用项目根（`Path.cwd().resolve()`）构造 `permission.Engine`、注入 tui。
- **smoke（改造）**：非交互，以 `Mode.BYPASS` 运行（无法人在回路、避免阻塞在 Ask），构造一个根于 `cwd` 的引擎。

数据流（单个工具调用）：
```
agent.execute_batched(calls, mode)
  └→ read_only 实参由批类型决定（只读批=True / 串行批=False，等价于 registry.is_read_only(name)）
     decision, reason = engine.check(mode, call, read_only)   # 前四层，短路：
       ① 黑名单(仅 Exec 类)  → 命中 Deny
       ② 沙箱(仅文件类)      → 逃逸 Deny
       ③ 规则引擎(会话/本地/项目/用户) → 命中 allow→Allow / deny→Deny
       ④ 模式兜底矩阵        → Allow 或 Ask
  decision==Allow → await tool.execute(...)
  decision==Deny  → ToolResult(tool_call_id, content=reason, is_error=True) 回灌
  decision==Ask   → (第五层) emit ApprovalRequest(name,args,reason,respond_future)
                      → await respond_future
              用户四选一(↑↓+回车 / 数字键 1·2·3·4) → AllowOnce(执行) /
                        AllowSession(engine.allow_session+执行) /
                        AllowForever(engine.persist_local_allow+执行) / DenyOnce(回灌)
```

## 核心数据结构

### permission.Mode（迁移自 agent + 扩展）
```python
from enum import IntEnum

class Mode(IntEnum):
    DEFAULT      = 0  # 只读 Allow / 文件写 Ask / 命令执行 Ask
    ACCEPT_EDITS = 1  # 文件写 Allow / 命令执行 Ask
    PLAN         = 2  # 仅只读工具可见（沿用 ch04）；矩阵同 default 作防御兜底
    BYPASS       = 3  # 全 Allow（黑名单/沙箱仍拦）

    def __str__(self) -> str: ...   # "default" / "acceptEdits" / "plan" / "bypassPermissions"

def parse_mode(s: str) -> tuple[Mode, bool]:
    """大小写不敏感识别四档名；未知返回 (Mode.DEFAULT, False)。"""
```

### permission.Decision / Category
```python
class Decision(IntEnum):
    ALLOW = 0
    DENY  = 1
    ASK   = 2

class Category(IntEnum):
    READ  = 0
    WRITE = 1
    EXEC  = 2
```

### permission.Rule / RuleSet
```python
from dataclasses import dataclass, field

@dataclass
class Rule:
    tool: str         # 友好名：Bash/Read/Write/Edit/Glob/Grep
    pattern: str      # 模式段；"" 表示匹配该工具全部调用
    allow: bool       # True=allow, False=deny

@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule]  = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        """先 deny 再 allow；返回 (Allow|Deny, 命中?)。"""
```

### permission.Settings（单个 YAML 文件结构，F4）
```python
@dataclass
class PermissionsBlock:
    allow: list[str] = field(default_factory=list)
    deny:  list[str] = field(default_factory=list)

@dataclass
class Settings:
    default_mode: str = ""        # 可选：default/acceptEdits/plan/bypassPermissions
    permissions: PermissionsBlock = field(default_factory=PermissionsBlock)
```

### permission.Engine（核心，前四层 + 配置）
```python
@dataclass
class Engine:
    root: str                          # 项目根（绝对、已解析符号链接）
    blacklist: list[re.Pattern]        # 内置危险命令正则（不可配，N1）
    session: RuleSet                   # 当前进程会话级（仅内存）
    user: RuleSet                      # 用户级
    project: RuleSet                   # 项目级
    local: RuleSet                     # 本地级
    local_path: str                    # 永久放行的写入目标（本地层文件）
    default_mode: Mode                 # 启动默认模式（取自配置）
```

### permission.Outcome（人在回路四选一结果）
```python
class Outcome(IntEnum):
    DENY_ONCE     = 0  # 拒绝本次
    ALLOW_ONCE    = 1  # 允许本次（不留规则）
    ALLOW_SESSION = 2  # 允许本会话（+内存会话规则，精确匹配）
    ALLOW_FOREVER = 3  # 永久允许（+写本地层文件，精确匹配）
```

### agent.ApprovalRequest / Event（新增，人在回路回路 F8）
```python
import asyncio
from dataclasses import dataclass

@dataclass
class ApprovalRequest:
    name: str                              # 工具内部名（用于展示 ● name(args)）
    args: str                              # 参数预览
    reason: str                            # 触发 Ask 的原因（模式 + 类别）
    respond: asyncio.Future[Outcome]       # 单次未来量：TUI 回传用户选择
```
现有 `Event` 增加 `approval: ApprovalRequest | None` 字段；Agent 通过现有异步生成器直接 `yield Event(approval=request)`，随后等待 `request.respond`。TUI 消费者拿到事件后暂停对该异步生成器的下一次迭代，待用户按键在 `respond` 上设置结果后，Agent 才继续产生后续事件。

## 核心接口

### permission 模块
```python
def new_engine(root: str) -> tuple[Engine, Exception | None]:
    """
    构造：解析项目根、加载三层配置、编译黑名单、确定启动模式。
    即使发生致命错误（仅当项目根不可解析时），也返回非 None 的"空规则安全引擎"
    （root 退化为传入值、四层规则空、default_mode=Mode.DEFAULT）+ err；
    配置文件格式错误绝不致错，只降级该文件为空。
    """

def check(engine: Engine, mode: Mode, call: ToolCall, read_only: bool) -> tuple[Decision, str]:
    """
    前四层判定（agent 每次执行工具前调用）；read_only 由调用方按批类型给定
    （等价 registry.is_read_only）。返回 (裁决, 原因)；原因文案见下「Decision→reason 来源表」。
    """

def persist_local_allow(engine: Engine, call: ToolCall) -> None:
    """永久放行由 agent 在人在回路后应用（生成精确规则）：精确 allow 规则写入 local 文件 + 内存。"""

def allow_session(engine: Engine, call: ToolCall) -> None:
    """本会话放行由 agent 应用（生成精确规则）：仅写入 session 内存规则集。"""

```

> 上述函数也可作为 `Engine` 的方法挂出（`engine.check(...)`、`engine.allow_session(...)`、`engine.persist_local_allow(...)`）。本文档以方法形式编排，纯函数式实现亦可。

**check → reason 文案来源表**（统一文案，供 Deny 回灌与 Ask 展示一致）：

| 裁决来源 | reason 文案（示例） |
|---|---|
| 黑名单命中 | `命中危险命令黑名单：<命令片段>` |
| 沙箱逃逸 | `路径在项目目录之外：<target>` |
| deny 规则命中 | `匹配 deny 规则：<Tool(pattern)>` |
| 模式兜底 Ask | `<mode> 模式下 <category> 类操作需确认` |
| Allow（各来源） | `""`（空，无需展示） |

**内部辅助函数**（标注所属文件）：
```python
# settings.py：
def friendly_name(internal: str) -> str:
    """bash→Bash, read_file→Read, write_file→Write, edit_file→Edit,
       glob→Glob, grep→Grep；未知原样。"""

def categorize(internal: str, read_only: bool) -> Category:
    """见下判定表。"""

def extract_target(call: ToolCall) -> tuple[str, bool, bool]:
    """见下：内部 json.loads(call.input) 取字段；返回 (target, is_file, ok)。"""

# rule.py：
def parse_rule(s: str) -> tuple[Rule, bool]: ...
def match_pattern(pattern: str, target: str) -> bool:
    """glob：* 任意串；** 仅文件路径跨段。"""

# engine.py：
def mode_fallback(mode: Mode, cat: Category) -> Decision:
    """F5 矩阵；只读/bypass→Allow，否则 Allow|Ask。"""

# blacklist.py：
def hits_blacklist(command: str) -> bool: ...

# sandbox.py：
def sandbox_ok(engine: Engine, path: str) -> bool: ...
```

**`categorize` 判定表**（区分 Write 与 Exec 靠内部名，因二者 read_only 均为 False）：

| 内部工具名 | Category | 说明 |
|---|---|---|
| read_file / glob / grep（或 read_only==True） | Category.READ | 只读 |
| write_file / edit_file | Category.WRITE | 文件写 |
| bash | Category.EXEC | 命令执行 |
| 未知/未注册工具（read_only==False） | **Category.EXEC** | N7 最严：归命令执行类，触发模式 Ask；但**黑名单层只对真正的 bash 命令短路**，未知工具因 `extract_target` 取不到 command 而 is_file=False、target=""，不会被黑名单/沙箱拦，落到规则→模式兜底（Exec→Ask）。`read_only==True` 一律 Read，优先于名字判定。 |

**`extract_target` 解析与失败归属**（关 N7/AC15）：
- 内部对 `call.input`（`str` 或 `dict`）做 `json.loads`（若是 `str`）取字段：`read_file/write_file/edit_file` 取 `path`；`glob/grep` 取 `path`（**搜索根目录**，空→`"."`；注意：glob/grep 真正遍历目标是 `pattern`/`glob` 字段，沙箱只围栏其搜索根 `path`——见决策表「glob/grep 沙箱盲区」）；`bash` 取 `command`（is_file=False）。
- 返回 `(target, is_file, ok)`：`ok=False` 表示解析失败或缺必填字段。
- **失败归属**：
  - 文件类工具 `ok=False`（input 不可解析 / 缺 path）→ `check` 在沙箱层**直接判 Deny**（`无法解析文件路径参数，安全拒绝`），不静默放行。
  - bash `ok=False`（缺 command）→ command 视为空串，**不命中黑名单**（不短路），落到规则→模式兜底（Exec→Ask），由人在回路兜底，绝不直接 Allow。
  - 未知工具 → `is_file=False`、走 Exec 类模式兜底 Ask。

### agent 模块（构造函数变更）
```python
Agent(provider: Provider, registry: Registry, version: str, engine: Engine)

async def Agent.run(
    self, conv: Conversation, mode: Mode, cancel: asyncio.Event | None = None
) -> AsyncIterator[Event]: ...
```

### tui 模块
```python
# 现有 MewCodeApp 构造函数仅末尾增 engine 形参：
MewCodeApp(
    providers: list[ProviderConfig],
    version: str,
    registry: Registry,
    engine: Engine,
)
```

## 模块设计

### permission 模块
**职责：** 前四层判定、配置加载与合并、黑名单、沙箱、规则匹配、模式矩阵、会话/永久规则写入。
**关键点：**
- **`check` 流水线（F6，短路）**：
  1. `cat == Category.EXEC and target != "" and hits_blacklist(target)` → `Deny`（N1，最高优先，bypass 也拦）。
  2. 文件类（`is_file`）：`not ok` → `Deny`（路径参数不可解析）；否则 `not sandbox_ok(target)` → `Deny`（N2）。
  3. 规则引擎：按 `session → local → project → user` 顺序，每层 `match(friendly, target)`；命中 allow→`Allow`、deny→`Deny`，**就近命中即返回**。session 规则只在当前 `Engine` 实例存活期间有效。
  4. 未命中 → `mode_fallback(mode, cat)` → `Allow` 或 `Ask`。
- **黑名单（F1/N1）**：模块级一组编译好的 `re.Pattern` 列表，匹配命令串。Unix shell 示例模式：`r"rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(/|~|\$HOME|/\*)"`、`r"dd\s+.*of=/dev/"`、`r":\(\)\s*\{.*\|.*&\s*\}"`（fork bomb）、`r"mkfs\."`、`r">\s*/dev/(sd|hd|nvme|disk)"`、`r"chmod\s+-R\s+0?777\s+/"`；Windows PowerShell/CMD 示例模式：`Remove-Item` 搭配递归和强制删除、`del`/`erase` 搭配 `/s` `/q`、`format`、`diskpart`、`Clear-Disk`。匹配采用大小写不敏感正则。注释标明「启发式、非完备、不可配置放开」。
- **沙箱（F2/N2）**：`sandbox_ok(path)`——空 path 视为 root；相对路径相对 `root` 解析；`resolved = eval_symlinks_or_ancestor(abs_path)`（存在则 `Path.resolve(strict=True)`；不存在则逐级回退到最近**已存在祖先**目录 `resolve(strict=True)` 后拼回剩余段）；返回 `resolved == root or str(resolved).startswith(root + os.sep)`。用 `pathlib` / `os.sep` 而非硬编码 `/`。
- **规则解析**：`parse_rule("Bash(git *)")`→`Rule(tool="Bash", pattern="git *")`；`"Read"`→`pattern=""`（全匹配）。加载时 allow/deny 两列分别解析；非法条目跳过并降级（N5）。
- **匹配（`match_pattern`）**：命令用「命令 glob」——`*` 匹配任意字符（含空格），其余字面，`**` 等价 `*`；文件路径用 `*`（段内）/`**`（跨段）匹配（参照 `tool/glob.py` 的 `match_segments` 思路），目标为项目相对 slash 路径。`pattern == ""` 恒匹配。
- **`allow_session`**（人在回路「允许本会话」调用）：据 `extract_target` 生成**精确** allow 规则（`Bash(<command>)` 或 `Write(<relpath>)` 等，无通配），只追加进 `session` 内存规则集；不读写文件，当前进程退出后自然失效。
- **`persist_local_allow`**（人在回路「永久允许」调用）：据 `extract_target` 生成**精确**规则（`Bash(<command>)` 或 `Write(<relpath>)` 等，无通配），追加进 local 文件的 `permissions.allow` 并重写 + 同步 `local` 层内存；失败仅抛/记日志（agent 侧捕获、不阻断执行）。
- **配置加载**：`load_settings(path)`：文件不存在→空 `Settings`、不抛；`yaml.safe_load` 失败→零值 + 抛 `SettingsError`（`new_engine` 据此降级跳过该文件，**不向上抛致命异常**）。`new_engine` 固定加载 `Path.home() / ".mewcode/settings.yaml"`、`root / ".mewcode/settings.yaml"`、`root / ".mewcode/settings.local.yaml"` 三层；`default_mode` 依次取 local/project/user 的有效 `default_mode`（`parse_mode` 成功者，local 优先），皆空→`Mode.DEFAULT`。**唯一可能返回致命 err 的情形是 `resolve_root` 失败**，此时仍返回非 None 空规则安全引擎 + err。

**依赖：** `llm`（`ToolCall`）、`pyyaml`（`yaml.safe_load` / `yaml.safe_dump`）、标准库（`re`、`pathlib`、`json`、`os`）。不依赖 agent/tool/tui。

### agent 模块（`src/mewcode/agent/__init__.py`）
**职责：** 在工具执行链接入前四层判定；承载第五层人在回路；模式类型迁移。
**关键点：**
- `Mode` 相关常量/类型从 agent 删除，改用 `permission.Mode`；`run` 形参与 `mode == Mode.PLAN` 判断更新；`defs` 选择、`plan_reminder` 注入逻辑不变（仅类型换名）。无论 plan 来自 `/plan` 命令还是 `default_mode=plan` 配置，agent 一律按 `mode == Mode.PLAN` 应用只读工具集 + 计划提醒。
- `Agent` 构造函数增加 `engine: Engine` 字段；沿用现有 `Agent(...)` 直接构造方式，不新增 `new_agent` 工厂函数。
- **被拒结果构造**：直接构造 `ToolResult(tool_call_id=calls[k].id, content=reason, is_error=True)`（与既有 `execute_batched` 结果构造一致）。
- `execute_batched(calls, mode)`（增 `mode` 形参）：
  - **只读批**：对区间内每个 `calls[k]` 先 `decision, reason = engine.check(mode, calls[k], True)`；按调用序发 `PhaseStart`；`decision==Deny`→ 预置 `results[k] = ToolResult(..., is_error=True)`、`done[k]=True`、**不纳入 `asyncio.gather`**；`decision==Allow`→ 纳入并发（只读永不 Ask，N3 并发不退化）。`asyncio.gather` 结束后按调用序发 `PhaseEnd`（Deny 项 `is_error=True`、Allow 项为真实结果），**Deny 与 Allow 项的开始/结束事件均按调用序**，与有副作用 Deny 行为一致。
  - **有副作用串行**：`decision, reason = engine.check(mode, calls[i], False)`；`Allow`→`await tool.execute(...)`；`Deny`→`ToolResult(..., is_error=True)`；`Ask`→`outcome = await request_approval(call, reason)` 拿 `Outcome`：`asyncio.CancelledError`→取消收尾（`completed=False`，沿用既有取消路径）；`ALLOW_ONCE`→执行；`ALLOW_SESSION`→`engine.allow_session(calls[i])` + 执行；`ALLOW_FOREVER`→`engine.persist_local_allow(calls[i])`（写入异常仅记、不阻断）+执行；`DENY_ONCE`→被拒结果。
- `request_approval(call, reason) -> AsyncIterator[Event | Outcome]`：
  ```python
  async def request_approval(self, call, reason):
      respond: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()
      yield Event(approval=ApprovalRequest(name=call.name, args=args_preview(call.input),
                                            reason=reason, respond=respond))
      try:
          yield await respond
      except asyncio.CancelledError:
          raise
  ```
  `_execute_batched` 透传该事件并取得 Outcome；上层 TUI 在收到事件后调 `respond.set_result(outcome)`。取消时上层先设置 `DENY_ONCE` 解开等待，再走既有 cancel event 收尾；没有新增内部事件队列或 `_emit`。

### tui 模块（app.py / stream.py / view.py；select.py 不动）
**职责：** 新增待批准交互态；模式切换命令；状态栏模式徽标；全局取消覆盖 approving 态。
**关键点：**
- `MewCodeApp`：`mode: permission.Mode`（初值 `engine.default_mode`）；加 `engine: Engine`、`pending: ApprovalRequest | None`。
- `MewCodeApp(providers, version, registry, engine)` 构造函数末尾新增 `engine` 参数：存引擎、置初始模式；沿用现有直接构造方式，不新增 `new_app` 工厂函数。
- **全局按键分派**：沿用现有 `BINDINGS` 与 `action_*` 处理方式，把 `ctrl+c`/`escape` 的取消条件从仅 `SessionState.STREAMING` 扩展到 `SessionState.STREAMING` 与 `SessionState.APPROVING`；在 approving 态触发取消时，先在 `self.pending.respond` 上 `set_result(Outcome.DENY_ONCE)`（兜底解开 Agent 等待），再设置既有 `turn_cancel`。
- 流式协程处理 `Event.approval`：保存 `self.pending = req`、切 `SessionState.APPROVING`、渲染批准块，然后等待 TUI 按键处理器设置 `req.respond`；这会暂停消费 `agent.run(...)` 的下一事件，而 Agent 正在 await `respond`。
- `update_approving`：维护光标 `approve_cursor`（0..3，进入 approving 态时重置为 0）；`up`/`k`、`down`/`j` 循环移动光标；`enter` 提交当前光标项；数字键 `1`/`2`/`3`/`4` 直选并提交；另 `y`=允许本次、`n`/`d`=拒绝本次 便捷键。索引→`Outcome` 由 `outcome_for_index` 显式映射（0=ALLOW_ONCE、1=ALLOW_SESSION、2=ALLOW_FOREVER、3=DENY_ONCE）。选定后回 `SessionState.STREAMING`、清 `pending`，并在清空前对 `pending.respond.set_result(outcome)` 让 agent 续跑。
- `View` / `Approving`：渲染**多行待批准块**——`● <动作名>` + 缩进参数预览、灰字触发原因、`是否继续?`、四行菜单（当前光标项以 `> ` + 高亮色，其余 `  ` 前缀）`1. 允许本次 / 2. 允许本会话 / 3. 永久允许（写入本地配置） / 4. 拒绝本次`、底部灰字 `↑↓ 选择 · 回车确认 · Esc 取消`；`approval_block(req, cursor)` 据 `cursor` 高亮当前项。
- **Shift+Tab 循环切换**：在现有 `BINDINGS` 新增 `shift+tab` 对应 action（仅 `SessionState.IDLE` 生效，streaming/approving 态忽略）；`self.mode = next_mode(self.mode)`，`next_mode` 即 `Mode((m + 1) % 4)`，循环 DEFAULT→ACCEPT_EDITS→PLAN→BYPASS→DEFAULT（四档全循环，含 BYPASS）；调用现有 `append_timeline(notice_entry(...))` 显示切换提示。切到/切出 plan 时同样作用于 agent（mode==Mode.PLAN 即只读 defs + plan_reminder），但 Shift+Tab **不**注入 `/do` 的执行指令。
- `submit`：保留 `/plan`(→Mode.PLAN)、`/do`(→Mode.DEFAULT，固定回 default 并注入执行指令)、`/exit`，作为计划工作流的专用入口/出口；**不再新增 `/mode` 命令**（模式切换统一走 Shift+Tab）。
- `status_bar`：左侧改为**常驻显示当前权限模式**（取代 provider 名）：Mode.DEFAULT→`DEFAULT`(灰/绿)、Mode.ACCEPT_EDITS→`ACCEPT EDITS`、Mode.PLAN→`PLAN`(黄)、Mode.BYPASS→`BYPASS`(红)；右侧保留模型名 + token 用量不变。可在启动提示行（prompt 模块的 ready hint）补「Shift+Tab 切换权限模式」。

### cli / smoke
- `cli.py`：`root = str(Path.cwd().resolve())`；`engine, err = permission.new_engine(root)`；`err is not None` 仅 `print("权限引擎降级:", err, file=sys.stderr)` 后**继续**（`engine` 必非 None——`new_engine` 致命错也返回空规则安全引擎）；以新增的 `engine` 参数直接构造 `MewCodeApp`。
- `examples/smoke.py`：新增 `cwd = str(Path.cwd().resolve())`；`engine, _ = permission.new_engine(cwd)`；`Agent(provider, new_default_registry(), "smoke", engine)`；`await agent.run(conversation, Mode.BYPASS)`。确认 smoke 现有用例文件操作目标均在 cwd 子树内（否则会被沙箱拦）。

## 模块交互

```
cli → permission.new_engine(root) → MewCodeApp(..., engine)
TUI ─按 shift+tab→ self.mode 循环切换 DEFAULT→ACCEPT_EDITS→PLAN→BYPASS→DEFAULT（跨轮保持）
TUI ─begin_turn→ Agent(provider, registry, version, engine).run(conv, self.mode)
  agent.execute_batched(calls, mode):
    decision, reason = engine.check(mode, call, read_only(批类型))   # 前四层
    Allow → await tool.execute(...)
    Deny  → ToolResult(content=reason, is_error=True)  ──回灌──→ conv.add_tool_results
    Ask   → ApprovalRequest(...,respond) ──→ TUI(Approving)   # 第五层（四选一菜单）
                                            ←── respond.set_result(outcome) ──
            ALLOW_SESSION → engine.allow_session(call) (仅内存)
            ALLOW_FOREVER → engine.persist_local_allow(call) (写本地层文件)
            → 执行(ALLOW_ONCE/ALLOW_SESSION/ALLOW_FOREVER) 或 回灌(DENY_ONCE)
```

依赖方向（无环）：`tui → {agent, permission, config, llm, ...}`；`agent → {permission, llm, tool, conversation, prompt}`；`permission → llm`。`llm` 不变、不 import permission。

## 文件组织

```
mewcode/
├── src/mewcode/permission/
│   ├── __init__.py        — 新:Mode 四档 + str/parse_mode;Decision/Category;Outcome；对外暴露 Engine/check/allow_session/persist_local_allow
│   ├── engine.py          — 新:Engine、new_engine、check 前四层流水线、mode_fallback
│   ├── blacklist.py       — 新:内置危险命令正则集 + hits_blacklist（不可配，N1）
│   ├── sandbox.py         — 新:sandbox_ok、eval_symlinks_or_ancestor、resolve_root（N2）
│   ├── rule.py            — 新:Rule/RuleSet、parse_rule、match、match_pattern(glob)
│   ├── settings.py        — 新:Settings YAML、load_settings、to_rule_set、friendly_name、categorize、extract_target
│   └── persist.py         — 新:allow_session、persist_local_allow、rule_for（写入内存或本地层文件）
├── src/mewcode/agent/__init__.py — 改:删 Mode（迁 permission）;Agent 加 engine;execute_batched(+mode)接入 check;request_approval;ApprovalRequest 事件;Deny 用 ToolResult 构造
├── src/mewcode/tui/
│   ├── app.py             — 改:mode→permission.Mode、MewCodeApp 构造函数加 engine/pending/approve_cursor;Approving 态分派;全局 ctrl+c/esc 覆盖 approving;shift+tab 循环模式(next_mode)
│   ├── stream.py          — 改:处理 ApprovalRequest;update_approving;submit 保留 /plan·/do(去掉 /mode);begin_turn 传 engine
│   └── view.py            — 改:status_bar 左侧常驻模式(取代 provider 名);待批准块渲染
├── src/mewcode/config.py  — 不改（provider 配置与 permission settings 分离）
├── src/mewcode/cli.py     — 改:构造 permission.Engine 注入 tui
├── examples/smoke.py      — 改:cwd + 构造引擎、Mode.BYPASS 运行
├── tests/
│   ├── test_permission_*.py  — 新:黑名单/沙箱(含祖先回退)/规则/优先级/矩阵/加载降级/解析失败 单测
│   ├── test_agent.py      — 改/新:权限集成(Allow/Deny/Ask/会话/永久)、保序、只读并发不退化、取消、模式迁移
│   └── test_tui.py        — 改/新:shift+tab 循环切换、approval 态按键回传、Esc 取消兜底、状态栏常驻模式、模式跨轮保持
├── .gitignore             — 改:加 .mewcode/settings.local.yaml
└── .mewcode/settings.yaml.example — 新:权限配置示例（default_mode + allow/deny）
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 权限判定落点 | 独立 permission 模块(前四层) + agent 编排层(第五层) | 与 provider 解耦（N6 免费）；逻辑内聚、可单测；不污染 tool/llm |
| 五层短路 | `check` 顺序 黑名单→沙箱→规则→模式 单函数 early-return；Ask 作第五层信号 | 满足 F6；黑名单/沙箱按类别跳过；规则就近命中即返回；人在回路在 agent |
| 黑名单不可配 | 模块内编译好的 `re.Pattern` 常量列表、无加载入口 | N1：任何配置/模式都碰不到它；bypass 也拦 |
| 黑名单完备性 | 启发式、显式声明非完备 | 不可能穷尽危险命令；防御纵深由沙箱+规则+人在回路补 |
| 沙箱解析顺序 | 先 `Path.resolve(strict=True)`（或最近祖先）再前缀比对 | N2：防软链接逃逸；新建文件按已存在祖先判，避免误判 |
| 沙箱不管命令执行 | bash 不做路径围栏 | 无法可靠静态解析任意命令的文件访问；交黑名单+规则+模式 |
| glob/grep 沙箱盲区 | extract_target 取其搜索根 `path` 做围栏；`pattern` 不参与沙箱 | glob/grep 真正遍历目标是 pattern，但任意 pattern 的越界遍历由工具内部 `pathlib.Path.walk`/`os.walk`(不跟随目录软链接)限制；沙箱对 glob/grep 为**尽力围栏搜索根**，登记为已知盲区 |
| Mode 归属 | 迁到 permission 模块、四档统一 | 用户拍板「统一一个模式轴」；mode 是权限概念，agent/tui 共用 |
| 模式切换方式 | Shift+Tab 循环四档（含 bypass）；保留 /plan·/do | 用户拍板用 Shift+Tab、四档全循环；/plan·/do 保留计划工作流的执行语义；不再设 /mode 命令 |
| 状态栏左侧内容 | 常驻显示当前权限模式，取代 provider 名 | 用户拍板「别展示 provider 名、展示权限模式」；右侧模型名+用量不变 |
| plan 语义 | 沿用 ch04 硬限制（只读工具集+提醒）+ /do | 用户拍板；矩阵 plan 行仅防御性兜底；/plan 与 default_mode=plan 都按 Mode.PLAN 应用 |
| 模式兜底值域 | 只产 Allow/Ask（无 Deny 档） | 用户拍板矩阵；Deny 仅来自黑名单/沙箱/deny 规则/人在回路 |
| 规则优先级 | 会话>本地>项目>用户；同层 deny 优先 allow | 会话级只存当前 Engine 内存；持久层按距离项目由近到远；deny 优先更安全 |
| 永久放行落点 | 写本地层 `.mewcode/settings.local.yaml`（gitignore） | 用户拍板；不进 git、不影响队友（对齐 Claude Code don't-ask-again） |
| 自动规则泛化 | 不泛化，只生成精确规则 | 自动猜泛化模式有误放行风险；泛化交用户手写 |
| 规则名 | 友好名 Bash/Read/Write/Edit/Glob/Grep ↔ 内部名映射 | 用户示例即友好名；对齐 Claude Code 习惯，规则更可读 |
| 参数解析失败归属 | 文件类不可解析→Deny；bash 缺 command→落 Ask；未知工具→Exec/Ask | N7/AC15 安全默认，绝不静默 Allow |
| 人在回路选项集 | 四选一（允许本次/允许本会话/永久允许/拒绝）+ 菜单式 ↑↓·回车·数字键直选、默认高亮允许本次 | 允许本会话生成精确内存规则；永久允许生成精确本地配置规则；均不自动泛化 |
| 人在回路回路 | `ApprovalRequest` 事件 + agent 内 `await asyncio.Future` | Textual 单线程事件循环；事件 + Future 是 async 惯用法；`CancelledError` 可解阻塞（N4） |
| respond 通道 | `asyncio.Future` 单次未来量 | TUI 调 `set_result(...)` 永不阻塞；取消竞态下兜底送 `DENY_ONCE` 不泄漏 |
| approving 态取消 | 全局 ctrl+c/esc 分派覆盖 Approving | 否则 approving 态 ctrl+c 走 `app.exit()` 退出程序，违 N4 |
| 会话/永久规则写入方 | agent 在 Loop 内调引擎（TUI 只回传 Outcome） | 引擎状态变更集中一处；职责清晰 |
| 只读权限检查 | 批内逐个 check，但只读永不 Ask | N3：保留 ch04 并发（`asyncio.gather`）；只读最多被沙箱/deny 规则拦为 Deny，无需交互 |
| settings 与 config 分离 | 新 settings.yaml(.local) 而非塞进 config.yaml | 权限配置与 provider 凭据职责不同；config.yaml 已精确 gitignore（含密钥），settings 项目级需可提交 |
| smoke 运行模式 | Mode.BYPASS、根于 cwd | 非交互无法人在回路；bypass 跳过 Ask（黑名单/沙箱仍在），用例文件操作须落 cwd 内 |
| new_engine 失败处理 | 致命错(仅 resolve_root)也返回非 None 空规则安全引擎 + err | cli 注入永不为 None、check 不抛；配置格式错只降级不致错（N5） |
