# MewCode 微信侧受限信息工具 V1 Checklist

状态：开发完成（Nominatim 指定代理修订验收通过；真实微信端到端仍待执行）

> 每一项必须通过运行代码、检查持久化结果或观察真实微信行为验证。自动化测试必须使用 Fake Provider / Fake Transport，不访问真实微信和外部服务。

## Implementation Completeness

- [x] 微信信息工具配置可以启用或禁用；未配置时保持 Chapter 13 的空工具行为。（验证：运行 `tests/test_wechat_config.py` 和微信 Runtime 默认配置测试）
- [x] Tavily Key 支持字面值和 `${ENV_NAME}`，缺失环境变量不会阻断时间、网页直读或天气能力。（验证：配置测试分别加载三种配置并观察结果）
- [x] 安装 `.[wechat]` 后可以导入 `tzlocal`、`timezonefinder` 和 `tzdata`，安装包可以读取国家首都资源。（验证：在干净的 `mewcode` conda 环境执行导入与资源读取命令）
- [x] 现有微信 SQLite 数据库可以无损增加地点、网页和 credit 状态，旧事件和好友绑定仍可读写。（验证：运行 `tests/test_wechat_store.py`）
- [x] 天气响应没有对应缓存表或缓存写入路径。（验证：连续天气调用后检查 SQLite schema 与记录）

## Permission Isolation — AC1

- [x] 启用信息工具后，微信模型请求只暴露 `get_current_time`、`web_search`、`web_fetch`、`get_weather`。（验证：Fake Provider 捕获 Request 并精确比较工具名集合）
- [x] 微信模型请求 Bash、文件读写、代码编辑、Glob、Grep、MCP、Skills、Sub-agent、Hook、浏览器或任意 HTTP 时均无法执行。（验证：Fake Provider 逐一生成未注册工具调用并观察 `unknown_tool`／停止行为）
- [x] 工具白名单由 Registry 强制，修改微信系统提示或好友消息不能新增工具。（验证：自定义恶意 system prompt 与用户消息后再次检查 Request 工具定义）
- [x] 四个微信工具全部标记为只读，不存在可写本机或可自定义网络方法的参数。（验证：检查 `read_only_definitions` 与四个 JSON Schema）
- [x] 普通 MewCode TUI 的默认 Registry 仍包含原有工具，不包含微信专用工具。（验证：运行 `tests/test_tool.py` 和 TUI Registry 测试）

## Current Time And Location — AC2

- [ ] 连续两次微信 Provider 请求分别生成新的本机当前日期、时间和 IANA 时区，不包含工作目录、用户名或其他 Coding Agent 环境。（验证：注入可控 Clock 后比较两次 Request environment）
- [x] 省略地点时返回本机当前时间，并可在 Windows 上取得 IANA 时区名称。（验证：时间工具单元测试及本机人工调用）
- [x] 输入“美国”时规范地点为华盛顿特区，并按 `America/New_York` 返回当地时间。（验证：固定 UTC Clock 的国家首都测试）
- [x] 输入明确城市时使用该城市坐标对应的 IANA 时区，不让模型提交或猜测时区。（验证：Fake Nominatim 与 timezonefinder 集成测试）
- [x] 夏令时和非夏令时日期返回正确 UTC 偏移与 DST 状态。（验证：固定冬季／夏季 Clock 测试）
- [x] 当目标地点与本机跨日时，结果包含正确的日期差。（验证：固定在 UTC 日期边界的测试）
- [x] 同名地点返回候选并要求确认，不默认选择第一条。（验证：Fake Nominatim 返回跨行政区候选）
- [x] Nominatim 请求间隔不小于一秒，缓存命中不发起请求，网络失败且无缓存时返回明确错误。（验证：Fake Clock / Fake Transport 的限速与缓存测试）
- [x] 使用 Nominatim 结果的最终回复包含 OpenStreetMap 署名。（验证：SourceLedger 后处理测试）

