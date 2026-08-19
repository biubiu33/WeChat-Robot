# MewCode 微信侧受限信息工具 V1 Plan

状态：已批准（含 Nominatim 指定代理修订）

## Architecture Overview

微信消息监听、队列、会话绑定和 UI Automation 发送链路保持不变。本次在 `WechatAgentRuntime` 与现有 `Agent` 之间增加微信专用公共信息服务层：运行时启动时创建长期服务对象，每条好友消息开始时创建独立的回合上下文和只包含四个工具的 `Registry`。

```text
微信好友消息
    |
    v
WechatAgentRuntime
    |-- 每轮安全时间环境
    |-- 微信固定工具策略
    |-- WechatInfoServices.new_turn(...)
    |       |-- 独立 TurnBudget / SourceLedger
    |       `-- 仅四个工具的 Registry
    |
    v
MewCode Agent ReAct Loop
    |-- get_current_time -> LocationResolver -> zoneinfo
    |-- web_search      -> Tavily Basic
    |-- web_fetch       -> SafePublicHttpClient
    `-- get_weather     -> LocationResolver -> Open-Meteo
    |
    v
回复后处理（来源与署名兜底）
    |
    v
原微信会话发送
```

所有网络客户端使用固定用途接口。不存在可由模型指定方法、请求头或请求体的通用 HTTP 工具。网络 I/O 通过标准库客户端在线程中执行，避免为简单 JSON API 增加 SDK；坐标到 IANA 时区使用专门时区数据库依赖。

## Core Data Structures

### WechatInfoConfig

微信公共信息工具配置，作为 `WechatConfig` 的嵌套字段：

```python
@dataclass(frozen=True)
class WechatInfoConfig:
    enabled: bool = False
    tavily_api_key: str = ""
    nominatim_user_agent: str = "MewCode-WeChat/0.1"
    nominatim_proxy: str = ""
    nominatim_proxy_configured: bool = False
```

- `enabled`：是否为微信运行时注册四个信息工具；省略配置时保持 Chapter 13 的空 Registry 行为。
- `tavily_api_key`：允许字面值或 `${ENV_NAME}` 环境变量引用；缺失只禁用网页搜索，不影响时间、网页直读和天气。
- `nominatim_user_agent`：公共 Nominatim 请求使用的可识别客户端标识。
- `nominatim_proxy`：仅供 Nominatim 使用的显式 HTTP/HTTPS 代理 URL；支持字面值或 `${ENV_NAME}` 环境变量引用。
- `nominatim_proxy_configured`：区分“未配置，允许直连”和“已配置但环境变量缺失／无效，必须失败关闭”，避免静默直连。
- Tavily 搜索深度、结果数、外部端点、调用上限和付费模式不做可配置项，使用 spec 已批准的安全常量。

### HttpRequest / HttpResponse

```python
@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None = None
    timeout: float = 10.0
    max_bytes: int = 2 * 1024 * 1024

@dataclass(frozen=True)
class HttpResponse:
    status: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes

class HttpTransport(Protocol):
    async def request(self, request: HttpRequest) -> HttpResponse: ...
```

生产实现使用 `urllib.request` 和 `asyncio.to_thread`。`UrllibTransport` 增加可选的显式代理构造参数：缺省时继续安装空 `ProxyHandler`，不继承系统代理；提供代理时只安装该 HTTP/HTTPS 代理。测试使用内存 Fake Transport，不连接真实 Tavily、Nominatim 或 Open-Meteo。

### LocationCandidate / LocationResolution

```python
@dataclass(frozen=True)
class LocationCandidate:
    display_name: str
    country_code: str
    latitude: float
    longitude: float
    timezone: str
    source: Literal["capital", "cache", "nominatim"]

@dataclass(frozen=True)
class LocationResolution:
    status: Literal["resolved", "ambiguous", "not_found"]
    location: LocationCandidate | None = None
    candidates: tuple[LocationCandidate, ...] = ()
    attribution_required: bool = False
```

只有 `resolved` 结果可以进入时间或天气请求。`ambiguous` 以候选列表返回模型，要求追问用户。

### TurnBudget

```python
@dataclass
class TurnBudget:
    started_at: float
    search_calls: int = 0
    page_calls: int = 0
    web_wait_seconds: float = 0.0

    def reserve_search(self) -> Result | None: ...
    def reserve_page(self) -> Result | None: ...
    def remaining_web_seconds(self) -> float: ...
```

