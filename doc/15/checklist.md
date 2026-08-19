# MewCode 微信天气改用网页搜索 Checklist

状态：开发完成（自动化与真实后端验收通过；未执行项见记录）

> 每一项必须通过自动化测试、静态扫描、构建产物检查或经批准的真实后端冒烟验证。自动化测试使用 Fake Provider / Fake Transport，不连接微信或外部服务。

## Implementation Completeness

- [x] `src/mewcode/wechat/info/weather.py` 已删除，Registry 不再导入、构造或注册专用天气实现。（验证：文件检查、导入检查与源码残留扫描）
- [x] 天气地点跟随正则、好友地点字典、回调和 Open-Meteo 来源标记已删除，不新增替代天气状态。（验证：源码扫描与 `WechatInfoServices` 状态检查）
- [x] `runtime.py`、Registry 稳定策略和动态环境统一描述三个只读公共信息工具。（验证：源码检查与 Fake Provider Request）
- [x] README 已删除专用天气接口说明，并明确天气自动复用 Tavily Basic 和安全网页读取。（验证：文档扫描）
- [x] Nominatim 指定代理、地点缓存和首都数据仅保留给地点时间，不因本次删除改变配置或 Store schema。（验证：配置、schema 与地点时间回归测试）

## Three-Tool Permission Boundary — AC1

- [x] 启用微信公共信息能力后，Provider Request 精确只暴露 `get_current_time`、`web_search`、`web_fetch`。（验证：Fake Provider 捕获并精确比较工具名集合）
- [x] 三个工具全部标记为只读，参数中不存在命令、文件、本机网络或任意 HTTP 方法入口。（验证：检查 `read_only_definitions` 与 JSON Schema）
- [x] 调用 `get_weather` 返回未知工具或无法获取，好友消息和系统提示均不能重新注册该工具。（验证：Registry 负向测试与提示注入测试）
- [x] Bash、文件、代码编辑、浏览器、MCP、Skill、Sub-agent 等权限仍未向微信模型开放。（验证：既有权限隔离回归测试）
- [x] 普通 MewCode TUI 的工具 Registry 不受微信三工具白名单影响。（验证：普通 Agent／Tool 测试）

## Automatic Weather Web Search — AC2

- [x] 明确城市的当前天气、明天预报、降雨、温度、风力、穿衣和出行天气问题允许模型自动调用 `web_search`，无需普通联网确认。（验证：稳定策略检查及 Fake Provider 工具循环）
- [x] 天气 query 只含必要地点、日期范围和天气关键词，不含好友名、Session ID 或完整对话。（验证：Fake Tavily 捕获请求并扫描 canary）
- [x] 搜索摘要不足时可以在既有页面预算内调用 `web_fetch`，且不会启动动态浏览器。（验证：Fake Provider 两工具循环与进程检查）
- [ ] 未给地点且当前好友上下文没有唯一地点时先追问，不调用网页工具。（验证：无地点会话测试）
- [x] 同一好友的紧邻追问可从 Session 历史沿用明确地点，另一好友不能继承该地点。（验证：双好友 Fake Provider 会话测试）
- [x] 天气搜索计入每轮最多两次搜索、每轮最多五页读取、累计等待上限和每月 1,000 credits。（验证：既有 TurnBudget、credit 与缓存测试）
- [x] 天气搜索继续遵守敏感 query 确认规则；自动搜索不等于允许上传完整地址或个人信息。（验证：隐私参数化测试）

## Sources And Failure Handling — AC3

- [x] 天气最终回复标明地点和日期，并只追加当前回合实际使用的网页来源，最多三个。（验证：SourceLedger 完整工具循环）
- [x] 稳定策略要求优先气象部门、政府和可识别天气服务；官方预警、台风和灾害信息优先官方来源。（验证：策略检查与批准 Provider 冒烟）
- [ ] 来源明显冲突时说明差异，不把普通天气网页描述成官方预警。（验证：冲突 fixture 与 Fake Provider 回合）
- [x] 缺 Tavily Key、额度耗尽、鉴权失败、网络失败或来源不足时明确说明无法查询，不编造结果。（验证：逐类 Fake 错误测试）
- [x] 失败路径不调用 Open-Meteo、其他搜索服务或浏览器，也不产生固定天气署名。（验证：调用序列、进程与回复扫描）
- [x] 网页 SSRF、重定向、内容类型、大小、敏感参数和不可信页面指令防护继续生效。（验证：既有网页安全测试）

## Dedicated Weather Removal — AC4

- [x] `src` 和 README 中不存在 `get_weather`、`WeatherTool`、`OpenMeteo`、`Open-Meteo`、天气专用状态或署名。（验证：`rg` 零命中；历史 `doc/14` 不参与）
- [x] 测试中除 `get_weather` 的旧工具负向断言外，不存在专用天气实现标识或 fixture。（验证：测试目录残留扫描）
- [x] `tests/test_wechat_info_weather.py` 已删除，天气网页行为由 Registry／Runtime 集成测试覆盖。（验证：文件检查和测试收集结果）
- [x] 构建出的 wheel 不包含 `mewcode/wechat/info/weather.py` 或等价专用天气实现。（验证：列出 wheel 内容）
- [x] 运行时没有可到达的 Open-Meteo URL、客户端或请求路径。（验证：源码、字节码／包内容扫描及测试网络拦截）
- [x] 已脱敏的旧天气工具中间记录仍可恢复并从长期 Provider 历史过滤，旧最终聊天内容仍可读。（验证：旧会话 fixture 的关闭、重启与恢复测试）

