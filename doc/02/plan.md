# 任意路径启动配置发现 Plan

## 架构概览
在配置层新增“配置发现”能力，CLI 启动时先解析出应使用的配置路径，再调用现有 `load(path)` 完成 YAML 读取和校验。

查找顺序固定为：

1. 环境变量 `MEWCODE_CONFIG`
2. 当前工作目录 `.mewcode/config.yaml`
3. 用户主目录 `.mewcode/config.yaml`

## 核心接口

### ConfigDiscoveryResult
表示配置发现结果。

```python
@dataclass(frozen=True)
class ConfigDiscoveryResult:
    path: Path
    attempted_paths: list[Path]
```

字段含义：
- `path`：最终找到的配置文件路径。
- `attempted_paths`：按顺序尝试过的路径，用于错误提示和测试。

### discover_config_path

```python
def discover_config_path(env: Mapping[str, str] | None = None, cwd: Path | None = None, home: Path | None = None) -> ConfigDiscoveryResult:
    ...
```

行为：
- `env` 默认使用 `os.environ`。
- `cwd` 默认使用 `Path.cwd()`。
- `home` 默认使用 `Path.home()`。
- 若 `MEWCODE_CONFIG` 存在且非空，只检查该路径。
- 若 `MEWCODE_CONFIG` 缺失或为空，依次检查 `cwd / ".mewcode/config.yaml"` 和 `home / ".mewcode/config.yaml"`。
- 找到第一个存在的文件即返回。
- 全部不存在时抛出 `ConfigError`，错误信息列出尝试过的路径。

## 模块改动

### `src/mewcode/config.py`
- 新增常量：
  - `CONFIG_ENV_VAR = "MEWCODE_CONFIG"`
  - `CONFIG_RELATIVE_PATH = Path(".mewcode") / "config.yaml"`
- 新增 `ConfigDiscoveryResult`。
- 新增 `discover_config_path(...)`。
- 保持 `load(path)` 和 provider 配置校验逻辑不变。

### `src/mewcode/cli.py`
- 移除写死的 `CONFIG_PATH = ".mewcode/config.yaml"`。
- 启动流程改为：
  1. `config_path = discover_config_path().path`
  2. `cfg = load(str(config_path))`
  3. 启动 `MewCodeApp`
- `ConfigError` 仍统一输出中文错误并退出码 1。

### `README.md`
- 将“配置文件路径固定为 `.mewcode/config.yaml`”改为配置查找顺序说明。
- 增加推荐用户级配置路径：
  - Windows：`%USERPROFILE%\.mewcode\config.yaml`
  - macOS/Linux：`~/.mewcode/config.yaml`
- 增加 `MEWCODE_CONFIG` 使用示例。

## 技术决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 配置发现位置 | `config.py` | 属于配置层职责，CLI 保持装配逻辑 |
| 环境变量优先级 | 最高 | 便于脚本和临时切换 |
| 当前目录优先于用户目录 | 是 | 保留项目级覆盖能力 |
| 用户目录获取 | `Path.home()` | 跨 Windows 和类 Unix |
| 缺配置错误 | 列出尝试路径 | 方便用户复制/创建正确位置 |

## 验证策略
- 单元测试覆盖环境变量路径优先。
- 单元测试覆盖当前目录配置优先于用户目录配置。
- 单元测试覆盖用户目录 fallback。
- 单元测试覆盖全部缺失时错误信息包含尝试路径。
- 编译检查 `python -m compileall src\mewcode tests`。