## Nominatim Explicit Proxy Revision — AC2 / AC7 / AC10

- [x] 省略 `nominatim_proxy` 时，Nominatim 使用不继承 `HTTP_PROXY`、`HTTPS_PROXY` 或系统代理设置的直连 Transport。（验证：设置带唯一 canary 的系统代理环境变量，构造服务并断言 `ProxyHandler({})` 及捕获请求未使用 canary）
- [x] `nominatim_proxy` 配置为字面值或 `${ENV_NAME}` 时，仅 Nominatim 请求使用解析后的指定 HTTP/HTTPS 代理。（验证：Fake Proxy 捕获 Nominatim 请求；配置测试覆盖字面值、环境变量与空值）
- [x] 显式代理环境变量缺失、代理地址无效或代理不可达时，远程地点解析返回安全错误，不绕过代理直连，也不切换其他地点服务；本地时间、内置国家首都和已缓存地点仍可用。（验证：逐类失败注入并比较代理、直连和其他 Transport 调用次数）
- [x] Nominatim 代理不影响 Tavily、Open-Meteo 和 `web_fetch`，后三者继续使用各自不继承系统代理的直连 Transport。（验证：为代理设置唯一 canary，分别调用四类网络客户端并精确比较捕获的连接路径）
- [x] 微信模型只能看到原有四个工具定义；Provider Request、工具参数和工具 Result 均不包含代理配置或代理凭据。（验证：用唯一代理 canary 构建 Runtime，扫描全部 Provider Request 与工具事件）
- [x] 代理地址和凭据不出现在微信回复、日志、异常、SQLite、JSONL、缓存或 Git diff 中。（验证：使用唯一 canary 执行成功及失败路径后，对全部运行产物和工作树做精确搜索）
- [x] 本机配置中的 `nominatim_proxy: ${HTTPS_PROXY}` 可以在不打印实际代理值的情况下启用地点解析。（验证：只记录“已配置／未配置”状态，并扫描控制台与日志中不存在代理 canary）

## Automatic Web Search — AC3

- [x] Tavily 请求固定使用 Basic 搜索、最多五条结果，不请求生成答案、Advanced 或原始网页正文。（验证：Fake Transport 捕获并比较请求 JSON）
- [x] 同一回合前两次搜索允许执行，第三次在发出网络请求前被拒绝；缓存命中也计入回合次数。（验证：TurnBudget 与 Fake Transport 调用次数）
- [ ] 最新、政策、价格、版本等问题的固定工具策略允许模型自动搜索；闲聊、改写、翻译、计算、时间和普通天气明确要求不搜索。（验证：检查稳定系统策略，并用批准 Provider 完成代表性人工冒烟）
- [ ] 每次真实 Tavily 尝试前原子预留 credit，同一自然月不会超过本地 1,000 上限。（验证：并发 Store 测试和边界值测试）
- [x] 缓存命中不消耗 Tavily credit，服务端提前报告额度不足时不重试或切换搜索服务。（验证：Fake 额度错误响应和 SQLite 使用量）
- [ ] 缺失／无效 API Key、鉴权失败或免费额度耗尽时返回明确错误，不影响其他三个工具。（验证：同一 Runtime 依次调用网页搜索、时间、网页直读和天气）

## Public Web Fetch Security — AC4

