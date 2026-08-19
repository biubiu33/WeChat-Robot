"""Deterministic place resolution and local-time lookup."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib.resources import files
from typing import Literal
from zoneinfo import ZoneInfo

from timezonefinder import TimezoneFinder
from tzlocal import get_localzone_name

from mewcode.tool import Result, error_result, parse_arguments
from mewcode.wechat.store import CachedLocation, WechatStateStore

from .http import HttpError, HttpRequest, HttpTransport, UrllibTransport


LOCATION_CACHE_SECONDS = 30 * 24 * 60 * 60
PRECISE_ADDRESS_RE = re.compile(
    r"(?:\d{5,}|\d+\s*(?:号|栋|室|单元|弄|巷|路|街|avenue|ave\.?|street|st\.?|road|rd\.?))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LocationCandidate:
    display_name: str
    country_code: str
    latitude: float
    longitude: float
    timezone: str
    source: Literal["capital", "cache", "nominatim"]


@dataclass(frozen=True)
class LocationResolution:
    status: Literal["resolved", "ambiguous", "not_found", "privacy_rejected"]
    location: LocationCandidate | None = None
    candidates: tuple[LocationCandidate, ...] = ()
    attribution_required: bool = False


class NominatimRateLimiter:
    def __init__(
        self,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request = float("-inf")
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            delay = 1.0 - (self._monotonic() - self._last_request)
            if delay > 0:
                await self._sleep(delay)
            self._last_request = self._monotonic()


class LocationResolver:
    def __init__(
        self,
        store: WechatStateStore,
        user_agent: str,
        *,
        transport: HttpTransport | None = None,
        rate_limiter: NominatimRateLimiter | None = None,
        clock: Callable[[], float] = time.time,
        timezone_finder: TimezoneFinder | None = None,
    ) -> None:
        self._store = store
        self._user_agent = user_agent
        self._transport = transport or UrllibTransport()
        self._rate_limiter = rate_limiter or NominatimRateLimiter()
        self._clock = clock
        self._timezone_finder = timezone_finder or TimezoneFinder(in_memory=True)
        self._capitals = _load_capitals(self._timezone_finder)

    async def resolve(
        self, query: str, *, coarse_only: bool = False
    ) -> LocationResolution:
        normalized = normalize_location(query)
        if not normalized:
            return LocationResolution("not_found")
        if coarse_only and PRECISE_ADDRESS_RE.search(normalized):
            return LocationResolution("privacy_rejected")
        local = self._capitals.get(normalized.casefold())
        if local is not None:
            return LocationResolution("resolved", location=local)

        cache_key = _cache_key(normalized, coarse_only)
        cached = self._store.get_location(cache_key)
        if cached and self._clock() - cached.updated_at <= LOCATION_CACHE_SECONDS:
            restored = _resolution_from_json(cached.value_json)
            if restored is not None:
                return _mark_cached(restored)

        await self._rate_limiter.wait()
        params = urllib.parse.urlencode(
            {
                "q": normalized,
                "format": "jsonv2",
                "limit": "5",
                "addressdetails": "1",
                "accept-language": "zh-CN,en",
            }
        )
        try:
            response = await self._transport.request(
                HttpRequest(
                    "GET",
                    f"https://nominatim.openstreetmap.org/search?{params}",
                    {"User-Agent": self._user_agent, "Accept": "application/json"},
                    timeout=10,
                )
            )
            if response.status != 200:
                return LocationResolution("not_found")
            raw = json.loads(response.body)
        except (HttpError, OSError, ValueError, json.JSONDecodeError):
            return LocationResolution("not_found")
        resolution = self._from_nominatim(raw)
        self._store.put_location(
            CachedLocation(cache_key, _resolution_to_json(resolution), self._clock())
        )
        return resolution

    def _from_nominatim(self, raw: object) -> LocationResolution:
        if not isinstance(raw, list):
            return LocationResolution("not_found")
        grouped: dict[tuple[str, str, str], LocationCandidate] = {}
        for item in raw[:5]:
            if not isinstance(item, dict):
                continue
            try:
                latitude = float(item["lat"])
                longitude = float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            timezone = self._timezone_finder.timezone_at(lat=latitude, lng=longitude)
            if not timezone:
                continue
            address_value = item.get("address")
            address: dict[str, object] = (
                address_value if isinstance(address_value, dict) else {}
            )
            city = next(
                (
                    str(address[key])
                    for key in ("city", "town", "village", "municipality", "county")
                    if key in address
                ),
                "",
            )
            region = str(address.get("state", ""))
            country = str(address.get("country", ""))
            key = (city.casefold(), region.casefold(), country.casefold())
            grouped.setdefault(
                key,
                LocationCandidate(
                    str(item.get("display_name", city or country))[:300],
                    str(address.get("country_code", "")).upper(),
                    latitude,
                    longitude,
                    timezone,
                    "nominatim",
                ),
            )
        candidates = tuple(grouped.values())
        if not candidates:
            return LocationResolution("not_found", attribution_required=True)
        if len(candidates) > 1:
            return LocationResolution(
                "ambiguous", candidates=candidates, attribution_required=True
            )
        return LocationResolution(
            "resolved", location=candidates[0], attribution_required=True
        )


class CurrentTimeTool:
    read_only = True

    def __init__(
        self,
        resolver: LocationResolver,
        *,
        clock: Callable[[], float] = time.time,
        on_osm_used: Callable[[], None] | None = None,
    ) -> None:
        self._resolver = resolver
        self._clock = clock
        self._on_osm_used = on_osm_used

    def name(self) -> str:
        return "get_current_time"

    def description(self) -> str:
        return "查询本机或指定地点的当前时间。国家名称按首都时区处理。"

    def parameters(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "可选地点；国家名称按其首都处理",
                }
            },
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, error = parse_arguments(args)
        if error is not None or values is None:
            return error or error_result("invalid_arguments", "参数无效")
        location = values.get("location", "")
        if not isinstance(location, str):
            return error_result("invalid_arguments", "location 必须是字符串")
        if location.strip():
            resolution = await self._resolver.resolve(location)
            if resolution.attribution_required and self._on_osm_used is not None:
                self._on_osm_used()
            if resolution.status == "ambiguous":
                return error_result(
                    "ambiguous_location",
                    "地点存在歧义，请让用户从候选中确认："
                    + "；".join(
                        item.display_name for item in resolution.candidates[:5]
                    ),
                )
            if resolution.status != "resolved" or resolution.location is None:
                return error_result(
                    "location_not_found", "无法确定该地点，请补充城市和地区"
                )
            candidate = resolution.location
            timezone_name = candidate.timezone
            display_name = candidate.display_name
        else:
            timezone_name = get_localzone_name()
            display_name = "本机"
        try:
            timestamp = self._clock()
            local_time = datetime.fromtimestamp(timestamp, ZoneInfo(timezone_name))
            host_time = datetime.fromtimestamp(
                timestamp, ZoneInfo(get_localzone_name())
            )
        except Exception:
            return error_result("timezone_error", "无法计算该地点的当前时间")
        offset = local_time.utcoffset()
        dst = local_time.dst()
        payload = {
            "ok": True,
            "location": display_name,
            "local_time": local_time.isoformat(timespec="seconds"),
            "timezone": timezone_name,
            "utc_offset": _format_offset(int(offset.total_seconds()) if offset else 0),
            "daylight_saving": bool(dst and dst.total_seconds()),
            "date_difference_from_host": (local_time.date() - host_time.date()).days,
        }
        return Result(json.dumps(payload, ensure_ascii=False))


def normalize_location(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())[:200]


def _cache_key(query: str, coarse_only: bool) -> str:
    return f"{'coarse' if coarse_only else 'place'}:{query.casefold()}"


def _load_capitals(finder: TimezoneFinder) -> dict[str, LocationCandidate]:
    payload = json.loads(
        files("mewcode.wechat.info")
        .joinpath("country_capitals.json")
        .read_text(encoding="utf-8")
    )
    result: dict[str, LocationCandidate] = {}
    for item in payload.get("countries", []):
        timezone = finder.timezone_at(lat=item["latitude"], lng=item["longitude"])
        if not timezone:
            continue
        display = f"{item['capital']}（{item['names'][0]}首都）"
        candidate = LocationCandidate(
            display,
            item["code"],
            float(item["latitude"]),
            float(item["longitude"]),
            timezone,
            "capital",
        )
        for name in item["names"]:
            result[normalize_location(name).casefold()] = candidate
    return result


def _resolution_to_json(resolution: LocationResolution) -> str:
    return json.dumps(
        {
            "status": resolution.status,
            "location": asdict(resolution.location) if resolution.location else None,
            "candidates": [asdict(item) for item in resolution.candidates],
            "attribution_required": resolution.attribution_required,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _resolution_from_json(value: str) -> LocationResolution | None:
    try:
        raw = json.loads(value)
        location = LocationCandidate(**raw["location"]) if raw.get("location") else None
        candidates = tuple(
            LocationCandidate(**item) for item in raw.get("candidates", [])
        )
        return LocationResolution(
            raw["status"], location, candidates, bool(raw.get("attribution_required"))
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _mark_cached(resolution: LocationResolution) -> LocationResolution:
    def cached(item: LocationCandidate) -> LocationCandidate:
        return LocationCandidate(
            item.display_name,
            item.country_code,
            item.latitude,
            item.longitude,
            item.timezone,
            "cache",
        )

    return LocationResolution(
        resolution.status,
        cached(resolution.location) if resolution.location else None,
        tuple(cached(item) for item in resolution.candidates),
        resolution.attribution_required,
    )


def _format_offset(seconds: int) -> str:
    sign = "+" if seconds >= 0 else "-"
    hours, remainder = divmod(abs(seconds), 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


__all__ = [
    "CurrentTimeTool",
    "LocationCandidate",
    "LocationResolution",
    "LocationResolver",
    "NominatimRateLimiter",
    "normalize_location",
]
