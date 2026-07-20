from __future__ import annotations

from .model import CommandContext, CommandControl, InputKind, ParsedInput
from .registry import CommandRegistry


def parse_input(text: str) -> ParsedInput:
    normalized = text.strip()
    if not normalized:
        return ParsedInput(InputKind.EMPTY)
    if not normalized.startswith("/"):
        return ParsedInput(InputKind.MESSAGE, text=normalized)
    name, separator, argument = normalized[1:].partition(" ")
    return ParsedInput(
        InputKind.COMMAND,
        command_name=name.lower(),
        argument=argument.strip() if separator else "",
    )


class CommandDispatcher:
    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    async def dispatch(self, parsed: ParsedInput, control: CommandControl) -> None:
        if parsed.kind is not InputKind.COMMAND:
            raise ValueError("只能分发 Slash 命令输入")
        command = self.registry.resolve(parsed.command_name)
        if command is None:
            await control.show_message(
                f"未知命令 /{parsed.command_name}。输入 /help 查看可用命令。"
            )
            return
        if parsed.argument and not command.argument_hint:
            await control.show_message(
                f"命令 /{command.name} 不接受参数。用法: {command.usage}"
            )
            return
        await command.handler(CommandContext(self.registry, control), parsed.argument)