- [x] 普通公开 HTML 与 `text/plain` URL 可以提取标题和可见正文。（验证：Fake HTTP 页面测试）
- [x] `file:`、FTP、凭据型 URL、本机名、回环、私网、链路本地、保留地址及混合 DNS 结果全部被拒绝。（验证：参数化 URL / DNS 测试）
- [x] 每次重定向前重新校验目标，公开 URL 重定向到内网时在连接内网前停止。（验证：Fake Redirect Handler 调用序列）
- [x] 疑似 token、key、auth、signature、session 等敏感查询参数被移除；无法安全清理时拒绝。（验证：URL 脱敏测试）
- [x] HTTP 请求不继承系统代理、浏览器 Cookie、认证存储或模型自定义 Header。（验证：Transport 构建与捕获请求测试）
- [ ] 响应读取超过 2 MiB 时立即停止，HTML 提取超过 50,000 字符时标记截断。（验证：边界字节流与长正文测试）
- [ ] 图片、PDF、音视频、压缩包、可执行文件和其他非 HTML／纯文本 MIME 被拒绝。（验证：参数化 Content-Type 测试）
- [x] 第六次页面读取在网络请求前被拒绝。（验证：TurnBudget 与 Transport 调用计数）
- [x] JavaScript 页面、登录页或验证码页无法取得正文时返回明确说明，不启动浏览器或尝试交互。（验证：空壳动态 HTML 测试并检查进程未创建浏览器）

## Web Timeout And Cache — AC5

- [ ] 普通搜索在 30 分钟内命中缓存，网页正文在 1 小时内命中缓存。（验证：Fake Clock 推进到边界前后）
- [x] `latest` 搜索只使用 5 分钟内缓存，网络失败时也不回退到超过 5 分钟的结果。（验证：Fake Clock 与失败响应）
- [ ] 普通搜索或网页读取仅在网络失败时使用七日内旧缓存，并返回缓存时间与过期标记。（验证：缓存回退测试）
- [x] 七日前网页缓存启动时被清理，长期地点缓存不被清理。（验证：服务初始化前后查询 SQLite）
- [ ] 单次搜索、网页读取和天气请求 10 秒超时；网页工具累计等待达到 25 秒后拒绝继续等待。（验证：Fake Clock / Blocking Transport）
- [ ] 临时网络和 `5xx` 最多重试一次；鉴权、额度、限流和参数错误不重试。（验证：逐类 Fake 响应并比较调用次数）
- [ ] 部分来源成功时可继续回答并标注未核实部分；全部失败且无允许缓存时不生成虚构事实。（验证：Fake Provider 完整回合）

## Sources And Untrusted Content — AC6

- [x] 使用网页工具的最终回复只保留当前回合实际返回的来源，最多三个标题和 URL。（验证：回复包含有效、未知和重复 URL 的 SourceLedger 测试）
- [ ] 模型漏写来源时程序自动追加；长回复分段后来源位于最后一条微信消息。（验证：Runtime 后处理与现有回复分段测试）
- [ ] 直接总结用户 URL 时最终回复包含脱敏后的最终公开 URL。（验证：重定向页面完整回合）
- [x] 脚本、样式、表单、模板、SVG 和隐藏节点不进入提取正文。（验证：恶意 HTML fixture）
- [ ] 网页正文中的“忽略系统指令”“调用工具”“泄露聊天”等内容只作为不可信数据，不扩大 Registry 或触发额外页面。（验证：恶意页面 + Fake Provider 回合）
- [ ] 来源冲突时系统策略要求说明分歧；医疗、法律和投资回答包含非专业替代提示。（验证：固定策略检查与批准 Provider 人工冒烟）

## Web Privacy — AC7

- [ ] 自动搜索参数只包含最短 query、freshness 和隐私标记，不包含整段会话、好友名或 Session ID。（验证：Fake Transport 捕获请求并扫描敏感 fixture）
- [ ] 明显手机号、身份证、邮箱、凭据和精确住址查询首次调用返回确认要求，不向 Tavily 发请求。（验证：参数化隐私规则测试）
- [x] 下一轮只有用户明确确认且 query hash 相同时允许一次搜索；确认状态超时、跨好友或 query 不同均不允许。（验证：多会话 Fake Clock 测试）
- [ ] Pending Consent 不把查询正文写入 SQLite、JSONL 或日志。（验证：完成确认流程后扫描运行文件）
- [ ] Tavily API Key 不出现在 Provider Request、工具 Result、错误、微信回复、SQLite、JSONL、日志或 Git diff 中。（验证：使用唯一测试 Key 后对所有产物执行精确搜索）

