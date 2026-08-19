from __future__ import annotations

import asyncio
from functools import wraps
from pathlib import Path

from mewcode.wechat.bot import WechatBot
from mewcode.wechat.config import WechatConfig
from mewcode.wechat.models import WechatDesktopEvent
from mewcode.wechat.runtime import WechatTurnCancelled
from mewcode.wechat.store import WechatStateStore


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


class FakeDriver:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def establish_baseline(self) -> None:
        pass

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def wait_for_events(self, stop) -> list[WechatDesktopEvent]:
        stop.wait(0.01)
        return []

    def send_text(self, event: WechatDesktopEvent, text: str) -> None:
        self.sent.append((event.conversation_name, text))


class FakeRuntime:
    def __init__(self, replies: dict[str, str] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[str] = []

    async def reply(self, name: str, text: str, cancel: asyncio.Event) -> str:
        self.calls.append(text)
        await asyncio.sleep(0)
        return self.replies.get(text, f"reply:{text}")

    async def close(self) -> None:
        pass


class BlockingRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def reply(self, name: str, text: str, cancel: asyncio.Event) -> str:
        self.calls.append(text)
        self.started.set()
        await cancel.wait()
        raise WechatTurnCancelled


class FailingRuntime(FakeRuntime):
    async def reply(self, name: str, text: str, cancel: asyncio.Event) -> str:
        self.calls.append(text)
        if text == "fail":
            raise RuntimeError("secret detail")
        return "recovered"


def config(max_chars: int = 20) -> WechatConfig:
    return WechatConfig(
        True,
        "fake",
        ("A", "B"),
        "safe",
        2,
        max_chars,
        "INFO",
    )


def event(
    event_id: str,
    name: str,
    text: str,
    *,
    fingerprint: str | None = None,
) -> WechatDesktopEvent:
    return WechatDesktopEvent(
        event_id,
        fingerprint or event_id,
        f"row-{name}",
        name,
        name,
        text,
        1.0,
        True,
        True,
    )


async def wait_idle(bot: WechatBot) -> None:
    await asyncio.wait_for(bot._queue.join(), 1)
    await asyncio.sleep(0)


@async_test
async def test_allowlist_dedup_and_fifo_happen_before_runtime(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FakeRuntime()
    bot = WechatBot(config(), driver, runtime, store)
    bot._consumer = asyncio.create_task(bot._consume())

    assert bot.submit_event(event("x", "陌生人", "ignored")) is False
    assert bot.submit_event(event("1", "A", "first")) is True
    assert bot.submit_event(event("2", "B", "second")) is True
    assert bot.submit_event(event("3", "A", "duplicate", fingerprint="1")) is False
    await wait_idle(bot)

    assert runtime.calls == ["first", "second"]
    assert driver.sent == [("A", "reply:first"), ("B", "reply:second")]
    await bot.stop()


@async_test
async def test_cancel_only_affects_same_friend_and_queue_continues(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = BlockingRuntime()
    bot = WechatBot(config(), driver, runtime, store)
    bot._consumer = asyncio.create_task(bot._consume())
    bot.submit_event(event("1", "A", "slow"))
    await runtime.started.wait()

    bot.submit_event(event("2", "B", "/cancel"))
    await asyncio.sleep(0)
    assert bot._active is not None and not bot._active.cancel.is_set()
    bot.submit_event(event("3", "A", "/cancel"))
    await wait_idle(bot)

    assert ("B", "当前没有可取消的任务。") in driver.sent
    assert ("A", "已取消当前任务。") in driver.sent
    await bot.stop()


@async_test
async def test_reply_split_and_failure_do_not_stop_next_message(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FailingRuntime()
    bot = WechatBot(config(max_chars=4), driver, runtime, store)
    bot._consumer = asyncio.create_task(bot._consume())
    bot.submit_event(event("1", "A", "fail"))
    bot.submit_event(event("2", "A", "next"))
    await wait_idle(bot)

    sent_text = [text for _, text in driver.sent]
    assert "处理失败，请稍后再试。" == "".join(sent_text[:3])
    assert "recovered" == "".join(sent_text[3:])
    await bot.stop()
