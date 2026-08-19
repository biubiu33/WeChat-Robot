# MewCode 微信侧受限信息工具 V1 Tasks

状态：已批准（含 Nominatim 指定代理修订 T20-T24）

## File List

| Action | File | Responsibility |
|---|---|---|
| Modify | `pyproject.toml` | 增加时区依赖并打包国家首都数据 |
| Modify | `README.md` | 说明微信工具配置、指定代理、权限、费用与服务边界 |
| Modify | `.mewcode/config.yaml.example` | 增加不含真实地址的 Nominatim 代理环境变量示例 |
| Modify | `src/mewcode/context/controller.py` | 微信工具续轮禁止原始工具结果落盘和压缩 |
| Modify | `src/mewcode/session/runtime.py` | 支持可选会话归档消息变换 |
| Modify | `src/mewcode/wechat/config.py` | 解析 `wechat.info_tools`、密钥与 Nominatim 代理环境变量 |
| Modify | `src/mewcode/wechat/runtime.py` | 接入四工具 Registry、时间环境、会话脱敏和回复后处理 |
| Modify | `src/mewcode/wechat/store.py` | 地点／网页缓存和 Tavily 月度 credit 状态 |
| Create | `src/mewcode/wechat/info/__init__.py` | 导出微信公共信息服务接口 |
| Create | `src/mewcode/wechat/info/registry.py` | 服务集合、Nominatim 代理隔离、回合预算、来源账本和敏感搜索确认 |
| Create | `src/mewcode/wechat/info/http.py` | 直连／显式代理 HTTP Transport、SSRF 防护和静态正文提取 |
| Create | `src/mewcode/wechat/info/location.py` | 地点解析、代理失败关闭、时区计算和当前时间工具 |
| Create | `src/mewcode/wechat/info/web.py` | Tavily 搜索和公开网页读取工具 |
| Create | `src/mewcode/wechat/info/weather.py` | Open-Meteo 客户端和天气工具 |
| Create | `src/mewcode/wechat/info/country_capitals.json` | 国家别名、首都和坐标静态数据 |
| Create | `tests/test_context_controller.py` | transient 工具结果不落盘测试 |
| Create | `tests/test_session_runtime.py` | Session 归档变换兼容与脱敏测试 |
| Modify | `tests/test_wechat_config.py` | 微信信息工具及 Nominatim 代理配置测试 |
| Modify | `tests/test_wechat_store.py` | 缓存、清理和 credit 原子上限测试 |
| Create | `tests/test_wechat_info_http.py` | 直连／显式代理、URL、DNS、重定向、MIME、大小与 HTML 测试 |
| Create | `tests/test_wechat_info_location.py` | 国家首都、Nominatim 代理、歧义、缓存、时区与 DST 测试 |
| Modify (local) | `C:\Users\nhdt_\.mewcode\config.yaml` | 启用信息工具并显式引用本机 Nominatim 代理；不纳入 Git |
| Create | `tests/test_wechat_info_web.py` | Tavily、限次、缓存、隐私、来源和失败测试 |
| Create | `tests/test_wechat_info_weather.py` | 天气字段、单位、范围、无缓存和失败测试 |
| Modify | `tests/test_wechat_runtime.py` | 四工具隔离、环境、归档、恢复和后处理集成测试 |
| Modify | `doc/14/spec.md` | 保留批准状态 |
| Modify | `doc/14/plan.md` | 保留批准状态 |
| Create | `doc/14/task.md` | 开发任务拆分 |
| Create | `doc/14/checklist.md` | 后续验收设计 |

## T1：增加时区依赖和数据打包规则

**Files:** `pyproject.toml`
**Dependencies:** None

**Steps:**

1. 在 `wechat` 可选依赖中增加兼容 Python 3.12 的 `tzlocal`、`timezonefinder` 和 `tzdata`。
2. 配置构建系统把 `country_capitals.json` 包含进 wheel。
3. 不把 Tavily、Open-Meteo SDK、浏览器或 HTML 第三方解析器加入依赖。

**Validation:**

```powershell
conda run -n mewcode python -m pip install -e ".[wechat]"
conda run -n mewcode python -c "import timezonefinder, tzlocal, tzdata"
```

期望：可选依赖安装成功，三个模块均可导入。

## T2：扩展微信信息工具配置

