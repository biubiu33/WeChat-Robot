# 任意路径启动配置发现 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 修改 | `src/mewcode/config.py` | 新增配置发现结果、路径查找函数和缺配置错误 |
| 修改 | `src/mewcode/cli.py` | 启动时使用配置发现结果，不再写死当前目录配置 |
| 修改 | `tests/test_config.py` | 增加配置发现单元测试 |
| 修改 | `README.md` | 说明任意路径启动、用户级配置和环境变量 |

## T1: 实现配置发现函数

**文件：** `src/mewcode/config.py`

**依赖：** 已批准 `doc/02/plan.md`

**步骤：**
1. 新增 `CONFIG_ENV_VAR = "MEWCODE_CONFIG"`。
2. 新增 `CONFIG_RELATIVE_PATH = Path(".mewcode") / "config.yaml"`。
3. 新增 `ConfigDiscoveryResult` dataclass。
4. 实现 `discover_config_path(env=None, cwd=None, home=None)`。
5. 当环境变量非空时只检查环境变量路径。
6. 当环境变量为空时按当前目录、用户目录顺序检查。
7. 全部缺失时抛出 `ConfigError`，错误信息包含尝试过的路径。

**验证：** 运行 `python -m compileall src\mewcode`，期望通过。

## T2: 增加配置发现测试

**文件：** `tests/test_config.py`

**依赖：** T1

**步骤：**
1. 测试 `MEWCODE_CONFIG` 指向存在文件时优先返回该路径。
2. 测试当前目录配置优先于用户目录配置。
3. 测试当前目录无配置时 fallback 到用户目录配置。
4. 测试全部缺失时抛出 `ConfigError`，且错误信息包含尝试过的路径。

**验证：** 在安装测试依赖的环境运行 `pytest tests/test_config.py`，期望通过。

## T3: CLI 接入配置发现

**文件：** `src/mewcode/cli.py`

**依赖：** T1

**步骤：**
1. 移除固定 `CONFIG_PATH` 常量。
2. 导入 `discover_config_path`。
3. 在 `main()` 中先调用 `discover_config_path()`。
4. 将发现到的路径传给 `load()`。
5. 保持 `ConfigError` 的中文错误输出和退出码 1。

**验证：** 运行 `python -m compileall src\mewcode`，期望通过。

## T4: 更新 README

**文件：** `README.md`

**依赖：** T1、T3

**步骤：**
1. 说明 `mewcode` 安装后可在任意路径运行。
2. 说明配置查找顺序：`MEWCODE_CONFIG`、当前目录、用户目录。
3. 增加 Windows 用户级配置创建示例。
4. 增加 macOS/Linux 用户级配置创建示例。
5. 增加 `MEWCODE_CONFIG` 临时指定配置示例。

**验证：** 运行 UTF-8 检查脚本，期望 README 可按 UTF-8 解码且不含替换字符。

## T5: 回归验证

**文件：** 无

**依赖：** T1 到 T4

**步骤：**
1. 运行 `python -m compileall src\mewcode tests`。
2. 运行 UTF-8 替换字符检查。
3. 若当前环境安装了 pytest，运行 `pytest tests/test_config.py`。

**验证：** 编译和 UTF-8 检查通过；pytest 在可用环境中通过。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5
```
