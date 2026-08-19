# MewCode 微信天气改用网页搜索 Tasks

状态：已批准

## File List

| Action | File | Responsibility |
|---|---|---|
| Modify | `src/mewcode/wechat/info/registry.py` | 移除天气服务、状态、署名和注册；更新三工具与网页天气策略 |
| Delete | `src/mewcode/wechat/info/weather.py` | 删除 Open-Meteo 与独立天气工具实现 |
| Modify | `src/mewcode/wechat/runtime.py` | 收缩 Agent 工具白名单和动态环境说明 |
| Modify | `tests/test_wechat_info_registry.py` | 三工具、旧工具不可用和天气网页工具循环测试 |
| Delete | `tests/test_wechat_info_weather.py` | 删除专用天气测试 |
| Modify if needed | `tests/test_wechat_runtime.py` | 更新三工具权限或稳定策略断言 |
| Modify | `README.md` | 说明天气自动网页搜索及费用、失败和来源边界 |
| Preserve | `.mewcode/config.yaml.example` | Nominatim 代理仍用于地点时间，无需修改 |
| Preserve | `src/mewcode/wechat/info/location.py` | 地点时间能力保持不变 |
| Preserve | `src/mewcode/wechat/info/web.py` | 天气复用现有网页搜索，不新增专用实现 |
| Preserve | `doc/14/` | 保留历史设计与验收记录 |
| Modify | `doc/15/spec.md` | 保留批准状态 |
| Modify | `doc/15/plan.md` | 保留批准状态 |
| Create | `doc/15/task.md` | 本任务拆分 |
| Create | `doc/15/checklist.md` | 后续验收设计 |

## T1：删除独立天气模块与服务状态

**Files:** `src/mewcode/wechat/info/registry.py`, `src/mewcode/wechat/info/weather.py`
**Dependencies:** None

**Steps:**

1. 删除天气模块文件，连同 Open-Meteo 请求、天气字段与单位转换、WMO 映射和临时控制台输出。
2. 从服务组装中移除天气导入、客户端构造和工具注册。
3. 删除天气地点跟随正则、好友地点字典及其读写回调。
4. 删除来源账本中的天气标记和 Open-Meteo 固定署名，只保留网页来源与 OpenStreetMap 地点时间署名。
5. 把稳定策略改为三个工具，并明确普通天气、预报和天气建议自动使用网页搜索；地点缺失时先追问，失败时不得猜测或声称国内城市不支持。

**Validation:**

```powershell
conda run -n mewcode python -m compileall -q src/mewcode/wechat/info
rg -n "WeatherTool|OpenMeteo|Open-Meteo|FOLLOW_UP_WEATHER|weather_used|_last_weather_location|get_weather" src/mewcode/wechat/info
```

期望：模块可编译；第二条无命中，不存在导入、类、状态、注册、端点或旧工具名。

## T2：收缩微信 Agent 权限为三工具

**Files:** `src/mewcode/wechat/runtime.py`
**Dependencies:** T1

**Steps:**

1. 从 Agent 工具策略白名单中删除旧天气工具名。
2. 把动态环境能力描述从四个工具改为三个工具。
3. 保持会话归档与恢复的通用工具脱敏逻辑不变，使旧脱敏天气工具记录仍能恢复并被长期历史过滤。
4. 不改变 Provider、Session、取消、超时和微信 UIA 路径。

**Validation:**

```powershell
conda run -n mewcode python -m compileall -q src/mewcode/wechat/runtime.py
rg -n "get_current_time|web_search|web_fetch|三个只读" src/mewcode/wechat/runtime.py
rg -n "get_weather|四个只读" src/mewcode/wechat/runtime.py
```

期望：运行时可编译并只声明三个工具；最后一条无命中。

## T3：更新三工具与天气网页集成测试

**Files:** `tests/test_wechat_info_registry.py`, `tests/test_wechat_runtime.py`, `tests/test_wechat_info_weather.py`
**Dependencies:** T1, T2

**Steps:**

