from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

from mewcode.wechat.info.http import HttpRequest, HttpResponse
from mewcode.wechat.info.location import CurrentTimeTool, LocationResolver
from mewcode.wechat.info.location import NominatimRateLimiter
from mewcode.wechat.store import WechatStateStore


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


class FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.requests: list[HttpRequest] = []

    async def request(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return HttpResponse(
            200,
            request.url,
            {"Content-Type": "application/json"},
            json.dumps(self.payload).encode(),
        )


@async_test
async def test_country_name_uses_capital_coordinates_without_network(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    transport = FakeTransport([])
    resolver = LocationResolver(store, "Test/1.0", transport=transport)

    resolution = await resolver.resolve("美国")

    assert resolution.status == "resolved"
    assert resolution.location is not None
    assert "Washington" in resolution.location.display_name
    assert resolution.location.timezone == "America/New_York"
    assert resolution.location.source == "capital"
    assert transport.requests == []
    store.close()


@async_test
async def test_nominatim_ambiguity_is_cached_and_attributed(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    transport = FakeTransport(
        [
            {
                "display_name": "London, Greater London, United Kingdom",
                "lat": "51.5074",
                "lon": "-0.1278",
                "address": {
                    "city": "London",
                    "state": "England",
                    "country": "UK",
                    "country_code": "gb",
                },
            },
            {
                "display_name": "London, Ontario, Canada",
                "lat": "42.9837",
                "lon": "-81.2497",
                "address": {
                    "city": "London",
                    "state": "Ontario",
                    "country": "Canada",
                    "country_code": "ca",
                },
            },
        ]
    )
    resolver = LocationResolver(store, "MewCode-Test/1.0", transport=transport)

    first = await resolver.resolve("London")
    second = await resolver.resolve("London")

    assert first.status == "ambiguous"
    assert len(first.candidates) == 2
    assert first.attribution_required
    assert second.status == "ambiguous"
    assert all(candidate.source == "cache" for candidate in second.candidates)
    assert len(transport.requests) == 1
    assert transport.requests[0].headers["User-Agent"] == "MewCode-Test/1.0"
    store.close()


@async_test
async def test_weather_location_rejects_precise_address_before_network(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    transport = FakeTransport([])
    resolver = LocationResolver(store, "Test/1.0", transport=transport)

    resolution = await resolver.resolve(
        "苏州市工业园区星湖街 88 号 2 栋", coarse_only=True
    )

    assert resolution.status == "privacy_rejected"
    assert transport.requests == []
    store.close()


@async_test
async def test_time_tool_returns_iana_offset_dst_and_host_date_difference(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    fixed = datetime(2026, 1, 15, 3, 0, tzinfo=UTC).timestamp()
    resolver = LocationResolver(
        store, "Test/1.0", transport=FakeTransport([]), clock=lambda: fixed
    )
    tool = CurrentTimeTool(resolver, clock=lambda: fixed)

    result = await tool.execute('{"location":"USA"}')
    payload = json.loads(result.content)

    assert payload["ok"] is True
    assert payload["timezone"] == "America/New_York"
    assert payload["utc_offset"] == "-05:00"
    assert payload["daylight_saving"] is False
    assert payload["date_difference_from_host"] == -1

    summer = datetime(2026, 7, 15, 12, 0, tzinfo=UTC).timestamp()
    summer_tool = CurrentTimeTool(resolver, clock=lambda: summer)
    summer_payload = json.loads(
        (await summer_tool.execute('{"location":"美国"}')).content
    )
    assert summer_payload["utc_offset"] == "-04:00"
    assert summer_payload["daylight_saving"] is True

    local_payload = json.loads((await tool.execute("{}")).content)
    assert local_payload["ok"] is True
    assert local_payload["location"] == "本机"
    store.close()


@async_test
async def test_nominatim_rate_limiter_waits_one_second_between_requests() -> None:
    now = [0.0]
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = NominatimRateLimiter(lambda: now[0], sleep)
    await limiter.wait()
    await limiter.wait()

    assert sleeps == [1.0]
