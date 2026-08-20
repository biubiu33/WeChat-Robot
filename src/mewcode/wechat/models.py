from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationRow:
    key: str
    name: str
    runtime_id: tuple[int, ...] = ()
    signature: str = ""
    unread_count: int = 0
    private: bool = True


@dataclass(frozen=True)
class VisibleMessage:
    key: str
    conversation_key: str
    text: str
    incoming: bool
    kind: str = "text"
    sender_name: str = ""


@dataclass(frozen=True)
class WechatDesktopEvent:
    event_id: str
    fingerprint: str
    conversation_key: str
    conversation_name: str
    sender_name: str
    text: str
    observed_at: float
    incoming: bool
    private: bool


@dataclass(frozen=True)
class ConversationBinding:
    conversation_name: str
    session_id: str


@dataclass
class PendingBatch:
    events: list[WechatDesktopEvent]
    revision: int
    timer: asyncio.Task[None] | None = None
    queued: bool = False


@dataclass(frozen=True)
class QueuedBatch:
    conversation_name: str
    events: tuple[WechatDesktopEvent, ...]
    revision: int
    enqueued_at: float

    @property
    def text(self) -> str:
        return "\n".join(event.text for event in self.events)


@dataclass(frozen=True)
class WechatReply:
    messages: tuple[str, ...]
    chat: bool
    source_message: str = ""


__all__ = [
    "ConversationBinding",
    "ConversationRow",
    "PendingBatch",
    "QueuedBatch",
    "VisibleMessage",
    "WechatDesktopEvent",
    "WechatReply",
]
