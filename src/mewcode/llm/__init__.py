from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from mewcode.config import ProviderConfig


ROLE_USER: Literal["user"] = "user"
ROLE_ASSISTANT: Literal["assistant"] = "assistant"
ROLE_TOOL: Literal["tool"] = "tool"


@dataclass(frozen=True)
class Usage:
    """一轮 Provider 请求的输入与输出 token 数。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0


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
class ImageContent:
    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    data: str
    detail: Literal["original"] = "original"
    sha256: str = ""
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    created_at: int = 0
    degraded: bool = False
    cleared: bool = False


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    images: list[ImageContent] = field(default_factory=list)


@dataclass(frozen=True)
class System:
    """稳定系统提示与每轮动态环境信息。"""

    stable: str = ""
    environment: str = ""
    context: str = ""


@dataclass(frozen=True)
class Request:
    """一次 Provider 请求的完整、可扩展载荷。"""

    messages: list[Message] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)
    system: System = field(default_factory=System)
    reminder: str = ""


@dataclass(frozen=True)
class StreamEvent:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    done: bool = False
    err: Exception | None = None


class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def redact(self, text: str) -> str: ...

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]: ...


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


def message_request_chars(message: Message) -> int:
    """Return a conservative text-equivalent request size without counting Base64."""
    active_images = sum(not image.cleared and bool(image.data) for image in message.images)
    return len(message.content) + active_images * 384 * 4


__all__ = [
    "ImageContent",
    "Message",
    "Provider",
    "Request",
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "ROLE_USER",
    "StreamEvent",
    "System",
    "ToolCall",
    "ToolDefinition",
    "ToolResult",
    "Usage",
    "new_provider",
    "redact_secret",
    "message_request_chars",
]
