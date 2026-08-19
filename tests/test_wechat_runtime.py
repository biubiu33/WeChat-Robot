from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import wraps
from pathlib import Path

import pytest

from mewcode.config import ProviderConfig
from mewcode.llm import Message, Request, StreamEvent, ToolCall, ToolResult
from mewcode.wechat.config import WechatConfig
from mewcode.wechat.runtime import (
    WechatAgentRuntime,
    WechatTurnCancelled,
    _wechat_history_messages,
)
from mewcode.wechat.store import WechatStateStore


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, replies: list[str]) -> None:
        self.replies = iter(replies)
        self.requests: list[Request] = []

    def redact(self, text: str) -> str:
        return text

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        yield StreamEvent(text=next(self.replies))
        yield StreamEvent(done=True)


class BlockingProvider(FakeProvider):
    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        await asyncio.sleep(10)
        yield StreamEvent(text="late")


def configs(timeout: float = 2.0) -> tuple[ProviderConfig, WechatConfig]:
    provider = ProviderConfig(
        "fake", "openai", "secret", "fake-model", context_window=10000
    )
    wechat = WechatConfig(True, "fake", ("A", "B"), "安全微信助手", timeout, 20, "INFO")
    return provider, wechat


def test_history_filter_drops_legacy_weather_tool_messages() -> None:
    messages = [
        Message("user", "南昌天气"),
        Message(
            "assistant",
            "[微信公共信息工具内容未写入会话档案]",
            [ToolCall("legacy-weather", "get_weather", "{}")],
        ),
        Message(
            "tool",
            "[微信公共信息工具内容未写入会话档案]",
            tool_results=[
                ToolResult(
                    "legacy-weather",
                    "[微信公共信息工具内容未写入会话档案]",
                )
            ],
        ),
        Message("assistant", "旧的最终天气回复"),
    ]

    assert _wechat_history_messages(messages) == [messages[0], messages[3]]


@async_test
async def test_runtime_isolates_and_restores_friend_sessions(tmp_path: Path) -> None:
    provider_config, wechat_config = configs()
    store = WechatStateStore(tmp_path)
    provider = FakeProvider(["南昌今天多云", "请告诉我城市", "南昌明天有雨"])
    runtime = WechatAgentRuntime(
        tmp_path, provider_config, wechat_config, store, provider=provider
    )

    assert await runtime.reply("A", "南昌今天天气", asyncio.Event()) == "南昌今天多云"
    assert await runtime.reply("B", "那明天呢", asyncio.Event()) == "请告诉我城市"
    assert store.get_session_id("A") != store.get_session_id("B")

    restored = WechatAgentRuntime(
        tmp_path, provider_config, wechat_config, store, provider=provider
    )
    assert await restored.reply("A", "那明天呢", asyncio.Event()) == "南昌明天有雨"
    assert [message.content for message in provider.requests[-1].messages] == [
        "南昌今天天气",
        "南昌今天多云",
        "那明天呢",
    ]
    assert all(
        "南昌" not in message.content for message in provider.requests[1].messages
    )
    store.close()


@async_test
async def test_runtime_exposes_no_tools_or_local_environment(tmp_path: Path) -> None:
    provider_config, wechat_config = configs()
    store = WechatStateStore(tmp_path)
    provider = FakeProvider(["只做文字回答"])
    runtime = WechatAgentRuntime(
        tmp_path, provider_config, wechat_config, store, provider=provider
    )

    await runtime.reply("A", "读取本地文件", asyncio.Event())

    request = provider.requests[0]
    assert request.tools == []
    assert request.system.stable == "安全微信助手"
    assert "不能访问本地环境" in request.system.environment
    assert str(tmp_path) not in request.system.environment
    store.close()


@async_test
async def test_runtime_timeout_and_cancel_close_current_turn(tmp_path: Path) -> None:
    provider_config, timeout_config = configs(0.01)
    store = WechatStateStore(tmp_path)
    runtime = WechatAgentRuntime(
        tmp_path,
        provider_config,
        timeout_config,
        store,
        provider=BlockingProvider([]),
    )
    with pytest.raises(TimeoutError):
        await runtime.reply("A", "slow", asyncio.Event())

    _, cancel_config = configs(2)
    cancel_runtime = WechatAgentRuntime(
        tmp_path,
        provider_config,
        cancel_config,
        store,
        provider=BlockingProvider([]),
    )
    cancel = asyncio.Event()
    task = asyncio.create_task(cancel_runtime.reply("B", "cancel", cancel))
    await asyncio.sleep(0.01)
    cancel.set()
    with pytest.raises(WechatTurnCancelled):
        await task
    store.close()
