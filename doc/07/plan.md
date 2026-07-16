# MCP 客户端 Plan

> 技术栈：Python 3.12+；使用 **官方 SDK** `mcp`（`pip install mcp` / `uv add mcp`，import 名 `mcp`）承载协议层（JSON-RPC 编解码、`initialize` 握手、stdio 与 Streamable HTTP 传输）。本章新增 **`mewcode.mcp` 子包**，改造配置发现、入口装配与 MCP 权限规则匹配；**不改 tool / agent / tui / llm / conversation / prompt**。

## 架构概览

- **`mewcode.mcp` 子包（新增）**：承载 MCP 客户端的全部职责——加载用户级 `~/.mewcode/mcp.yaml`、`${VAR}` 展开、字段校验、调用 SDK 建立 stdio / HTTP 会话、把远端工具适配成内置 `Tool` 协议、统一管理生命周期。仅依赖 `mewcode.tool`、SDK 与标准库；不依赖 agent / tui / permission / conversation。
- **`mewcode.config`（改造）**：Provider 配置发现只读取用户级 `~/.mewcode/config.yaml`；移除 `MEWCODE_CONFIG` 与项目级配置发现。原有 Provider 配置的内容与校验规则不变。
- **`mewcode.cli`（改造）**：先按新的 Provider 发现规则加载 Provider 配置；再在 `new_default_registry()` 之后、`new_engine(...)` 与 `MewCodeApp(...).run()` 之前加载 MCP 配置、启动 Manager、注册工具。通过 `asyncio.run()` 与 `MewCodeApp.run_async()` 进入 TUI，并在 `finally` 中关闭 Manager。
- **`mewcode.tool` 包（零改）**：`Registry.register` 与 `Tool` 协议本就是开放抽象，直接吃 `McpTool` 实例；`is_read_only` 对 MCP 工具返回正确值。
- **agent / tui 包（零改）**：工具流转链路对工具来源透明。
- **permission 包（窄改）**：`friendly_name` 对未知名原样返回；仅对以 `mcp__` 开头且含 `*` 的工具规则启用已有 glob 逻辑，使 `mcp__<server>__*` 可匹配同一 Server 的工具。`categorize` 在 `read_only==True` 时走 CategoryRead、否则归 CategoryExec；`extract_target` 对未知工具返回 `("", False, False)`，黑名单与沙箱自动跳过。
- **llm / provider（零改）**：工具定义透传，协议无关。

数据流（单次调用）：
```
agent.execute_batched(calls, mode)
  └→ engine.check(...)  → Allow → registry.execute(name, args)
       └→ McpTool.execute(args_json)                   [本章新增工具实现]
            ├→ 解析现有 Tool 协议传入的 JSON 对象
            ├→ await asyncio.wait_for(..., timeout=30)
            ├→ session.call_tool(remote_name, arguments=map)
            └→ 拼接 text content / 映射 is_error / 协议错转 is_error
       └→ Result(content, is_error)                    ── 回灌 conv
```

## 核心数据结构

### `mewcode.mcp.Config` / `mewcode.mcp.ServerConfig`（对外）
```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class ServerConfig:
    """单个 MCP server 的完整定义（已展开 ${VAR}、已校验）。"""
    type: Literal["stdio", "http"]
    command: str = ""                       # stdio 必填
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""                           # http 必填
    headers: dict[str, str] = field(default_factory=dict)

@dataclass
class Config:
    """mcp_servers 在内存中的归一化形式（已校验）。"""
    servers: dict[str, ServerConfig] = field(default_factory=dict)
```

### `mewcode.mcp.Manager`（对外不透明）
```python
import asyncio
from contextlib import AsyncExitStack
from mcp import ClientSession

class Manager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: list[_Session] = []        # 成功建立的会话（供 close）
        self._tools: list[McpTool] = []            # 适配好的工具（供 cli 注册）
        self._stack = AsyncExitStack()             # 持有 stdio / http 上下文，close 时统一退栈

@dataclass
class _Session:
    name: str
    session: ClientSession
```

### 工具适配（包内私有）
```python
# McpTool 实现 mewcode.tool.Tool 协议。
@dataclass
class McpTool:
    full_name: str                    # "mcp__<server>__<tool>"
    remote_name: str                  # server 上的原始工具名
    description: str
    parameters: dict[str, Any]        # JSON Schema 透传
    read_only: bool                   # 仅来自远端 annotations.readOnlyHint==True
    caller: CallerSession             # 协议形式持有，便于单测注入 stub

class CallerSession(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> CallToolResult: ...
```

