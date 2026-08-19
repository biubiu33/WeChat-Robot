from __future__ import annotations

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


@dataclass(frozen=True)
class QueuedMessage:
    event: WechatDesktopEvent
    enqueued_at: float


@dataclass(frozen=True)
class WechatReply:
    conversation_name: str
    text: str


__all__ = [
    "ConversationBinding",
    "ConversationRow",
    "QueuedMessage",
    "VisibleMessage",
    "WechatDesktopEvent",
    "WechatReply",
]