1. 删除独立天气测试文件。
2. 把 Registry、Provider Request、只读定义和动态环境断言更新为精确三个工具。
3. 更新 SourceLedger 测试，确认只追加实际网页来源和需要的 OpenStreetMap 署名，不出现 Open-Meteo 固定署名。
4. 增加旧天气工具不可注册、不可获取或不可执行的断言。
5. 使用 Fake Provider 与 Fake Tavily Transport 完成“南昌明天天气 -> web_search -> 最终回复 -> 来源追加”的完整工具循环，断言最短 query 不含好友名或完整对话。
6. 覆盖无地点先追问、同好友紧邻追问使用会话上下文、不同好友不复用地点的 Provider 行为测试；不新增进程内天气状态。
7. 覆盖缺 Key、额度或搜索失败时只返回网页工具错误，不出现旧天气工具或专用天气署名。

**Validation:**

```powershell
conda run -n mewcode python -m pytest tests/test_wechat_info_registry.py tests/test_wechat_info_web.py tests/test_wechat_runtime.py -q -p no:cacheprovider
```

期望：三工具权限、天气网页循环、来源、失败和会话隔离测试全部通过，测试不访问真实外部服务或微信。

## T4：更新用户文档

**Files:** `README.md`
**Dependencies:** T1, T2

**Steps:**

1. 把微信公共信息能力从四工具改为三个工具。
2. 删除 Open-Meteo、天气专用查询范围、单位、无缓存和专用署名说明。
3. 说明当前天气、预报、降雨、穿衣和出行天气建议自动使用 Tavily Basic，必要时读取公开静态页面。
4. 说明天气查询消耗既有每轮搜索次数和每月免费 credit；缺 Key、额度或可靠来源时无法回答，不编造或回退其他服务。
5. 说明天气回答附实际网页来源，官方预警优先气象部门或政府来源。
6. 保留 Nominatim 指定代理说明，但明确其仅服务地点时间；不修改用户当前配置。

**Validation:**

```powershell
rg -n "三个只读|天气|Tavily|每轮最多|1,000|Nominatim|地点时间" README.md
rg -n "get_weather|OpenMeteo|Open-Meteo|天气数据：" README.md
```

期望：第一条定位到完整新说明；第二条无命中。

## T5：执行删除验收和完整回归

**Files:** All changed source, tests, docs, and build output
**Dependencies:** T3, T4

**Steps:**

1. 扫描运行源码和 README，确认没有旧天气工具、Open-Meteo、天气专用状态或署名残留；测试中只允许 `get_weather` 出现在“旧工具不可用”的负向断言，其他天气实现标识必须清零；历史 `doc/14` 和当前变更文档不参与源码残留判断。
2. 构建 wheel 并检查包内容不包含天气模块。
3. 运行全部微信测试和完整项目测试，确认地点时间、Nominatim 代理、网页安全、会话恢复和 UIA 无回退。
4. 对改动文件运行 Ruff format、Ruff lint、Mypy 和 `git diff --check`；记录既有全项目问题但不混入无关修复。
5. 若当前配置含有效 Tavily Key，使用批准 Provider 执行一次不发送微信消息的“南昌明天天气”真实后端冒烟，确认模型只调用网页工具并返回实际来源；若 Key 不可用，记录为真实验收待办而不伪造通过。
6. 不访问 Open-Meteo，不启动浏览器，不连接或操作微信客户端。

**Validation:**

```powershell
rg -n "get_weather|WeatherTool|OpenMeteo|Open-Meteo|weather_used|_last_weather_location|天气数据：Open-Meteo" src README.md
rg -n "WeatherTool|OpenMeteo|Open-Meteo|weather_used|_last_weather_location|天气数据：Open-Meteo" tests
conda run -n mewcode python -m build --wheel
$wechatTests = (Get-ChildItem -LiteralPath tests -Filter 'test_wechat_*.py' -File).FullName
conda run -n mewcode python -m pytest $wechatTests -q -p no:cacheprovider
conda run -n mewcode python -m pytest -q -p no:cacheprovider
conda run -n mewcode python -m ruff format --check src tests
conda run -n mewcode python -m ruff check src tests
conda run -n mewcode python -m mypy src/mewcode/wechat/info/registry.py src/mewcode/wechat/runtime.py
git diff --check
```

期望：残留扫描无命中；wheel 不含天气模块；新增／修改测试、微信测试和完整回归通过；改动文件质量检查通过。

## Execution Order

```text
T1 -> T2 -> T3 --+--> T5
           T4 --+
```

T3 与 T4 在 T1、T2 完成后可以并行；T5 必须最后执行。
