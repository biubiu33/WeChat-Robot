from __future__ import annotations

from rich.text import Text
from textual.widgets import OptionList

from mewcode.command import Command


class CommandCompletionMenu(OptionList):
    can_focus = False

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._commands: tuple[Command, ...] = ()
        self.display = False

    @property
    def commands(self) -> tuple[Command, ...]:
        return self._commands

    def set_commands(self, commands: tuple[Command, ...]) -> None:
        self.clear_options()
        self._commands = commands
        if not commands:
            self.highlighted = None
            self.display = False
            return

        self.add_options(self._render_command(command) for command in commands)
        self.highlighted = 0
        self.display = True
        self.scroll_to_highlight()

    def move_highlight(self, delta: int) -> None:
        if not self._commands:
            return
        current = self.highlighted if self.highlighted is not None else 0
        self.highlighted = (current + delta) % len(self._commands)
        self.scroll_to_highlight()

    def highlighted_name(self) -> str | None:
        if self.highlighted is None:
            return None
        return self.command_name_at(self.highlighted)

    def command_name_at(self, index: int) -> str | None:
        if not 0 <= index < len(self._commands):
            return None
        return self._commands[index].name

    @staticmethod
    def _render_command(command: Command) -> Text:
        return Text.assemble(
            (f"/{command.name}", "bold"),
            (f"  {command.description}", "dim"),
        )
