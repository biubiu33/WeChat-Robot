from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mewcode.errors import ProviderError, StreamProtocolError
from mewcode.models import ChatMessage, ProviderProfile
from mewcode.providers.anthropic import ANTHROPIC_VERSION, AnthropicProvider


def make_profile(thinking: bool = False) -> ProviderProfile:
    return ProviderProfile(
        name="claude",
        protocol="anthropic",
        model="claude-test",
        base_url="https://anthropic.test/v1",
        api_key="sk-ant-secret",
        thinking=thinking,
    )


def make_client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def sse_response(lines: list[str]) -> httpx.Response:
    return httpx.Response(200, content="".join(lines).encode("utf-8"))


def test_anthropic_request_shape() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return sse_response(["event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"])

    provider = AnthropicProvider(make_profile(), make_client(handler))

    list(provider.stream_chat([ChatMessage(role="user", content="你好")]))

    assert captured["url"] == "https://anthropic.test/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-secret"
    assert captured["headers"]["anthropic-version"] == ANTHROPIC_VERSION
    assert captured["json"] == {
        "model": "claude-test",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": "你好"}],
        "stream": True,
    }


def test_anthropic_streams_text_chunks() -> None:
    provider = AnthropicProvider(
        make_profile(),
        make_client(
            lambda _request: sse_response(
                [
                    'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"你"}}\n\n',
                    'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"好"}}\n\n',
                ]
            )
        ),
    )

    chunks = list(provider.stream_chat([ChatMessage(role="user", content="中文")]))

    assert [chunk.text for chunk in chunks] == ["你", "好"]


def test_anthropic_includes_thinking_when_enabled() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return sse_response(["event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"])

    provider = AnthropicProvider(make_profile(thinking=True), make_client(handler))

    list(provider.stream_chat([ChatMessage(role="user", content="你好")]))

    assert captured["json"]["thinking"] == {
        "type": "adaptive",
        "display": "omitted",
    }


def test_anthropic_ignores_non_text_deltas() -> None:
    provider = AnthropicProvider(
        make_profile(thinking=True),
        make_client(
            lambda _request: sse_response(
                [
                    'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"内部"}}\n\n',
                    'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"signature_delta","signature":"abc"}}\n\n',
                    'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"可见"}}\n\n',
                ]
            )
        ),
    )

    chunks = list(provider.stream_chat([ChatMessage(role="user", content="中文")]))

    assert [chunk.text for chunk in chunks] == ["可见"]


def test_anthropic_error_redacts_api_key() -> None:
    provider = AnthropicProvider(
        make_profile(),
        make_client(
            lambda _request: httpx.Response(401, text="bad key sk-ant-secret")
        ),
    )

    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream_chat([ChatMessage(role="user", content="你好")]))

    assert "sk-ant-secret" not in str(exc_info.value)
    assert "[已隐藏]" in str(exc_info.value)


def test_anthropic_invalid_json_raises_stream_error() -> None:
    provider = AnthropicProvider(
        make_profile(),
        make_client(
            lambda _request: sse_response(
                ["event: content_block_delta\ndata: {bad json}\n\n"]
            )
        ),
    )

    with pytest.raises(StreamProtocolError):
        list(provider.stream_chat([ChatMessage(role="user", content="你好")]))


def test_anthropic_error_event_raises_provider_error() -> None:
    provider = AnthropicProvider(
        make_profile(),
        make_client(
            lambda _request: sse_response(
                ['event: error\ndata: {"type":"error","error":{"message":"模型错误"}}\n\n']
            )
        ),
    )

    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream_chat([ChatMessage(role="user", content="你好")]))

    assert "模型错误" in str(exc_info.value)