- 第三次搜索和第六次页面读取在发起网络请求前被拒绝。
- 搜索或读取命中缓存也消耗该轮对应调用次数，防止模型循环调用。
- 所有网页能力共用 25 秒等待预算；单次操作仍受 10 秒限制。

### SourceLedger

```python
@dataclass
class SourceRef:
    title: str
    url: str
    kind: Literal["search", "page"]

@dataclass
class SourceLedger:
    sources: list[SourceRef]
    osm_used: bool = False
    weather_used: bool = False

    def record(self, source: SourceRef) -> None: ...
    def finalize_reply(self, text: str) -> str: ...
```

Ledger 只存在于当前回合内。后处理验证模型给出的 URL 必须来自当前回合已返回的来源；缺少来源或署名时，追加最多三个来源以及 `地点数据：OpenStreetMap` / `天气数据：Open-Meteo`。追加内容位于完整回复末尾，因此现有分段发送自然把来源放入最后一条微信消息。

### PendingSearchConsent

```python
@dataclass(frozen=True)
class PendingSearchConsent:
    query_hash: str
    expires_at: float
```

只在进程内按会话暂存查询哈希和短期过期时间，不保存查询正文。明显手机号、身份证、邮箱、凭据或精确住址类查询首次调用时返回 `confirmation_required`；下一轮只有用户明确确认且模型提交相同规范化查询时才允许一次。真实人物姓名等无法可靠用规则识别的语义场景由固定系统策略要求模型先确认。

### Cache Records

```python
@dataclass(frozen=True)
class CachedLocation:
    key: str
    value_json: str
    updated_at: float

@dataclass(frozen=True)
class CachedWebSearch:
    key: str
    query: str
    result_json: str
    fetched_at: float

@dataclass(frozen=True)
class CachedWebPage:
    key: str
    url: str
    title: str
    content: str
    fetched_at: float
```

所有缓存写入现有微信 SQLite 状态库，不包含联系人或 Session 字段。天气响应没有缓存结构。

## Public Tool Interfaces

### get_current_time

```python
{
  "location": "可选地点；省略时返回本机当前时间"
}
```

成功结果包含规范地点、当地 ISO 时间、IANA 时区、UTC 偏移、夏令时状态和相对本机日期差。本机 IANA 时区由 `tzlocal` 在 Windows 上解析；国家名称先查静态首都数据，其他地点经过缓存和 Nominatim，再由 `timezonefinder` 得到时区，最终由 `zoneinfo` 计算当前时间。

### web_search

```python
{
  "query": "最短必要搜索词",
  "freshness": "normal | latest",
  "personal_data": false
}
```

- 固定调用 Tavily `/search`，`search_depth=basic`、`max_results=5`，不请求 Tavily 生成答案或返回整页正文。
- `latest` 只允许使用五分钟内的搜索缓存；`normal` 使用三十分钟缓存。
- `personal_data` 用于触发确认门；明显敏感模式无论该字段为何值都由程序拦截。
- 返回标题、URL、摘要和可用发布时间，并标记是否来自缓存及缓存时间。

### web_fetch

```python
{
  "url": "公开 HTTP(S) URL"
}
```

- 工具不接收方法、请求头、Cookie、认证信息或请求体。
- 返回规范化最终 URL、标题、可见正文、是否截断、缓存状态和缓存时间。
- 正文以结构化 JSON 字符串提供并明确标记为不可信外部内容。

### get_weather

```python
{
  "location": "城市、区县、乡镇或公开地标",
  "mode": "current | hourly | daily",
  "temperature_unit": "celsius | fahrenheit",
  "wind_speed_unit": "kmh | mph",
  "precipitation_unit": "mm | inch"
}
```

- `current` 返回当前值及当天最高／最低、日出和日落。
- `hourly` 返回从当前当地时间起最多 48 小时的批准字段。
- `daily` 返回从当地今天起最多 7 天的批准字段。
- 每次调用都访问 Open-Meteo，不读取或写入天气缓存。

## Module Design

### `mewcode.wechat.info.registry`

**Responsibility:** 创建长期服务集合、每轮状态和四工具 Registry；集中执行来源后处理与敏感查询短期确认。

**Public Interface:**

```python
class WechatInfoServices:
    def __init__(
        self,
        config: WechatInfoConfig,
        store: WechatStateStore,
        transport: HttpTransport | None = None,
        clock: Clock | None = None,
    ) -> None: ...

    def new_turn(
        self,
        conversation_name: str,
        user_text: str,
    ) -> WechatInfoTurn: ...

class WechatInfoTurn:
    registry: Registry
    ledger: SourceLedger

    def finalize_reply(self, text: str) -> str: ...
```

