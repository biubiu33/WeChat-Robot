# 微信 4.0.5.15 单版本兼容 Plan

状态：已批准（第二次修订）

## Architecture Overview

保留现有微信 UIA 客户端、驱动和机器人结构，将唯一受支持版本切换到 4.0.5.15，并适配该版本已实测的会话项可访问名称及无联系人专属 ID 的搜索结果。运行时继续执行精确版本匹配；联系人切换继续要求精确显示名、唯一结果和切换后标题复核。观察循环输出受控 UIA 错误的具体原因。CLI 帮助文本从同一版本常量生成，文档同步更新。

## Core Data Structures

### `SUPPORTED_WECHAT_VERSION`

- 类型：`str`
- 值：`"4.0.5.15"`
- 用途：构造 UIA 客户端时的默认期望版本，也是 CLI 帮助文本的版本来源。

### `WechatUiaClient`

- `__init__(expected_version: str = SUPPORTED_WECHAT_VERSION)`：保留可注入期望版本的测试接口。
- `_main_window() -> Any`：保留唯一窗口检查、版本读取、精确匹配和句柄缓存行为。
- `probe() -> None`：保留主窗口及三个必要控件的只读验证。

## Module Design

### UIA 客户端

**Responsibility:** 将唯一兼容版本切换到 4.0.5.15；从该版本的组合会话文本中识别联系人名和“`N条未读`”计数；会话项和搜索结果均不依赖该版本不存在的联系人专属 ID。搜索结果按结果控件类型与精确显示名筛选，仍要求唯一，并在 Enter 后复核聊天标题。保留已实测兼容的输入框、焦点、草稿写入、目标复核、Enter 发送和发送后清空校验。

**Public Interface:** 现有接口不变。

**Dependencies:** `uiautomation`、`pywin32`。

### CLI

**Responsibility:** `--probe` 帮助文本使用 UIA 客户端公开的版本常量，避免代码内版本文字漂移。

**Public Interface:** `mewcode-wechat [--probe]` 不变。

### 机器人观察循环

**Responsibility:** 保持单次 UIA 异常隔离和有限重试，同时记录异常类型及受控错误原因，便于定位缺失控件、搜索失败和目标复核失败。

**Public Interface:** 不新增接口。

### 自动化测试

**Responsibility:** 用内存假窗口验证 4.0.5.15 被接受、其他版本被拒绝，并覆盖组合会话文本、未读计数、通用会话项 ID、无 ID 搜索结果、重名拒绝和具体错误日志；不接触真实微信。

### 用户文档

**Responsibility:** README 和示例配置只声明 4.0.5.15。历史设计章节保留原始记录，不回写。

## Module Interactions

```text
CLI / Bot
  -> WechatUiaClient(default 4.0.5.15)
     -> discover unique mmui main window
     -> read executable version
     -> exact version match
     -> parse "联系人 N条未读 预览 时间"
     -> find one result by exact class and display name
     -> switch and validate the resulting chat title
     -> probe or normal UIA operation

UIA observer
  -> isolate one scan failure
  -> log exception type and controlled reason
  -> bounded retry
```

## File Organization

```text
src/mewcode/wechat/uia_client.py    - 唯一兼容版本和运行时校验
src/mewcode/wechat/cli.py           - 复用版本常量的命令帮助
src/mewcode/wechat/bot.py           - 可诊断的 UIA 观察错误日志
tests/test_wechat_uia_driver.py     - 版本、会话与搜索回归测试
tests/test_wechat_bot.py            - 观察错误日志回归测试
README.md                           - 用户安装与探测说明
.mewcode/config.yaml.example        - 示例配置版本说明
doc/17/                             - 本次变更的规格、设计、任务和验收记录
```

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| 版本范围 | 仅精确支持 4.0.5.15 | 符合已批准规格，不对未验收版本作保证 |
| 版本表达 | 保留一个运行时常量 | 最小改动，并让 CLI 帮助复用真源 |
| 会话解析 | 识别 4.0.5.15 的“`联系人 N条未读 预览 时间`” | 本机已观察到联系人被组合文本包裹，旧解析会把整串误作名称并得到零未读 |
| 会话定位 | 删除 `session_item_<联系人>` 前置依赖，复用现有精确键盘搜索与切换后复核 | 该版本所有会话项只暴露通用 `session_item`，旧前置检查必然失败；后续安全校验已完整覆盖唯一目标 |
| 搜索结果定位 | 使用结果类型和精确显示名，要求唯一 | 该版本实测结果 ID 为空，但类型和名称稳定；拒绝零结果与多结果保持安全边界 |
| 发送控件 | 保留现有输入框 ID、控件类、ValuePattern 和 Enter 流程 | 真实客户端已完成不发送的聚焦、草稿写入、目标复核与清空测试，全部通过 |
| 观察错误日志 | 记录异常类型和受控错误文本 | 当前只记录类型，无法区分控件、搜索或复核失败 |
| 测试方式 | 内存假 UIA 窗口 | 自动化测试不操作真实微信 |
| 历史文档 | 不修改 `doc/13` | 保留当时已批准设计的历史准确性 |