**Files:** `src/mewcode/wechat/config.py`, `tests/test_wechat_config.py`
**Dependencies:** None

**Steps:**

1. 增加 `WechatInfoConfig` 并作为带默认值的 `WechatConfig` 字段，保持旧的构造和无配置行为兼容。
2. 解析 `wechat.info_tools.enabled`、`tavily_api_key` 和 `nominatim_user_agent`。
3. 支持 Tavily Key 的 `${ENV_NAME}` 展开；缺失变量返回未配置状态，不回显密钥。
4. 为错误类型、默认禁用、字面 Key、环境变量 Key 和缺失 Key 增加测试。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_config.py -q
```

期望：旧微信配置继续通过，新配置与密钥展开测试通过。

## T3：扩展 SQLite 信息缓存和免费额度状态

**Files:** `src/mewcode/wechat/store.py`, `tests/test_wechat_store.py`
**Dependencies:** None

**Steps:**

1. 增加地点、网页搜索、网页正文和 Tavily 月度使用量表。
2. 增加缓存记录的读取、覆盖写入和七日前网页缓存清理方法。
3. 实现单事务 `reserve_tavily_credit`，在 1,000 credits 上限前原子预留。
4. 测试缓存不含好友／Session 字段、重开数据库后仍可读取、并发预留不超过上限。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_store.py -q
```

期望：现有事件与绑定测试及新增缓存／credit 测试全部通过。

## T4：实现 Session 归档消息变换

**Files:** `src/mewcode/session/runtime.py`, `tests/test_session_runtime.py`
**Dependencies:** None

**Steps:**

1. 为 `SessionRuntime.__init__`、`new` 和 `restore` 增加默认关闭的 `archive_message_transform`。
2. 写入 JSONL 前调用变换；内存 Conversation 继续保留原消息供当前 Provider 使用。
3. 验证不传 transform 时归档字节级行为保持不变。
4. 验证 transform 可以清除工具参数和结果，但不改变用户及最终助手消息。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_session_runtime.py tests/test_session_archive.py -q
```

期望：新增变换测试和原会话档案测试通过。

## T5：禁止微信 transient 工具结果进入会话缓存

**Files:** `src/mewcode/context/controller.py`, `tests/test_context_controller.py`
**Dependencies:** T4

**Steps:**

1. 为 `ContextController` 增加默认关闭的 `transient_tool_results` 选项。
2. 该选项启用且当前尾部为工具结果时，跳过 artifact spill、自动压缩和 checkpoint 写入。
3. 普通 TUI 默认路径继续执行现有大型工具归档与压缩。
4. 分别测试 transient 与默认模式，确认原始工具正文不会写入 cache 或 JSONL。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_context_controller.py tests/test_context_artifact.py tests/test_context_budget.py -q
```

期望：微信 transient 模式不落盘，普通 Context 行为无回退。

## T6：实现回合预算、来源账本和确认门

**Files:** `src/mewcode/wechat/info/registry.py`, `tests/test_wechat_info_web.py`
**Dependencies:** T3

**Steps:**

1. 实现 `TurnBudget` 的两次搜索、五次页面和 25 秒累计等待限制。
2. 实现 `SourceLedger` 的来源去重、未知 URL 移除、最多三条来源与 OSM／Open-Meteo 署名兜底。
3. 实现只保存 query hash 的进程内 `PendingSearchConsent`，并设置短期失效与一次性消费。
4. 先为这些纯逻辑组件添加单元测试，不在本任务创建真实工具 Registry。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_web.py -q -k "budget or ledger or consent"
```

期望：所有回合硬限制、来源后处理和确认状态测试通过。

## T7：实现固定用途 HTTP Transport

**Files:** `src/mewcode/wechat/info/http.py`, `tests/test_wechat_info_http.py`
**Dependencies:** None

**Steps:**

1. 定义 `HttpRequest`、`HttpResponse`、`HttpTransport` 与标准库 `UrllibTransport`。
2. 使用 `asyncio.to_thread` 执行阻塞 I/O，默认验证 TLS，禁用继承的代理和 Cookie。
3. 分块读取并强制 `max_bytes`，请求 `Accept-Encoding: identity`。
4. 使用 Fake Transport 测试状态码、超时、取消和响应上限，不访问公网。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_http.py -q -k "transport or limit or timeout"
```