**Dependencies:** `Registry`、四个工具实现、SQLite Store、共享 HTTP Transport。

服务对象跨回合复用 Nominatim 限速器和短期确认状态；`WechatInfoTurn` 每轮新建，确保调用计数不会跨好友或跨回合污染。

生产组装时只把显式代理交给 `LocationResolver` 的 Nominatim Transport。Tavily 与 Open-Meteo 继续使用无代理 Transport；公开网页读取继续执行公网地址校验并使用无代理 Transport。测试注入的 Fake Transport 保持现有接口，不需要代理或真实网络。

### `mewcode.wechat.info.http`

**Responsibility:** 标准库 HTTP Transport、固定 API 请求、公开网页 SSRF 防护、重定向检查、响应大小限制和 HTML 正文提取。

**Public Interface:**

```python
class UrllibTransport(HttpTransport):
    def __init__(self, proxy_url: str | None = None) -> None: ...
    async def request(self, request: HttpRequest) -> HttpResponse: ...

class SafePublicHttpClient:
    async def fetch(self, url: str, timeout: float) -> PublicPage: ...

def validate_public_url(url: str) -> ValidatedUrl: ...
def extract_visible_text(body: bytes, content_type: str) -> ExtractedPage: ...
def sanitize_url_secrets(url: str) -> str: ...
```

**Security flow:**

1. 只接受 `http` / `https`，拒绝凭据型 URL。
2. 解析主机并用 `socket.getaddrinfo` 取得全部地址；任何地址不是 `ipaddress.is_global` 时拒绝。
3. 自定义重定向处理器在每次跳转前重复协议、主机、DNS 和敏感参数校验。
4. 缺省不使用系统代理、浏览器 Cookie 或认证存储，不接受模型自定义 Header，并请求 `Accept-Encoding: identity` 避免压缩内容绕过大小限制；显式代理构造参数只供固定 Nominatim 客户端使用。
5. 分块读取，超过 2 MiB 立即中止；只接受 HTML 或纯文本 MIME。
6. 标准库 HTML Parser 跳过脚本、样式、表单、模板、SVG 和隐藏节点，合并可见文本并截断到 50,000 字符。

### `mewcode.wechat.info.location`

**Responsibility:** 地点规范化、国家首都匹配、Nominatim 查询、歧义处理、地点缓存和坐标到 IANA 时区。

**Public Interface:**

```python
class LocationResolver:
    async def resolve(
        self,
        query: str,
        *,
        coarse_only: bool = False,
    ) -> LocationResolution: ...

class CurrentTimeTool:
    read_only = True
    async def execute(self, args: str) -> Result: ...
```

**Dependencies:** 静态国家首都数据、`timezonefinder`、`zoneinfo`、Nominatim Client、WechatStateStore、仅限 Nominatim 的显式代理 Transport。

国家首都数据包含常用中文／英文国名与别名、首都名称和坐标。Nominatim 使用进程级异步锁保证请求间隔至少一秒；查询最多取五个候选。跨城市或行政区的多个可信候选返回 `ambiguous`，不以第一条结果自动决定。

生产环境为 Nominatim 单独创建 Transport：未出现代理配置键时使用直连；配置键存在且能解析出合法 HTTP/HTTPS URL 时使用该代理；配置键存在但环境变量缺失、URL 非法或代理不可达时返回安全的地点解析失败，不尝试直连。该 Transport 不传给 Tavily、Open-Meteo 或 `SafePublicHttpClient`，代理地址不得进入 `HttpRequest`、模型结果或日志。

`coarse_only=True` 用于天气；检测到门牌、楼栋、手机号或疑似精确地址时返回隐私错误或要求提供城市。

### `mewcode.wechat.info.web`

**Responsibility:** Tavily Basic 搜索、公开页面读取、查询隐私检查、网页缓存、重试和回合预算。

**Public Interface:**

```python
class TavilySearchClient:
    async def search(self, query: str) -> SearchResponse: ...

class WebSearchTool:
    read_only = True
    async def execute(self, args: str) -> Result: ...

class WebFetchTool:
    read_only = True
    async def execute(self, args: str) -> Result: ...
```

