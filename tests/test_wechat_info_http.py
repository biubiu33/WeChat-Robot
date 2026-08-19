from __future__ import annotations

import asyncio
import socket
import urllib.request
from functools import wraps

import pytest

from mewcode.wechat.info.http import (
    HttpError,
    HttpRequest,
    HttpResponse,
    SafePublicHttpClient,
    UrllibTransport,
    extract_visible_text,
    sanitize_url_secrets,
    validate_public_url,
)


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


def test_urllib_transport_uses_only_explicit_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: list[tuple[object, ...]] = []

    class FakeOpener:
        pass

    def build_opener(*items: object) -> FakeOpener:
        handlers.append(items)
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    UrllibTransport()
    UrllibTransport("http://proxy-user:proxy-pass@proxy.example:8080")

    direct = handlers[0][0]
    explicit = handlers[1][0]
    assert isinstance(direct, urllib.request.ProxyHandler)
    assert direct.proxies == {}
    assert isinstance(explicit, urllib.request.ProxyHandler)
    assert explicit.proxies == {
        "http": "http://proxy-user:proxy-pass@proxy.example:8080",
        "https": "http://proxy-user:proxy-pass@proxy.example:8080",
    }


@pytest.mark.parametrize(
    "proxy_url",
    ["socks5://proxy-user:secret@proxy.example:1080", "http://"],
)
def test_urllib_transport_rejects_invalid_proxy_without_leaking_secret(
    proxy_url: str,
) -> None:
    with pytest.raises(HttpError) as captured:
        UrllibTransport(proxy_url)
    assert captured.value.code == "invalid_proxy"
    assert "secret" not in str(captured.value)


def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


@async_test
async def test_public_url_validation_blocks_non_public_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HttpError, match="http"):
        await validate_public_url("file:///etc/passwd")
    with pytest.raises(HttpError, match="用户名"):
        await validate_public_url("https://user:pass@example.com/")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ],
    )
    with pytest.raises(HttpError, match="公网"):
        await validate_public_url("http://example.test/")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
        ],
    )
    with pytest.raises(HttpError, match="公网"):
        await validate_public_url("http://mixed.example/")


@async_test
async def test_redirect_target_is_revalidated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def dns(host: str, *args, **kwargs):
        nonlocal calls
        calls += 1
        address = "93.184.216.34" if host == "public.example" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    transport = FakeTransport(
        [
            HttpResponse(
                302, "https://public.example", {"Location": "http://internal.test"}, b""
            )
        ]
    )
    client = SafePublicHttpClient(transport)

    with pytest.raises(HttpError) as captured:
        await client.fetch("https://public.example")
    assert captured.value.code == "private_address"
    assert len(transport.requests) == 1
    assert calls == 2


@async_test
async def test_static_page_fetch_has_fixed_headers_and_extracts_visible_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_dns(monkeypatch)
    transport = FakeTransport(
        [
            HttpResponse(
                200,
                "https://example.com/page",
                {"Content-Type": "text/html; charset=utf-8"},
                b"<title>Demo</title><main>Hello <b>world</b></main>"
                b"<script>ignore me</script><p hidden>hidden</p>",
            )
        ]
    )
    page = await SafePublicHttpClient(transport).fetch("https://example.com/page")

    assert page.title == "Demo"
    assert page.content == "Hello world"
    assert transport.requests[0].headers["Accept-Encoding"] == "identity"
    assert "Cookie" not in transport.requests[0].headers


def test_content_type_and_secret_url_boundaries() -> None:
    with pytest.raises(HttpError) as captured:
        extract_visible_text(b"%PDF", "application/pdf")
    assert captured.value.code == "unsupported_content_type"
    assert (
        sanitize_url_secrets(
            "https://example.com/a?token=secret&query=ok&api_key=hidden&session=private#fragment"
        )
        == "https://example.com/a?query=ok"
    )

    long_page = extract_visible_text(
        ("<main>" + "字" * 50_001 + "</main>").encode(), "text/html"
    )
    assert len(long_page.content) == 50_000
    assert long_page.truncated

    hostile = extract_visible_text(
        b"<main>safe</main><style>style</style><form>form</form>"
        b"<template>template</template><svg>svg</svg><p aria-hidden='true'>hidden</p>",
        "text/html",
    )
    assert hostile.content == "safe"


@async_test
async def test_dynamic_shell_returns_clear_error_without_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_dns(monkeypatch)
    transport = FakeTransport(
        [
            HttpResponse(
                200,
                "https://example.com/app",
                {"Content-Type": "text/html"},
                b"<html><script>renderApp()</script></html>",
            )
        ]
    )

    with pytest.raises(HttpError) as captured:
        await SafePublicHttpClient(transport).fetch("https://example.com/app")
    assert captured.value.code == "empty_page"
