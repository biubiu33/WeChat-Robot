# 多协议 LLM 终端对话客户端 Tasks

> 包名：`mewcode`（Python 3.12+）。源码位于 `src/mewcode/`，内部模块以 `mewcode.xxx` 导入。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `pyproject.toml` | PEP 621 项目元数据、依赖、脚本入口 |
| 新建 | `.mewcode/config.yaml.example` | 配置模板 |
| 修改 | `.gitignore` | 忽略 `.mewcode/config.yaml` |
| 新建 | `src/mewcode/__init__.py` | 包标识、版本号 `__version__` |
| 新建 | `src/mewcode/__main__.py` | `python -m mewcode` 入口（转调 `cli.main`） |
| 新建 | `src/mewcode/config.py` | `Config` / `ProviderConfig`、`load`、校验 |
| 新建 | `src/mewcode/prompt.py` | `SYSTEM_PROMPT`、`CAT_BANNER`、`render_banner` |
| 新建 | `src/mewcode/llm/__init__.py` | `Provider` Protocol、`Message`、`StreamEvent`、`new_provider` 工厂 |
| 新建 | `src/mewcode/conversation.py` | 单会话多轮历史 |
| 新建 | `src/mewcode/llm/anthropic_provider.py` | anthropic 适配器 |
| 新建 | `src/mewcode/llm/openai_provider.py` | openai 适配器 |
| 新建 | `src/mewcode/tui/__init__.py` | TUI 包标识 |
| 新建 | `src/mewcode/tui/app.py` | `MewCodeApp`、状态机、`run` |
| 新建 | `src/mewcode/tui/stream.py` | `_consume_stream`、`_tick` 计时 |
| 新建 | `src/mewcode/tui/select.py` | provider 选择（`OptionList`） |
| 新建 | `src/mewcode/tui/view.py` | 渲染拼装、状态栏、错误样式、markdown 定型 |
| 新建 | `src/mewcode/cli.py` | 入口装配 |
| 新建 | `tests/test_config.py` | config 单测 |
| 新建 | `tests/test_conversation.py` | conversation 单测 |

---

## T1: 初始化 Python 项目骨架与依赖
**文件：** `pyproject.toml`、`src/mewcode/__init__.py`、`src/mewcode/__main__.py`、`src/mewcode/cli.py`（临时占位）
**依赖：** 无
**步骤：**
1. 用 `uv init` 或手写 `pyproject.toml`，关键字段：
   ```toml
   [project]
   name = "mewcode"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = [
     "textual>=0.80",
     "rich>=13",
     "anthropic>=0.40",
     "openai>=1.50",
     "pyyaml>=6",
   ]

   [project.scripts]
   mewcode = "mewcode.cli:main"

   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"

   [tool.hatch.build.targets.wheel]
   packages = ["src/mewcode"]

   [dependency-groups]
   dev = ["pytest>=8", "ruff>=0.6", "mypy>=1.10"]
   ```
2. `src/mewcode/__init__.py`：定义 `__version__ = "0.1.0"`。
3. `src/mewcode/__main__.py`：`from .cli import main; main()`。
4. `src/mewcode/cli.py` 写一个临时 `main()`，打印 `f"mewcode {__version__}"` 并退出，确保可启动。
5. 安装依赖：`uv sync`（推荐）或 `pip install -e ".[dev]"`。

**验证：** `python -m mewcode` 能打印版本号；`uv run mewcode`（或 `mewcode`）同样可用；`uv pip list` / `pip list` 能看到上述依赖。

## T2: config 模块
**文件：** `src/mewcode/config.py`、`tests/test_config.py`
**依赖：** T1
**步骤：**
1. 定义 `@dataclass class ProviderConfig` 字段：`name`、`protocol`、`api_key`、`model`、`base_url: str | None = None`、`thinking: bool = False`；以及 `@dataclass class Config(providers: list[ProviderConfig])`。
2. 定义 `class ConfigError(Exception)`。
3. 实现 `load(path: str) -> Config`：用 `pathlib.Path(path).read_text()` + `yaml.safe_load` 解析；
   再调 `_from_dict(...)` 把 dict 映射到 dataclass（手动映射保留校验时机）。
4. 校验：`providers` 非空；逐项 `name` / `protocol` / `api_key` / `model` 非空；
   `protocol ∈ {"anthropic", "openai"}`。失败抛 `ConfigError`，message 形如
   `providers[1].api_key 不能为空`。
5. 文件不存在 → `ConfigError(f"配置文件不存在: {path}")`；YAML 解析失败 → 转换为 `ConfigError(...)`。
6. 写 `tests/test_config.py`：合法配置返回正确条数；缺字段 / 非法 protocol / 文件缺失分别抛 `ConfigError`。

