from __future__ import annotations

import json

from rich.console import Group
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from mewcode.agent import Mode


def user_block(text: str) -> Text:
    return Text(f"● {text}", style="bold cyan")


def assistant_block(reply: str, elapsed_seconds: int) -> Group:
    heading = Text(f"● MewCode ({elapsed_seconds}s)", style="bold green")
    return Group(heading, Markdown(reply))


def error_block(err: Exception) -> Text:
    return Text(f"● 错误: {err}", style="bold red")


def streaming_block(reply: str, elapsed_seconds: int, iteration: int = 0) -> Group:
    body = reply or "等待模型响应..."
    detail = f"Imagining... ({elapsed_seconds}s"
    if iteration:
        detail += f" · 第 {iteration} 轮"
    detail += ")"
    return Group(
        Text(f"● {body}", style="green"),
        Text(detail, style="dim"),
    )


def tools_running_block(
    tools: list[tuple[str, str]], elapsed_seconds: int
) -> Group:
    rows: list[Text] = []
    for name, args in tools:
        rows.append(tool_line(name, args))
        rows.append(Text(f"  Running... ({elapsed_seconds}s)", style="dim"))
    return Group(*rows)


def tool_line(name: str, args: str) -> Text:
    return Text(f"● {name}({_argument_preview(name, args)})", style="bold cyan")


def tool_result_summary(result: str, is_error: bool) -> Text:
    lines = result.splitlines()
    truncated = len(lines) > 8
    summary = lines[:8]
    if truncated:
        summary.append("[truncated]")
    body = "\n  ".join(summary) if summary else "(empty)"
    style = "red" if is_error else "dim"
    return Text(f"  -> {body}", style=style)


def notice_block(text: str) -> Text:
    return Text(f"● {text}", style="dim yellow")


def _argument_preview(name: str, args: str) -> str:
    try:
        values = json.loads(args or "{}")
    except json.JSONDecodeError:
        values = {}
    key = {
        "read_file": "path",
        "write_file": "path",
        "edit_file": "path",
        "bash": "command",
        "glob": "pattern",
        "grep": "pattern",
    }.get(name)
    value = values.get(key, "") if isinstance(values, dict) and key else ""
    preview = str(value).replace("\r", " ").replace("\n", " ")
    if len(preview) > 100:
        preview = preview[:97] + "..."
    return preview


def status_bar(
    provider_name: str,
    model: str,
    mode: Mode = Mode.NORMAL,
    usage_in: int = 0,
    usage_out: int = 0,
) -> Table:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    plan = " [PLAN]" if mode is Mode.PLAN else ""
    usage = f"↑{_compact_tokens(usage_in)} ↓{_compact_tokens(usage_out)} tok"
    table.add_row(f"Provider: {provider_name}{plan}", f"Model: {model}  {usage}")
    return table


def _compact_tokens(value: int) -> str:
    if value < 1_000:
        return str(value)
    return f"{value / 1_000:.1f}k"


def selecting_status() -> Table:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    table.add_row("请选择 provider", "Enter 确认")
    return table