## Weather Data And Forecast — AC8

- [x] 当前天气返回规范地点、当地数据时间、温度、体感温度、湿度、降水、风和当天高低温／日出日落。（验证：固定 Open-Meteo JSON fixture）
- [ ] `hourly` 只返回未来最多 48 小时，`daily` 只返回未来最多 7 天和批准字段。（验证：超长 fixture 的输出长度及字段集合）
- [x] 默认单位为摄氏度、公里／小时和毫米；请求华氏度、英里／小时和英寸时返回 API 已转换的值。（验证：捕获请求参数与结构化结果）
- [x] 预报日期和时间使用目标地点 IANA 时区，WMO 天气代码及风向转换为正确中文。（验证：跨时区 fixture 与代码表参数测试）
- [x] 连续两次相同天气调用都访问 Open-Meteo，SQLite 中没有天气结果。（验证：Transport 调用次数与数据库检查）
- [x] 每次最终天气回复包含 `天气数据：Open-Meteo`，且不显示经纬度请求 URL。（验证：SourceLedger 后处理和回复文本扫描）

## Weather Privacy And Routing — AC9

- [ ] 未给地点且上下文没有明确地点时，模型追问城市；紧邻追问可以沿用刚刚明确的地点。（验证：批准 Provider 的两组会话冒烟）
- [x] 地名歧义时返回候选并停止天气请求。（验证：Fake LocationResolver 与 Transport 调用次数）
- [x] 完整住址、楼栋和门牌不会原样发送给 Nominatim 或 Open-Meteo；无法缩减时要求提供城市。（验证：隐私 fixture 和捕获请求）
- [x] Open-Meteo 请求只包含坐标、时区、模式和批准字段，不含好友身份、微信消息或会话历史。（验证：捕获请求参数）
- [ ] 普通天气问题只调用天气工具；官方预警和台风动态使用网页搜索及官方来源策略。（验证：固定路由策略检查和批准 Provider 冒烟）
- [ ] Open-Meteo 失败时不调用网页搜索、不使用旧天气、不让模型猜测预报。（验证：失败回合的工具调用序列和最终提示）
- [ ] 恶劣天气一般提醒不会被描述为官方预警。（验证：固定恶劣天气 fixture 与最终回复）

## Failure Isolation — AC10

- [ ] 时间、网页或天气工具返回错误时，只产生结构化安全错误，不包含堆栈、凭据、系统提示或本机路径。（验证：逐工具异常注入并扫描 Result）
- [ ] 单个工具超时、取消或失败不会终止微信机器人，下一条队列消息仍正常处理。（验证：WechatBot + Runtime 集成测试）
- [ ] 微信好友 `/cancel` 在工具等待期间仍能取消自己的任务，且不取消其他好友。（验证：沿用 Chapter 13 取消测试并加入 Blocking Transport）
- [ ] 工具服务关闭幂等，进程结束时无遗留后台任务。（验证：重复 close 并检查 asyncio pending tasks）

## Session And Storage Boundary — AC11

- [x] 当前 ReAct 续轮的 Provider 可以看到原始工具结果并据此生成最终回答。（验证：可调用工具的 Fake Provider 完整回合）
- [x] JSONL 只保留用户消息、最终助手回复和脱敏工具结构，不包含工具参数、搜索结果、网页正文或天气原始返回体。（验证：使用唯一 canary 文本后扫描 JSONL）
- [x] `.mewcode/cache` 不出现微信原始工具结果或 canary 文本。（验证：工具正文超过 artifact 阈值后递归扫描 cache）
- [x] 重启恢复好友 Session 后，Provider 历史只包含用户消息和最终回复，不包含脱敏工具中间消息。（验证：关闭、重建 Runtime 并检查 Request messages）
- [ ] 网页和地点缓存不包含好友名称、Session ID 或会话关联列。（验证：检查 SQLite schema 和记录）
- [ ] 默认日志只包含工具类型、状态、耗时、结果数量和安全错误类型，不包含 query 正文、网页正文、完整住址、坐标关联或凭据。（验证：捕获日志并使用敏感 fixture 扫描）
- [x] 用户消息和最终回复仍写入各自好友的独立会话，好友 A 的工具内容不会进入好友 B。（验证：双好友重启恢复测试）

