from __future__ import annotations

import hashlib
import re
import threading
import time
import unicodedata
from collections import Counter
from collections.abc import Collection
from dataclasses import replace
from difflib import SequenceMatcher

from .group_sender_ocr import GroupSenderOcr
from .models import ConversationRow, VisibleMessage, WechatDesktopEvent
from .shell_hook import WindowsShellHook
from .uia_client import WechatUiaClient


def strip_self_mention(
    text: str,
    self_names: Collection[str],
) -> tuple[str, bool]:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.replace("\u2005", " ").replace("\u00a0", " ")
    matched = False
    for name in sorted(self_names, key=len, reverse=True):
        target = unicodedata.normalize("NFKC", name.strip())
        if not target:
            continue
        pattern = re.compile(rf"@{re.escape(target)}(?=$|[\s,，:：;；.!?。！？])")
        value, count = pattern.subn("", value)
        matched = matched or count > 0
    return re.sub(r"^[ \t]+", "", value).strip(), matched


class WechatUiaDriver:
    def __init__(
        self,
        client: WechatUiaClient,
        hook: WindowsShellHook | None = None,
        *,
        allowed_contacts: Collection[str] | None = None,
        allowed_groups: Collection[str] | None = None,
        self_names: Collection[str] = (),
        group_sender_ocr: GroupSenderOcr | None = None,
        reconcile_seconds: float = 2.0,
    ) -> None:
        self._client = client
        self._hook = hook or WindowsShellHook(client.process_ids)
        self._reconcile_seconds = max(0.2, reconcile_seconds)
        self._lock = threading.RLock()
        self._allowed_contacts = (
            frozenset(allowed_contacts) if allowed_contacts is not None else None
        )
        self._allowed_groups = frozenset(allowed_groups or ())
        self._self_names = tuple(self_names)
        self._group_sender_ocr = group_sender_ocr
        if self._allowed_groups and self._group_sender_ocr is None:
            self._group_sender_ocr = GroupSenderOcr()
        self._signatures: dict[str, str] = {}
        self._seen_messages: dict[str, set[str]] = {}
        self._group_snapshots: dict[str, list[VisibleMessage]] = {}
        self._group_baseline_ready: set[str] = set()
        self._baseline_ready = False

    def start(self) -> None:
        self._hook.start()

    def close(self) -> None:
        self._hook.close()

    def preload_group_ocr(self) -> None:
        if self._group_sender_ocr is not None:
            self._group_sender_ocr.preload()

    def establish_baseline(self) -> None:
        with self._lock:
            rows = self._rows()
            by_name = {row.name: row for row in rows}
            self._signatures = {row.name: row.signature for row in rows}
            for name in self._allowed_groups:
                row = by_name.get(name, ConversationRow(name, name))
                try:
                    self._client.focus_conversation(replace(row, private=False))
                    if self._client.current_conversation_is_private():
                        continue
                    messages = self._client.visible_text_messages(row)
                    self._seen_messages[name] = {message.key for message in messages}
                    self._group_snapshots[name] = list(messages)
                    self._group_baseline_ready.add(name)
                except Exception:  # noqa: BLE001 - defer unavailable baseline safely
                    self._seen_messages.setdefault(name, set())
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
            try:
                return self._client.validate_target(
                    event.conversation_name, event.private
                )
            except TypeError:
                return self._client.validate_target(event.conversation_name)

    def send_text(self, event: WechatDesktopEvent, text: str) -> None:
        with self._lock:
            row = ConversationRow(
                key=event.conversation_key,
                name=event.conversation_name,
                private=event.private,
            )
            self._client.send_text(row, text)

    def send_group_first(
        self,
        event: WechatDesktopEvent,
        sender_name: str,
        text: str,
    ) -> tuple[bool, str]:
        with self._lock:
            row = ConversationRow(
                key=event.conversation_key,
                name=event.conversation_name,
                private=False,
            )
            real = self._client.send_group_text_with_mention(row, sender_name, text)
            return real, "" if real else self._client.mention_fallback_reason()

    def _rows(self) -> list[ConversationRow]:
        reader = getattr(self._client, "visible_conversations", None)
        if callable(reader):
            return list(reader())
        return list(self._client.visible_private_conversations())

    def _scan(self) -> list[WechatDesktopEvent]:
        rows = self._rows()
        counts = Counter(row.name for row in rows)
        events: list[WechatDesktopEvent] = []
        for row in rows:
            previous = self._signatures.get(row.name)
            self._signatures[row.name] = row.signature
            expected_private = self._expected_private(row.name)
            if expected_private is None or counts[row.name] != 1:
                continue
            if self._baseline_ready and previous == row.signature:
                current_name = getattr(
                    self._client, "current_conversation_name", lambda: ""
                )()
                if current_name != row.name:
                    continue
            if expected_private and row.unread_count <= 0:
                continue

            row = replace(row, private=expected_private)
            self._client.focus_conversation(row)
            actual_private = self._client.current_conversation_is_private()
            if actual_private is not expected_private:
                continue
            messages = self._client.visible_text_messages(row)
            if actual_private:
                candidates = messages[-min(row.unread_count, len(messages)) :]
                for index, message in enumerate(candidates):
                    events.append(
                        self._event(row, message, candidates, index, private=True)
                    )
                continue

            if self._group_sender_ocr is None:
                continue
            bounds_reader = getattr(self._client, "message_list_bounds", None)
            pane_bounds = bounds_reader() if callable(bounds_reader) else None
            resolved = self._group_sender_ocr.enrich(messages, pane_bounds)
            resolved = self._stabilize_group_messages(row.name, resolved)
            seen = self._seen_messages.setdefault(row.name, set())
            if row.name not in self._group_baseline_ready:
                seen.update(message.key for message in resolved)
                self._group_baseline_ready.add(row.name)
                continue
            new_messages = [message for message in resolved if message.key not in seen]
            seen.update(message.key for message in resolved)
            for index, message in enumerate(new_messages):
                if (
                    not message.incoming
                    or not message.sender_name
                    or message.kind != "text"
                ):
                    continue
                cleaned, is_at = strip_self_mention(message.text, self._self_names)
                events.append(
                    self._event(
                        row,
                        message,
                        new_messages,
                        index,
                        private=False,
                        is_at=is_at,
                        text=cleaned if is_at else message.text,
                    )
                )
        return events

    def _stabilize_group_messages(
        self,
        conversation_name: str,
        messages: list[VisibleMessage],
    ) -> list[VisibleMessage]:
        previous = self._group_snapshots.get(conversation_name, [])
        previous_signatures = [(item.kind, item.text) for item in previous]
        current_signatures = [(item.kind, item.text) for item in messages]
        stable = list(messages)
        matcher = SequenceMatcher(
            None,
            previous_signatures,
            current_signatures,
            autojunk=False,
        )
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                old = previous[block.a + offset]
                current_index = block.b + offset
                stable[current_index] = replace(
                    stable[current_index],
                    key=old.key,
                )
        self._group_snapshots[conversation_name] = stable
        return stable

    def _expected_private(self, name: str) -> bool | None:
        if (
            self._allowed_contacts is None or name in self._allowed_contacts
        ) and name not in self._allowed_groups:
            return True
        if name in self._allowed_groups:
            return False
        return None

    @staticmethod
    def _event(
        row: ConversationRow,
        message: VisibleMessage,
        candidates: list[VisibleMessage],
        index: int,
        *,
        private: bool = True,
        is_at: bool = False,
        text: str | None = None,
    ) -> WechatDesktopEvent:
        start = max(0, index - 4)
        suffix = "\0".join(item.text for item in candidates[start : index + 1])
        fingerprint = hashlib.sha256(
            f"{row.name}\0{message.key}\0{message.sender_name}\0{suffix}".encode()
        ).hexdigest()
        event_id = hashlib.sha256(
            f"{row.key}\0{message.key}\0{fingerprint}".encode()
        ).hexdigest()
        return WechatDesktopEvent(
            event_id=event_id,
            fingerprint=fingerprint,
            conversation_key=row.key,
            conversation_name=row.name,
            sender_name=message.sender_name or row.name,
            text=message.text if text is None else text,
            observed_at=time.time(),
            incoming=True,
            private=private,
            is_at=is_at,
            raw_text=message.text,
        )


__all__ = ["WechatUiaDriver", "strip_self_mention"]
