"""Data models for isolated sub-agent execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")


class DefinitionSource(str, Enum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"
    PLUGIN = "plugin"


class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    BYPASS = "bypassPermissions"
    DONT_ASK = "dontAsk"


class TaskStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Definition:
    name: str
    description: str
    instruction: str
    tools: frozenset[str] | None
    disallowed_tools: frozenset[str]
    model_profile: str | None
    max_turns: int
    permission_mode: PermissionMode
    background: bool
    source: DefinitionSource
    path: Path


@dataclass(frozen=True)
class AgentDiagnostic:
    path: Path
    message: str


@dataclass(frozen=True)
class LaunchRequest:
    prompt: str
    description: str
    subagent_type: str | None = None
    model_profile: str | None = None
    run_in_background: bool = False
    name: str | None = None


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0

    def add(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_write: int = 0,
        cache_read: int = 0,
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_write += cache_write
        self.cache_read += cache_read


@dataclass(frozen=True)
class TaskSummary:
    task_id: str
    status: str
    result: str = ""


def normalize_name(value: str) -> str:
    return value.strip().lower()


class DefinitionError(ValueError):
    pass


__all__ = [
    "AgentDiagnostic",
    "Definition",
    "DefinitionError",
    "DefinitionSource",
    "LaunchRequest",
    "NAME_RE",
    "PermissionMode",
    "TaskStatus",
    "TaskSummary",
    "TokenUsage",
    "normalize_name",
]