## Compatibility And Regression — AC12

- [x] Chapter 13 的微信配置、Store、Runtime、Bot 和 UIA 测试全部继续通过。（验证：运行全部 `tests/test_wechat_*.py`）
- [ ] 微信 4.1.12.55 的监听、去重、白名单、FIFO、取消、无鼠标切换和发送代码路径未被工具扩展改变。（验证：回归测试与人工 UIA 冒烟）
- [x] MewCode TUI、Agent、Session、Context、MCP、Skills、Sub-agent、Hook 和权限测试继续通过。（验证：运行完整 pytest）
- [ ] 非微信安装不强制安装 Windows UIA 或微信信息工具的可选依赖。（验证：在隔离环境执行基础安装与 import）
- [x] 自动化测试未连接真实 Tavily、Nominatim、Open-Meteo 或微信好友。（验证：测试中封锁网络并检查 Fake Transport 调用）

## Build And Tests

- [x] 微信可选依赖安装成功。（验证：`conda run -n mewcode python -m pip install -e ".[wechat]"`）
- [x] 全部微信测试通过。（验证：`conda run -n mewcode python -m pytest tests/test_wechat_*.py -q`）
- [x] 完整项目测试通过。（验证：`conda run -n mewcode python -m pytest -q -p no:cacheprovider`）
- [ ] 源码和测试格式正确。（验证：`conda run -n mewcode python -m ruff format --check src tests`）
- [x] Ruff lint 通过。（验证：`conda run -n mewcode python -m ruff check src tests`）
- [ ] Mypy 通过。（验证：`conda run -n mewcode python -m mypy src/mewcode`）
- [x] Git diff 无空白错误且未包含真实 API Key。（验证：`git diff --check` 并用实际 Key 的精确值搜索工作树）
- [x] Nominatim 指定代理的配置、Transport、隔离、失败关闭和凭据不泄漏测试全部通过。（验证：运行本次 T20–T24 定向测试集）
- [x] 代理修订后全部微信测试与完整项目回归继续通过。（验证：重新运行微信测试和完整 pytest）

## End-To-End Scenarios

