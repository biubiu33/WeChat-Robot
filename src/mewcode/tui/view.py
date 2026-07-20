from __future__ import annotations

import json

from rich.console import Group
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from textual.widgets import Collapsible, Static

from mewcode.permission import Mode


def user_entry(text: str) -> Static:
    return Static(
        Group(
            Text("你", style="bold cyan"),
            Text(text),
        ),
        classes="timeline-entry user-entry",
    )


def assistant_entry(reply: str, elapsed_seconds: int) -> Static:
    heading = Text(f"● MewCode ({elapsed_seconds}s)", style="bold green")
    return Static(
        Group(heading, Markdown(reply)), classes="timeline-entry assistant-entry"
    )


def error_entry(err: Exception) -> Static:
    return Static(
        Text(f"● 错误: {err}", style="bold red"),
        classes="timeline-entry error-entry",
    )


def notice_entry(text: str) -> Static:
    return Static(
        Text(f"● {text}", style="dim yellow"),
        classes="timeline-entry notice-entry",
    )


def system_entry(text: str) -> Static:
    return Static(Text(text, style="dim"), classes="timeline-entry system-entry")


def command_output_entry(text: str) -> Static:
    return Static(Text(text), classes="timeline-entry command-output-entry")


def streaming_block(reply: str, elapsed_seconds: int, iteration: int = 0) -> Group:
    body = reply or "等待模型响应..."
    detail = f"生成中...（{elapsed_seconds}s"
    if iteration:
        detail += f"，第 {iteration} 轮"
    detail += "）"
    return Group(
        Text(f"● {body}", style="green"),
        Text(detail, style="dim"),
    )


def tools_running_block(tools: list[tuple[str, str]], elapsed_seconds: int) -> Group:
    rows: list[Text] = []
    for name, args in tools:
        rows.append(tool_line(name, args))
        rows.append(Text(f"  运行中...（{elapsed_seconds}s）", style="dim"))
    return Group(*rows)


def tool_line(name: str, args: str) -> Text:
    return Text(f"● {name}({_argument_preview(name, args)})", style="bold cyan")


def tool_result_entry(
    name: str,
    args: str,
    result: str,
    is_error: bool,
) -> Collapsible:
    status = "失败" if is_error else "完成"
    detail_class = (
        "tool-result-detail tool-result-error" if is_error else "tool-result-detail"
    )
    title = f"工具 {name} · {status} · {_argument_preview(name, args)}"
    return Collapsible(
        Static(tool_result_summary(result, is_error), classes=detail_class),
        title=title,
        collapsed=True,
        classes=(
            "timeline-entry tool-result-entry tool-result-entry-error"
            if is_error
            else "timeline-entry tool-result-entry"
        ),
    )


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


def status_bar(
    model: str,
    mode: Mode = Mode.DEFAULT,
    usage_in: int = 0,
    usage_out: int = 0,
) -> Table:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    usage = f"↑{_compact_tokens(usage_in)} ↓{_compact_tokens(usage_out)} tok"
    table.add_row(f"权限: [{_mode_label(mode)}]", f"Model: {model}  {usage}")
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


def approval_block(name: str, args: str, reason: str, cursor: int) -> Group:
    options = (
        "允许本次",
        "允许本会话",
        "永久允许（写入本地配置）",
        "拒绝本次",
    )
    rows: list[Text] = [
        tool_line(name, args),
        Text(f"  {reason}", style="dim"),
        Text("是否继续?", style="bold"),
    ]
    for index, option in enumerate(options):
        marker = "> " if index == cursor else "  "
        style = "bold cyan" if index == cursor else ""
        rows.append(Text(f"{marker}{index + 1}. {option}", style=style))
    rows.append(Text("↑↓ 选择 · Enter 确认 · Esc 取消", style="dim"))
    return Group(*rows)


def _mode_label(mode: Mode) -> str:
    return {
        Mode.DEFAULT: "DEFAULT",
        Mode.ACCEPT_EDITS: "ACCEPT EDITS",
        Mode.PLAN: "PLAN",
        Mode.BYPASS: "BYPASS",
    }[mode]
