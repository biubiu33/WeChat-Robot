# MewCode 微信天气改用网页搜索 Plan

状态：已批准

## Architecture Overview

微信公共信息运行时由四工具收缩为三工具：

```text
WechatAgentRuntime
  -> WechatInfoServices
       |-- get_current_time -> LocationResolver -> 首都数据／地点缓存／Nominatim
       |-- web_search       -> TavilySearchClient -> 网页搜索缓存与 credit
       `-- web_fetch        -> SafePublicHttpClient -> 公网页面校验与正文提取
```

天气不再拥有客户端、工具、状态或署名路径。普通天气和预报由稳定系统策略路由到现有 `web_search`，搜索摘要不足时由模型在既有页面预算内调用 `web_fetch`。不增加关键词路由器、天气适配层或备用服务。

## Core Data Structures

### WechatInfoServices

保留以下长期服务：

```python
class WechatInfoServices:
    _resolver: LocationResolver
    _tavily: TavilySearchClient
    _public_http: SafePublicHttpClient
    _pending_consents: dict[str, PendingSearchConsent]
```

删除 Open-Meteo 客户端和好友天气地点跟随状态。`LocationResolver` 继续存在，但只由当前时间工具调用。

### SourceLedger

```python
@dataclass
class SourceLedger:
    sources: list[SourceRef]
    osm_used: bool = False
```

删除天气来源标记和 Open-Meteo 固定署名。天气回答和普通网页回答一样，只能引用当前回合搜索或读取实际登记的网页来源。地点时间使用 Nominatim 时仍追加 OpenStreetMap 署名。

### Registry And Tool Policy

每轮 Registry 和 Agent 工具策略的名称集合精确为：

```python
{"get_current_time", "web_search", "web_fetch"}
```

不保留隐藏或未注册的天气工具。旧名称 `get_weather` 作为未知工具处理。

## Module Design

### `mewcode.wechat.info.registry`

**Responsibility:** 组装三工具 Registry、稳定路由策略、来源账本和网页隐私确认。

**Changes:**

- 移除天气模块导入、Open-Meteo 客户端构造和天气工具注册。
- 移除天气地点正则、跨回合地点字典、读取／写入地点回调。
- 移除 SourceLedger 的天气字段和 Open-Meteo 署名分支。
- 把稳定策略从“四个工具”改为“三个工具”。
- 明确当前天气、预报、降雨、穿衣和出行天气建议自动调用 `web_search`；地点不明确时先追问。
- 明确天气搜索只发送地点、日期范围和天气关键词；摘要不足时可调用 `web_fetch`。
- 明确优先气象部门、政府和可识别天气来源；失败时不得猜测或声称国内城市不受支持。

### `mewcode.wechat.runtime`

**Responsibility:** 向 Agent 提供微信三工具权限和动态环境。

**Changes:**

- 工具策略白名单删除 `get_weather`。
- 动态环境描述由“四个只读公共信息工具”改为“三个”。
- 会话归档和恢复逻辑保持通用；旧脱敏工具对仍按角色和工具调用结构过滤，无需迁移。

### `mewcode.wechat.info.weather`

**Responsibility:** 无。

**Changes:** 删除整个模块，包括 Open-Meteo 请求、字段筛选、单位转换、天气代码转换和临时控制台调试输出。

### `mewcode.wechat.info.location`

**Responsibility:** 国家首都、Nominatim 地点解析和当前时间。

**Changes:** 不改接口和行为。天气删除后，生产调用方只剩当前时间工具；指定代理、缓存、限速、歧义和时区逻辑保持不变。

### `mewcode.wechat.info.web`

**Responsibility:** Tavily Basic 搜索、缓存、隐私确认、额度和公网页面读取。

**Changes:** 不新增天气专用参数或客户端。天气查询复用现有最短 query、每轮两次、每月 1,000 credits、失败分类、缓存和来源登记逻辑。

### `mewcode.wechat.config` 与 Store

**Changes:** 不增加配置或数据库迁移。Tavily Key 继续决定网页天气是否可用；Nominatim 代理继续决定具体地点时间是否可用。现有地点、网页和 credit 表保留。

### README And Example Config

**Changes:**

- 把微信能力说明由四工具改为三工具。
- 删除 Open-Meteo、天气专用字段、无天气缓存和专用署名说明。
- 说明天气自动使用 Tavily 网页搜索，计入现有限次和免费 credit；Key 或额度不可用时无法查询。
- 说明 Nominatim 及其代理只用于地点时间；配置示例中的代理字段继续保留。
- `doc/14` 作为已完成历史设计保留不改，`doc/15` 成为本次变更记录。

## Module Interactions

### 明确地点的天气问题

```text
好友：“南昌明天天气怎么样”
  -> WechatAgentRuntime 注入三工具和天气网页路由策略
  -> 模型调用 web_search("南昌 明天 天气")
  -> TurnBudget 预留本轮搜索次数
  -> 缓存命中，或 Tavily credit 原子预留后调用 Basic 搜索
  -> SourceLedger 登记实际结果 URL
  -> 摘要足够：模型回答
  -> 摘要不足：可调用 web_fetch 读取公开静态页面
  -> 回复后处理移除未知 URL，并追加实际来源
