from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mewcode.errors import ProviderError, StreamProtocolError
from mewcode.models import ChatMessage, ProviderProfile
from mewcode.providers.openai import OpenAIProvider


def make_profile() -> ProviderProfile:
    return ProviderProfile(
        name="openai",
        protocol="openai",
        model="gpt-test",
        base_url="https://openai.test/v1",
        api_key="sk-openai-secret",
    )


def make_client(
    handler: httpx.MockTransport | Any,
) -> httpx.Client:
    if isinstance(handler, httpx.MockTransport):
        return httpx.Client(transport=handler)
    return httpx.Client(transport=httpx.MockTransport(handler))


def sse_response(lines: list[str]) -> httpx.Response:
    return httpx.Response(200, content="".join(lines).encode("utf-8"))


def test_openai_request_shape() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return sse_response(["data: [DONE]\n\n"])

    provider = OpenAIProvider(make_profile(), make_client(handler))

    list(provider.stream_chat([ChatMessage(role="user", content="你好")]))

    assert captured["url"] == "https://openai.test/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer sk-openai-secret"
    assert captured["json"] == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": True,
    }


def test_openai_streams_text_chunks() -> None:
    provider = OpenAIProvider(
        make_profile(),
        make_client(
            lambda _request: sse_response(
                [
                    'data: {"choices":[{"delta":{"content":"你"}}]}\n\n',
                    'data: {"choices":[{"delta":{"content":"好"}}]}\n\n',
                    "data: [DONE]\n\n",
                ]
            )
        ),
    )

    chunks = list(provider.stream_chat([ChatMessage(role="user", content="中文")]))

    assert [chunk.text for chunk in chunks] == ["你", "好"]


def test_openai_error_redacts_api_key() -> None:
    provider = OpenAIProvider(
        make_profile(),
        make_client(
            lambda _request: httpx.Response(
                401,
                text="bad key sk-openai-secret",
            )
        ),
    )

    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream_chat([ChatMessage(role="user", content="你好")]))

    assert "sk-openai-secret" not in str(exc_info.value)
    assert "[已隐藏]" in str(exc_info.value)


def test_openai_invalid_json_raises_stream_error() -> None:
    provider = OpenAIProvider(
        make_profile(),
        make_client(lambda _request: sse_response(["data: {bad json}\n\n"])),
    )

    with pytest.raises(StreamProtocolError):
        list(provider.stream_chat([ChatMessage(role="user", content="你好")]))


def test_openai_error_event_raises_provider_error() -> None:
    provider = OpenAIProvider(
        make_profile(),
        make_client(
            lambda _request: sse_response(
                ['data: {"error":{"message":"模型错误"}}\n\n']
            )
        ),
    )

    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream_chat([ChatMessage(role="user", content="你好")]))

    assert "模型错误" in str(exc_info.value)
