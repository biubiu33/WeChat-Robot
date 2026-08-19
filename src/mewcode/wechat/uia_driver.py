from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter
from collections.abc import Collection

from .models import ConversationRow, VisibleMessage, WechatDesktopEvent
from .shell_hook import WindowsShellHook
from .uia_client import WechatUiaClient


class WechatUiaDriver:
    def __init__(
        self,
        client: WechatUiaClient,
        hook: WindowsShellHook | None = None,
        *,
        allowed_contacts: Collection[str] | None = None,
        reconcile_seconds: float = 2.0,
    ) -> None:
        self._client = client
        self._hook = hook or WindowsShellHook(client.process_ids)
        self._reconcile_seconds = max(0.2, reconcile_seconds)
        self._lock = threading.RLock()
        self._allowed_contacts = (
            frozenset(allowed_contacts) if allowed_contacts is not None else None
        )
        self._signatures: dict[str, str] = {}
        self._baseline_ready = False

    def start(self) -> None:
        self._hook.start()

    def close(self) -> None:
        self._hook.close()

    def establish_baseline(self) -> None:
        with self._lock:
            rows = self._client.visible_private_conversations()
            self._signatures = {row.name: row.signature for row in rows}
            self._baseline_ready = True

    def wait_for_events(self, stop: threading.Event) -> list[WechatDesktopEvent]:
        if stop.is_set():
            return []
        self._hook.wait(self._reconcile_seconds)
        if stop.is_set():
            return []
        with self._lock:
            return self._scan()

    def validate_target(self, event: WechatDesktopEvent) -> bool:
        with self._lock:
            return self._client.validate_target(event.conversation_name)

    def send_text(self, event: WechatDesktopEvent, text: str) -> None:
        with self._lock:
            row = ConversationRow(
                key=event.conversation_key,
                name=event.conversation_name,
            )
            self._client.send_text(row, text)

    def _scan(self) -> list[WechatDesktopEvent]:
        rows = self._client.visible_private_conversations()
        counts = Counter(row.name for row in rows)
        events: list[WechatDesktopEvent] = []
        for row in rows:
            previous = self._signatures.get(row.name)
            self._signatures[row.name] = row.signature
            if (
                self._allowed_contacts is not None
                and row.name not in self._allowed_contacts
            ):
                continue
            if counts[row.name] != 1 or row.unread_count <= 0:
                continue
            if self._baseline_ready and previous == row.signature:
                continue
            self._client.focus_conversation(row)
            if not self._client.current_conversation_is_private():
                continue
            messages = self._client.visible_text_messages(row)
            candidates = messages[-min(row.unread_count, len(messages)) :]
            for index, message in enumerate(candidates):
                events.append(self._event(row, message, candidates, index))
        return events

    @staticmethod
    def _event(
        row: ConversationRow,
        message: VisibleMessage,
        candidates: list[VisibleMessage],
        index: int,
    ) -> WechatDesktopEvent:
        start = max(0, index - 4)
        suffix = "\0".join(item.text for item in candidates[start : index + 1])
        fingerprint = hashlib.sha256(
            f"{row.name}\0{message.key}\0{suffix}".encode("utf-8")
        ).hexdigest()
        event_id = hashlib.sha256(
            f"{row.key}\0{message.key}\0{fingerprint}".encode("utf-8")
        ).hexdigest()
        return WechatDesktopEvent(
            event_id=event_id,
            fingerprint=fingerprint,
            conversation_key=row.key,
            conversation_name=row.name,
            sender_name=message.sender_name or row.name,
            text=message.text,
            observed_at=time.time(),
            incoming=True,
            private=True,
        )


__all__ = ["WechatUiaDriver"]
