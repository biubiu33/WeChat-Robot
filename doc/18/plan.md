# 微信 4.1.9.30 UIA 兼容 Plan

状态：已批准

## Architecture Overview

本次继续使用现有 `WechatUiaClient` 和 `mmui::*` 控件选择器，不新增版本适配层。启动或 `--probe` 时先读取桌面根节点：若存在唯一 `mmui::MainWindow`，读取进程版本并按双版本白名单校验；若不存在可用主窗口但发现属于 `Weixin.exe` 的 Qt 窗口外壳，则立即返回讲述人激活提示；否则保留现有主窗口数量错误。

```text
UIA desktop root
  -> one mmui::MainWindow
       -> read Weixin.exe version
       -> accept 4.0.5.15 or 4.1.9.30
       -> validate required controls
  -> no mmui::MainWindow + Weixin Qt shell
       -> fail with Narrator/restart guidance
  -> zero or multiple usable main windows
       -> fail with existing cardinality guidance
```

消息发现、搜索切换、输入框写入、目标复核和发送流程不变。

## Core Data Structures

### Supported version tuple

```python
SUPPORTED_WECHAT_VERSIONS: tuple[str, ...] = (
    "4.0.5.15",
    "4.1.9.30",
)
```

使用有序元组保持 CLI 和错误消息顺序稳定，不增加配置字段或版本对象。

### `WechatUiaClient`

```python
class WechatUiaClient:
    def __init__(
        self,
        *,
        expected_versions: tuple[str, ...] = SUPPORTED_WECHAT_VERSIONS,
    ) -> None: ...

    def _main_window(self) -> Any: ...
    def _wechat_process_path(self, window: Any) -> str: ...
    def _wechat_version(self, window: Any) -> str: ...
    def _is_weixin_shell(self, control: Any) -> bool: ...
```

- `expected_versions` 只用于版本门禁和测试注入。
- `_wechat_process_path` 复用现有进程查询逻辑，避免版本读取和外壳识别各自打开进程。
- `_is_weixin_shell` 同时检查 Qt 顶层窗口类形态和进程文件名，避免把其他 Qt 应用误报成微信。
- `_main_window` 只负责选择唯一主窗口、区分未激活外壳并校验版本；必要控件仍由现有 `probe()` 和业务调用唯一性检查完成。

## Module Design

### `mewcode.wechat.uia_client`

**Responsibility:** 扩展受支持版本集合，并区分“微信未提供 UIA 树”和“没有唯一微信主窗口”。

**Changes:**

- 将单一版本常量替换为双版本有序元组。
- 唯一 `mmui::MainWindow` 的实际版本属于元组时通过，否则错误列出全部支持版本。
- 当桌面根节点包含属于 `Weixin.exe` 的 `Qt*QWindowIcon`，但没有 `mmui::MainWindow` 时，抛出包含“请先启动 Windows 讲述人并重启微信”的 `WechatUiaError`。
- 不调用讲述人、系统设置、微信重启或进程写入 API。

### `mewcode.wechat.cli`

**Responsibility:** 在 `--probe` 帮助文本中展示两个支持版本。

**Changes:** 使用统一格式化后的版本列表，不保留单版本说明。

### `tests.test_wechat_uia_driver`

**Responsibility:** 验证双版本门禁、外壳诊断和原有缓存行为。

**Changes:**

- 参数化验证 `4.0.5.15` 与 `4.1.9.30` 均通过。
- 验证同一 HWND 仍只读取一次版本。
- 验证其他版本被拒绝且错误列出两个支持版本。
- 验证只有 Weixin Qt 外壳时给出讲述人提示。
- 验证其他 Qt 窗口不会被误判为微信外壳。

### `README.md`

**Responsibility:** 说明双版本支持和 `4.1.9.30` 的讲述人启动前置条件。

**Changes:**

- 把单版本兼容说明改为双版本。
- 更新 `--probe` 成功条件。
- 加入手动启动讲述人、完全退出并重启微信的顺序。
- 明确程序不会自动操作讲述人或微信进程。

## Module Interactions

```text
CLI / Bot
  -> WechatUiaClient._main_window()
      -> UIA desktop children
      -> mmui main window? -> process path -> version whitelist
      -> Weixin Qt shell?  -> actionable Narrator error
  -> probe / existing driver operations
```

错误继续通过现有 CLI 顶层异常处理输出到标准错误并以状态码 1 退出。

## File Organization

```text
doc/18/spec.md                       - 已批准行为范围
doc/18/plan.md                       - 本技术设计
src/mewcode/wechat/uia_client.py     - 双版本门禁和 UIA 外壳诊断
src/mewcode/wechat/cli.py            - 双版本帮助文本
tests/test_wechat_uia_driver.py      - 版本和诊断回归测试
README.md                            - 安装与讲述人前置说明
```

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| 版本范围 | 精确支持两个版本 | 与真实验证一致，避免未经验证的宽泛 4.x 匹配 |
| 控件选择器 | 两个版本复用现有 `mmui::*` 选择器 | 真实 `4.1.9.30` 已验证三个必要节点唯一，无需分叉 |
| 无障碍激活 | 仅诊断并提示用户手动操作 | 满足安全边界，不改变系统或微信状态 |
| 外壳识别 | Qt 类形态加 `Weixin.exe` 进程路径 | 比仅检查通用 Qt 类名更准确 |
| 版本表示 | 一个有序元组 | 最小实现，可直接用于校验、帮助文本和错误消息 |
| 依赖 | 不新增 | 复用已安装的 `uiautomation`、`pywin32` 和标准库 |
