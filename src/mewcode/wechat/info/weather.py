"""Open-Meteo weather tool with a fixed field and unit allowlist."""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

from mewcode.tool import Result, error_result, parse_arguments

from .http import HttpError, HttpRequest, HttpTransport, UrllibTransport
from .location import LocationCandidate, LocationResolver


WMO_ZH = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "轻微冻毛毛雨",
    57: "冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻微冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}


@dataclass(frozen=True)
class WeatherUnits:
    temperature: str = "celsius"
    wind_speed: str = "kmh"
    precipitation: str = "mm"


class WeatherError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class OpenMeteoClient:
    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport = transport or UrllibTransport()

    async def forecast(
        self,
        location: LocationCandidate,
        mode: str,
        units: WeatherUnits,
    ) -> dict[str, object]:
        current_fields = (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m,wind_direction_10m"
        )
        hourly_fields = (
            "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "precipitation_probability,precipitation,weather_code,"
            "wind_speed_10m,wind_direction_10m"
        )
        daily_fields = (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,precipitation_probability_max,"
            "wind_speed_10m_max,wind_direction_10m_dominant,sunrise,sunset"
        )
        params: dict[str, object] = {
            "latitude": f"{location.latitude:.5f}",
            "longitude": f"{location.longitude:.5f}",
            "timezone": location.timezone,
            "models": "best_match",
            "temperature_unit": units.temperature,
            "wind_speed_unit": units.wind_speed,
            "precipitation_unit": units.precipitation,
        }
        if mode == "current":
            params.update(current=current_fields, daily=daily_fields, forecast_days=1)
        elif mode == "hourly":
            params.update(hourly=hourly_fields, forecast_hours=48)
        else:
            params.update(daily=daily_fields, forecast_days=7)
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = await self._transport.request(
                    HttpRequest(
                        "GET",
                        url,
                        {
                            "Accept": "application/json",
                            "User-Agent": "MewCode-WeChat/0.1",
                        },
                        timeout=10,
                    )
                )
            except (HttpError, OSError, TimeoutError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
                break
            if response.status >= 500 and attempt == 0:
                continue
            if response.status < 200 or response.status >= 300:
                raise WeatherError("天气服务拒绝了请求")
            try:
                raw = json.loads(response.body)
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt == 0:
                    continue
                break
            return _select_weather(raw, mode)
        raise WeatherError("天气服务暂时不可用") from last_error


def _print_weather_result(result: Result) -> Result:
    print(f"[get_weather 返回结果] {result.content}", flush=True)
    return result


class WeatherTool:
    read_only = True

    def __init__(
        self,
        resolver: LocationResolver,
        client: OpenMeteoClient,
        *,
        on_osm_used: Callable[[], None] | None = None,
        on_weather_used: Callable[[], None] | None = None,
        previous_location: Callable[[], str | None] | None = None,
        remember_location: Callable[[str], None] | None = None,
    ) -> None:
        self._resolver = resolver
        self._client = client
        self._on_osm_used = on_osm_used
        self._on_weather_used = on_weather_used
        self._previous_location = previous_location
        self._remember_location = remember_location

    def name(self) -> str:
        return "get_weather"

    def description(self) -> str:
        return "查询指定地点的当前天气、未来 48 小时或未来 7 天预报。"

    def parameters(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "mode": {"type": "string", "enum": ["current", "hourly", "daily"]},
                "temperature_unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                },
                "wind_speed_unit": {"type": "string", "enum": ["kmh", "mph"]},
                "precipitation_unit": {"type": "string", "enum": ["mm", "inch"]},
            },
            "required": ["location"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, error = parse_arguments(args)
        if error is not None or values is None:
            return _print_weather_result(
                error or error_result("invalid_arguments", "参数无效")
            )
        location = values.get("location", "")
        if not isinstance(location, str):
            return _print_weather_result(
                error_result("invalid_arguments", "location 必须是字符串")
            )
        location = location.strip()
        if not location and self._previous_location is not None:
            location = self._previous_location() or ""
        if not location:
            return _print_weather_result(
                error_result("location_required", "请先询问用户要查询哪个城市")
            )
        mode = values.get("mode", "current")
        temperature = values.get("temperature_unit", "celsius")
        wind_speed = values.get("wind_speed_unit", "kmh")
        precipitation = values.get("precipitation_unit", "mm")
        if mode not in {"current", "hourly", "daily"}:
            return _print_weather_result(error_result("invalid_arguments", "mode 无效"))
        if temperature not in {"celsius", "fahrenheit"}:
            return _print_weather_result(
                error_result("invalid_arguments", "temperature_unit 无效")
            )
        if wind_speed not in {"kmh", "mph"}:
            return _print_weather_result(
                error_result("invalid_arguments", "wind_speed_unit 无效")
            )
        if precipitation not in {"mm", "inch"}:
            return _print_weather_result(
                error_result("invalid_arguments", "precipitation_unit 无效")
            )

        resolution = await self._resolver.resolve(location, coarse_only=True)
        if resolution.status == "privacy_rejected":
            return _print_weather_result(
                error_result(
                    "location_too_precise", "请只提供城市、区县、乡镇或公开地标"
                )
            )
        if resolution.attribution_required and self._on_osm_used is not None:
            self._on_osm_used()
        if resolution.status == "ambiguous":
            return _print_weather_result(
                error_result(
                    "ambiguous_location",
                    "地点存在歧义，请让用户确认："
                    + "；".join(
                        item.display_name for item in resolution.candidates[:5]
                    ),
                )
            )
        if resolution.status != "resolved" or resolution.location is None:
            return _print_weather_result(
                error_result("location_not_found", "无法确定地点，请补充城市和地区")
            )
        candidate = resolution.location
        if self._remember_location is not None:
            self._remember_location(location)
        try:
            report = await self._client.forecast(
                candidate,
                str(mode),
                WeatherUnits(str(temperature), str(wind_speed), str(precipitation)),
            )
        except WeatherError:
            return _print_weather_result(
                error_result("weather_unavailable", "天气服务暂时不可用，请稍后再试")
            )
        if self._on_weather_used is not None:
            self._on_weather_used()
        return _print_weather_result(
            Result(
                json.dumps(
                    {
                        "ok": True,
                        "location": candidate.display_name,
                        "timezone": candidate.timezone,
                        "mode": mode,
                        "units": {
                            "temperature": temperature,
                            "wind_speed": wind_speed,
                            "precipitation": precipitation,
                        },
                        "data": report,
                    },
                    ensure_ascii=False,
                )
            )
        )


def _select_weather(raw: object, mode: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise WeatherError("天气服务返回了无效数据")
    if mode == "current":
        current = _mapped_codes(_selected_dict(raw.get("current")))
        daily = _mapped_codes(_slice_series(raw.get("daily"), 1))
        return {"current": current, "today": daily}
    if mode == "hourly":
        return {"hourly": _mapped_codes(_slice_series(raw.get("hourly"), 48))}
    return {"daily": _mapped_codes(_slice_series(raw.get("daily"), 7))}


def _selected_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "time",
        "interval",
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "precipitation",
        "weather_code",
        "wind_speed_10m",
        "wind_direction_10m",
    }
    return {str(key): item for key, item in value.items() if key in allowed}


def _slice_series(value: object, limit: int) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    selected: dict[str, object] = {}
    for key, item in value.items():
        selected[str(key)] = item[:limit] if isinstance(item, list) else item
    return selected


def _mapped_codes(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    for key in ("weather_code", "weathercode"):
        codes = result.get(key)
        if isinstance(codes, list):
            result["weather_description"] = [
                WMO_ZH.get(int(code), "未知") if code is not None else "未知"
                for code in codes
            ]
        elif isinstance(codes, (int, float)):
            result["weather_description"] = WMO_ZH.get(int(codes), "未知")
    for key in ("wind_direction_10m", "wind_direction_10m_dominant"):
        directions = result.get(key)
        if isinstance(directions, list):
            result[f"{key}_zh"] = [
                _direction_zh(float(direction)) if direction is not None else "未知"
                for direction in directions
            ]
        elif isinstance(directions, (int, float)):
            result[f"{key}_zh"] = _direction_zh(float(directions))
    return result


def _direction_zh(degrees: float) -> str:
    names = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")
    return names[int((degrees % 360 + 22.5) // 45) % 8]


__all__ = ["OpenMeteoClient", "WeatherTool", "WeatherUnits"]