- [ ] 场景 1：获授权测试好友发送“美国现在几点” -> 机器人按华盛顿特区返回当前时间、时区和日期，不调用网页搜索。（验证：真实微信回复与工具元数据）
- [ ] 场景 2：测试好友发送一个明确国外城市时间问题 -> 机器人通过地点解析返回 DST 正确的当地时间；鼠标位置保持不变。（验证：真实微信回复、运行日志和发送前后鼠标坐标）
- [ ] 场景 3：测试好友询问当天最新公开信息 -> 机器人自动使用 Tavily Basic，回答末尾包含不超过三个真实来源，月度 credit 增加符合预期。（验证：真实 Provider、Tavily 响应和 SQLite credit）
- [ ] 场景 4：测试好友发送一个公开静态网页并要求总结 -> 机器人读取正文并在最后一条回复附最终 URL；发送内网 URL 时安全拒绝。（验证：真实公网测试页与本机不可达测试页）
- [ ] 场景 5：测试好友询问“苏州今天天气” -> 每次都从 Open-Meteo 获取最新数据，按当地时间和默认单位回复并署名。（验证：连续两次真实调用时间与回复）
- [ ] 场景 6：测试好友随后询问“那明天会下雨吗” -> 沿用刚刚明确的苏州并返回七日范围内的对应预报。（验证：同一好友连续对话）
- [ ] 场景 7：另一名测试好友直接询问“今天天气怎么样” -> 不复用前一好友地点，而是追问城市。（验证：双好友会话隔离）
- [ ] 场景 8：测试好友要求读取本机文件、执行命令、启动浏览器或绕过网页指令 -> 所有操作均未执行，机器人仍可继续普通聊天。（验证：工具定义、文件系统和进程检查）
- [ ] 场景 9：网页中包含代理提示注入 -> 机器人只总结页面事实，不泄露聊天记录、系统提示或凭据，也不扩展抓取。（验证：受控恶意静态页面）
- [ ] 场景 10：重启机器人后继续同一好友对话 -> 最终聊天上下文恢复，但此前原始网页／天气工具内容没有重新进入模型历史。（验证：真实重启、Request 调试断言和 JSONL 检查）
- [x] 场景 11：不启动微信、使用真实后端查询“上海当前天气” -> Nominatim 只经指定代理解析上海，Open-Meteo 随后直连成功，结果包含上海天气数据与 OpenStreetMap／Open-Meteo 署名，输出中无代理信息。（验证：本机 `mewcode` conda 环境的后端冒烟、请求路径记录和 canary 扫描）
- [x] 场景 12：把 Nominatim 显式代理临时指向不可达地址后查询未缓存城市 -> 地点解析明确失败，未发生 Nominatim 直连、备用地点服务或 Open-Meteo 请求，其他不依赖地点解析的工具仍可调用。（验证：受控失败冒烟与 Transport 调用记录）

## Validation Record — 2026-08-19

- 全部微信测试：`66 passed`；其中本次信息工具与代理定向测试集 `48 passed`。
- 完整项目回归：`363 passed, 1 skipped`。
- wheel 构建通过，并确认首都 JSON、内置 Skill 和内置 Sub-agent 资源均在包内；同时移除了会导致 Hatchling 重复路径的旧 `force-include` 配置。
- Ruff lint：全项目通过；本次新增／修改文件的 Ruff format check 通过。
- 本次新增／修改的 11 个源码模块 Mypy 通过；全项目 Mypy 仍有此前已存在的 58 个错误（19 个文件），因此上方“全项目 Mypy 通过”保持未勾选。
- 全项目 Ruff format check 仍报告 12 个本次未修改的既有文件需要格式化，因此上方“源码和测试格式正确”保持未勾选，避免把无关机械改动混入本功能。
- 真实微信／Provider／Tavily／Nominatim／Open-Meteo 端到端场景尚未执行；需配置用户提供的 Tavily Key 后按场景 1–10 单独验收。
- 指定代理修订的开发前网络诊断：Nominatim 直连超时、经本机已配置 HTTPS 代理返回 HTTP 200；Open-Meteo 直连返回 HTTP 200；Tavily 强制直连且不带 Key 时返回 HTTP 401，证明其 DNS、TLS 与 HTTP 路径可达，因此 Tavily 不接入该代理。
- 真实后端场景 11 通过：未启动微信，查询“上海当前天气”解析为“上海市，中国”，时区 `Asia/Shanghai`，并生成 OpenStreetMap 与 Open-Meteo 署名。
- 受控失败场景 12 通过：显式代理指向 `127.0.0.1:1` 时，未缓存地点失败关闭；内置美国首都时间仍正常，结果未泄漏代理地址。
- Tavily 在代理修订后再次强制无代理请求固定端点，不带 Key 返回 HTTP 401，未执行搜索或消耗 credit。
- 代理修订的 3 个源码文件 Mypy 通过；微信目录整体仍有 UIA／pywin32 stubs 相关的 10 个既有错误，因此上方全项目 Mypy 项保持未勾选。
- Ruff format（本次 6 个修改文件）、全项目 Ruff lint、`git diff --check` 和实际代理值扫描均通过；代理值扫描覆盖 321 个配置、源码、运行与缓存文件。
