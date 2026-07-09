# 任意路径启动配置发现 Checklist

> 每一项必须通过运行代码或观察行为验证。

## 实现完整性

- [ ] 配置层提供配置发现函数，并能返回最终配置路径与尝试路径（验证：运行 `pytest tests/test_config.py`）
- [ ] 设置 `MEWCODE_CONFIG` 且目标文件存在时，只使用环境变量指定的配置（验证：配置发现单元测试）
- [ ] 未设置 `MEWCODE_CONFIG` 且当前目录存在 `.mewcode/config.yaml` 时，使用当前目录配置（验证：配置发现单元测试）
- [ ] 当前目录无配置且用户目录存在 `.mewcode/config.yaml` 时，使用用户级配置（验证：配置发现单元测试）
- [ ] 所有候选配置缺失时，错误信息为中文，并列出尝试过的路径（验证：配置发现单元测试或运行 `python -m mewcode`）
- [ ] provider YAML 字段和校验规则保持不变（验证：原有配置加载测试仍通过）

## CLI 集成

- [ ] CLI 启动时调用配置发现函数，不再写死当前目录配置路径（验证：代码检查与 `python -m compileall src\mewcode`）
- [ ] 配置发现失败时，CLI 输出中文配置错误并返回非零退出码（验证：在无配置目录运行 `python -m mewcode`）
- [ ] 配置发现成功后，CLI 将发现到的路径传给现有配置加载逻辑（验证：配置发现测试和启动手测）

## 文档

- [ ] README 说明安装后可以在任意路径执行 `mewcode`（验证：阅读 README）
- [ ] README 说明配置查找顺序：`MEWCODE_CONFIG`、当前目录、用户目录（验证：阅读 README）
- [ ] README 给出 Windows 用户级配置路径示例（验证：阅读 README）
- [ ] README 给出 macOS/Linux 用户级配置路径示例（验证：阅读 README）
- [ ] README 给出 `MEWCODE_CONFIG` 临时指定配置示例（验证：阅读 README）

## 构建与测试

- [ ] Python 编译检查通过（验证：运行 `python -m compileall src\mewcode tests`）
- [ ] UTF-8 检查通过，文本文件不含 Unicode replacement character（验证：运行 UTF-8 检查脚本）
- [ ] 配置发现测试通过（验证：运行 `pytest tests/test_config.py`，若当前环境已安装 pytest）

## 端到端场景

- [ ] 场景 1：在任意非项目目录执行 `mewcode`，当用户目录存在 `.mewcode/config.yaml` 时可以启动（验证：手动运行）
- [ ] 场景 2：在项目目录执行 `mewcode`，当前目录 `.mewcode/config.yaml` 覆盖用户目录配置（验证：手动运行或测试）
- [ ] 场景 3：设置 `MEWCODE_CONFIG` 到临时配置文件后，在任意路径执行 `mewcode` 使用该配置（验证：手动运行或测试）
- [ ] 场景 4：删除/移走所有候选配置后执行 `mewcode`，输出中文错误和候选路径列表（验证：手动运行）
