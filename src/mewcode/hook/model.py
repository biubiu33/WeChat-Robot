from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from mewcode.permission.rule import Pattern


class HookEvent(str, Enum):
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"


BLOCKING_EVENTS = frozenset({HookEvent.PRE_TOOL_USE, HookEvent.USER_PROMPT_SUBMIT})


@dataclass(frozen=True)
class Condition:
    field: str
    match: Pattern


@dataclass(frozen=True)
class ConditionGroup:
    mode: str
    conditions: tuple[Condition, ...]


@dataclass(frozen=True)
class Action:
    type: str
    command: str = ""
    text: str = ""
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    agent_name: str = ""
    prompt: str = ""


@dataclass(frozen=True)
class Hook:
    name: str
    event: HookEvent
    condition: ConditionGroup | None
    action: Action
    only_once: bool = False
    asynchronous: bool = False
    timeout_seconds: float = 30.0
    source: Path = Path()


@dataclass(frozen=True)
class HookContext:
    event: HookEvent
    payload: dict[str, Any]

    def value(self, field_path: str) -> Any:
        value: Any = self.payload
        for part in field_path.split("."):
            if not isinstance(value, dict) or part not in value:
                return ""
            value = value[part]
        return value

    def json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, sort_keys=True)


@dataclass
class HookSessionState:
    reserved: set[str] = field(default_factory=set)
    executed: set[str] = field(default_factory=set)
    reminders: list[str] = field(default_factory=list)
    background_tasks: set[asyncio.Task[None]] = field(default_factory=set)


@dataclass(frozen=True)
class HookDispatch:
    blocked_by: str = ""
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_by)


@dataclass(frozen=True)
class ActionResult:
    success: bool
    blocked: bool = False
    reason: str = ""


@dataclass(frozen=True)
class HookSnapshotEntry:
    name: str
    event: HookEvent
    action_type: str
    only_once: bool
    asynchronous: bool


@dataclass(frozen=True)
class HookSnapshot:
    entries: tuple[HookSnapshotEntry, ...] = ()
    sources: tuple[Path, ...] = ()


@dataclass(frozen=True)
class HookCatalog:
    hooks: tuple[Hook, ...] = ()
    sources: tuple[Path, ...] = ()