**验证：** `pytest tests/test_config.py` 通过；`ruff check src/mewcode/config.py` 无告警。

## T3: 配置模板与忽略
**文件：** `.mewcode/config.yaml.example`、`.gitignore`
**依赖：** T2
**步骤：**
1. 写 `.mewcode/config.yaml.example`：含 anthropic 条目（含 `thinking: true`）与一段注释掉的 openai 条目示例，字段与 `ProviderConfig` 对齐。
2. `.gitignore` 追加 `.mewcode/config.yaml`。

**验证：** 复制 example 为 `.mewcode/config.yaml` 后 `config.load(...)` 通过；`git status` 确认 `.mewcode/config.yaml` 被忽略。

## T4: prompt 模块
**文件：** `src/mewcode/prompt.py`
**依赖：** T1
**步骤：**
1. 定义 `SYSTEM_PROMPT: str = """..."""`（一段简洁的固定 system prompt）。
2. 定义 `CAT_BANNER: str = """..."""`（ASCII 猫：`/\\_/\\`、`( o.o )`、`> ^ <`）。
3. 实现 `def render_banner(version: str, cwd: str) -> str`：拼出"猫 + MewCode vX + cwd + 就绪提示行"。

**验证：** `python -c "from mewcode.prompt import render_banner; print(render_banner('0.1.0', '/tmp'))"` 输出含三要素与提示行。

## T5: llm 包骨架
**文件：** `src/mewcode/llm/__init__.py`
**依赖：** T2
**步骤：**
1. 定义 `@dataclass class Message(role: Literal["user","assistant"], content: str)`、
   `@dataclass class StreamEvent(text: str = "", done: bool = False, err: Exception | None = None)`。
2. 定义 `class Provider(Protocol)`：`name` / `model`（property）；
   `def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]: ...`。
3. 实现 `def new_provider(cfg: ProviderConfig) -> Provider`：按 `cfg.protocol` 分派
   `AnthropicProvider` / `OpenAIProvider`；未知协议抛 `ValueError`。
   （适配器在 T7/T8 实现，先 import 占位，可在 `from .anthropic_provider import ...` 处暂用 `try/except` 让骨架可 import。）

**验证：** `python -c "from mewcode.llm import Provider, Message, StreamEvent, new_provider"` 不报错。

