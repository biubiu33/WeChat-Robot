from __future__ import annotations

from typing import Iterator, Protocol, Sequence

from mewcode.models import ChatMessage, StreamChunk


class ChatProvider(Protocol):
    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[StreamChunk]:
        ...


def redact_secret(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "[已隐藏]")
