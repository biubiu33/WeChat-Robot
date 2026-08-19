from __future__ import annotations

import asyncio
import json
import urllib.parse
from functools import wraps

import pytest

from mewcode.wechat.info.http import HttpRequest, HttpResponse
from mewcode.wechat.info.location import LocationCandidate, LocationResolution
from mewcode.wechat.info.weather import OpenMeteoClient, WeatherTool, WeatherUnits


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


BEIJING = LocationCandidate(
    "北京",
    "CN",
    39.9042,
    116.4074,
    "Asia/Shanghai",
    "capital",
)


class FakeResolver:
    def __init__(self, resolution: LocationResolution) -> None:
        self.resolution = resolution
        self.calls: list[tuple[str, bool]] = []

    async def resolve(
        self, query: str, *, coarse_only: bool = False
    ) -> LocationResolution:
        self.calls.append((query, coarse_only))
        return self.resolution


class FakeWeatherClient:
    def __init__(self) -> None:
        self.calls = 0

    async def forecast(
        self, location: LocationCandidate, mode: str, units: WeatherUnits
    ) -> dict[str, object]:
        self.calls += 1
        return {"current": {"temperature_2m": 22, "weather_description": "晴"}}


class FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.requests: list[HttpRequest] = []

    async def request(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return HttpResponse(200, request.url, {}, json.dumps(self.payload).encode())


@async_test
async def test_weather_tool_never_caches_and_records_attribution() -> None:
    resolver = FakeResolver(LocationResolution("resolved", BEIJING))
    client = FakeWeatherClient()
    attributions: list[str] = []
    tool = WeatherTool(
        resolver,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        on_weather_used=lambda: attributions.append("weather"),
    )

    first = await tool.execute('{"location":"北京","mode":"current"}')
    second = await tool.execute('{"location":"北京","mode":"current"}')

    assert not first.is_error and not second.is_error
    assert client.calls == 2
    assert resolver.calls == [("北京", True), ("北京", True)]
    assert attributions == ["weather", "weather"]


@async_test
async def test_weather_location_boundaries_ask_instead_of_guessing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    resolver = FakeResolver(LocationResolution("privacy_rejected"))
    tool = WeatherTool(
        resolver,  # type: ignore[arg-type]
        FakeWeatherClient(),  # type: ignore[arg-type]
    )

    missing = await tool.execute('{"location":""}')
    precise = await tool.execute('{"location":"星湖街 88 号 2 栋"}')

    assert missing.is_error and "location_required" in missing.content
    assert precise.is_error and "location_too_precise" in precise.content

    ambiguous_client = FakeWeatherClient()
    ambiguous = WeatherTool(
        FakeResolver(
            LocationResolution(
                "ambiguous",
                candidates=(
                    BEIJING,
                    LocationCandidate(
                        "南京", "CN", 32.06, 118.79, "Asia/Shanghai", "nominatim"
                    ),
                ),
            )
        ),  # type: ignore[arg-type]
        ambiguous_client,  # type: ignore[arg-type]
    )
    ambiguous_result = await ambiguous.execute('{"location":"同名地点"}')
    assert (
        ambiguous_result.is_error and "ambiguous_location" in ambiguous_result.content
    )
    assert ambiguous_client.calls == 0
    output = capsys.readouterr().out
    assert "[get_weather 返回结果]" in output
    assert "location_required" in output
    assert "location_too_precise" in output
    assert "ambiguous_location" in output


@async_test
async def test_open_meteo_uses_fixed_endpoint_fields_timezone_and_units() -> None:
    transport = FakeTransport(
        {
            "hourly": {
                "time": [f"2026-08-{index:02d}T00:00" for index in range(1, 52)],
                "temperature_2m": list(range(51)),
                "weather_code": [0] * 51,
            }
        }
    )
    client = OpenMeteoClient(transport)

    result = await client.forecast(
        BEIJING, "hourly", WeatherUnits("fahrenheit", "mph", "inch")
    )

    request = transport.requests[0]
    parsed = urllib.parse.urlsplit(request.url)
    params = urllib.parse.parse_qs(parsed.query)
    assert parsed.netloc == "api.open-meteo.com"
    assert params["models"] == ["best_match"]
    assert params["timezone"] == ["Asia/Shanghai"]
    assert params["forecast_hours"] == ["48"]
    assert params["temperature_unit"] == ["fahrenheit"]
    assert params["wind_speed_unit"] == ["mph"]
    assert params["precipitation_unit"] == ["inch"]
    assert len(result["hourly"]["time"]) == 48  # type: ignore[index]
    assert result["hourly"]["weather_description"][0] == "晴"  # type: ignore[index]


@async_test
async def test_current_weather_selects_approved_fields_and_chinese_direction() -> None:
    transport = FakeTransport(
        {
            "current": {
                "time": "2026-08-19T15:00",
                "temperature_2m": 30,
                "apparent_temperature": 33,
                "relative_humidity_2m": 70,
                "precipitation": 0,
                "weather_code": 2,
                "wind_speed_10m": 12,
                "wind_direction_10m": 90,
                "unapproved": "drop",
            },
            "daily": {
                "time": ["2026-08-19"],
                "temperature_2m_max": [32],
                "temperature_2m_min": [24],
                "sunrise": ["2026-08-19T05:30"],
                "sunset": ["2026-08-19T18:40"],
                "weather_code": [2],
                "wind_direction_10m_dominant": [225],
            },
        }
    )

    result = await OpenMeteoClient(transport).forecast(
        BEIJING, "current", WeatherUnits()
    )

    current = result["current"]  # type: ignore[assignment]
    assert "unapproved" not in current
    assert current["weather_description"] == "局部多云"  # type: ignore[index]
    assert current["wind_direction_10m_zh"] == "东"  # type: ignore[index]
    assert result["today"]["wind_direction_10m_dominant_zh"] == ["西南"]  # type: ignore[index]
