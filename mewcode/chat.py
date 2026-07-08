from __future__ import annotations

from collections.abc import Sequence

from mewcode.errors import ProviderError
from mewcode.io import ConsoleIO, default_console_io
from mewcode.models import ChatMessage
from mewcode.providers.base import ChatProvider

EXIT_COMMANDS = {"/exit", "/quit", "退出", "再见"}


def run_chat(
    provider: ChatProvider, profile_name: str, io: ConsoleIO | None = None
) -> int:
    console = io or default_console_io()
    history: list[ChatMessage] = []

    console.write(f"欢迎使用 MewCode，当前配置：{profile_name}\n")
    console.write("输入 /exit、/quit、退出 或 再见 可以结束会话。\n")
    console.flush()

    while True:
        try:
            user_input = console.input("你> ")
        except EOFError:
            console.write("\n已退出 MewCode。\n")
            console.flush()
            return 0

        text = user_input.strip()
        if not text:
            continue
        if text in EXIT_COMMANDS:
            console.write("已退出 MewCode。\n")
            console.flush()
            return 0

        request_history = [*history, ChatMessage(role="user", content=text)]
        console.write("MewCode> ")
        console.flush()

        assistant_parts: list[str] = []
        try:
            for chunk in provider.stream_chat(request_history):
                assistant_parts.append(chunk.text)
                console.write(chunk.text)
                console.flush()
        except ProviderError as exc:
            console.write(f"\n请求失败：{exc}\n")
            console.flush()
            continue

        console.write("\n")
        console.flush()
        assistant_text = "".join(assistant_parts)
        history.append(ChatMessage(role="user", content=text))
        history.append(ChatMessage(role="assistant", content=assistant_text))


def is_exit_command(text: str) -> bool:
    return text.strip() in EXIT_COMMANDS