## 核心接口

```python
# 加载用户级 MCP 配置；返回归一化的 Config。
# - 文件位置固定为 ~/.mewcode/mcp.yaml
# - 文件不存在 → 视为零 server；格式非法 → stderr 告警并返回零 server（降级，N1）
# - 内部完成 ${VAR} 展开与字段校验（非法 server 直接剔除，N2）
# - 永不抛出（签名只返 Config）
def load_config() -> Config: ...

# 启动 Manager：并发连接所有 server，每个 server 30s 超时，失败仅跳过 + 告警。
# 阻塞直到所有 server 的尝试结束（成功 / 失败 / 超时）。
# version 透传到 Implementation.version（便于 server 端识别 mewcode 版本）。
async def new_manager(cfg: Config, version: str) -> Manager: ...

# 返回适配好的工具列表（按 server 名 → 工具名 稳定排序）。
def Manager.tools(self) -> list[McpTool]: ...

# 关闭所有会话（stdio 子进程终止、HTTP DELETE）；总超时 5s 兜底，绝不阻塞退出。
async def Manager.close(self) -> None: ...
```

## 模块设计

### `src/mewcode/mcp/config.py`
**职责：** 加载用户级 MCP YAML、展开 `${VAR}`、校验。
**关键点：**
- 内部 `@dataclass class _RawServer`（含全部可能字段：type / command / args / env / url / headers，可选）。
- `_load_file(path: Path) -> dict[str, _RawServer]`：
  - 文件不存在 → 返回空 `{}`；
  - 文件读 / `yaml.safe_load` 失败 → stderr 告警一行 + 返回空 `{}`（调用方降级）。该文件独立于 Provider 配置，不影响 Provider 启动语义。
  - 取 `mcp_servers` 段，缺失视为空；该段不是 map 或 server 名不是字符串时告警并跳过对应层或条目。
- `_expand_vars(s: str) -> tuple[str, list[str]]`：正则 `\$\{([A-Za-z_][A-Za-z0-9_]*)\}`，用 `os.environ.get` 取值；未定义变量名记录到 `undefined`（供告警）。**仅作用于 env / headers 的值**。
- `_apply_expansion(name: str, srv: _RawServer) -> None`：对 `srv.env`、`srv.headers` 每个值跑 `_expand_vars`；未定义变量在 stderr 输出 `[mcp] warn: undefined env var ${X} referenced by server <name>`（同 server 同变量限一次，用局部 `set` 去重）。
- `_validate_server(name: str, srv: _RawServer) -> ServerConfig | None`：
  - `srv.type` 必为 `"stdio"` 或 `"http"`，否则跳过；
  - `stdio` 必填 `command`；`http` 必填 `url`；缺失则跳过；
  - `command`、`url` 必为非空字符串；`args` 必为字符串数组；`env` 与 `headers` 必为字符串 map。任一已声明字段的类型非法则跳过整个 server。
  - 违规时 stderr 告警 `[mcp] warn: skip server <name>: <reason>`。
- `load_config() -> Config`：
  - 仅读取 `Path.home() / ".mewcode" / "mcp.yaml"`。
  - 对该文件的 server 定义逐个展开与校验，组装 `Config`。

### `src/mewcode/mcp/manager.py`
**职责：** 连接 server、缓存会话、关闭。
**关键点：**
- `connect_timeout`、`close_timeout` 作为模块级变量（非常量），便于单测临时改小，结束 restore。生产值 30s / 5s。
- `async def new_manager(cfg: Config, version: str) -> Manager`：
  - 内部 `mgr = Manager()`；为每个 `(name, srv)` 起一个 task：`asyncio.create_task(_connect_one(mgr, name, srv, version))`。
  - `await asyncio.gather(*tasks, return_exceptions=True)`（异常吸收，单 server 出错不影响其它）；
  - 全部完成后稳定排序 `mgr._tools`（按 `full_name`）。
- `async def _connect_one(mgr, name, srv, version)`：
  - `try: await asyncio.wait_for(_do_connect(mgr, name, srv, version), timeout=connect_timeout)`；
  - `except asyncio.TimeoutError`: stderr 告警 `[mcp] warn: connect server <name> timeout after 30s` 并 return；
  - `except Exception as e`: stderr 告警 `[mcp] warn: connect server <name> failed: <e>` 并 return。
