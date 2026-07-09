from __future__ import annotations

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
