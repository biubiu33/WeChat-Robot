from __future__ import annotations

import asyncio
import json
from functools import wraps
from pathlib import Path

from mewcode.wechat.config import WechatInfoConfig
from mewcode.wechat.info.http import HttpRequest, HttpResponse, PublicPage
from mewcode.wechat.info.registry import WechatInfoServices
from mewcode.wechat.info.web import (
    TavilyError,
    TavilySearchClient,
    TurnBudget,
    WebFetchTool,
    WebSearchTool,
)
from mewcode.wechat.store import WechatStateStore


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = iter(responses)
        self.requests: list[HttpRequest] = []

    async def request(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return next(self.responses)


class FakePublicClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    async def fetch(self, url: str, timeout: float) -> PublicPage:
        self.calls.append((url, timeout))
        return PublicPage(url, "Example", "visible body", False)


class FailingSearchClient:
    def __init__(self, error: TavilyError) -> None:
        self.error = error
        self.calls = 0

    @property
    def configured(self) -> bool:
        return True

    async def search(self, query: str, timeout: float):
        self.calls += 1
        raise self.error


def tavily_response(url: str = "https://official.example/news") -> HttpResponse:
    return HttpResponse(
        200,
        "https://api.tavily.com/search",
        {"Content-Type": "application/json"},
        json.dumps(
            {
                "results": [
                    {
                        "title": "Official release",
                        "url": url,
                        "content": "verified summary",
                        "published_date": "2026-08-19",
                    }
                ]
            }
        ).encode(),
    )


@async_test
async def test_tavily_request_is_fixed_basic_and_turn_limited(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    transport = FakeTransport([tavily_response(), tavily_response("https://b.example")])
    sources: list[tuple[str, str, str]] = []
    tool = WebSearchTool(
        TavilySearchClient("test-key", transport),
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: sources.append(item),
        allow_sensitive=lambda query, personal: True,
        clock=lambda: 1_777_000_000.0,
    )

    first = await tool.execute('{"query":"official current event"}')
    second = await tool.execute('{"query":"second event"}')
    third = await tool.execute('{"query":"third event"}')

    assert not first.is_error and not second.is_error
    assert third.is_error and "最多调用 2 次" in third.content
    request_body = json.loads(transport.requests[0].body or b"{}")
    assert request_body == {
        "api_key": "test-key",
        "query": "official current event",
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    assert len(sources) == 2
    assert store.tavily_credits("2026-04") == 2
    store.close()


@async_test
async def test_search_cache_does_not_consume_another_credit(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    transport = FakeTransport([tavily_response()])
    now = 1_777_000_000.0
    client = TavilySearchClient("test-key", transport)

    def tool() -> WebSearchTool:
        return WebSearchTool(
            client,
            store,
            TurnBudget.create(lambda: 0.0),
            record_source=lambda *item: None,
            allow_sensitive=lambda query, personal: True,
            clock=lambda: now,
        )

    first = await tool().execute('{"query":"cache me"}')
    second = await tool().execute('{"query":"cache me"}')

    assert json.loads(first.content)["cached"] is False
    assert json.loads(second.content)["cached"] is True
    assert len(transport.requests) == 1
    assert store.tavily_credits("2026-04") == 1
    store.close()


@async_test
async def test_latest_never_uses_old_cache_but_normal_can_use_stale_fallback(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    now = [100.0]
    seed = WebSearchTool(
        TavilySearchClient("test-key", FakeTransport([tavily_response()])),
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: None,
        allow_sensitive=lambda query, personal: True,
        clock=lambda: now[0],
    )
    assert not (
        await seed.execute('{"query":"cached topic","freshness":"latest"}')
    ).is_error
    seed_normal = WebSearchTool(
        TavilySearchClient("test-key", FakeTransport([tavily_response()])),
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: None,
        allow_sensitive=lambda query, personal: True,
        clock=lambda: now[0],
    )
    assert not (
        await seed_normal.execute('{"query":"cached topic","freshness":"normal"}')
    ).is_error

    now[0] += 1801
    latest_client = FailingSearchClient(
        TavilyError("temporarily_unavailable", "down", retryable=False)
    )
    latest = WebSearchTool(
        latest_client,  # type: ignore[arg-type]
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: None,
        allow_sensitive=lambda query, personal: True,
        clock=lambda: now[0],
    )
    latest_result = await latest.execute(
        '{"query":"cached topic","freshness":"latest"}'
    )
    normal_result = await WebSearchTool(
        latest_client,  # type: ignore[arg-type]
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: None,
        allow_sensitive=lambda query, personal: True,
        clock=lambda: now[0],
    ).execute('{"query":"cached topic","freshness":"normal"}')

    assert latest_result.is_error
    assert json.loads(normal_result.content)["stale_fallback"] is True
    store.close()


@async_test
async def test_sensitive_search_requires_next_turn_confirmation(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    transport = FakeTransport([tavily_response()])
    services = WechatInfoServices(
        WechatInfoConfig(True, "test-key", "Test/1.0"), store, transport
    )

    first_turn = services.new_turn("friend", "帮我搜索这个手机号")
    first = await first_turn.registry.execute(
        "web_search", '{"query":"13800138000 信息","personal_data":true}'
    )
    second_turn = services.new_turn("friend", "我确认，继续搜索")
    second = await second_turn.registry.execute(
        "web_search", '{"query":"13800138000 信息","personal_data":true}'
    )

    assert first.is_error and "confirmation_required" in first.content
    assert not second.is_error
    assert len(transport.requests) == 1
    store.close()


@async_test
async def test_sensitive_confirmation_is_hash_expiring_and_friend_scoped(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    now = [100.0]
    services = WechatInfoServices(
        WechatInfoConfig(True, "test-key", "Test/1.0"),
        store,
        FakeTransport([]),
        wall_clock=lambda: now[0],
        monotonic_clock=lambda: now[0],
    )
    args = '{"query":"13800138000 信息","personal_data":true}'
    assert (
        await services.new_turn("A", "搜索").registry.execute("web_search", args)
    ).is_error
    cross_friend = await services.new_turn("B", "确认").registry.execute(
        "web_search", args
    )
    wrong_hash = await services.new_turn("A", "确认").registry.execute(
        "web_search", '{"query":"13900139000 信息","personal_data":true}'
    )
    await services.new_turn("A", "搜索").registry.execute("web_search", args)
    now[0] += 301
    expired = await services.new_turn("A", "确认").registry.execute("web_search", args)

    assert cross_friend.is_error and wrong_hash.is_error and expired.is_error
    assert store.tavily_credits("1970-01") == 0
    store.close()


@async_test
async def test_page_fetch_uses_cache_and_removes_secret_parameters(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    client = FakePublicClient()
    sources: list[tuple[str, str, str]] = []
    tool = WebFetchTool(
        client,  # type: ignore[arg-type]
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: sources.append(item),
        clock=lambda: 100.0,
    )

    first = await tool.execute(
        '{"url":"https://example.com/page?token=private&view=full"}'
    )
    second = await tool.execute(
        '{"url":"https://example.com/page?token=another&view=full"}'
    )

    assert not first.is_error and json.loads(first.content)["cached"] is False
    assert json.loads(second.content)["cached"] is True
    assert client.calls == [("https://example.com/page?view=full", 10.0)]
    assert all("token" not in source[1] for source in sources)
    store.close()


@async_test
async def test_sixth_page_fetch_is_rejected_even_when_cache_hits(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    client = FakePublicClient()
    tool = WebFetchTool(
        client,  # type: ignore[arg-type]
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: None,
        clock=lambda: 100.0,
    )

    results = [
        await tool.execute('{"url":"https://example.com/page"}') for _ in range(6)
    ]

    assert all(not result.is_error for result in results[:5])
    assert results[5].is_error and "最多调用 5 次" in results[5].content
    assert len(client.calls) == 1
    store.close()


@async_test
async def test_search_configuration_and_quota_errors_do_not_retry(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    missing_transport = FakeTransport([])
    missing = WebSearchTool(
        TavilySearchClient("", missing_transport),
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: None,
        allow_sensitive=lambda query, personal: True,
        clock=lambda: 1_777_000_000.0,
    )
    missing_result = await missing.execute('{"query":"public info"}')

    quota_transport = FakeTransport(
        [HttpResponse(429, "https://api.tavily.com/search", {}, b"quota")]
    )
    quota = WebSearchTool(
        TavilySearchClient("unique-secret-key", quota_transport),
        store,
        TurnBudget.create(lambda: 0.0),
        record_source=lambda *item: None,
        allow_sensitive=lambda query, personal: True,
        clock=lambda: 1_777_000_000.0,
    )
    quota_result = await quota.execute('{"query":"other public info"}')

    assert missing_result.is_error and "not_configured" in missing_result.content
    assert missing_transport.requests == []
    assert store.tavily_credits("2026-04") == 1
    assert quota_result.is_error and "quota_or_rate_limit" in quota_result.content
    assert "unique-secret-key" not in quota_result.content
    assert len(quota_transport.requests) == 1
    store.close()
