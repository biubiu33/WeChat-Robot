from __future__ import annotations

from dataclasses import replace

from .model import Command


class CommandConflictError(ValueError):
    pass


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._lookup: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        name = _normalize_key(command.name, "命令名")
        aliases = tuple(_normalize_key(alias, "命令别名") for alias in command.aliases)
        normalized = replace(command, name=name, aliases=aliases)
        keys = (name, *aliases)
        if len(set(keys)) != len(keys):
            raise CommandConflictError(f"命令 {name} 的名称或别名重复")
        for key in keys:
            existing = self._lookup.get(key)
            if existing is not None:
                raise CommandConflictError(
                    f"命令名称或别名冲突: {key} 已由 {existing.name} 占用，"
                    f"无法注册 {name}"
                )
        self._commands[name] = normalized
        for key in keys:
            self._lookup[key] = normalized

    def resolve(self, name: str) -> Command | None:
        return self._lookup.get(name.strip().lower())

    def unregister(self, name: str) -> None:
        normalized = _normalize_key(name, "命令名称")
        command = self._commands.get(normalized)
        if command is None:
            return
        del self._commands[normalized]
        for key in (command.name, *command.aliases):
            self._lookup.pop(key, None)

    def replace_dynamic(
        self, previous_names: tuple[str, ...], commands: tuple[Command, ...]
    ) -> None:
        previous_commands = self._commands.copy()
        previous_lookup = self._lookup.copy()
        try:
            for name in previous_names:
                self.unregister(name)
            for command in commands:
                self.register(command)
        except Exception:
            self._commands = previous_commands
            self._lookup = previous_lookup
            raise

    def public_commands(self) -> tuple[Command, ...]:
        return tuple(
            sorted(
                (command for command in self._commands.values() if not command.hidden),
                key=lambda command: command.name,
            )
        )

    def completions(self, prefix: str) -> tuple[Command, ...]:
        normalized = prefix.strip().lower()
        matches = {
            command.name: command
            for command in self.public_commands()
            if command.name.startswith(normalized)
            or any(alias.startswith(normalized) for alias in command.aliases)
        }
        return tuple(matches[name] for name in sorted(matches))


def _normalize_key(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{label}不能为空")
    if normalized.startswith("/") or any(
        character.isspace() for character in normalized
    ):
        raise ValueError(f"{label}不能包含 / 前缀或空白: {value!r}")
    return normalized