每次真实 Tavily 请求前通过 SQLite 原子预留当月免费 credit；本项目自然月最多预留 1,000 credits。缓存命中不预留 credit。每个网络尝试都单独预留，避免重试使本地计数超过上限；Tavily 自身提前报告额度不足时直接返回额度错误。

搜索和页面缓存键分别由规范化查询／freshness 以及脱敏后的规范 URL 生成。读取缓存时根据 30 分钟、1 小时和 `latest` 五分钟规则决定新鲜度；网络失败时，普通搜索与页面读取才允许回退到七天保留期内的旧缓存并显式标记，`latest` 查询绝不使用超过五分钟的缓存。

### `mewcode.wechat.info.weather`

**Responsibility:** Open-Meteo Forecast API 请求、字段白名单、WMO 天气代码中文映射、单位与地点时区处理。

**Public Interface:**

```python
class OpenMeteoClient:
    async def forecast(
        self,
        location: LocationCandidate,
        mode: str,
        units: WeatherUnits,
    ) -> WeatherReport: ...

class WeatherTool:
    read_only = True
    async def execute(self, args: str) -> Result: ...
```

请求端点固定为 Open-Meteo 免费 Forecast API，模型不能选择模型、端点或任意字段。`models=best_match`，`timezone` 使用解析后的 IANA 名称。响应只保留 spec 批准的当前、48 小时与 7 天字段；错误结果不触发网页回退。

### `mewcode.wechat.store`

**Responsibility:** 在现有 `.mewcode/wechat.sqlite3` 中扩展地点、网页和免费额度状态。

**New Tables:**

```sql
location_cache(
    cache_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
)

web_search_cache(
    cache_key TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    result_json TEXT NOT NULL,
    fetched_at REAL NOT NULL
)

web_page_cache(
    cache_key TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    fetched_at REAL NOT NULL
)

tavily_monthly_usage(
    month_key TEXT PRIMARY KEY,
    credits INTEGER NOT NULL
)
```

**New Methods:**

```python
def get_location(self, cache_key: str) -> CachedLocation | None: ...
def put_location(self, record: CachedLocation) -> None: ...
def get_web_search(self, cache_key: str) -> CachedWebSearch | None: ...
def put_web_search(self, record: CachedWebSearch) -> None: ...
def get_web_page(self, cache_key: str) -> CachedWebPage | None: ...
def put_web_page(self, record: CachedWebPage) -> None: ...
def reserve_tavily_credit(self, month_key: str, limit: int = 1000) -> bool: ...
def prune_info_cache(self, before: float) -> None: ...
```

所有写入继续经过现有线程锁与事务；`reserve_tavily_credit` 使用单事务读改写保证原子性。天气不新增表。

### `mewcode.wechat.runtime`

**Responsibility:** 接入服务层、每轮安全环境、固定工具策略、归档脱敏和来源后处理。

**Changes:**

- 启动时按 `WechatInfoConfig.enabled` 创建 `WechatInfoServices`；关闭时释放服务资源。
- 每次 `reply` 创建 `WechatInfoTurn`，把其 Registry 交给 Agent。
- Stable System 由用户角色提示加固定工具策略组成，固定策略不能被自定义角色提示覆盖。
- `environment_supplier` 完全丢弃普通 Coding Agent 环境，只生成微信渠道、本机当前 ISO 时间和 IANA 时区。
- 工具正常完成后通过 `WechatInfoTurn.finalize_reply` 验证来源与署名。
- 恢复好友会话时，过滤以前已经脱敏归档的中间工具消息，只把用户消息和最终助手回复带入后续模型上下文。

### `mewcode.session.runtime` 与 `mewcode.context.controller`

**Responsibility:** 提供默认不影响 TUI 的可选微信归档策略。

**Changes:**

```python
MessageTransform = Callable[[Message], Message]

class SessionRuntime:
    # new / restore / __init__ 增加可选参数
    archive_message_transform: MessageTransform | None = None
    transient_tool_results: bool = False
```

- 默认值保持现有 TUI、Sub-agent 和其他 Session 行为完全不变。
- 微信 transform 保留工具调用 ID 和结构，但把工具参数、工具结果及中间助手文本替换为固定省略标记；用户消息和最终助手文本不变。
- `transient_tool_results=True` 时，如果当前请求尾部是本轮工具结果，ContextController 不执行工具结果落盘、自动压缩或持久化 checkpoint，避免原始网页／天气内容写入 `.mewcode/cache` 或摘要档案。
- 下一次好友消息恢复会话后，微信运行时移除已配对的脱敏工具中间消息；Provider 看到的长期历史仍是用户消息与最终回复。

