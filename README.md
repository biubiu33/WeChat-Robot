# MewCode

MewCode 是一个命令行 AI 对话助手。本阶段只实现纯对话：启动后进入交互式终端，选择一个 LLM profile，输入问题，并流式显示模型回复。

## 环境

- Python 3.12
- 运行依赖：`httpx`、`PyYAML`
- 测试依赖：`pytest`

## 安装

```bash
pip install -e ".[test]"
```

## 配置

复制示例配置：

```bash
cp examples/mewcode.yaml.example mewcode.yaml
```

配置文件使用 UTF-8 YAML，顶层是 `providers` 列表。每个 provider profile 包含：

- `name`：供应商配置名称
- `protocol`：协议类型，支持 `openai` 或 `anthropic`
- `model`：模型名称
- `base_url`：API 基础地址
- `api_key`：API Key
- `thinking`：可选，是否启用 Claude extended thinking

示例结构：

```yaml
providers:
  - name: openai
    protocol: openai
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key: sk-your-openai-key

  - name: claude
    protocol: anthropic
    model: claude-sonnet-5
    base_url: https://api.anthropic.com/v1
    api_key: sk-ant-your-anthropic-key
    thinking: true
```

## 运行

```bash
mewcode --config mewcode.yaml --profile openai
```

也可以使用：

```bash
python -m mewcode --config mewcode.yaml --profile claude
```

进入会话后输入中文问题即可。输入 `/exit`、`/quit`、`退出` 或 `再见` 可以结束会话。

## 范围

当前阶段不支持工具调用、文件操作、代码编辑或 Shell 执行，只提供多轮对话和流式输出。
