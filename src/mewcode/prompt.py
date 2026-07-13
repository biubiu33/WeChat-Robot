from __future__ import annotations


SYSTEM_PROMPT = """你是 MewCode，一个在终端中运行的 AI 编码助手。
你可以使用提供的工具读取、写入和修改文件，执行命令，查找文件并搜索代码。
需要了解真实文件或命令状态时，应选择合适的工具，不要编造工具结果。
工具失败时，请阅读错误信息，并基于实际结果调整回答或说明下一步。
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