- `async def _do_connect(mgr, name, srv, version)`：
  - 按 `srv.type` 构造 transport 上下文：
    - **stdio**：
      ```python
      from mcp import StdioServerParameters
      from mcp.client.stdio import stdio_client
      params = StdioServerParameters(
          command=srv.command,
          args=srv.args,
          env={**os.environ, **srv.env},   # 同名宿主变量被覆盖
      )
      ctx = stdio_client(params)
      ```
    - **http**：
      ```python
      import httpx
      from mcp.client.streamable_http import streamable_http_client
      client = await attempt_stack.enter_async_context(
          httpx.AsyncClient(headers=srv.headers)
      )
      ctx = streamable_http_client(srv.url, http_client=client)
      ```
  - 每个连接尝试先使用**局部 `AsyncExitStack`**持有 transport 与 `ClientSession` 上下文：
    ```python
    transport = await attempt_stack.enter_async_context(ctx)
    read, write = transport[0], transport[1]    # http 返回 3 元组，第三个是 metadata
    session = await attempt_stack.enter_async_context(
        ClientSession(read, write, client_info=Implementation(name="mewcode", version=version))
    )
    await session.initialize()                  # 握手
    listed = await session.list_tools()
    ```
  - 对 `listed.tools` 中每个 `Tool` 调 `adapt_tool(name, t, session)`；成功的入临时 list。若同一 server 重复返回同名工具，stderr 告警并保留后一个。
  - 完成握手与列工具后，在 `async with mgr._lock:` 内将局部栈的关闭回调转移到 `mgr._stack`，并统一 append `_sessions` / `_tools`。连接失败或超时则由局部栈立即退出，避免失败 server 的会话和子进程滞留到程序退出。
- `async def Manager.close(self)`：
  - 用 `asyncio.wait_for(self._stack.aclose(), timeout=close_timeout)` 包裹；
  - `TimeoutError` → stderr 告警 `[mcp] warn: close timeout (5s), some sessions may leak`，不再等。
- `Manager.tools()`：返回 `list(self._tools)` 副本（防外部修改）。

### `src/mewcode/mcp/tool.py`
**职责：** 把 SDK 返回的 `mcp.types.Tool` 适配为 mewcode `Tool` 协议。
**关键点：**
- 包级 `_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")`。
- 包级 `_non_text_warn_once: set[str] = set()`，配 `asyncio.Lock`（或在单线程 asyncio 中直接用 set）记录已告警的 `full_name`。
- `def adapt_tool(server_name: str, t: mcp.types.Tool, session: CallerSession) -> McpTool | None`：
  - `full_name = f"mcp__{server_name}__{t.name}"`。
  - **禁用字符校验**：`_VALID_NAME.fullmatch(full_name)` 不通过 → 返回 `None` + stderr 告警 `[mcp] warn: skip tool <full_name>: name contains illegal characters`。
  - `description`：`t.description` 为空时兜底 `f"来自 MCP server {server_name} 的工具 {t.name}"`。
  - `parameters`：`t.inputSchema` 转 `dict[str, Any]`（已是 dict 则 `dict(...)` 浅拷贝；为空时给 `{"type": "object"}` 兜底，避免 provider 拒收）。
  - `read_only`：`bool(t.annotations and t.annotations.readOnlyHint)`（None-safe）。
- `McpTool.name()` / `description()` / `parameters()` 与 `read_only`：实现现有 `mewcode.tool.Tool` 协议；前三者为方法，`read_only` 为布尔属性。
- `async def McpTool.execute(self, args: str) -> Result`：
  - 用 `mewcode.tool.parse_arguments(args)` 解析 JSON 字符串；解析失败时直接返回现有的结构化参数错误，空对象转为 `None` 传给远端。
  - ```python
    try:
        result = await asyncio.wait_for(
            self.caller.call_tool(self.remote_name, arg_map),
            timeout=30,
        )
    except asyncio.TimeoutError:
        return error_result("timeout", "MCP 工具调用超时（30 秒）")
    except Exception as e:
        return error_result("mcp_error", f"MCP 工具调用失败: {e}")
    ```
  - 遍历 `result.content`：`isinstance(block, mcp.types.TextContent)` → 收集 `block.text`；其余块计数，首次出现时 stderr 告警 `[mcp] warn: tool <full_name> returned non-text content blocks (dropped)`（per `full_name` 限一次）。
  - 用 `"\n".join(texts)` 拼出 `content`；返回 `Result(content=content, is_error=bool(result.isError))`。