## T6: conversation 模块
**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`
**依赖：** T5
**步骤：**
1. 定义 `class Conversation`，内部 `self._messages: list[Message] = []`。
2. 实现 `add_user(text)`、`add_assistant(text)`、`messages() -> list[Message]`（返回 `list(self._messages)` 副本）。
3. 单测：连续 `add_user` / `add_assistant` 后 `messages()` 顺序与 role 正确。

**验证：** `pytest tests/test_conversation.py` 通过。

## T7: anthropic 适配器
**文件：** `src/mewcode/llm/anthropic_provider.py`
**依赖：** T5、T4
**步骤：**
1. `class AnthropicProvider`：`__init__(self, cfg)` 中 `self._client = anthropic.AsyncAnthropic(api_key=cfg.api_key, base_url=cfg.base_url or None)`；保存 `cfg.model` / `cfg.name` / `cfg.thinking`。
2. `name` / `model` property 返回 `cfg.name` / `cfg.model`。
3. `async def stream(self, msgs) -> AsyncIterator[StreamEvent]`：
   - 把 `msgs` 转 `[{"role": m.role, "content": m.content} for m in msgs]`。
   - `params = {"model": self._model, "max_tokens": 4096, "system": SYSTEM_PROMPT, "messages": [...]}`。
   - 若 `self._thinking`，加 `thinking={"type": "enabled", "budget_tokens": 2048}`。
   - `try: async with self._client.messages.stream(**params) as stream: async for event in stream:`
     根据 `event.type` 判断：`content_block_delta` 且 `event.delta.type == "text_delta"` →
     `yield StreamEvent(text=event.delta.text)`；`thinking_delta` 跳过；其他事件忽略。
   - `else` 分支正常结束 → `yield StreamEvent(done=True)`。
   - `except asyncio.CancelledError: raise`；其他 `except Exception as e: yield StreamEvent(err=e)`。

**验证：** `python -c "from mewcode.llm.anthropic_provider import AnthropicProvider"` 不报错；联调留到 T14；可写小脚本用假 key 触发错误，确认拿到 `err` 事件。

## T8: openai 适配器
**文件：** `src/mewcode/llm/openai_provider.py`
**依赖：** T5、T4
**步骤：**
1. `class OpenAIProvider`：`__init__` 中 `self._client = openai.AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url or None)`；保存 `cfg.model` / `cfg.name`（`thinking` 忽略）。
2. `name` / `model` property 同上。
3. `async def stream(self, msgs) -> AsyncIterator[StreamEvent]`：
   - 组装 `messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [{"role": m.role, "content": m.content} for m in msgs]`。
   - `try: stream = await self._client.chat.completions.create(model=self._model, messages=messages, stream=True)`。
   - `async for chunk in stream: delta = chunk.choices[0].delta.content; if delta: yield StreamEvent(text=delta)`。
   - 结束后 `yield StreamEvent(done=True)`。
   - `except asyncio.CancelledError: raise`；其他 `except Exception as e: yield StreamEvent(err=e)`。

**验证：** import 不报错；同 T7 的错误路径手测。

## T9: TUI App 骨架
**文件：** `src/mewcode/tui/app.py`、`src/mewcode/tui/__init__.py`
**依赖：** T1、T2、T5、T6
**步骤：**
1. 定义 `class SessionState(Enum)`：`SELECTING` / `IDLE` / `STREAMING`。
2. 定义 `class MewCodeApp(App)`：构造参数 `providers: list[ProviderConfig]`；初始化 `state`、`provider: Provider | None`、`conv = Conversation()`、`cur_reply = ""`、`turn_start = 0.0`、`_stream_task = None`、`_timer = None`。
3. `compose() -> ComposeResult`：yield `RichLog`（id="log"，wrap=True，markup=True）、`Static`（id="streaming"，初始空，用作动态区显示流式 cur_reply + "Imagining… (Ns)"）、`TextArea`（id="input"，single_line=False，用作输入框；用 CSS 给上边框 + `❯` 前缀）、`Static`（id="statusbar"）。
4. `on_mount(self)`：把 `prompt.render_banner(__version__, os.getcwd())` 写进 `RichLog`；
   若 `len(self.providers) == 1`：`self.provider = new_provider(self.providers[0])`、`self.state = IDLE`、更新状态栏；
   否则切 `SELECTING`（在 T11 接入 `OptionList`）。
5. `BINDINGS = [("ctrl+c", "quit", "Quit")]`；`async def action_quit(self)`：若 `_stream_task` 存在则 `cancel()`，`self.exit()`。
6. `def main()`（在 `cli.py` 中调用）：`MewCodeApp(providers).run()`。

**验证：** `python -m mewcode`（搭配最小合法配置）能进入界面，看到 banner + 空对话区 + 输入框 + 状态栏；`ruff check src/mewcode/tui/app.py` 无告警。

## T10: TUI 流式接入与计时
**文件：** `src/mewcode/tui/stream.py`、`src/mewcode/tui/app.py`
**依赖：** T9、T5
**步骤：**
1. 在 `app.py` 给 `MewCodeApp` 添加 `async def submit(self, text: str)`：
   - 识别 `text.strip() == "/exit"` → `await self.action_quit()`。
   - 否则：`self.conv.add_user(text)`；`self.query_one("#log", RichLog).write(user_block(text))`；
     清空 TextArea；`self.cur_reply = ""`；`self.turn_start = time.monotonic()`；
     `self.state = STREAMING`；`self._stream_task = asyncio.create_task(self._consume_stream())`；
     `self._timer = self.set_interval(0.1, self._tick)`。
2. 在 `stream.py`（或 app.py 内）实现 `async def _consume_stream(self)`：
   ```python
   try:
       async for ev in self.provider.stream(self.conv.messages()):
           if ev.err is not None:
               self._finish_with_error(ev.err); return
           if ev.text:
               self.cur_reply += ev.text
               self._refresh_streaming_view()
           if ev.done:
               self._finish_with_assistant(self.cur_reply); return
   except asyncio.CancelledError:
       raise
   except Exception as e:
       self._finish_with_error(e)
   ```
3. `_tick`：仅 `STREAMING` 时刷新 `#streaming` 上的 `Imagining… ({int(elapsed)}s)`。
4. `_finish_with_assistant`：
   - 用 `rich.markdown.Markdown(reply)` 渲染 → `RichLog.write(...)` 追加；
   - `self.conv.add_assistant(reply)`；
   - `self._timer.stop()`；`self._stream_task = None`；`self.state = IDLE`；清空 `#streaming`。
5. `_finish_with_error`：`RichLog.write(error_block(e))`；同上回 IDLE。
6. 在 `app.py` 监听 `TextArea` 提交：默认 Enter 在 TextArea 是换行；用 binding `("enter", "submit", "Submit")` + 自定义检查 `if not alt: submit() else: 插入换行`（或反向使用 `shift+enter` 换行 + Enter 提交，按 spec 用 Alt+Enter 换行）。

