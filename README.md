# MewCode

MewCode 是一个 Claude Code 风格的终端 LLM 对话客户端。本阶段只做纯文本多轮对话：启动 TUI、选择 provider、输入消息、实时查看流式回复，并在回复完成后用 Markdown 定型渲染。

## 环境

- Python 3.12+
- 运行依赖：`textual`、`rich`、`anthropic`、`openai`、`pyyaml`
- 开发依赖：`pytest`、`ruff`、`mypy`

## 安装

推荐在你自己的 conda Python 3.12 环境中安装：

```bash
pip install -e .
```

如果使用 `uv`：

```bash
uv sync
```

安装完成后，`mewcode` 命令会注册到当前 Python 环境。只要该环境已激活，就可以在任意路径执行：

```bash
mewcode
```

## 配置

配置文件为 UTF-8 YAML，顶层字段是 `providers`，可配置一项或多项。MewCode 启动时按顺序查找：

1. 环境变量 `MEWCODE_CONFIG` 指定的配置文件
2. 当前目录 `.mewcode/config.yaml`
3. 用户目录 `.mewcode/config.yaml`

推荐把默认配置放在用户目录，这样可以在任意路径启动。

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "$HOME\.mewcode"
Copy-Item .mewcode\config.yaml.example "$HOME\.mewcode\config.yaml"
notepad "$HOME\.mewcode\config.yaml"
```

macOS/Linux：

```bash
mkdir -p ~/.mewcode
cp .mewcode/config.yaml.example ~/.mewcode/config.yaml
${EDITOR:-vi} ~/.mewcode/config.yaml
```

也可以临时指定配置：

Windows PowerShell：

```powershell
$env:MEWCODE_CONFIG = "D:\path\to\config.yaml"
mewcode
```

macOS/Linux：

```bash
MEWCODE_CONFIG=/path/to/config.yaml mewcode
```

配置示例：

```yaml
providers:
  - name: claude
    protocol: anthropic
    api_key: sk-ant-your-key
    model: claude-3-5-sonnet-latest
    base_url: https://api.anthropic.com
    thinking: true

  - name: openai
    protocol: openai
    api_key: sk-your-key
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
```

字段说明：

- `name`：界面状态栏显示的 provider 名称。
- `protocol`：`anthropic` 或 `openai`。
- `api_key`：API 密钥，不会在界面回显。
- `model`：模型名。
- `base_url`：可选，自定义兼容端点；留空时使用 SDK 默认端点。
- `thinking`：可选，仅 Anthropic 生效；为 `true` 时启用扩展思考，但界面不会显示思考文本。

## 运行

```bash
mewcode
```

或：

```bash
python -m mewcode
```

如果配置中只有一个 provider，MewCode 会直接进入对话；如果有多个 provider，会先显示方向键选择列表。进入对话后，按 `Enter` 提交，按 `Alt+Enter` 插入换行，输入 `/exit` 或按 `Ctrl+C` 退出。

## 当前范围

本阶段不支持工具调用、MCP、权限系统、文件读写、代码编辑、长期记忆、会话持久化、运行时切换模型或流式中断。它只负责把“人 ↔ LLM”的终端多轮对话闭环做稳。