### `src/mewcode/cli.py`（改造）
Provider 配置发现保留在 `main()` 的错误处理范围内；进入异步入口前先捕获配置错误。异步入口在 `registry = new_default_registry()` 之后、`new_engine(...)` 之前装配 MCP：
```python
from mewcode import mcp as mcp_client

async def _run_app(cfg: Config, root: Path) -> None:
    registry = new_default_registry()
    mcp_cfg = mcp_client.load_config()
    mcp_mgr = await mcp_client.new_manager(mcp_cfg, version=__version__)
    try:
        for t in mcp_mgr.tools():
            registry.register(t)
        engine, engine_error = new_engine(root)
        if engine_error is not None:
            print(f"权限引擎降级: {engine_error}", file=sys.stderr)
        app = MewCodeApp(cfg.providers, registry=registry, engine=engine)
        await app.run_async()
    finally:
        await mcp_mgr.close()

def main() -> None:
    try:
        cfg = load(str(Path.home() / ".mewcode" / "config.yaml"))
        asyncio.run(_run_app(cfg, Path.cwd()))
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
```
（`root` 复用现有 `os.getcwd()` 结果；version 复用 `__version__`。）

## 文件组织

```
mewcode/
├── pyproject.toml                       — 改：dependencies 增加 "mcp>=1.0"
├── src/mewcode/
│   ├── config.py                        — 改：Provider 仅从用户级 config.yaml 发现
│   ├── permission/rule.py                — 改：支持 `mcp__<server>__*` 工具规则匹配
│   ├── mcp/
│   │   ├── __init__.py                  — 新：暴露 Config / ServerConfig / Manager / load_config / new_manager
│   │   ├── config.py                    — 新：Config / ServerConfig、load_config、_load_file、_expand_vars、_validate_server
│   │   ├── manager.py                   — 新：Manager、new_manager（并发 + 30s 超时）、close（5s 兜底）、tools；模块级 connect_timeout / close_timeout
│   │   └── tool.py                      — 新：CallerSession Protocol、McpTool、adapt_tool、execute
│   └── cli.py                           — 改：装配 Manager，注册 MCP 工具，finally 关闭
├── tests/
│   ├── test_config.py                   — 改：Provider 仅从用户级配置发现
│   ├── test_mcp_config.py               — 新：单文件加载 / 变量展开 / 全字段校验 / 降级 单测
│   ├── test_mcp_tool.py                 — 新：命名拼接 / 禁用字符 / Execute 各分支（成功/远端 IsError/超时/协议错/非 text 块）
│   └── test_mcp_manager.py              — 新：连接成功/失败/超时、失败资源立即关闭、重复工具去重、close 不死锁、共享状态并发安全
├── doc/07/
│   └── spec.md / plan.md / task.md / checklist.md
├── .mewcode/
│   └── mcp-servers.example.yaml         — 新：配置示例（用 ${VAR}）
└── （其它包零改）
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 协议层实现 | 官方 Python SDK（`mcp`，PyPI 包名 `mcp`） | 用户拍板；避免自研 JSON-RPC / 握手 / 帧；SDK 已处理 stdio (`stdio_client`) 与 Streamable HTTP (`streamable_http_client`) |
| Provider 配置位置 | 用户级 `~/.mewcode/config.yaml` | 用户拍板；固定位置避免环境变量和项目目录改变 Provider 选择 |
| MCP 配置文件位置 | 用户级 `~/.mewcode/mcp.yaml` | 用户拍板；独立文件避免 MCP 与 Provider 配置互相影响 |
| 配置层数与合并 | 两类配置均为单一用户级文件，不合并 | 用户拍板；避免项目目录或配置优先级引入隐式行为 |
| server 字段校验 | server 定义的全部字段均做类型校验 | 防止非字符串命令、参数或凭据映射进入 SDK 后产生非隔离异常 |
| server 类型字段 | 显式 `type: stdio\|http` | 不靠字段嗅探（防止误判）；未来扩展易加（如 sse） |
| 变量展开范围 | 仅 env / headers 的值 | 避免 command / args / server 名 / 工具名被环境间接影响；凭据走 env / headers 已足够 |
| 未定义变量 | 空串 + 一次性告警（不阻断） | server 自决无凭据时是否能跑；mewcode 不替它拍板 |
| 工具命名 | `mcp__<server>__<tool>` | 用户拍板；Claude Code 风格；LLM 工具名安全字符；一眼识别来源 |
| 启动连接策略 | 同步进 TUI 前完成 + `asyncio.gather` 并发每 server `asyncio.wait_for(30s)` 超时 + 失败跳过 | 进 TUI 时工具集稳定；asyncio 并发缩短总时延；隔离避免单 server 拖死启动 |
| 调用超时 | 30s 硬编码 `asyncio.wait_for`，转 is_error | 与连接同值；不中断 Loop；避免长卡 |
| readOnly 适配 | 严格只信 `annotations.readOnlyHint==True` | 默认走 Ask，最严；声明只读才放行 |
| 资源 / 提示词 / 采样 / roots | 不实现 | 本章只覆盖工具能力 |
| 独立 SSE 通道 | 不订阅（不消费 `streamable_http_client` 返回的服务端推送流） | 只用请求-响应；省一条长连接；减少复杂度 |
| 非 text 内容块 | 静默丢弃 + 一次性告警 | 模型只能消费文本；丢弃比假装回灌更诚实 |
| 错误回灌 | 协议错 / 超时均转 is_error | 与不中断 Loop 的契约一致 |
| 连接资源归属 | 单 server 局部 `AsyncExitStack`，成功后才转移到 Manager 总栈 | 失败或超时立即清理资源，不让失败 server 的子进程或 HTTP 会话滞留 |
| 退出关闭 | Manager 总 `AsyncExitStack.aclose()` + 5s `wait_for` 兜底 | 让 SDK 的 async context 管理器统一收尾；避免某 server 卡死阻塞退出 |
| permission 接入方式 | 保持既有分类与模式链路，仅为 `mcp__...*` 增加工具名 glob 匹配 | 现有 RuleSet 仅精确匹配工具名；该窄改使 `mcp__server__*` 规则可用且不改变内置工具规则 |
| HTTP 自定义 headers | 通过 `httpx.AsyncClient(headers=...)` 注入 `streamable_http_client` | 使用 SDK 当前 API，不引入额外传输抽象 |
| OAuth | 不实现完整流程 | 用户预换 token 写 headers；本章范围最小化 |
| execute 接口注入 | `McpTool` 持 `CallerSession` Protocol 而非具体 `ClientSession` | 单测可注入 stub；生产代码无运行时开销 |

## 模块交互

```
cli.main()
  ├─ 读取用户级 config.yaml 中的 providers
  └─ asyncio.run(cli._run_app(...))
  ├─ new_default_registry()                        # 6 内置工具
  ├─ mcp.load_config()                             # 读用户级 mcp.yaml + ${VAR} 展开 + 校验
  ├─ await mcp.new_manager(cfg, version)           # asyncio.gather 并发连接所有 server，30s/各
  │     └─ 对每个 server：
  │         ├─ 构造 transport（stdio: stdio_client / http: streamable_http_client）
  │         ├─ 进入 ClientSession 上下文
  │         ├─ await session.initialize()          # 握手
  │         ├─ await session.list_tools()
  │         └─ adapt_tool 包装成 McpTool
  ├─ for t in mgr.tools(): registry.register(t)
  ├─ new_engine(root)
  ├─ await MewCodeApp(...).run_async()
  └─ finally: await mgr.close()                    # AsyncExitStack.aclose() + 5s 兜底
```

调用链（Agent 视角，工具来源透明）：
```
agent.execute_batched(calls, mode)
  └ engine.check(mode, call, registry.is_read_only(call.name))
       (MCP 工具：friendly_name 原样；categorize：read_only==True→Read, 否则→Exec；
        extract_target(未知工具)→is_file=False, target="" → 黑名单/沙箱自动跳过)
  └ Allow → registry.execute(name, args)
       └ McpTool.execute(args)
            ├ asyncio.wait_for(..., timeout=30)
            └ session.call_tool → 拼接 text / 映射 is_error / 协议错转 is_error
  └ Result 回灌 conv
```

依赖方向（无环）：`mewcode.cli → mewcode.mcp → {mewcode.tool, mcp(SDK), 标准库}`；`mewcode.mcp` 不依赖 agent / tui / permission / conversation。
