from __future__ import annotations


SYSTEM_PROMPT = """你是 MewCode，一个在终端中运行的 AI 对话助手。
当前阶段你只进行纯文本对话，不使用工具、不读取文件、不执行命令。
回答应清晰、直接，并优先使用用户使用的语言。"""

CAT_BANNER = r"""
 /\_/\
( o.o )
 > ^ <
"""


def render_banner(version: str, cwd: str) -> str:
    return (
        f"{CAT_BANNER}\n"
        f"MewCode v{version}\n"
        f"cwd: {cwd}\n"
        "就绪。输入消息开始对话，输入 /exit 或按 Ctrl+C 退出。"
    )
