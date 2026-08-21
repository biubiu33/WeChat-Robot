# 微信 4.1.9.30 UIA 兼容 Checklist

状态：已完成

> 每一项都必须通过运行代码、检查实际输出或观察真实微信行为验证。

## Implementation Completeness

- [x] 支持版本集合精确包含 `4.0.5.15` 和 `4.1.9.30`，顺序稳定且不接受其他版本。（verification：版本门禁参数化测试通过）
- [x] 两个支持版本使用同一套现有 UI Automation 主窗口和必要控件选择器。（verification：代码检查无版本选择器分支，双版本窗口测试通过）
- [x] 相同微信 HWND 被重复读取时只执行一次版本查询。（verification：句柄缓存单元测试通过）
- [x] 不支持版本错误同时列出 `4.0.5.15`、`4.1.9.30` 和实际版本。（verification：错误消息单元测试通过）
- [x] 微信只暴露 `Qt*QWindowIcon` 外壳且进程为 `Weixin.exe` 时，错误包含“请先启动 Windows 讲述人并重启微信”。（verification：外壳诊断单元测试通过）
- [x] 其他 Qt 应用窗口不会被误判为未激活的微信窗口。（verification：非微信 Qt 外壳单元测试仍得到主窗口数量错误）
- [x] `--probe --help` 同时展示两个支持版本。（verification：执行 CLI 帮助命令并检查输出）
- [x] README 说明双版本、`4.1.9.30` 的讲述人启动顺序和程序不自动操作的边界。（verification：检查对应使用说明）

## Integration

- [x] `--probe` 和机器人启动共用同一版本门禁与 UIA 外壳诊断。（verification：检查两个入口都构造默认 `WechatUiaClient`，无重复门禁）
- [x] 唯一 `mmui::MainWindow` 通过版本门禁后，现有会话列表、消息列表和输入区域唯一性检查继续执行。（verification：UIA 客户端测试和真实 probe 通过）
- [x] 未激活 UIA 的错误通过现有 CLI 错误处理输出到标准错误并以状态码 1 退出。（verification：检查现有 CLI 异常边界）
- [x] 现有消息监听、会话搜索切换、发送前目标复核和无鼠标发送测试继续通过。（verification：完整 `tests/test_wechat_uia_driver.py` 通过）
- [x] README 中现有未提交的其他用户修改被保留。（verification：检查最终 diff 只改动版本与讲述人相关段落）

## Safety Boundaries

- [x] 实现没有启动、停止或控制 Windows 讲述人。（verification：代码和 diff 中不存在 Narrator 启动调用或系统无障碍设置写入）
- [x] 实现没有自动启动、停止或重启微信。（verification：代码和 diff 中不存在新增进程控制调用）
- [x] 实现没有写入微信文件或进程内存。（verification：代码和 diff 中不存在文件写入、`WriteProcessMemory` 或注入逻辑）
- [x] 本次没有新增依赖、OCR、坐标点击或第二套自动化实现。（verification：依赖文件无改动，代码 diff 符合批准计划）

## Build And Tests

- [x] UIA 驱动专项测试通过。（verification：`python -m pytest tests/test_wechat_uia_driver.py -q`，17 passed）
- [x] 修改的 Python 模块可以编译。（verification：`python -m compileall src/mewcode/wechat/uia_client.py src/mewcode/wechat/cli.py`）
- [x] 修改范围 Ruff 检查通过。（verification：`python -m ruff check src/mewcode/wechat/uia_client.py src/mewcode/wechat/cli.py tests/test_wechat_uia_driver.py`）
- [x] 修改范围 Ruff 格式检查通过。（verification：`python -m ruff format --check src/mewcode/wechat/uia_client.py src/mewcode/wechat/cli.py tests/test_wechat_uia_driver.py`）
- [x] 全量自动化测试通过，或只存在已确认与本次无关的基线失败。（verification：`python -m pytest -q`，390 passed、1 skipped）
- [x] Git diff 没有空白错误。（verification：`git diff --check`）

## End-To-End Scenarios

- [x] E2E-1：讲述人已激活、微信 `4.1.9.30` 已登录时执行 `mewcode-wechat --probe`，成功输出实际版本和唯一的会话列表、消息列表、聊天输入区域。（verification：脱敏 probe 输出和退出码 0）
- [x] E2E-2：只读 probe 不发送消息、不切换当前会话、不移动鼠标。（verification：probe 路径代码检查和真实只读执行）
- [x] E2E-3：模拟 `4.0.5.15` 的唯一可用主窗口时版本门禁继续通过，保持旧版本兼容。（verification：参数化单元测试）
- [x] E2E-4：模拟 `4.1.9.30` 只暴露微信 Qt 外壳时快速失败并给出讲述人重启提示，不进入消息监听。（verification：外壳诊断测试完成且无重试）
- [x] E2E-5：模拟其他微信版本时安全拒绝，并明确列出两个支持版本。（verification：不支持版本测试）
