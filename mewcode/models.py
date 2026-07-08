from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProviderProtocol = Literal["openai", "anthropic"]
ChatRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    protocol: ProviderProtocol
    model: str
    base_url: str
    api_key: str
    thinking: bool = False


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str


@dataclass(frozen=True)
class StreamChunk:
    text: str