**验证：** 配真实 key 后跑通一轮：能看到 "Imagining… (Ns)" 计时；流式逐字；done 后看到 markdown 渲染追加到 RichLog。

## T11: TUI provider 选择
**文件：** `src/mewcode/tui/select.py`
**依赖：** T9、T2、T5
**步骤：**
1. 当 `state == SELECTING` 时，`compose` 中再 yield 一个 `OptionList`，列出 `f"{p.name} ({p.model})"` 每项。
2. 监听 `on_option_list_option_selected`：取出对应 `ProviderConfig` → `self.provider = new_provider(cfg)` → 更新状态栏 → 隐藏/移除 `OptionList` → 切 `IDLE`。
3. 进入 `SELECTING` 时把 `TextArea` / `RichLog` 隐藏，仅显示 list；切回 `IDLE` 时反过来。

**验证：** 用 2 条 provider 配置启动应出现选择列表（在 T14 端到端验证）。

## T12: TUI View 拼装与渲染
**文件：** `src/mewcode/tui/view.py`
**依赖：** T9、T4、T10
**步骤：**
1. banner 在 `on_mount` 时写入 `RichLog`（一次性），不在每帧渲染中重绘。
2. 动态区只有 `#streaming`（流式时显示 `● {cur_reply}\nImagining… (Ns)`）+ 输入框 + 状态栏。
3. 状态栏：用 Rich 的 `Text`/`Table.grid` 左 `provider.name`、右 `provider.model`，两端对齐；
   写到 `#statusbar: Static`。
4. 完成块（追加到 `RichLog`）：
   - `user_block(text)` = `Text("● " + text, style="bold")` 或纯文本（无 You/MewCode 文字标签）；
   - `render_markdown(reply)` = 一个 `Group(Text("● "), Markdown(reply))` 之类的组合；
   - 都无 You/MewCode 文字标签。
5. 错误样式：`error_block(err)` 用红色 lipgloss 等价的 `Text("● " + str(err), style="bold red")`。
6. 长行：Textual + Rich 默认按宽度软换行；CSS 设置 `#streaming: width: 1fr; height: auto;`，
   `Markdown`/`RichLog` 用 `width: 1fr;` 自适应（N6）。

**验证：** 把工具栏、状态栏、错误样式截图比对；`ruff check src/mewcode/tui/` 无告警。

## T13: 入口装配
**文件：** `src/mewcode/cli.py`（替换 T1 占位）
**依赖：** T2、T4、T9
**步骤：**
1. `def main() -> None`：
   - `try: cfg = config.load(".mewcode/config.yaml")`；`except ConfigError as e: print(e, file=sys.stderr); sys.exit(1)`。
   - 可选：先 `print(prompt.render_banner(__version__, os.getcwd()))`，或交给 TUI 在 `on_mount` 写 `RichLog`（二选一保持一致；本项目用后者）。
   - `MewCodeApp(cfg.providers).run()`；若抛非 KeyboardInterrupt 异常，`print(...)` 并 `sys.exit(1)`。

**验证：** `python -m mewcode` 在合法配置下能启动 TUI；缺配置时打印可读错误并退出码非零。

## T14: 端到端联调
**文件：** 无（运行验证）
**依赖：** T1–T13
**步骤：**
1. 用真实 anthropic 配置（`thinking: true`）跑：多轮对话、流式逐字、Imagining 计时、done 后 markdown 定型、思考内容不出现。
2. 用 openai 协议配置跑：同样多轮 + 流式。
3. 配两条 provider：启动出现选择列表，选定后状态栏正确。
4. 故意用错误 key：错误在对话区显示且不退出，可继续。
5. `/exit` 与 Ctrl+C：安全退出、终端无残留（终端 raw mode 由 Textual 自动还原）。
6. 建议用 tmux 验证 scrollback 行为：完成块用终端原生滚轮 / Ctrl+B + `[` 可回看。

**验证：** 逐条对照 `checklist.md` 记录证据。

## 执行顺序
```
T1 ─┬─ T2 ─┬─ T3
    │      └─ T5 ─┬─ T6
    │             ├─ T7
    │             └─ T8
    ├─ T4
    └─ T9 ─┬─ T10
           ├─ T11
           └─ T12
T2,T4,T9 ─ T13
T1..T13 ─ T14
```
（T4 可与 T2/T5 并行；T7、T8 可并行；T10/T11/T12 在 T9 后可并行推进。）