```

### 地点缺失与紧邻追问

```text
好友：“明天天气怎么样”且上下文无地点
  -> 模型先追问地点，不调用网页工具

同一好友：“南昌今天有雨吗” -> “那明天呢”
  -> 模型从当前好友会话历史取得“南昌”
  -> web_search("南昌 明天 天气")

另一好友：“那明天呢”
  -> 独立 Session 中无地点，先追问
```

不再用进程内天气地点字典；会话隔离由既有独立 Session 保证。

### 失败路径

```text
缺 Key／额度耗尽／网络失败／无可靠来源
  -> web_search 返回结构化错误
  -> 模型明确说明暂时无法查询
  -> 不调用 get_weather、Open-Meteo、其他搜索源或浏览器
  -> 微信机器人继续处理下一条消息
```

### 地点时间

```text
get_current_time(location)
  -> 国家首都／地点缓存／Nominatim 指定代理
  -> timezonefinder / zoneinfo
  -> 时间结果；需要时追加 OpenStreetMap 署名
```

该链路不受天气删除影响。

## File Organization

```text
src/mewcode/wechat/info/
  registry.py                 # 修改：三工具、天气网页策略、无天气状态
  weather.py                  # 删除：整个专用天气实现
src/mewcode/wechat/
  runtime.py                  # 修改：三工具 Agent 白名单和环境说明
tests/
  test_wechat_info_registry.py # 修改：三工具、旧工具不可用、网页天气集成
  test_wechat_info_weather.py  # 删除：专用天气测试
  test_wechat_runtime.py       # 修改：三工具权限与稳定策略断言（如有引用）
README.md                      # 修改：天气改用网页搜索的用户说明
doc/15/
  spec.md                      # 已批准需求
  plan.md                      # 本技术设计
  task.md                      # 后续任务拆分
  checklist.md                 # 后续验收设计
```

`.mewcode/config.yaml.example`、当前用户配置、Store schema、地点时间模块和网页模块不需要修改。

## Testing Strategy

- Registry 单元测试精确断言三工具集合，且 `get_weather` 不存在。
- Runtime 集成测试精确断言 Provider Request 只暴露三工具，动态环境和稳定策略均描述三工具。
- 使用 Fake Provider 和 Fake Tavily Transport 完成一次天气问题的 `web_search -> 最终回答 -> 来源追加` 工具循环，不访问公网。
- 断言天气搜索仍计入回合搜索次数和月度 credit，并沿用网页缓存、隐私与来源规则。
- 断言搜索失败后不会出现旧天气工具调用或 Open-Meteo 署名。
- 断言旧会话中已经脱敏的工具消息仍可恢复，当前时间与 Nominatim 代理测试继续通过。
- 删除专用天气测试后运行全部微信测试和完整项目回归。
- 对运行源码、测试、README 和构建产物搜索 `get_weather`、`OpenMeteo`、`Open-Meteo`，期望无可执行或用户文档残留；历史 `doc/14` 不参与该断言。

## Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| 删除范围 | 删除工具、客户端、状态、署名、模块和专用测试 | 用户选择彻底删除，避免隐藏死代码 |
| 天气路由 | 复用稳定系统策略驱动现有网页工具 | 与现有自动搜索机制一致，避免新增意图分类器 |
| 搜索与读取 | Tavily Basic + 必要时安全网页读取 | 复用已批准的限额、缓存、SSRF 和来源能力 |
| 地点跟随 | 使用好友独立 Session 上下文 | 删除专用状态，仍保持好友隔离 |
| 天气来源 | 网页实际来源，不固定天气署名 | 移除 Open-Meteo 后不能再追加专用署名 |
| 地点时间 | 完整保留 Nominatim 与代理链路 | 该能力仍是当前时间工具的必要依赖 |
| 历史文档 | 保留 `doc/14`，新增 `doc/15` | 历史验收记录不可伪装成从未存在，当前设计由新章节覆盖 |
| 依赖和 schema | 不变 | 专用天气实现使用标准库且无天气表，无迁移必要 |