期望：Transport 边界和取消行为测试通过。

## T8：实现公开 URL 安全与正文提取

**Files:** `src/mewcode/wechat/info/http.py`, `tests/test_wechat_info_http.py`
**Dependencies:** T7

**Steps:**

1. 实现 URL 规范化、敏感查询参数移除和凭据型 URL 拒绝。
2. 对初始地址及每次重定向执行协议、DNS 和全部 IP `is_global` 校验。
3. 仅接受 HTML／纯文本 MIME；拒绝文件、图片和其他类型。
4. 用标准库 HTML Parser 跳过脚本、样式、表单、模板、SVG 与隐藏节点，并截断到 50,000 字符。
5. 覆盖回环、私网、混合 DNS、重定向到内网、2 MiB 上限、非法编码和恶意 HTML 测试。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_http.py -q
```

期望：全部 SSRF、内容类型、大小和正文提取测试通过。

## T9：建立国家首都静态数据

**Files:** `src/mewcode/wechat/info/country_capitals.json`, `tests/test_wechat_info_location.py`
**Dependencies:** T1

**Steps:**

1. 添加国家中文／英文名称、常用别名、首都和 WGS84 坐标的静态数据。
2. 对美国明确映射华盛顿特区，并覆盖中国、日本、英国等常用输入。
3. 增加数据结构、重复别名、坐标范围和必填字段校验测试。
4. 验证安装后的包可通过资源 API 读取该 JSON。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_location.py -q -k "capital or dataset"
```

期望：首都数据完整性和包资源读取测试通过。

## T10：实现地点解析与 Nominatim 限速

**Files:** `src/mewcode/wechat/info/location.py`, `tests/test_wechat_info_location.py`
**Dependencies:** T1, T3, T7, T9

**Steps:**

1. 实现地点规范化、国家首都优先、SQLite 地点缓存和 Nominatim 兜底。
2. 固定 Nominatim 公共搜索参数并使用配置 User-Agent；进程级锁保证请求间隔至少一秒。
3. 使用 `timezonefinder` 把候选坐标转换为 IANA 时区。
4. 对跨城市／行政区的可信候选返回 `ambiguous`，不自动选第一项。
5. 实现 `coarse_only` 精确住址拦截，并测试缓存优先、无缓存失败、候选歧义、限速和 OSM 署名标记。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_location.py -q -k "resolver or nominatim or ambiguous or privacy"
```

期望：地点解析、缓存、限速、歧义和隐私测试通过，网络全部由 Fake Transport 提供。

## T11：实现当前时间／地点时间工具

**Files:** `src/mewcode/wechat/info/location.py`, `tests/test_wechat_info_location.py`
**Dependencies:** T10

**Steps:**

1. 实现 `CurrentTimeTool` 参数校验与无地点的本机时间路径。
2. 使用 `tzlocal` 取得 Windows 本机 IANA 时区，使用 `zoneinfo` 计算当地时间、UTC 偏移和 DST。
3. 地点查询返回规范地点、日期差和歧义候选；Nominatim 来源标记 OSM 署名。
4. 用固定 Clock 测试华盛顿特区、跨日、夏令时、非夏令时和未知地点。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_location.py -q
```

期望：国家首都、明确城市、DST、跨日及错误结果全部可重复通过。

## T12：实现 Tavily Basic 网页搜索

**Files:** `src/mewcode/wechat/info/web.py`, `tests/test_wechat_info_web.py`
**Dependencies:** T2, T3, T6, T7

**Steps:**

1. 实现固定 Tavily `/search` 客户端，只发送 Basic、最多五条、无生成答案／全文的请求。
2. 实现查询规范化、明显敏感信息检测、确认门和正常／latest 缓存策略。
3. 每次真实尝试前原子预留免费 credit；缺 key、鉴权、额度、限流和参数错误不重试。
4. 临时网络或 `5xx` 最多重试一次；普通查询可回退七日内旧缓存，latest 不得回退超过五分钟的缓存。
5. 测试缓存命中、每轮第三次拒绝、每月 1,000 上限、响应裁剪和错误脱敏。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_web.py -q -k "search or tavily or cache or credit or privacy"
```

期望：Tavily 请求参数、费用边界、缓存和失败策略测试通过，不产生真实 API 请求。

## T13：实现安全公开网页读取工具

**Files:** `src/mewcode/wechat/info/web.py`, `tests/test_wechat_info_web.py`
**Dependencies:** T3, T6, T8

**Steps:**

1. 实现 `WebFetchTool`，只接受 URL 并复用 `SafePublicHttpClient`。
2. 实现一小时新鲜缓存、七日失败回退和最终 URL 缓存键。
3. 返回结构化的不可信正文、标题、截断状态和缓存时间，并登记实际页面来源。
4. 测试第五／第六个页面、重定向最终来源、旧缓存标记、全部失败和提示注入文本仅作为数据返回。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_web.py -q -k "fetch or page or source or injection"
```

