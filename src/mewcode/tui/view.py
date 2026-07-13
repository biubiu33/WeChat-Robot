from __future__ import annotations

import json

from rich.console import Group
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text


def user_block(text: str) -> Text:
    return Text(f"● {text}", style="bold cyan")


def assistant_block(reply: str, elapsed_seconds: int) -> Group:
    heading = Text(f"● MewCode ({elapsed_seconds}s)", style="bold green")
    return Group(heading, Markdown(reply))


def error_block(err: Exception) -> Text:
    return Text(f"● 错误: {err}", style="bold red")


def streaming_block(reply: str, elapsed_seconds: int) -> Group:
    body = reply or "等待模型响应..."
    return Group(
        Text(f"● {body}", style="green"),
        Text(f"Imagining… ({elapsed_seconds}s)", style="dim"),
    )


def tool_running_block(name: str, args: str, elapsed_seconds: int) -> Group:
    return Group(
        tool_line(name, args),
        Text(f"  Running... ({elapsed_seconds}s)", style="dim"),
    )


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


def status_bar(provider_name: str, model: str) -> Table:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    table.add_row(f"Provider: {provider_name}", f"Model: {model}")
    return table


def selecting_status() -> Table:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    table.add_row("请选择 provider", "Enter 确认")
    return table
