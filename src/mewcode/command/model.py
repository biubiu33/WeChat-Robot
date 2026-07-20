from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Protocol, TYPE_CHECKING

from mewcode.permission import Mode

if TYPE_CHECKING:
    from .registry import CommandRegistry


class CommandKind(Enum):
    LOCAL = "local"
    UI = "ui"
    PROMPT = "prompt"


class InputKind(Enum):
    EMPTY = "empty"
    MESSAGE = "message"
    COMMAND = "command"


CommandHandler = Callable[["CommandContext", str], Awaitable[None]]


@dataclass(frozen=True)
class Command:
    name: str
    aliases: tuple[str, ...]
    description: str
    usage: str
    kind: CommandKind
    handler: CommandHandler
    argument_hint: str = ""
    hidden: bool = False


@dataclass(frozen=True)
class ParsedInput:
    kind: InputKind
    text: str = ""
    command_name: str = ""
    argument: str = ""


@dataclass(frozen=True)
class StatusSnapshot:
    mode: str
    input_tokens: int
    output_tokens: int
    tool_count: int
    memory_count: int
    model: str
    working_directory: str


@dataclass(frozen=True)
class MemorySnapshot:
    project: tuple[str, ...] = ()
    user: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.project) + len(self.user)


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    archive_path: str


class CommandControl(Protocol):
    async def show_message(self, text: str) -> None: ...

    async def send_user_message(self, text: str) -> None: ...

    async def compact_context(self) -> None: ...

    async def resume_session(self) -> None: ...

    async def clear_session(self) -> None: ...

    async def exit_app(self) -> None: ...

    def set_mode(self, mode: Mode) -> None: ...

    def refresh_status(self) -> None: ...

    def status_snapshot(self) -> StatusSnapshot: ...

    def memory_snapshot(self) -> MemorySnapshot: ...

    def session_snapshot(self) -> SessionSnapshot | None: ...


@dataclass(frozen=True)
class CommandContext:
    registry: CommandRegistry
    control: CommandControl
