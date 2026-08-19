from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import wraps
from pathlib import Path

import pytest

from mewcode.config import ProviderConfig
from mewcode.llm import Request, StreamEvent
from mewcode.wechat.config import WechatConfig
from mewcode.wechat.runtime import WechatAgentRuntime, WechatTurnCancelled
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


@async_test
async def test_runtime_isolates_and_restores_friend_sessions(tmp_path: Path) -> None:
    provider_config, wechat_config = configs()
    store = WechatStateStore(tmp_path)
    provider = FakeProvider(["A1", "B1", "A2"])
    runtime = WechatAgentRuntime(
        tmp_path, provider_config, wechat_config, store, provider=provider
    )

    assert await runtime.reply("A", "alpha", asyncio.Event()) == "A1"
    assert await runtime.reply("B", "beta", asyncio.Event()) == "B1"
    assert store.get_session_id("A") != store.get_session_id("B")

    restored = WechatAgentRuntime(
        tmp_path, provider_config, wechat_config, store, provider=provider
    )
    assert await restored.reply("A", "again", asyncio.Event()) == "A2"
    assert [message.content for message in provider.requests[-1].messages] == [
        "alpha",
        "A1",
        "again",
    ]
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