## Compatibility And Regression — AC5

- [x] 当前时间、本机时间、国家首都时间、具体城市时间、IANA 时区和 DST 测试继续通过。（验证：地点时间测试集）
- [x] Nominatim 仍只使用指定代理，网页搜索和网页读取不继承该代理。（验证：代理 canary 与 Transport 路径测试）
- [x] Tavily 仍固定 Basic、最多五条结果、每月免费上限，不启用 Advanced、超额付费或第二搜索源。（验证：捕获请求 JSON 与 credit 边界测试）
- [x] 微信监听、好友隔离、FIFO、取消、回复分段、无鼠标 UIA 路径和机器人错误隔离未回退。（验证：全部微信自动化测试；真实 UIA 仅在另行批准后冒烟）
- [x] 微信 SQLite 与 JSONL 不新增天气缓存、地点跟随或原始网页正文；现有好友会话仍隔离。（验证：schema、持久化产物和双好友恢复测试）
- [x] 普通 MewCode Agent、Session、Context、MCP、Skills、Sub-agent、Hook 和权限测试继续通过。（验证：完整 pytest）

## Build And Quality

- [x] 定向三工具、网页和 Runtime 测试通过。（验证：执行 T3 指定 pytest 命令）
- [x] 全部微信测试通过，且测试期间未连接真实微信或公网服务。（验证：PowerShell 收集 `test_wechat_*.py` 后运行 pytest，并检查 Fake Transport）
- [x] 完整项目测试通过。（验证：`conda run -n mewcode python -m pytest -q -p no:cacheprovider`）
- [x] wheel 构建成功且包内容检查通过。（验证：`python -m build --wheel` 与归档列表）
- [x] 改动文件 Ruff format、Ruff lint、目标 Mypy 和 `git diff --check` 通过；既有全项目问题单独记录。（验证：T5 质量命令）
- [ ] 工作树和运行产物不包含真实 Tavily Key、代理凭据或测试 canary。（验证：按实际秘密精确扫描，不打印秘密值）

## End-To-End Scenarios

- [x] 场景 1：不启动微信，使用批准 Provider 和有效 Tavily Key 询问“南昌明天天气” -> 模型只调用网页工具，返回地点、日期和实际来源。（验证：真实后端工具轨迹；Key 不可用则记录待验收）
- [ ] 场景 2：同一会话接着问“那后天呢” -> 使用 Session 中的南昌；新好友直接问同一句 -> 先追问地点。（验证：双 Session 后端冒烟）
- [ ] 场景 3：搜索服务不可用 -> 回复明确失败，进程无 Open-Meteo、浏览器或其他搜索请求，下一条消息仍可处理。（验证：受控失败冒烟）
- [ ] 场景 4：询问“美国现在几点” -> 仍按华盛顿特区时区回答，不使用网页搜索。（验证：地点时间后端冒烟）
- [ ] 场景 5：真实微信好友询问天气 -> 自动网页搜索并正常发送；该场景不属于自动开发动作，只有获得单独测试授权后执行。（验证：微信界面、控制台工具轨迹和鼠标位置）

## Validation Record

- 2026-08-19 定向三工具、网页和 Runtime 测试：`18 passed`。
- 删除专用天气测试并增加旧会话兼容测试后，全部微信测试：`64 passed`；完整项目回归：`361 passed, 1 skipped`。
- `src` 与 README 的专用天气标识扫描零命中；测试中只保留 `get_weather` 的旧工具不可用和旧会话恢复负向 fixture。
- 改动文件 Ruff format、Ruff lint、目标源码 Mypy 和 `git diff --check` 通过。
- 使用 Hatchling 成功构建 `dist/mewcode-0.1.0-py3-none-any.whl`，归档内不存在天气模块，只保留 `http.py`、`location.py`、`registry.py` 和 `web.py` 等三工具依赖。
- 使用当前批准 Provider 与 Tavily Key、在独立临时 Session 中执行“南昌明天天气怎么样”：未启动微信，回复包含南昌、2026-08-20 和三个实际网页来源。
- 首次完整回归曾因 pytest 临时目录放在另一个 Git 仓库下导致环境测试误判；改用非 Git 临时目录后完整通过，该次环境性失败不计为产品失败。
- 本机 `mewcode` Conda 环境原先缺少构建工具；验收期间安装了 `build 1.5.0` 与 `hatchling 1.32.0` 后使用 `--no-isolation` 构建。
- 敏感值扫描确认本次 diff 未新增真实 Tavily Key 或代理值。项目内被 Git 忽略的 `.mewcode/config.yaml` 按现有配置方式保存 Provider Key，旧 Session 与示例中的非活动占位值保持原状，因此“整个工作树零敏感值”项未勾选。
- 未执行：真实后端无地点／跨好友追问、受控搜索失败后的下一消息、美国时间真实后端冒烟，以及真实微信 UIA 收发；对应场景保持未勾选。