期望：页面预算、缓存、来源和不可信内容测试通过。

## T14：实现 Open-Meteo 天气工具

**Files:** `src/mewcode/wechat/info/weather.py`, `tests/test_wechat_info_weather.py`
**Dependencies:** T7, T10

**Steps:**

1. 实现固定 Open-Meteo Forecast API 客户端和批准字段白名单。
2. 实现 current、未来 48 小时 hourly、未来 7 天 daily 三种模式。
3. 使用解析地点的 IANA 时区和请求单位；把 WMO 天气代码与风向转换为中文。
4. 每次调用都发起新请求，不读写天气缓存；临时错误最多重试一次，失败不调用网页工具。
5. 测试无地点、歧义、精确地址拒绝、单位、当地日期、字段裁剪、连续调用和失败隔离。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_weather.py -q
```

期望：天气范围、单位、无缓存、隐私和失败测试通过。

## T15：组装微信四工具 Registry

**Files:** `src/mewcode/wechat/info/registry.py`, `src/mewcode/wechat/info/__init__.py`, `tests/test_wechat_info_web.py`, `tests/test_wechat_info_weather.py`
**Dependencies:** T11, T12, T13, T14

**Steps:**

1. 实现 `WechatInfoServices`，跨回合复用 Transport、LocationResolver、限速器和确认状态。
2. 服务启动时清理七日前网页缓存，但保留长期地点缓存。
3. 实现 `new_turn`，为每条消息创建独立 TurnBudget、SourceLedger 和仅四工具 Registry。
4. 保证四工具均为 read-only，Registry 不含默认文件、Bash、MCP 或系统控制工具。
5. 测试不同好友／不同回合计数隔离、启动清理、关闭工具时 Registry 为空、服务关闭幂等。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_web.py tests/test_wechat_info_weather.py -q -k "registry or isolation or close"
```

期望：Registry 名称精确等于四个批准工具，回合状态互不污染。

## T16：接入微信 Agent Runtime

**Files:** `src/mewcode/wechat/runtime.py`, `tests/test_wechat_runtime.py`
**Dependencies:** T2, T4, T5, T15

**Steps:**

1. 启动时创建 `WechatInfoServices`，每次 reply 使用当前回合 Registry。
2. 将固定工具安全／路由策略追加到用户角色提示，不能被自定义提示覆盖。
3. 每次 Provider 请求重新生成微信渠道、本机当前 ISO 时间和 IANA 时区环境，继续丢弃 Coding Agent 环境。
4. 为微信 Session 启用工具归档脱敏与 transient 结果模式；恢复时移除中间工具对。
5. Agent 完成后调用 SourceLedger 后处理，关闭运行时释放服务。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_runtime.py -q
```

期望：四工具定义、动态时间环境、好友会话恢复、取消和关闭测试通过。

## T17：验证归档、来源和权限端到端集成

**Files:** `tests/test_wechat_runtime.py`, `tests/test_session_runtime.py`, `tests/test_context_controller.py`
**Dependencies:** T16

**Steps:**

1. 用可调用工具的 Fake Provider 完成搜索／读取／最终回答的完整 ReAct 回合。
2. 断言当前 Provider 续轮能看到原始工具结果，但 JSONL 和 `.mewcode/cache` 不包含查询参数、网页正文、天气返回体或 API Key。
3. 重启并恢复 Session，断言模型历史只包含用户消息和最终回复。
4. 验证缺失来源、未知来源、OSM 与 Open-Meteo 署名由后处理安全规范化，来源位于回复末尾。
5. 验证请求 Bash、文件、MCP、浏览器和 Sub-agent 时均不存在可调用定义。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_runtime.py tests/test_session_runtime.py tests/test_context_controller.py -q
```

