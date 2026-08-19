"""Small HTTP layer with strict public-web boundaries for WeChat tools."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol


MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_PAGE_CHARS = 50_000
MAX_REDIRECTS = 5
SECRET_QUERY_PARTS = (
    "token",
    "key",
    "secret",
    "password",
    "signature",
    "auth",
    "session",
    "credential",
)


class HttpError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None = None
    timeout: float = 10.0
    max_bytes: int = MAX_BODY_BYTES


@dataclass(frozen=True)
class HttpResponse:
    status: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    async def request(self, request: HttpRequest) -> HttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class UrllibTransport:
    def __init__(self, proxy_url: str | None = None) -> None:
        proxies: dict[str, str] = {}
        if proxy_url is not None:
            try:
                parsed = urllib.parse.urlsplit(proxy_url)
                port = parsed.port
                valid = (
                    parsed.scheme.lower() in {"http", "https"}
                    and bool(parsed.hostname)
                    and (port is None or port > 0)
                )
            except ValueError:
                valid = False
            if not valid:
                raise HttpError("invalid_proxy", "代理配置无效")
            proxies = {"http": proxy_url, "https": proxy_url}
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies), _NoRedirect()
        )

    async def request(self, request: HttpRequest) -> HttpResponse:
        return await asyncio.to_thread(self._request_sync, request)

    def _request_sync(self, request: HttpRequest) -> HttpResponse:
        raw = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            response = self._opener.open(raw, timeout=request.timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        except (OSError, urllib.error.URLError):
            raise HttpError("network_error", "公共网络请求失败") from None
        with response:
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > request.max_bytes:
                raise HttpError("response_too_large", "响应超过 2 MiB 限制")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(65_536, request.max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > request.max_bytes:
                    raise HttpError("response_too_large", "响应超过 2 MiB 限制")
                chunks.append(chunk)
            return HttpResponse(
                int(response.status),
                response.geturl(),
                {str(key): str(value) for key, value in response.headers.items()},
                b"".join(chunks),
            )


@dataclass(frozen=True)
class ExtractedPage:
    title: str
    content: str
    truncated: bool


@dataclass(frozen=True)
class PublicPage:
    url: str
    title: str
    content: str
    truncated: bool


async def validate_public_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise HttpError("invalid_url", "只允许 http 或 https 公网链接")
    if parsed.username is not None or parsed.password is not None:
        raise HttpError("invalid_url", "链接不能包含用户名或密码")
    hostname = parsed.hostname
    if (
        not hostname
        or hostname.lower() == "localhost"
        or hostname.endswith(".localhost")
    ):
        raise HttpError("private_address", "链接目标不是公网地址")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise HttpError("invalid_url", "链接端口无效") from exc
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise HttpError("dns_error", "无法解析链接主机") from exc
    if not addresses:
        raise HttpError("dns_error", "无法解析链接主机")
    for item in addresses:
        address = ipaddress.ip_address(str(item[4][0]).split("%", 1)[0])
        if not address.is_global:
            raise HttpError("private_address", "链接目标不是公网地址")
    return urllib.parse.urlunsplit(parsed)


def sanitize_url_secrets(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if any(part in key.lower() for part in SECRET_QUERY_PARTS):
            continue
        query.append((key, value))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )


class SafePublicHttpClient:
    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport = transport or UrllibTransport()

    async def fetch(self, url: str, timeout: float = 10.0) -> PublicPage:
        current = url
        for redirect in range(MAX_REDIRECTS + 1):
            current = await validate_public_url(current)
            response = await self._transport.request(
                HttpRequest(
                    "GET",
                    current,
                    {
                        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                        "Accept-Encoding": "identity",
                        "User-Agent": "MewCode-WeChat/0.1",
                    },
                    timeout=timeout,
                )
            )
            if response.status in {301, 302, 303, 307, 308}:
                if redirect >= MAX_REDIRECTS:
                    raise HttpError("too_many_redirects", "网页重定向次数过多")
                location = _header(response.headers, "location")
                if not location:
                    raise HttpError("invalid_redirect", "网页重定向缺少目标")
                current = urllib.parse.urljoin(current, location)
                continue
            if response.status < 200 or response.status >= 300:
                raise HttpError(
                    "http_error",
                    f"网页返回 HTTP {response.status}",
                    status=response.status,
                )
            encoding = _header(response.headers, "content-encoding").strip().lower()
            if encoding and encoding != "identity":
                raise HttpError(
                    "unsupported_content_encoding", "网页返回了不受支持的压缩编码"
                )
            content_type = _header(response.headers, "content-type")
            extracted = extract_visible_text(response.body, content_type)
            if not extracted.content:
                raise HttpError(
                    "empty_page",
                    "静态方式未取得网页正文；该页面可能需要 JavaScript、登录或验证码",
                )
            final_url = await validate_public_url(response.final_url or current)
            return PublicPage(
                sanitize_url_secrets(final_url),
                extracted.title,
                extracted.content,
                extracted.truncated,
            )
        raise HttpError("too_many_redirects", "网页重定向次数过多")


def extract_visible_text(body: bytes, content_type: str) -> ExtractedPage:
    mime, _, parameters = content_type.partition(";")
    mime = mime.strip().lower()
    if mime not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise HttpError("unsupported_content_type", "只支持 HTML 或纯文本网页")
    charset = "utf-8"
    for item in parameters.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator and key.lower() == "charset":
            charset = value.strip(' "') or charset
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    if mime == "text/plain":
        normalized = _normalize_text(text)
        return ExtractedPage(
            "", normalized[:MAX_PAGE_CHARS], len(normalized) > MAX_PAGE_CHARS
        )
    parser = _VisibleTextParser()
    parser.feed(text)
    normalized = _normalize_text(" ".join(parser.parts))
    title = _normalize_text(" ".join(parser.title_parts))[:300]
    return ExtractedPage(
        title,
        normalized[:MAX_PAGE_CHARS],
        len(normalized) > MAX_PAGE_CHARS,
    )


class _VisibleTextParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._stack: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        values = {key.lower(): (value or "").lower() for key, value in attrs}
        hidden = "hidden" in values or values.get("aria-hidden") == "true"
        style = values.get("style", "").replace(" ", "")
        hidden = hidden or "display:none" in style or "visibility:hidden" in style
        activates_skip = lowered in self._SKIP_TAGS or hidden
        if activates_skip:
            self._skip_depth += 1
        if lowered not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self._stack.append((lowered, activates_skip))
        if lowered == "title" and not self._skip_depth:
            self._in_title = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        for index in range(len(self._stack) - 1, -1, -1):
            stacked_tag, activates_skip = self._stack[index]
            if stacked_tag != lowered:
                continue
            del self._stack[index:]
            if activates_skip:
                self._skip_depth = max(0, self._skip_depth - 1)
            break
        if lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.parts.append(data)


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _header(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


__all__ = [
    "ExtractedPage",
    "HttpError",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "PublicPage",
    "SafePublicHttpClient",
    "UrllibTransport",
    "extract_visible_text",
    "sanitize_url_secrets",
    "validate_public_url",
]