### `mewcode.wechat.config`

**Responsibility:** 解析嵌套 `wechat.info_tools`，验证类型并解析 Tavily Key 与 Nominatim 指定代理的环境变量引用。

**Example:**

```yaml
wechat:
  enabled: true
  provider: openai
  allowed_contacts:
    - 钟长春
  info_tools:
    enabled: true
    tavily_api_key: ${TAVILY_API_KEY}
    nominatim_user_agent: MewCode-WeChat/0.1
    nominatim_proxy: ${HTTPS_PROXY}
```

Tavily 环境变量不存在时保留“网页搜索未配置”状态。Nominatim 代理配置键省略时允许直连；配置键存在但环境变量不存在时只禁用远程地点解析，不在启动阶段阻断本机时间、已有地点缓存、网页直读或其他能力。配置错误消息不得回显 Key、代理地址或代理凭据。

## Module Interactions

### 时间查询

```text
get_current_time(location?)
  -> location 为空：读取当前系统 aware datetime
  -> 国家命中：静态首都坐标
  -> 地点缓存命中：复用坐标与时区
  -> 否则：Nominatim（全局 1 req/s；仅使用显式指定代理或未配置时直连）
  -> timezonefinder -> IANA timezone
  -> zoneinfo -> 当前当地时间／DST／日期差
  -> SourceLedger 记录 OSM 署名需求
```

### 网页搜索

```text
web_search(query, freshness)
  -> TurnBudget.reserve_search
  -> 规范化与隐私检查
  -> 缓存键与新鲜度判断
  -> 命中：返回缓存并记录来源
  -> 未命中：本月 credit 原子预留
  -> Tavily Basic（失败类型决定是否重试一次）
  -> 保存缓存
  -> SourceLedger 记录最多五条来源
```

### 网页读取

```text
web_fetch(url)
  -> TurnBudget.reserve_page
  -> 移除敏感参数／规范化
  -> 页面缓存检查
  -> 缓存未命中：协议 + DNS + IP 校验
  -> 每次重定向重新校验
  -> 分块读取 2 MiB 上限
  -> MIME 检查 + 可见正文提取 + 50,000 字符上限
  -> 保存缓存并登记来源
  -> 失败时按规则尝试七日内旧缓存
```

### 天气查询

```text
get_weather(location, mode, units)
  -> 地点隐私检查
  -> LocationResolver(coarse_only=True)
  -> 歧义：返回候选并停止
  -> Open-Meteo 最新请求（无天气缓存）
  -> 字段白名单／单位／当地时区转换
  -> SourceLedger 标记天气署名
```

### 会话归档

```text
当前回合内存：user -> assistant(tool args) -> tool(raw result) -> assistant(final)
                        |                   |
                        `---- archive transform ---->

JSONL：user -> assistant(tool omitted) -> tool(result omitted) -> assistant(final)

下次恢复给模型：user -> assistant(final)
```

## File Organization

```text
Mewcode/
+-- README.md                                      # 补充工具配置、权限和服务条款
+-- pyproject.toml                                 # 增加 timezonefinder/tzlocal/tzdata 并打包首都数据
+-- src/mewcode/context/controller.py              # 微信工具续轮禁止原始结果落盘／压缩
+-- src/mewcode/session/runtime.py                 # 可选归档消息变换
+-- src/mewcode/wechat/config.py                   # WechatInfoConfig 与嵌套配置解析
+-- src/mewcode/wechat/runtime.py                  # Registry、环境、归档和来源接入
+-- src/mewcode/wechat/store.py                    # 地点／网页缓存与 Tavily credit
+-- src/mewcode/wechat/info/
|   +-- __init__.py                                # 公开服务与类型导出
|   +-- registry.py                                # 服务集合、回合预算、来源账本、确认门
|   +-- http.py                                    # 标准库 HTTP、SSRF 防护、HTML 提取
|   +-- location.py                                # 地点解析、时区与时间工具
|   +-- web.py                                     # Tavily 搜索与公开网页读取工具
|   +-- weather.py                                 # Open-Meteo 与天气工具
|   `-- country_capitals.json                      # 国家别名、首都与坐标静态数据
+-- tests/test_context_controller.py               # transient 工具结果不落盘
+-- tests/test_session_runtime.py                  # archive transform 默认兼容与脱敏
+-- tests/test_wechat_config.py                    # info_tools 配置与密钥展开
+-- tests/test_wechat_store.py                     # 缓存、清理、credit 原子上限
+-- tests/test_wechat_info_http.py                 # URL、DNS、重定向、MIME、大小、HTML
+-- tests/test_wechat_info_location.py             # 首都、歧义、缓存、限速、DST
+-- tests/test_wechat_info_web.py                  # Tavily、限次、缓存、隐私、失败
+-- tests/test_wechat_info_weather.py              # 字段、单位、范围、无缓存、失败
+-- tests/test_wechat_runtime.py                    # 四工具隔离、时间环境、归档与来源
`-- doc/14/
    +-- spec.md
    +-- plan.md
    +-- task.md
    `-- checklist.md
```

## Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| 微信工具注册 | 每轮新建仅四工具 Registry | 程序级最小权限，调用计数天然按回合隔离 |
| 普通 MewCode 工具 | 不修改默认 Registry | 防止微信需求影响 TUI/Coding Agent |
| HTTP 实现 | 标准库 `urllib` + `asyncio.to_thread` | 三个简单 JSON API 和静态页面读取不需要额外 SDK |
| Nominatim 代理 | 独立显式代理 Transport，配置后失败关闭 | 解决当前网络直连不可达，同时不把代理扩散到其他工具或变成通用网络能力 |
| Tavily 网络 | 保持无代理直连 | 本机无 Key 连通性测试已返回 HTTP 401，证明固定端点直连可达，无需扩大代理范围 |
| HTML 提取 | 标准库 `html.parser` | 第一版只需静态可见文本，避免浏览器和解析器依赖 |
| 时区计算 | `tzlocal` + `timezonefinder` + `zoneinfo` + `tzdata` | Windows 本机时区与坐标时区都使用 IANA 数据并正确处理 DST |
| 国家时间 | 打包静态国家首都数据 | 国家查询必须确定性映射到首都，不交给模型或网络猜测 |
| 地点解析 | 本地规则／缓存优先，Nominatim 兜底 | 满足低频公共服务、限速和离线复用要求 |
| 搜索 | Tavily Basic 固定参数 | 符合免费额度与已批准功能范围 |
| 网页正文 | 直接安全 GET，不使用 Tavily Extract | 减少 credits，同时能强制 SSRF、大小和 MIME 边界 |
| 天气 | Open-Meteo best_match，每次请求 | 唯一免费非商业来源，明确不缓存天气 |
| 工具结果存储 | JSONL 只存脱敏结构，下一轮过滤 | 保持工具调用链和档案索引完整，同时不保存查询参数和原文 |
| 大型工具结果 | 微信工具续轮禁止 artifact spill 与压缩 | 防止原始网页和天气结果进入 `.mewcode/cache` 或 checkpoint |
| 网页来源 | 回合 Ledger + 回复后处理兜底 | 不只依赖模型记得附来源和署名 |
| 敏感搜索确认 | 内存短期 query hash | 不把搜索正文与好友关联持久化，也能支持下一轮明确确认 |
| 天气缓存 | 不创建 | 用户已明确要求每次查询最新数据 |
| 缓存存储 | 复用 `wechat.sqlite3` | 无需 Redis 或新服务，现有锁与生命周期已满足本地串行运行 |

## Spec Coverage

| Spec | Design Coverage |
|---|---|
| F1 | 每轮专用 Registry、固定四工具、默认 Registry 不变 |
| F2-F3 | 安全环境、LocationResolver、国家首都数据、timezonefinder/zoneinfo、Nominatim 独立显式代理 |
| F4 | Tavily Basic、TurnBudget、monthly credit |
| F5 | SafePublicHttpClient、重定向校验、MIME／大小限制、静态 HTML |
| F6 | 固定系统策略、SourceLedger、回复后处理 |
| F7-F8 | 查询隐私门、URL 脱敏、SSRF、外部内容不可信标记 |
| F9 | 回合等待预算、有限重试、SQLite 搜索／页面缓存与清理 |
| F10-F12 | OpenMeteoClient、无天气缓存、地点隐私、专用路由与失败策略 |
| F13 | archive transform、transient 工具续轮、日志最小化 |
| F14 | WechatInfoConfig、环境变量密钥与代理、失败关闭和服务降级 |
| N1-N7 | 程序硬限制、代理隔离、独立缓存、固定免费服务、Fake Transport 和回归测试 |