期望：完整工具循环、存储边界、来源后处理和权限隔离测试通过。

## T18：更新用户文档与配置示例

**Files:** `README.md`
**Dependencies:** T2, T16

**Steps:**

1. 更新微信配置示例，使用 `${TAVILY_API_KEY}`，不写真实 Key。
2. 说明四工具白名单、每轮限制、缓存位置、天气不缓存和原始工具结果不进入会话档案。
3. 说明 Tavily 免费 Basic、Open-Meteo 非商业与署名、Nominatim 限速与 OSM 署名边界。
4. 明确不支持动态浏览器、PDF、登录网页、任意 HTTP、本机工具和商业天气使用。

**Validation:**

```powershell
rg -n "info_tools|TAVILY_API_KEY|Open-Meteo|OpenStreetMap|每轮最多|不缓存" README.md
rg -n "tvly-[A-Za-z0-9_-]+" README.md
```

期望：第一条能定位完整说明，第二条没有真实 Tavily Key 命中。

## T19：执行完整质量与回归验证

**Files:** All changed source, tests, and docs
**Dependencies:** T1-T18

**Steps:**

1. 运行全部微信单元与集成测试，确认不连接真实外部服务或微信。
2. 运行项目完整测试套件，确认 TUI、Agent、Session、MCP、Skills、Sub-agent 和 Hook 无回退。
3. 运行 Ruff 格式检查、Ruff lint 和 Mypy。
4. 搜索 API Key、原始工具结果测试夹具泄漏、未完成标记和通用网络工具注册。
5. 记录实际通过数量和唯一跳过项，供 checklist 验收使用。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_*.py -q
conda run -n mewcode python -m pytest -q -p no:cacheprovider
conda run -n mewcode python -m ruff format --check src tests
conda run -n mewcode python -m ruff check src tests
conda run -n mewcode python -m mypy src/mewcode
git diff --check
```

期望：新增微信测试、完整回归、格式、lint、类型检查和 diff 检查全部通过。

## T20：解析 Nominatim 显式代理配置

**Files:** `src/mewcode/wechat/config.py`, `tests/test_wechat_config.py`
**Dependencies:** T19

**Steps:**

1. 为微信信息配置增加 Nominatim 代理值及“配置键是否出现”的内部状态，保持旧配置默认直连。
2. 支持代理字面值和 `${ENV_NAME}` 引用；环境变量缺失时保留“已配置但不可用”状态，不静默变成直连。
3. 只接受字符串配置，不在错误中回显代理地址或凭据，也不让代理配置阻止机器人整体启动。
4. 测试省略、字面值、环境变量、缺失环境变量和错误类型，确认 Tavily Key 的既有行为不变。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_config.py -q
```

期望：旧配置兼容，代理配置状态可区分，错误与断言不包含代理秘密。

## T21：为标准库 Transport 增加显式代理

**Files:** `src/mewcode/wechat/info/http.py`, `tests/test_wechat_info_http.py`
**Dependencies:** T20

**Steps:**

1. 为 `UrllibTransport` 增加可选代理参数；默认继续使用空 `ProxyHandler`，不得继承 `HTTP_PROXY`／`HTTPS_PROXY`。
2. 提供合法 HTTP/HTTPS 代理时，只向 opener 安装该显式代理；请求对象和工具参数中不出现代理 URL。
3. 拒绝不支持的代理协议和无主机代理值，错误只返回安全类别，不回显完整代理。
4. 用 monkeypatch 捕获 opener 配置，分别验证默认直连、显式代理和非法代理，不发真实网络请求。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_http.py -q -k "transport or proxy"
```

期望：Transport 仅使用显式代理，默认路径和公开网页安全行为不回退。

## T22：只为 Nominatim 组装代理并失败关闭

**Files:** `src/mewcode/wechat/info/registry.py`, `src/mewcode/wechat/info/location.py`, `tests/test_wechat_info_location.py`, `tests/test_wechat_info_weather.py`, `tests/test_wechat_info_web.py`
**Dependencies:** T20, T21

**Steps:**

1. 生产服务只为 `LocationResolver` 创建指定代理 Transport；测试注入的 Fake Transport 接口保持不变。
2. 配置键省略时维持 Nominatim 直连；配置键存在且代理有效时使用代理。
3. 配置键存在但环境变量缺失、URL 非法或代理不可达时，仍允许本地国家首都和已有地点缓存，但远程地点解析安全失败且不尝试直连。
4. 断言 Tavily、Open-Meteo 和公开网页读取仍使用无代理 Transport，模型无法提交或读取代理参数。
5. 使用唯一代理 canary 扫描工具结果、日志、SQLite、JSONL 和缓存，确认代理地址与凭据不泄漏。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_location.py tests/test_wechat_info_weather.py tests/test_wechat_info_web.py -q -k "proxy or resolver or registry or isolation"
```

