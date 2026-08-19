from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.wechat.models import WechatDesktopEvent
from mewcode.wechat.store import WechatStateStore


def event(
    event_id: str = "event-1", fingerprint: str = "fingerprint-1"
) -> WechatDesktopEvent:
    return WechatDesktopEvent(
        event_id=event_id,
        fingerprint=fingerprint,
        conversation_key="row-1",
        conversation_name="好友",
        sender_name="好友",
        text="你好",
        observed_at=1.0,
        incoming=True,
        private=True,
    )


def test_event_fingerprint_is_recorded_once(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)

    assert store.record_event_once(event()) is True
    assert store.record_event_once(event("event-2")) is False
    assert store.is_processed("event-1") is False
    store.mark_processed("event-1")
    assert store.is_processed("event-1") is True
    store.close()


def test_session_binding_is_idempotent_persistent_and_conflict_safe(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    store.bind_session("好友", "session-1")
    store.bind_session("好友", "session-1")
    with pytest.raises(ValueError, match="已绑定其他 Session"):
        store.bind_session("好友", "session-2")
    store.close()

    reopened = WechatStateStore(tmp_path)
    assert reopened.get_session_id("好友") == "session-1"
    assert reopened.get_session_id("陌生人") is None
    reopened.close()
