# 任意路径启动配置发现 Spec

## 背景
当前 MewCode 已通过 `pyproject.toml` 暴露 `mewcode` 命令入口，但启动时只读取当前工作目录下的 `.mewcode/config.yaml`。这导致用户在项目目录之外运行 `mewcode` 时无法找到配置，不能实现“任意路径下启动”。

## 目标
- 用户安装 MewCode 后，可以在任意命令行路径执行 `mewcode` 启动。
- 保留当前目录配置能力，方便项目级覆盖。
- 支持用户级默认配置，避免每个目录都复制配置文件。
- 支持通过环境变量显式指定配置文件，便于临时切换或脚本使用。

## 功能需求
- F1：启动时优先读取环境变量 `MEWCODE_CONFIG` 指定的配置文件。
- F2：未设置 `MEWCODE_CONFIG` 时，优先读取当前工作目录下的 `.mewcode/config.yaml`。
- F3：当前工作目录没有配置时，读取用户主目录下的 `.mewcode/config.yaml`。
- F4：若三种来源都没有可用配置，启动时输出清晰中文错误，说明已尝试的配置位置。
- F5：配置文件加载和校验规则沿用现有 YAML providers 规则。
- F6：README 说明任意路径启动方式、配置查找顺序和用户级配置创建方法。

## 非功能需求
- N1：不改变 provider 配置字段格式。
- N2：不在错误信息中输出 API Key。
- N3：不引入新的运行依赖。
- N4：Windows 与类 Unix 路径都应通过 `pathlib.Path.home()` 兼容。

## 范围外
- 新增命令行参数解析。
- 支持多个配置文件合并。
- 自动迁移已有配置文件。
- 修改 provider 选择或 TUI 行为。

## 验收标准
- AC1：设置 `MEWCODE_CONFIG` 为有效配置路径时，`mewcode` 使用该配置启动。
- AC2：未设置环境变量且当前目录存在 `.mewcode/config.yaml` 时，`mewcode` 使用当前目录配置。
- AC3：未设置环境变量、当前目录无配置、用户主目录存在 `.mewcode/config.yaml` 时，`mewcode` 使用用户级配置。
- AC4：所有候选配置都不存在时，`mewcode` 输出中文错误，并列出尝试过的位置。
- AC5：README 包含任意路径启动步骤和推荐的用户级配置路径。