期望：Nominatim 代理成功、失败关闭和其他服务隔离测试全部通过。

## T23：更新配置示例、用户文档和本机配置

**Files:** `README.md`, `.mewcode/config.yaml.example`, `C:\Users\nhdt_\.mewcode\config.yaml`
**Dependencies:** T22

**Steps:**

1. 在版本库示例中使用 `nominatim_proxy: ${HTTPS_PROXY}`，不写入真实代理地址或凭据。
2. 说明代理仅用于固定 Nominatim 地址；Tavily、Open-Meteo 和公开网页读取仍不使用该代理。
3. 说明配置键省略、环境变量缺失和代理不可达时的直连／失败关闭行为。
4. 在本机生效配置中加入 `${HTTPS_PROXY}` 引用；不修改 Provider、好友白名单或其他凭据，不把本机配置提交 Git。

**Validation:**

```powershell
rg -n "nominatim_proxy|HTTPS_PROXY|Nominatim|Tavily|Open-Meteo" README.md .mewcode/config.yaml.example
conda run -n mewcode python -c "from mewcode.config import discover_config_path, load; from mewcode.wechat.config import parse_wechat_config; p=load(str(discover_config_path().path)); w=parse_wechat_config(p.wechat,{x.name for x in p.providers}); assert w.info_tools.enabled and w.info_tools.nominatim_proxy_configured and w.info_tools.nominatim_proxy"
```

期望：示例无真实代理，当前配置解析为信息工具启用且 Nominatim 指定代理可用。

## T24：执行代理修订验收和完整回归

**Files:** All proxy-revision source, tests, docs, and local config
**Dependencies:** T23

**Steps:**

1. 运行代理修订定向测试、全部微信测试和完整项目测试。
2. 对改动文件运行 Ruff format、Ruff lint、Mypy 和 `git diff --check`。
3. 扫描工作树和运行产物，确认没有真实代理地址、代理凭据或 Tavily Key。
4. 使用本机配置执行不发送微信消息的真实“上海当前天气”后端冒烟，确认 Nominatim 经指定代理解析、Open-Meteo 直连并返回署名状态。
5. 再次执行无 Key Tavily 无代理连通性检查，预期到达固定端点且不消耗 credit。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_config.py tests/test_wechat_info_http.py tests/test_wechat_info_location.py tests/test_wechat_info_weather.py tests/test_wechat_info_web.py -q
conda run -n mewcode python -m pytest tests/test_wechat_*.py -q
conda run -n mewcode python -m pytest -q -p no:cacheprovider
conda run -n mewcode python -m ruff format --check src tests
conda run -n mewcode python -m ruff check src tests
conda run -n mewcode python -m mypy src/mewcode/wechat
git diff --check
```

期望：自动化验证全部通过；真实后端冒烟成功且不发送微信消息；Tavily 保持无代理直连。

## Execution Order

```text
T1 ----> T9
 |        |
 |        v
 |       T10 ---> T11 --+
 |        |              |
 |        +----> T14 ----+
 |                       |
T2 ----> T12 ------------+
 |                        |
T3 -> T6 -> T12 -> T13 --+--> T15 --> T16 --> T17 --> T18 --> T19
 |         ^              |
 |         |              |
 +-------> T7 -> T8 ------+

T4 --> T5 ----------------------------> T16

T19 -> T20 -> T21 -> T22 -> T23 -> T24
```

独立底座任务 T1-T8 可按文件冲突约束交错执行；同一文件的任务必须保持编号顺序。原功能完成 T19 后，代理修订严格按 T20-T24 执行并单独验收。
