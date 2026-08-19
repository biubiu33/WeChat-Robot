from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.wechat.models import WechatDesktopEvent
from mewcode.wechat.store import (
    CachedLocation,
    CachedWebPage,
    CachedWebSearch,
    WechatStateStore,
)


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


def test_info_cache_records_are_global_and_prunable(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    store.put_location(CachedLocation("place:a", '{"value":1}', 10))
    store.put_web_search(CachedWebSearch("search:a", "query", "[]", 20))
    store.put_web_page(CachedWebPage("page:a", "https://a.example", "A", "body", 30))

    assert store.get_location("place:a") == CachedLocation("place:a", '{"value":1}', 10)
    assert store.get_web_search("search:a") == CachedWebSearch(
        "search:a", "query", "[]", 20
    )
    assert store.get_web_page("page:a") == CachedWebPage(
        "page:a", "https://a.example", "A", "body", 30
    )

    store.prune_info_cache(25)
    assert store.get_location("place:a") is not None
    assert store.get_web_search("search:a") is None
    assert store.get_web_page("page:a") is not None
    store.close()


def test_tavily_monthly_credit_reservation_stops_at_limit(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    assert store.reserve_tavily_credit("2026-08", limit=2)
    assert store.reserve_tavily_credit("2026-08", limit=2)
    assert not store.reserve_tavily_credit("2026-08", limit=2)
    assert store.tavily_credits("2026-08") == 2
    assert store.reserve_tavily_credit("2026-09", limit=2)
    store.close()
