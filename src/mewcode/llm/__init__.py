from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from mewcode.config import ProviderConfig


ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: str


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass(frozen=True)
class StreamEvent:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False
    err: Exception | None = None


class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def redact(self, text: str) -> str: ...

    def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]: ...


def new_provider(cfg: ProviderConfig) -> Provider:
    if cfg.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg)
    raise ValueError(f"未知 provider 协议: {cfg.protocol}")


def redact_secret(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


__all__ = [
    "Message",
    "Provider",
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "ROLE_USER",
    "StreamEvent",
    "ToolCall",
    "ToolDefinition",
    "ToolResult",
    "new_provider",
    "redact_secret",
]
