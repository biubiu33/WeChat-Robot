"""每轮动态补充指令。"""

from __future__ import annotations

EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"

_PLAN_REMINDER_FULL = """当前处于计划模式。你只能使用只读工具（read_file、glob、grep）调研工作区，不得写入或修改文件，也不得执行命令。请先收集必要事实，再给出清晰、可执行的分步计划，然后停止并等待用户输入 /do 批准执行。"""
_PLAN_REMINDER_CONCISE = """仍处于计划模式：只可使用只读工具，不得写入、修改或执行命令。继续基于事实完善计划，等待 /do 后再执行。"""


def system_reminder(body: str) -> str:
    """为动态补充指令添加不会被当作普通提问的显式标签。"""
    return f"<system-reminder>\n{body.strip()}\n</system-reminder>"


def plan_reminder(full: bool) -> str:
    """返回完整或精简的计划模式补充指令。"""
    body = _PLAN_REMINDER_FULL if full else _PLAN_REMINDER_CONCISE
    return system_reminder(body)
