"""MewCode 的稳定系统提示、动态环境与补充指令。"""

from __future__ import annotations

from collections.abc import Sequence

from .environment import Environment, gather_environment
from .modules import Module, fixed_modules, optional_modules
from .reminder import EXECUTE_DIRECTIVE, plan_reminder, system_reminder


CAT_BANNER = r"""
 /\_/\
( o.o )
 > ^ <
"""

READY_HINT = "就绪。输入消息开始对话，输入 /exit 或按 Ctrl+C 退出。"


def assemble_system(modules: Sequence[Module]) -> str:
    """按优先级确定性地渲染非空系统提示模块。"""
    ordered = sorted(enumerate(modules), key=lambda item: (item[1].priority, item[0]))
    rendered = [
        f"## {module.name}\n{module.content.strip()}"
        for _, module in ordered
        if module.content.strip()
    ]
    return "\n\n".join(rendered)


def build_system_prompt() -> str:
    """构造跨轮稳定、可用于缓存的系统提示。"""
    return assemble_system([*fixed_modules(), *optional_modules()])


def render_banner(version: str, cwd: str) -> str:
    return f"{CAT_BANNER}\nMewCode v{version}\ncwd: {cwd}\n{READY_HINT}"


__all__ = [
    "CAT_BANNER",
    "EXECUTE_DIRECTIVE",
    "Environment",
    "Module",
    "READY_HINT",
    "assemble_system",
    "build_system_prompt",
    "fixed_modules",
    "gather_environment",
    "optional_modules",
    "plan_reminder",
    "render_banner",
    "system_reminder",
]
